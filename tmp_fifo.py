# -*- coding: utf-8 -*-
"""4개 동시 투입 (대기 없이) → 상태 스냅샷으로 FIFO 검증."""
import sys, time
sys.path.insert(0, ".")
from tmp_webrun import upload
import urllib.request, re

BASE = "http://localhost:8040"
files = ["test/4..pdf",
         "test/1.ROME-locating-and-editing-factual-associations-in-gpt-Paper-Conference.pdf",
         "test/2.MEMIT.pdf",
         "test/3.AlphaEdit_Null_Space_Cons.pdf"]
jids = []
for f in files:
    j = upload(f, "")
    jids.append(j)
    print("queued", f.split("/")[-1][:25], j, flush=True)

def snap():
    html = urllib.request.urlopen(BASE + "/", timeout=15).read().decode("utf-8", "ignore")
    rows = re.findall(r"(job\d+_\d+) — (\d+)% ([^<]+)", html)
    return rows

for k in range(6):
    time.sleep(10)
    rows = snap()
    states = [(j, p, s.strip()[:30]) for j, p, s in rows if j in jids]
    running = [j for j, p, s in states if "남은" in s or "곧 완료" in s]
    print(f"t={k*10}s", states, "RUNNING:", running, flush=True)
print("JIDS:", jids)
