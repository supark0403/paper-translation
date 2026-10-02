# -*- coding: utf-8 -*-
import pymupdf
orig = pymupdf.open("test/4..pdf")
ko = pymupdf.open("outputs/4._3_ko.pdf")
print("pages:", len(orig), len(ko))
for i in range(len(orig)):
    o = orig[i].get_pixmap(dpi=90)
    k = ko[i].get_pixmap(dpi=90)
    w, h = o.width, o.height
    combo = pymupdf.Pixmap(o.colorspace, (0, 0, w * 2 + 10, h), o.alpha)
    combo.set_rect(combo.irect, (255, 255, 255))
    combo.copy(o, o.irect)
    combo.copy(k, pymupdf.IRect(w + 10, 0, w * 2 + 10, h))
    combo.save(f"outputs/cmp_p{i}.png")
    print("saved cmp_p%d.png" % i)
