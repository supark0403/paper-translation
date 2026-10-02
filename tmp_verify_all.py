# -*- coding: utf-8 -*-
import sys
sys.path.insert(0, ".")
from tmp_verify import check
pairs = [
    ("test/4..pdf", "outputs/4._4_ko.pdf", "slide"),
    ("test/1.ROME-locating-and-editing-factual-associations-in-gpt-Paper-Conference.pdf",
     "outputs/1.ROME-locating-and-editing-factual-associations-in-gpt-Paper-Conference_3_ko.pdf", "rome"),
    ("test/2.MEMIT.pdf", "outputs/2.MEMIT_3_ko.pdf", "memit"),
    ("test/3.AlphaEdit_Null_Space_Cons.pdf", "outputs/3.AlphaEdit_Null_Space_Cons_3_ko.pdf", "alpha"),
]
total = 0
for a, b, n in pairs:
    try:
        total += check(a, b, n)
    except Exception as e:
        print("ERR", n, e)
print("TOTAL:", total)
