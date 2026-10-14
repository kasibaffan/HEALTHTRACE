import io
import re

_SENTENCE_END = re.compile(r"[.!?:]$")


def extract_pages(data: bytes, ext: str) -> list[str]:
    """Returns one string per page. Images (no OCR in this build) yield a single empty page."""
    if ext == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise ValueError("Encrypted PDFs are not supported.")
        return [(p.extract_text() or "") for p in reader.pages] or [""]
    if ext == ".docx":
        from docx import Document as DocxDocument

        doc = DocxDocument(io.BytesIO(data))
        pages, current = [], []
        for para in doc.paragraphs:
            current.append(para.text)
            if 'w:br w:type="page"' in para._p.xml or "w:lastRenderedPageBreak" in para._p.xml:
                pages.append("\n".join(current))
                current = []
        pages.append("\n".join(current))
        return [p for p in pages if p.strip()] or [""]
    if ext == ".txt":
        text = data.decode("utf-8", errors="replace")
        return [p for p in text.split("\f")] or [""]
    return [""]


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def paragraphs(page_text: str) -> list[str]:
    """Merges hard-wrapped continuation lines (next line starts lowercase) into one paragraph."""
    out: list[str] = []
    for raw in page_text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if out and not _SENTENCE_END.search(out[-1]) and line[0].islower():
            out[-1] += " " + line
        else:
            out.append(line)
    return out
