"""Training and evaluation of the document classifier. Run with:  python -m app.ml.training  (see --help).

Protocol
  1. Generate synthetic documents (fixed seed) and split them 80/20, stratified by class. The test split is set aside.
  2. On the training split only, choose the regularisation strength C by 5-fold stratified cross-validation. The TF-IDF
     vectorizer lives inside the scikit-learn Pipeline, so it is re-fitted on each training fold and never sees held-out text.
  3. Re-fit the winning pipeline on the whole training split, then score the untouched test split once.
  4. Also score a small hand-written challenge set that did not come from the generator (a distribution-shift probe).
Nothing here is evidence of accuracy on real documents.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from app.ml.labels import LABELS
from app.ml.synthetic_data import Dataset, generate_dataset

BACKEND_DIR = Path(__file__).resolve().parents[2]
DEFAULT_ARTIFACT_DIR = BACKEND_DIR / "ml" / "artifacts" / "document_classifier"
CHALLENGE_SET = BACKEND_DIR / "ml" / "data" / "challenge_set.jsonl"
C_GRID = (1.0, 3.0, 10.0, 30.0)
DEFAULT_MIN_SCORE = 0.5
ALGORITHM = "TfidfVectorizer(word 1-2grams, sublinear_tf) + LogisticRegression(multinomial, L2, class_weight=balanced)"


def build_pipeline(c: float, seed: int):
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline

    return Pipeline([
        ("tfidf", TfidfVectorizer(lowercase=True, strip_accents="unicode", ngram_range=(1, 2), min_df=2, max_df=0.9, sublinear_tf=True, max_features=30000, dtype=np.float32)),
        ("clf", LogisticRegression(C=c, max_iter=2000, class_weight="balanced", solver="lbfgs", random_state=seed)),
    ])


def _brier(proba: np.ndarray, y_true: list[str], classes: list[str]) -> float:
    idx = {c: i for i, c in enumerate(classes)}
    onehot = np.zeros_like(proba)
    for row, y in enumerate(y_true):
        onehot[row, idx[y]] = 1.0
    return float(np.mean(np.sum((proba - onehot) ** 2, axis=1)))


def evaluate(pipeline, texts: list[str], labels: list[str], min_score: float = DEFAULT_MIN_SCORE) -> dict:
    from sklearn.metrics import accuracy_score, confusion_matrix, log_loss, precision_recall_fscore_support

    classes = [str(c) for c in pipeline.classes_]
    proba = pipeline.predict_proba(texts)
    pred = [classes[i] for i in proba.argmax(axis=1)]
    p, r, f, support = precision_recall_fscore_support(labels, pred, labels=classes, zero_division=0)
    top = proba.max(axis=1)
    kept = top >= min_score
    correct = np.array([a == b for a, b in zip(pred, labels)])
    return {
        "n": len(labels),
        "accuracy": float(accuracy_score(labels, pred)),
        "macro_precision": float(p.mean()), "macro_recall": float(r.mean()), "macro_f1": float(f.mean()),
        "per_class": {c: {"precision": float(p[i]), "recall": float(r[i]), "f1": float(f[i]), "support": int(support[i])} for i, c in enumerate(classes)},
        "confusion_matrix": {"labels": classes, "rows_are_true_columns_are_predicted": confusion_matrix(labels, pred, labels=classes).tolist()},
        "log_loss": float(log_loss(labels, proba, labels=classes)),
        "brier_score": _brier(proba, labels, classes),
        "selective": {"min_score": min_score, "coverage": float(kept.mean()),
                      "accuracy_when_scored_at_or_above_min": float(correct[kept].mean()) if kept.any() else None,
                      "accuracy_when_below_min": float(correct[~kept].mean()) if (~kept).any() else None},
    }


def load_challenge_set(path: Path = CHALLENGE_SET) -> tuple[list[str], list[str]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [r["text"] for r in rows], [r["label"] for r in rows]


def train(per_class: int = 300, seed: int = 42, test_size: float = 0.2, cv_folds: int = 5, c_grid: tuple[float, ...] = C_GRID,
          challenge_path: Path | None = CHALLENGE_SET) -> tuple[object, dict]:
    """Returns (fitted pipeline, report). Pure function of its arguments (no files written)."""
    from sklearn.model_selection import StratifiedKFold, cross_val_score, train_test_split

    data: Dataset = generate_dataset(per_class=per_class, seed=seed)
    x_train, x_test, y_train, y_test = train_test_split(data.texts, data.labels, test_size=test_size, stratify=data.labels, random_state=seed)
    assert not (set(x_train) & set(x_test)), "train/test overlap"

    cv = StratifiedKFold(n_splits=cv_folds, shuffle=True, random_state=seed)
    cv_scores = {}
    for c in c_grid:
        cv_scores[c] = float(np.mean(cross_val_score(build_pipeline(c, seed), x_train, y_train, cv=cv, scoring="f1_macro")))
    best_c = max(c_grid, key=lambda c: (cv_scores[c], -c))  # ties -> stronger regularisation

    model = build_pipeline(best_c, seed).fit(x_train, y_train)
    report = {
        "seed": seed,
        "dataset": {"source": "synthetic (app.ml.synthetic_data)", "per_class_requested": per_class, "total": len(data.texts), "sha256": data.fingerprint(),
                    "train_size": len(x_train), "test_size": len(x_test),
                    "class_distribution_train": {c: y_train.count(c) for c in LABELS}, "class_distribution_test": {c: y_test.count(c) for c in LABELS}},
        "model_selection": {"cv_folds": cv_folds, "metric": "f1_macro", "cv_scores_by_C": {str(c): s for c, s in cv_scores.items()}, "chosen_C": best_c,
                            "vocabulary_size": len(model.named_steps["tfidf"].vocabulary_)},
        "test": evaluate(model, x_test, y_test),
    }
    if challenge_path and Path(challenge_path).exists():
        cx, cy = load_challenge_set(Path(challenge_path))
        report["challenge_set"] = {"description": "hand-written, not from the generator; n is small, treat as indicative", **evaluate(model, cx, cy)}
    return model, report


def save_artifacts(model, report: dict, out_dir: Path, min_score: float = DEFAULT_MIN_SCORE) -> dict:
    import joblib
    import scipy
    import sklearn

    out_dir.mkdir(parents=True, exist_ok=True)
    model_path = out_dir / "model.joblib"
    joblib.dump(model, model_path, compress=3)
    digest = hashlib.sha256(model_path.read_bytes()).hexdigest()
    version = f"tfidf-lr-synthetic-v1-{report['dataset']['sha256'][:8]}"
    meta = {
        "modelVersion": version, "algorithm": ALGORITHM, "labels": [str(c) for c in model.classes_], "minScoreDefault": min_score,
        "scoreMeaning": "Top-class softmax output of the logistic regression. NOT a calibrated probability; do not present it as a percentage chance of being correct.",
        "trainedAtUtc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "seed": report["seed"],
        "datasetSha256": report["dataset"]["sha256"], "datasetSource": report["dataset"]["source"],
        "trainSize": report["dataset"]["train_size"], "testSize": report["dataset"]["test_size"],
        "chosenC": report["model_selection"]["chosen_C"],
        "artifactSha256": digest,
        "environment": {"python": platform.python_version(), "scikit-learn": sklearn.__version__, "numpy": np.__version__, "scipy": scipy.__version__},
        "warning": "Trained on synthetic fictional text only. Not validated on real documents. Decision support, not a clinical or coding decision.",
    }
    (out_dir / "metadata.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    (out_dir / "metrics.json").write_text(json.dumps({"modelVersion": version, **report}, indent=2) + "\n", encoding="utf-8")
    return meta


def format_summary(report: dict) -> str:
    t = report["test"]
    lines = [f"Test accuracy {t['accuracy']:.3f}  macro-F1 {t['macro_f1']:.3f}  (n={t['n']}; synthetic, same generator as training)"]
    for c, m in t["per_class"].items():
        lines.append(f"  {c:<18} P {m['precision']:.3f}  R {m['recall']:.3f}  F1 {m['f1']:.3f}  n={m['support']}")
    if "challenge_set" in report:
        ch = report["challenge_set"]
        lines.append(f"Challenge set accuracy {ch['accuracy']:.3f}  macro-F1 {ch['macro_f1']:.3f}  (n={ch['n']}, hand-written)")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Train and evaluate the HealthTrace document classifier on synthetic data.")
    ap.add_argument("--per-class", type=int, default=300)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", type=Path, default=DEFAULT_ARTIFACT_DIR, help="artifact directory (default: backend/ml/artifacts/document_classifier)")
    args = ap.parse_args(argv)
    model, report = train(per_class=args.per_class, seed=args.seed)
    meta = save_artifacts(model, report, args.out)
    print(format_summary(report))
    print(f"Saved {meta['modelVersion']} to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
