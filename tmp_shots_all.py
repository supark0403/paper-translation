# -*- coding: utf-8 -*-
"""전 페이지 좌우 비교샷 생성 (PIL 합성)."""
import sys
import pymupdf
from PIL import Image

PAIRS = [
    ("test/4..pdf", "outputs/4._4_ko.pdf", "cmp_slide"),
    ("test/1.ROME-locating-and-editing-factual-associations-in-gpt-Paper-Conference.pdf", "outputs/1.ROME-locating-and-editing-factual-associations-in-gpt-Paper-Conference_3_ko.pdf", "cmp_rome"),
    ("test/2.MEMIT.pdf", "outputs/2.MEMIT_3_ko.pdf", "cmp_memit"),
    ("test/3.AlphaEdit_Null_Space_Cons.pdf", "outputs/3.AlphaEdit_Null_Space_Cons_3_ko.pdf", "cmp_alpha"),
]

if len(sys.argv) > 1:
    only = sys.argv[1]
    PAIRS = [p for p in PAIRS if only in p[2]]

for orig_path, ko_path, tag in PAIRS:
    try:
        orig = pymupdf.open(orig_path)
        ko = pymupdf.open(ko_path)
    except Exception as e:
        print(tag, "SKIP", e)
        continue
    assert len(orig) == len(ko), f"{tag} 페이지 수 불일치"
    for i in range(len(orig)):
        o = orig[i].get_pixmap(dpi=80)
        k = ko[i].get_pixmap(dpi=80)
        o.save(f"outputs/{tag}_o{i}.png")
        k.save(f"outputs/{tag}_k{i}.png")
        io_ = Image.open(f"outputs/{tag}_o{i}.png")
        ik = Image.open(f"outputs/{tag}_k{i}.png")
        w = max(io_.width, ik.width)
        h = max(io_.height, ik.height)
        combo = Image.new("RGB", (w * 2 + 10, h), "white")
        combo.paste(io_, (0, 0))
        combo.paste(ik, (w + 10, 0))
        combo.save(f"outputs/{tag}_p{i}.png")
    print(tag, len(orig), "pages done")
