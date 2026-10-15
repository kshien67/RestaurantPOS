"""A tiny PDF writer for the virtual printer: one narrow page that looks like
the paper slip (same width, same fixed-width letters, same bold/big lines).

PDF files are text with a simple structure: numbered "objects" (the page,
the fonts, the drawing commands) and, at the end, a table ("xref") giving
the byte position of each object. Courier is one of the 14 fonts every PDF
reader has built in, so no font file needs to be embedded.
"""

CHAR_WIDTH = 0.6        # Courier letters are 0.6 x the font size wide
MARGIN = 10             # points (1 point = 1/72 inch)


def _escape(text):
    raw = text.encode("cp1252", errors="replace")      # PDF's standard Western encoding
    return raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def render(lines, width_chars, paper_mm=80):
    """Styled lines (text, style, align) -> the bytes of a one-page PDF."""
    page_w = paper_mm * 72 / 25.4
    size = (page_w - 2 * MARGIN) / (width_chars * CHAR_WIDTH)   # font size so a line fits
    leading = size * 1.25
    heights = [2 if style in ("big", "tall") else 1 for _text, style, _align in lines]
    page_h = 2 * MARGIN + leading * max(sum(heights), 1)

    ops = []
    y = page_h - MARGIN
    for (text, style, align), h in zip(lines, heights):
        y -= leading * h
        sx = 2 if style == "big" else 1                      # double width
        sy = 2 if style in ("big", "tall") else 1            # double height
        font = "F1" if style == "normal" else "F2"           # F2 = bold
        text_w = len(text) * CHAR_WIDTH * size * sx
        x = MARGIN if align == "left" else (page_w - text_w) / 2
        baseline = y + leading * 0.25 * h
        ops.append(b"BT /%s %.2f Tf %d 0 0 %d %.2f %.2f Tm (" % (
            font.encode(), size, sx, sy, x, baseline) + _escape(text) + b") Tj ET")
    stream = b"\n".join(ops)

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %.2f %.2f] "
        b"/Resources << /Font << /F1 5 0 R /F2 6 0 R >> >> /Contents 4 0 R >>" % (page_w, page_h),
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier /Encoding /WinAnsiEncoding >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier-Bold /Encoding /WinAnsiEncoding >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref_at = len(out)
    out += b"xref\n0 %d\n" % (len(objects) + 1)
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset                  # each entry is exactly 20 bytes
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1, xref_at)
    return bytes(out)


def write(lines, path, width_chars, paper_mm=80):
    path.write_bytes(render(lines, width_chars, paper_mm))
