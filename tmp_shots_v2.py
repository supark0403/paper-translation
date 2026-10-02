# -*- coding: utf-8 -*-
import pymupdf
from PIL import Image

JOBS = [
    ("test/4..pdf", "outputs/v2_slide_ko.pdf", "v2s", [2, 5]),
    ("test/1.ROME-locating-and-editing-factual-associations-in-gpt-Paper-Conference.pdf", "outputs/v2_rome_ko.pdf", "v2r", [5, 9, 11, 13]),
    ("test/2.MEMIT.pdf", "outputs/v2_memit_ko.pdf", "v2m", [0, 4, 9, 16]),
    ("test/3.AlphaEdit_Null_Space_Cons.pdf", "outputs/v2_alpha_ko.pdf", "v2a", [5, 10, 17, 25]),
]
for orig_path, ko_path, tag, pages in JOBS:
    orig = pymupdf.open(orig_path)
    ko = pymupdf.open(ko_path)
    for i in pages:
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
    print(tag, "done")
