# -*- coding: utf-8 -*-
"""4개 동시 투입 → ping 유지 → 완료마다 다운로드."""
import sys, time, re, urllib.request
sys.path.insert(0, ".")
from tmp_webrun import upload
from pathlib import Path

BASE = "http://localhost:8040"
PING = urllib.request.Request(BASE + "/ping", data=b"", method="POST")
FILES = [
    ("test/4..pdf", "outputs/web_slide_ko.pdf"),
    ("test/1.ROME-locating-and-editing-factual-associations-in-gpt-Paper-Conference.pdf", "outputs/web_rome_ko.pdf"),
    ("test/2.MEMIT.pdf", "outputs/web_memit_ko.pdf"),
    ("test/3.AlphaEdit_Null_Space_Cons.pdf", "outputs/web_alpha_ko.pdf"),
]
jids = []
for pdf, _ in FILES:
    j = upload(pdf, "")
    jids.append(j)
    print("queued", pdf.split("/")[-1][:25], j, flush=True)

pending = dict(zip(jids, [o for _, o in FILES]))
for i in range(800):
    time.sleep(15)
    try:
        urllib.request.urlopen(PING, timeout=10)
        h = urllib.request.urlopen(BASE + "/", timeout=15).read().decode("utf-8", "ignore")
    except Exception as e:
        print("server gone?", e, flush=True)
        break
    for j in list(pending):
        m = re.search(re.escape(j) + r" — (\d+)% ([^<]+)", h)
        st = m.group(0)[:100] if m else "?"
        if m and ("done" in st or "error" in st or "cancelled" in st):
            print(f"[{j}] FINISHED {st}", flush=True)
            out = pending.pop(j)
            om = re.search(re.escape(j) + r"[\s\S]{0,3000}?완료: ([^\s<]+\.pdf)", h)
            if om:
                dl = urllib.request.urlopen(BASE + "/download/" + Path(om.group(1)).name, timeout=300).read()
                open(out, "wb").write(dl)
                print("saved", out, len(dl), flush=True)
    if not pending:
        break
    if i % 4 == 0:
        print(f".. waiting {list(pending)}", flush=True)
print("DONE pending=", list(pending))
