import io
import re
import uuid
import zipfile
from pathlib import PurePosixPath, PureWindowsPath

from app.core.config import settings
from app.core.errors import AppError

ALLOWED_EXTENSIONS = {".pdf": "application/pdf", ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                      ".txt": "text/plain", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}


def _detect(data: bytes) -> str | None:
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                if "word/document.xml" in z.namelist():
                    return ALLOWED_EXTENSIONS[".docx"]
        except zipfile.BadZipFile:
            return None
        return None
    if b"\x00" not in data[:4096]:
        try:
            data.decode("utf-8")
            return "text/plain"
        except UnicodeDecodeError:
            return None
    return None


def display_name(filename: str | None) -> str:
    """Strip any path component and unsafe characters. Only used for display; storage names are generated."""
    base = PureWindowsPath(PurePosixPath(filename or "document").name).name
    cleaned = re.sub(r"[^A-Za-z0-9._ \-()]", "_", base).strip(" .") or "document"
    return cleaned[:200]


def validate_upload(filename: str | None, data: bytes) -> tuple[str, str]:
    """Returns (extension, detected_mime). The client-declared content type is deliberately ignored."""
    name = display_name(filename)
    ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise AppError(415, "Unsupported file type. Allowed: PDF, DOCX, TXT, PNG, JPG.", "unsupported_type")
    if not data:
        raise AppError(400, "The file is empty.", "empty_file")
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise AppError(413, f"File exceeds the {settings.max_upload_mb} MB limit.", "too_large")
    detected = _detect(data)
    if detected != ALLOWED_EXTENSIONS[ext]:
        raise AppError(415, "The file content does not match its extension.", "content_mismatch")
    return ext, detected


def storage_key(org_id: uuid.UUID, case_id: uuid.UUID, ext: str) -> str:
    return f"{org_id}/{case_id}/{uuid.uuid4().hex}{ext}"


def classify_doc_type(filename: str) -> str:
    n = filename.lower()
    if "referral" in n:
        return "Referral"
    if "policy" in n:
        return "Policy"
    if any(k in n for k in ("imaging", "radiolog", "mri", "xray", "x-ray", "scan")):
        return "Imaging"
    if any(k in n for k in ("clinical", "note", "progress", "discharge")):
        return "Clinical"
    return "Supporting"
