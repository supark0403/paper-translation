# -*- coding: utf-8 -*-
"""완료 대기 → 다운로드 → 전 페이지 좌우 스크린샷 → 자동 검증."""
import sys, time, re, urllib.request
sys.path.insert(0, ".")
from pathlib import Path

BASE = "http://localhost:8040"
JIDS = ["job68756_2", "job68762_3", "job68768_4"]
ORIGS = {
    "job68756_2": "test/1.ROME-locating-and-editing-factual-associations-in-gpt-Paper-Conference.pdf",
    "job68762_3": "test/2.MEMIT.pdf",
    "job68768_4": "test/3.AlphaEdit_Null_Space_Cons.pdf",
}
OUTS = {"job68756_2": "outputs/web_rome_ko.pdf",
        "job68762_3": "outputs/web_memit_ko.pdf",
        "job68768_4": "outputs/web_alpha_ko.pdf"}

def html():
    return urllib.request.urlopen(BASE + "/", timeout=15).read().decode("utf-8", "ignore")

pending = set(JIDS)
PING = urllib.request.Request(BASE + "/ping", data=b"", method="POST")
for i in range(240):
    time.sleep(30)
    try:
        urllib.request.urlopen(PING, timeout=10)
        h = html()
    except Exception as e:
        print("server gone?", e, flush=True)
        break
    for j in list(pending):
        m = re.search(re.escape(j) + r" — (\d+)% ([^<]+)", h)
        st = m.group(0)[:90] if m else "?"
        if m and ("done" in st or "error" in st or "cancelled" in st):
            print(f"[{j}] FINISHED {st}", flush=True)
            pending.discard(j)
            om = re.search(re.escape(j) + r"[\s\S]{0,3000}?완료: ([^\s<]+\.pdf)", h)
            if om and j in OUTS:
                dl = urllib.request.urlopen(BASE + "/download/" + Path(om.group(1)).name, timeout=300).read()
                open(OUTS[j], "wb").write(dl)
                print("saved", OUTS[j], len(dl), flush=True)
    if not pending:
        break
    if i % 4 == 0:
        print(f".. waiting {pending}", flush=True)
print("DONE pending=", pending)
