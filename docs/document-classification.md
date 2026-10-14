# Document classification (ML)

HealthTrace suggests a **document type** for every uploaded document using a scikit-learn model. It is decision support: the suggestion is shown as *unverified*, a human reviewer can confirm or correct it, and nothing in policy evaluation depends on it.

> **Read this first.** The model is trained and tested only on *synthetic, fictional* text produced by `backend/app/ml/synthetic_data.py`. Its scores describe how well it learned that generator. They are **not** evidence of accuracy on real clinical, laboratory, or billing documents, and the feature has not been clinically validated. It is suitable for local demonstration, not for production use.

## What it does

| Item | Detail |
|---|---|
| Task | Single-label text classification of extracted document text |
| Model | `TfidfVectorizer` (word 1-2 grams, sublinear TF, min_df 2) + multinomial `LogisticRegression` (L2, `class_weight=balanced`) in one `sklearn.pipeline.Pipeline` |
| Labels | `CLINICAL_REPORT`, `IMAGING_REPORT`, `LABORATORY_RESULT`, `REFERRAL_ORDER`, `CLAIM_BILLING`, `POLICY_DOCUMENT`, `OTHER` (defined in `app/ml/labels.py`; display names in `LABEL_NAMES`) |
| Input | Text of the document's extracted pages (first `DOC_CLASSIFIER_MAX_CHARS` characters) |
| Output | label, `score`, `lowConfidence`, model version |

`score` is the top-class softmax output of the logistic regression. It is **not a calibrated probability** and the UI never shows it as a percentage. `lowConfidence` is true when it is below `DOC_CLASSIFIER_MIN_SCORE` (default 0.5, a convenience threshold, not a validated one).

The existing `documents.doc_type` column (derived from the filename: Referral / Policy / Imaging / Clinical / Supporting) is **unchanged** and still drives evidence extraction. The ML suggestion is stored in separate columns so rule results cannot change because of a model error.

## Where it runs

`services/processing.py` → `_run()`: right after page extraction (35 %), `classify_document()` (in `services/classification.py`) runs inside the existing background job. Inference takes milliseconds, so no new queue or endpoint is needed in the upload path. If the model is missing, corrupt, disabled, or throws, the document status becomes `UNAVAILABLE` / `ERROR` / `DISABLED` and **processing continues normally**. Images (no OCR in this build) and near-empty documents get `NO_TEXT` instead of a guess.

Every outcome writes an audit event (`Document type suggested` / `not suggested`, actor kind `AI`, reason "Machine suggestion; not verified"). Document text is never logged.

## API (additive; nothing existing was changed or removed)

* `document_dict` (used by `GET /api/documents/{id}`, `GET /api/cases/{id}/documents`, the upload response, case detail) gains a `classification` object:
  `{status, label, score, lowConfidence, modelVersion, classifiedAt, reviewedLabel, reviewedBy, reviewedAt, effectiveLabel}`.
  `status` is one of `NOT_RUN` (rows created before the feature), `CLASSIFIED`, `NO_TEXT`, `UNAVAILABLE`, `DISABLED`, `ERROR`.
* `PATCH /api/documents/{id}/classification` body `{"label": "<LABEL>" | null}`. Human correction; `null` clears it. Needs `evidence:verify` (reviewer, owner). Unknown labels → 422. Audited as `Document type reviewed`.
* `POST /api/documents/{id}/classification/retry`. Re-runs the model on the stored page text (reloads the artifact first). Needs `case:update`; document must be `PROCESSED` (else 409). A human correction is preserved.

All three resolve documents through the org-scoped `get_document`, so another organisation's document is indistinguishable from a missing one (404).

## Database

Migration `backend/alembic/versions/0002_document_classification.py` adds nine **nullable** columns to `documents` (`ml_status`, `ml_label`, `ml_score`, `ml_low_confidence`, `ml_model_version`, `ml_classified_at`, `reviewed_label`, `reviewed_label_by` → `users.id`, `reviewed_label_at`). It is purely additive: existing rows keep NULL and are reported as `NOT_RUN`. Verified on a throwaway PostgreSQL database (upgrade → downgrade → upgrade, then `alembic check` reported no model drift); it has **not** been applied to your development database. Apply it yourself: `cd backend && alembic upgrade head`.

## Train, evaluate, load

```powershell
cd backend
python -m pip install -r requirements-dev.txt      # includes scikit-learn
python -m app.ml.training                          # ~15 s on a laptop CPU; --seed 42 --per-class 300 are the defaults
python -m pytest tests/test_ml_classifier.py tests/test_document_classification_api.py -q
```

Training writes to `backend/ml/artifacts/document_classifier/` (override with `--out`):

* `model.joblib`: the fitted pipeline (about 250 KB)
* `metadata.json`: model version, labels, seed, dataset fingerprint, scikit-learn/numpy/scipy versions, `artifactSha256`
* `metrics.json`: the full held-out evaluation

Protocol (`app/ml/training.py`): generate 2100 synthetic documents (300 per class, seed 42, exact duplicates removed) → stratified 80/20 split (1680 train / 420 test) → choose `C ∈ {1, 3, 10, 30}` by 5-fold stratified CV **on the training split only** (the vectorizer is inside the pipeline so it is re-fitted per fold) → refit on the full training split → score the untouched test split once. Same seed and package versions give the same data, split, and metrics (covered by a test).

### Results (from `metrics.json`, model `tfidf-lr-synthetic-v1-d450ebf9`, scikit-learn 1.9.1)

Held-out synthetic test set (n = 420, 60 per class). Chosen `C = 10`; CV macro-F1 0.990.

| Class | Precision | Recall | F1 | n |
|---|---|---|---|---|
| CLAIM_BILLING | 1.000 | 0.983 | 0.992 | 60 |
| CLINICAL_REPORT | 1.000 | 1.000 | 1.000 | 60 |
| IMAGING_REPORT | 1.000 | 0.983 | 0.992 | 60 |
| LABORATORY_RESULT | 0.984 | 1.000 | 0.992 | 60 |
| OTHER | 1.000 | 1.000 | 1.000 | 60 |
| POLICY_DOCUMENT | 1.000 | 1.000 | 1.000 | 60 |
| REFERRAL_ORDER | 0.984 | 1.000 | 0.992 | 60 |

Accuracy 0.995, macro-F1 0.995, log-loss 0.086, Brier 0.030. Confusion matrix (rows true, columns predicted; order as in the table): the only errors are one CLAIM_BILLING → LABORATORY_RESULT and one IMAGING_REPORT → REFERRAL_ORDER.

**Why this number should not be trusted.** Train and test come from the same generator, so near-perfect scores mostly show that the pipeline works and that the generator's classes have distinguishable vocabulary. A first, easier version of the generator scored 1.000, so it was made harder (shorter documents, more cross-class sentences). That change was a general difficulty increase, not a response to individual errors on the challenge set below (which had already been scored once at that point), but the data is still templated.

**Distribution-shift probe.** `backend/ml/data/challenge_set.jsonl` holds 30 short fictional documents written by hand in different wording (built by `ml/data/build_challenge_set.py`). They were not used for training or model selection. Result: accuracy **0.900**, macro-F1 0.884, log-loss 0.63. Errors: 1 claim → laboratory, 1 claim → referral, 1 clinical → imaging; claim/billing recall was 0.50 (n = 4). With n = 30 this is indicative only (one document is 3.3 points). Documents scoring at or above 0.5 (70 % of them) were all correct; those below were 67 % correct, which is the intended use of `lowConfidence`, but again with a tiny sample.

### Artifact strategy

The artifact is small and fully reproducible, but `joblib` files are pickles: **only load artifacts you built yourself or trust**. The loader therefore verifies the SHA-256 recorded in `metadata.json` *before* unpickling, requires the same scikit-learn major.minor version as training, and checks that the model's classes match the metadata; any failure yields `UNAVAILABLE` rather than an exception. The checksum protects against corruption and accidental mismatches, not against someone who can rewrite both files. Decide whether to commit the artifact or build it in your deploy step (`python -m app.ml.training`); none of it is committed by this change. Real documents must never be added to the training data without a privacy and governance review.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `DOC_CLASSIFIER_ENABLED` | `true` | `false` skips classification (`DISABLED`) |
| `DOC_CLASSIFIER_ARTIFACT_DIR` | `backend/ml/artifacts/document_classifier` | where `model.joblib` and `metadata.json` live |
| `DOC_CLASSIFIER_MIN_SCORE` | `0.5` | below this, `lowConfidence` is set |
| `DOC_CLASSIFIER_MAX_CHARS` | `20000` | input is truncated to this many characters |

Runs on CPU only; no GPU. Dependency: `scikit-learn>=1.5,<2` (pulls numpy, scipy, joblib).

## Frontend

On the case page, each processed document in the **Documents** list shows `Model suggestion: <type>` with a "Not verified" tag (and "Low model score: check carefully" when applicable), any reviewer-set type with the reviewer's name, a **Confirm or correct type** control, and **Retry suggestion** when the model was unavailable. The control is shown to all roles; the backend enforces permissions and the error is displayed. Component: `frontend/src/components/DocumentClassification.tsx`; tests: `npm test`.

## Evidence extraction and policy matching (reviewed, not changed)

The existing pipeline already ties every finding to source evidence: facts come from verbatim sentences validated against the page text (`services/processing.py`), evidence rows carry document and page, and `services/analysis.py` evaluates deterministic rules to `MATCH` / `MISSING` / `CONFLICT` / `INCONCLUSIVE` with the documents searched recorded; a missing finding states that no qualifying evidence was found, not that the event did not occur. That behaviour is rule-based, not ML, and was left as is. Added alongside it (rule-based, **not ML**, nothing persisted): `GET /api/documents/{id}/structured-fields` (`case:view`, org-scoped) returns dates and lab-style results (`HbA1c 58 mmol/mol H`) computed on demand from stored pages, each with page and exact character span (`services/structured_extraction.py`). Ambiguous numeric dates such as `03/04/2025` are returned unparsed, and the response states that absence of a field proves nothing. It is not yet shown in the UI and does not feed policy rules. Still not implemented: using the document-type suggestion to prioritise which documents are searched.

## Known limitations

* Synthetic-only training and evaluation (see above); real-document performance is unknown and likely lower.
* English only; no OCR, so scanned images and image-only PDFs get `NO_TEXT`.
* Only the first 20,000 characters are used; very long, mixed-type files (a "packet" of several documents) get one label.
* The score is uncalibrated; the 0.5 threshold is not tuned on real data.
* The classification is not used for policy rules by design.
* No automated retraining, drift monitoring, or labelled-feedback export exists (reviewer corrections are stored and audited, but not fed back).
* Not a HIPAA compliance claim, not clinically validated, not production-ready.
