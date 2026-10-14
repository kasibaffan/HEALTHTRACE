"""Inference service for the document classifier.

Loads the trained scikit-learn pipeline once (lazily, thread-safe) and exposes `classify_pages`, which never raises:
failures become a `ClassificationResult` with a non-CLASSIFIED status so document processing can continue.
Document text is never logged. The model output is a SUGGESTION, not a verified fact.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings
from app.ml.labels import OTHER, is_valid_label

log = logging.getLogger("healthtrace.ml")

CLASSIFIED = "CLASSIFIED"
NO_TEXT = "NO_TEXT"
UNAVAILABLE = "UNAVAILABLE"
DISABLED = "DISABLED"
ERROR = "ERROR"
MIN_WORDS = 5
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class ClassifierUnavailable(RuntimeError):
    """The model artifact is missing, corrupt, tampered with, or incompatible with this environment."""


@dataclass(frozen=True)
class ClassificationResult:
    status: str
    label: str | None = None
    score: float | None = None
    low_confidence: bool = False
    model_version: str | None = None
    truncated: bool = False


def prepare_text(value: object, max_chars: int) -> tuple[str, bool]:
    """Validates and normalises input. Raises ValueError for unsupported input types."""
    if not isinstance(value, str):
        raise ValueError("Document text must be a string.")
    cleaned = _CONTROL.sub(" ", value)
    cleaned = re.sub(r"[ \t]+", " ", cleaned).strip()
    truncated = len(cleaned) > max_chars
    return (cleaned[:max_chars] if truncated else cleaned), truncated


class DocumentClassifier:
    def __init__(self, pipeline, metadata: dict):
        self._pipeline = pipeline
        self.metadata = metadata
        self.model_version: str = metadata["modelVersion"]
        self.labels: list[str] = list(metadata["labels"])

    @classmethod
    def load(cls, artifact_dir: Path) -> "DocumentClassifier":
        meta_path, model_path = artifact_dir / "metadata.json", artifact_dir / "model.joblib"
        if not meta_path.is_file() or not model_path.is_file():
            raise ClassifierUnavailable("model artifact not found")
        try:
            metadata = json.loads(meta_path.read_text(encoding="utf-8"))
            expected, version, labels = metadata["artifactSha256"], metadata["modelVersion"], metadata["labels"]
        except (OSError, ValueError, KeyError) as exc:
            raise ClassifierUnavailable("model metadata unreadable or incomplete") from exc
        if not isinstance(labels, list) or not all(is_valid_label(x) for x in labels) or not isinstance(version, str):
            raise ClassifierUnavailable("model metadata has unexpected labels")
        raw = model_path.read_bytes()
        # Integrity check BEFORE unpickling: joblib files are pickles and must only come from a trusted build.
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ClassifierUnavailable("model artifact does not match its recorded checksum")
        try:
            import io

            import joblib
            import sklearn

            trained = (metadata.get("environment") or {}).get("scikit-learn", "")
            if trained.split(".")[:2] != sklearn.__version__.split(".")[:2]:
                raise ClassifierUnavailable(f"model was trained with scikit-learn {trained}; installed is {sklearn.__version__}. Retrain with python -m app.ml.training")
            pipeline = joblib.load(io.BytesIO(raw))
        except ClassifierUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001 - ImportError, unpickling errors, version skew
            raise ClassifierUnavailable(f"model could not be loaded ({type(exc).__name__})") from exc
        if [str(c) for c in getattr(pipeline, "classes_", [])] != [str(x) for x in labels]:
            raise ClassifierUnavailable("model classes do not match metadata")
        return cls(pipeline, metadata)

    def predict(self, text: str, min_score: float) -> ClassificationResult:
        proba = self._pipeline.predict_proba([text])[0]
        best = int(proba.argmax())
        score = float(proba[best])
        return ClassificationResult(CLASSIFIED, self.labels[best], round(score, 4), score < min_score, self.model_version)


_lock = threading.Lock()
_classifier: DocumentClassifier | None = None
_failure: str | None = None


def get_classifier() -> DocumentClassifier:
    """Loads on first use and caches the outcome (including failure) for the process lifetime."""
    global _classifier, _failure
    if _classifier is not None:
        return _classifier
    with _lock:
        if _classifier is None:
            if _failure is not None:
                raise ClassifierUnavailable(_failure)
            try:
                _classifier = DocumentClassifier.load(settings.doc_classifier_artifact_dir)
                log.info("document classifier loaded", extra={"model_version": _classifier.model_version})
            except ClassifierUnavailable as exc:
                _failure = str(exc)
                log.warning("document classifier unavailable: %s", exc)
                raise
    return _classifier


def reset_classifier() -> None:
    """Forget the cached model/failure (used by tests and after re-training without a restart)."""
    global _classifier, _failure
    with _lock:
        _classifier, _failure = None, None


def classify_text(text: object) -> ClassificationResult:
    if not settings.doc_classifier_enabled:
        return ClassificationResult(DISABLED)
    try:
        cleaned, truncated = prepare_text(text, settings.doc_classifier_max_chars)
    except ValueError:
        return ClassificationResult(ERROR)
    if len(cleaned.split()) < MIN_WORDS:
        return ClassificationResult(NO_TEXT)
    try:
        clf = get_classifier()
    except ClassifierUnavailable:
        return ClassificationResult(UNAVAILABLE)
    try:
        result = clf.predict(cleaned, settings.doc_classifier_min_score)
    except Exception as exc:  # noqa: BLE001 - never let inference break document processing
        log.error("document classification failed: %s", type(exc).__name__)  # exception type only: messages can echo input
        return ClassificationResult(ERROR, model_version=clf.model_version)
    return ClassificationResult(result.status, result.label, result.score, result.low_confidence, result.model_version, truncated)


def classify_pages(pages: list[str]) -> ClassificationResult:
    """Classify a whole document from its extracted pages (only the first `doc_classifier_max_chars` characters are used)."""
    try:
        joined = "\n".join(p for p in pages if isinstance(p, str))
    except TypeError:
        return ClassificationResult(ERROR)
    return classify_text(joined)


__all__ = ["CLASSIFIED", "NO_TEXT", "UNAVAILABLE", "DISABLED", "ERROR", "OTHER", "ClassificationResult", "ClassifierUnavailable", "DocumentClassifier",
           "classify_pages", "classify_text", "get_classifier", "prepare_text", "reset_classifier"]
