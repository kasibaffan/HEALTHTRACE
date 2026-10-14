"""Tiny dependency-free PDF writer used to generate the synthetic demo documents (real PDFs, real text layer)."""


def _esc(text: str) -> str:
    text = text.encode("latin-1", "replace").decode("latin-1")
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def make_pdf(pages: list[tuple[str, list[str]]]) -> bytes:
    """pages: [(heading, [lines])]. Returns PDF bytes with one page per entry."""
    longest = max((len(line) for _, lines in pages for line in lines), default=60)
    body_size = max(7.5, min(10.5, 495 / (0.52 * longest)))

    objects: list[bytes] = []

    def add(payload: str | bytes) -> int:
        objects.append(payload.encode("latin-1") if isinstance(payload, str) else payload)
        return len(objects)

    add("<< /Type /Catalog /Pages 2 0 R >>")
    add("")  # pages placeholder (object 2)
    add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>")

    page_ids = []
    for heading, lines in pages:
        ops = [f"BT /F2 15 Tf 50 750 Td ({_esc(heading)}) Tj ET"]
        y = 715
        for line in lines:
            ops.append(f"BT /F1 {body_size:.1f} Tf 50 {y} Td ({_esc(line)}) Tj ET")
            y -= 24
        stream = "\n".join(ops)
        content_id = add(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
        page_ids.append(add(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {content_id} 0 R /Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> >>"))

    objects[1] = f"<< /Type /Pages /Kids [{' '.join(f'{i} 0 R' for i in page_ids)}] /Count {len(page_ids)} >>".encode("latin-1")

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)
