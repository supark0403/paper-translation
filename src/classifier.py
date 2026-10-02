"""paper(논문) vs slide(PPT형) 분류."""
from __future__ import annotations

import pymupdf  # type: ignore

from . import config


def classify(pdf_path: str) -> dict:
    doc = pymupdf.open(pdf_path)
    n = len(doc)
    landscape = 0
    total_blocks = 0
    font_sizes: list[float] = []
    for i in range(min(n, 6)):
        page = doc[i]
        if page.rect.width > page.rect.height * 1.05:
            landscape += 1
        d = page.get_text("dict")
        nb = 0
        for b in d["blocks"]:
            if b["type"] == 0:
                t = "".join(s["text"] for l in b["lines"] for s in l["spans"]).strip()
                if len(t) >= 2:
                    nb += 1
                for l in b["lines"]:
                    for s in l["spans"]:
                        font_sizes.append(float(s["size"]))
        total_blocks += nb
    doc.close()
    avg_blocks = total_blocks / max(1, min(n, 6))
    avg_fs = sum(font_sizes) / max(1, len(font_sizes))
    w0, h0 = _first_size(pdf_path)
    aspect = w0 / max(1.0, h0)
    is_slide = (
        (aspect >= 1.15 and landscape >= min(n, 6) // 2)
        or (avg_blocks <= config.SLIDE_MAX_AVG_BLOCKS and avg_fs >= config.SLIDE_MIN_AVG_FONTSIZE and aspect > 1.0)
    )
    kind = "slide" if is_slide else "paper"
    return {
        "kind": kind,
        "pages": n,
        "aspect": round(aspect, 3),
        "avg_blocks": round(avg_blocks, 1),
        "avg_fontsize": round(avg_fs, 1),
    }


def _first_size(pdf_path: str):
    doc = pymupdf.open(pdf_path)
    r = doc[0].rect
    doc.close()
    return r.width, r.height
