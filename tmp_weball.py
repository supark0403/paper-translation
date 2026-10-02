# -*- coding: utf-8 -*-
"""웹으로 4개 파일 순차 투입 → 각각 다운로드. FIFO이므로 순서대로 돈다."""
import sys
sys.path.insert(0, ".")
from tmp_webrun import upload, wait_done
import urllib.request, re

BASE = "http://localhost:8040"
jobs = [
    ("test/4..pdf", "", "outputs/web_slide_ko.pdf"),
    ("test/1.ROME-locating-and-editing-factual-associations-in-gpt-Paper-Conference.pdf", "", "outputs/web_rome_ko.pdf"),
    ("test/2.MEMIT.pdf", "", "outputs/web_memit_ko.pdf"),
    ("test/3.AlphaEdit_Null_Space_Cons.pdf", "", "outputs/web_alpha_ko.pdf"),
]
for pdf, pages, out in jobs:
    jid = upload(pdf, pages)
    print("JOB", pdf.split("/")[-1][:25], jid, flush=True)
    if not jid or not wait_done(jid, timeout_min=180):
        print("FAILED", pdf, flush=True)
        continue
    html = urllib.request.urlopen(BASE + "/", timeout=15).read().decode("utf-8", "ignore")
    m = re.search(re.escape(jid) + r"[\s\S]{0,3000}?완료: ([^\s<]+\.pdf)", html)
    if m and out:
        from pathlib import Path as _P
        dl = urllib.request.urlopen(BASE + "/download/" + _P(m.group(1)).name, timeout=300).read()
        open(out, "wb").write(dl)
        print("saved", out, len(dl), flush=True)
print("ALL QUEUED/DONE")
