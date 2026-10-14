"""Document classifier: training reproducibility, loading, inference behaviour, and failure handling (synthetic data only)."""
import dataclasses
import json
import logging
from pathlib import Path

import numpy as np
import pytest

from app.core.config import settings as real_settings
from app.ml import classifier as clf_mod
from app.ml import training
from app.ml.labels import CLAIM_BILLING, LABELS, LABORATORY_RESULT, OTHER
from app.ml.synthetic_data import generate_dataset

SMALL = dict(per_class=40, seed=11, cv_folds=3, c_grid=(3.0,), challenge_path=None)
CANARY = "ZEBRA-CANARY-7731"
FILLER = "some perfectly reasonable document text with enough words"


@pytest.fixture(scope="module")
def trained(tmp_path_factory):
    out = tmp_path_factory.mktemp("model")
    model, report = training.train(**SMALL)
    meta = training.save_artifacts(model, report, out)
    return out, model, report, meta


@pytest.fixture(autouse=True)
def _fresh_classifier():
    clf_mod.reset_classifier()
    yield
    clf_mod.reset_classifier()


@pytest.fixture
def use_artifact(monkeypatch):
    def _use(path: Path, **overrides):
        monkeypatch.setattr(clf_mod, "settings", dataclasses.replace(real_settings, doc_classifier_artifact_dir=path, **overrides))
        clf_mod.reset_classifier()

    return _use


# ---------------------------------------------------------------------------------------------- data + training
def test_dataset_is_deterministic_stratified_and_has_no_duplicates():
    a, b = generate_dataset(per_class=30, seed=5), generate_dataset(per_class=30, seed=5)
    assert a.texts == b.texts and a.labels == b.labels and a.fingerprint() == b.fingerprint()
    assert generate_dataset(per_class=30, seed=6).fingerprint() != a.fingerprint()
    assert {y: a.labels.count(y) for y in LABELS} == {y: 30 for y in LABELS}
    assert len(set(a.texts)) == len(a.texts)


def test_training_is_reproducible(trained):
    _, model, report, _ = trained
    model2, report2 = training.train(**SMALL)
    assert report["test"] == report2["test"] and report["dataset"] == report2["dataset"]
    probe = generate_dataset(per_class=5, seed=99).texts
    assert np.allclose(model.predict_proba(probe), model2.predict_proba(probe))


def test_test_split_is_held_out_and_report_is_computed_not_hardcoded(trained):
    _, _, report, _ = trained
    d = report["dataset"]
    assert d["train_size"] + d["test_size"] == d["total"] == 40 * len(LABELS)
    t = report["test"]
    assert t["n"] == d["test_size"] and sum(m["support"] for m in t["per_class"].values()) == t["n"]
    cm = np.array(t["confusion_matrix"]["rows_are_true_columns_are_predicted"])
    assert cm.sum() == t["n"] and np.trace(cm) / cm.sum() == pytest.approx(t["accuracy"])


# ------------------------------------------------------------------------------------------------- loading + inference
def test_artifact_loads_and_predicts_with_expected_structure(trained, use_artifact):
    out, _, _, meta = trained
    use_artifact(out)
    r = clf_mod.classify_text("Claim number CLM-12345 payer Example Assurance total billed $1200.00 allowed amount $900.00 CPT 99213 units 1 charge $145.00")
    assert r.status == clf_mod.CLASSIFIED and r.label in LABELS and r.model_version == meta["modelVersion"]
    assert 0.0 < r.score <= 1.0 and isinstance(r.low_confidence, bool) and r.truncated is False
    assert r.label == CLAIM_BILLING


def test_valid_documents_are_classified_correctly_on_fresh_synthetic_samples(trained, use_artifact):
    use_artifact(trained[0])
    fresh = generate_dataset(per_class=10, seed=2024)
    hits = sum(clf_mod.classify_text(t).label == y for t, y in zip(fresh.texts, fresh.labels))
    assert hits / len(fresh.texts) >= 0.85


def test_lab_style_text(trained, use_artifact):
    use_artifact(trained[0])
    assert clf_mod.classify_text("Haemoglobin: 11.2 g/dL L\nPlatelets result 250 x10^9/L\nSodium 139 mmol/L ref 135-145\nSpecimen venous blood accession LAB-45512").label == LABORATORY_RESULT


@pytest.mark.parametrize("value", ["", "   \n\t ", "ok", "\x00\x01\x02\x03"])
def test_empty_or_too_short_input_is_no_text(trained, use_artifact, value):
    use_artifact(trained[0])
    assert clf_mod.classify_text(value).status == clf_mod.NO_TEXT


@pytest.mark.parametrize("value", [None, 123, b"bytes", ["list"], {"a": 1}])
def test_non_string_input_is_rejected_safely(trained, use_artifact, value):
    use_artifact(trained[0])
    assert clf_mod.classify_text(value).status == clf_mod.ERROR
    with pytest.raises(ValueError):
        clf_mod.prepare_text(value, 100)


def test_oversized_input_is_truncated_not_rejected(trained, use_artifact):
    use_artifact(trained[0], doc_classifier_max_chars=500)
    r = clf_mod.classify_text("Claim number CLM-12345 billed charge CPT payer. " * 2000)
    assert r.status == clf_mod.CLASSIFIED and r.truncated is True
    assert len(clf_mod.prepare_text("a " * 10_000, 500)[0]) == 500


def test_ambiguous_text_is_flagged_low_confidence_or_other(trained, use_artifact):
    use_artifact(trained[0], doc_classifier_min_score=0.9)
    r = clf_mod.classify_text("see attached for details and kindly reply at your earliest convenience regarding the matter we discussed")
    assert r.status == clf_mod.CLASSIFIED and (r.low_confidence or r.label == OTHER)


def test_pages_are_joined(trained, use_artifact):
    use_artifact(trained[0])
    assert clf_mod.classify_pages(["", "Claim number CLM-1 billed charge CPT units payer allowed amount", ""]).status == clf_mod.CLASSIFIED
    assert clf_mod.classify_pages([""]).status == clf_mod.NO_TEXT


# --------------------------------------------------------------------------------------------------------- failures
def test_missing_artifact_is_unavailable_not_an_exception(tmp_path, use_artifact):
    use_artifact(tmp_path / "nope")
    assert clf_mod.classify_text(FILLER).status == clf_mod.UNAVAILABLE
    with pytest.raises(clf_mod.ClassifierUnavailable):
        clf_mod.get_classifier()


def test_tampered_model_file_is_refused_before_unpickling(trained, tmp_path, use_artifact):
    out = trained[0]
    (tmp_path / "metadata.json").write_bytes((out / "metadata.json").read_bytes())
    (tmp_path / "model.joblib").write_bytes((out / "model.joblib").read_bytes() + b"tamper")
    use_artifact(tmp_path)
    with pytest.raises(clf_mod.ClassifierUnavailable, match="checksum"):
        clf_mod.DocumentClassifier.load(tmp_path)
    assert clf_mod.classify_text(FILLER).status == clf_mod.UNAVAILABLE


def test_corrupt_metadata_and_version_skew_are_unavailable(trained, tmp_path):
    out = trained[0]
    (tmp_path / "model.joblib").write_bytes((out / "model.joblib").read_bytes())
    (tmp_path / "metadata.json").write_text("{not json")
    with pytest.raises(clf_mod.ClassifierUnavailable):
        clf_mod.DocumentClassifier.load(tmp_path)
    meta = json.loads((out / "metadata.json").read_text())
    meta["environment"]["scikit-learn"] = "0.20.0"
    (tmp_path / "metadata.json").write_text(json.dumps(meta))
    with pytest.raises(clf_mod.ClassifierUnavailable, match="Retrain"):
        clf_mod.DocumentClassifier.load(tmp_path)


def test_disabled_flag(trained, use_artifact):
    use_artifact(trained[0], doc_classifier_enabled=False)
    assert clf_mod.classify_text(FILLER).status == clf_mod.DISABLED


def test_inference_errors_become_error_status_and_never_log_document_text(trained, use_artifact, monkeypatch, caplog):
    use_artifact(trained[0])
    clf = clf_mod.get_classifier()

    def boom(*_a, **_k):
        raise ValueError(f"cannot process {CANARY}")

    monkeypatch.setattr(clf._pipeline, "predict_proba", boom)
    with caplog.at_level(logging.DEBUG):
        r = clf_mod.classify_text(f"{CANARY} " * 20)
    assert r.status == clf_mod.ERROR
    assert CANARY not in caplog.text


def test_shipped_artifact_loads_and_matches_its_metadata():
    shipped = training.DEFAULT_ARTIFACT_DIR
    if not (shipped / "model.joblib").exists():
        pytest.skip("no trained artifact in backend/ml/artifacts; run: python -m app.ml.training")
    clf = clf_mod.DocumentClassifier.load(shipped)
    assert clf.labels == sorted(LABELS) and clf.metadata["datasetSource"].startswith("synthetic")
