# -*- coding: utf-8 -*-
"""웹 E2E: /convert 업로드 → 완료 대기 → 다운로드. 브라우저 대신 HTTP로 동일 경로 구동."""
import sys, time, re, urllib.request

BASE = "http://localhost:8040"

class NoRedir(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def upload(pdf_path, pages="", provider="local", model="", baseurl="", apikey="",
           src="English", tgt="Korean"):
    bound = "BNDW"
    data = open(pdf_path, "rb").read()
    fname = pdf_path.split("/")[-1].split("\\")[-1]
    parts = []
    parts.append(f'--{bound}\r\nContent-Disposition: form-data; name="pdffile"; filename="{fname}"\r\nContent-Type: application/pdf\r\n\r\n'.encode() + data + b"\r\n")
    for k, v in [("doctype", "auto"), ("pages", pages), ("provider", provider),
                 ("model", model), ("baseurl", baseurl), ("apikey", apikey),
                 ("srclang", src), ("tgtlang", tgt)]:
        parts.append(f'--{bound}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    parts.append(f"--{bound}--\r\n".encode())
    body = b"".join(parts)
    req = urllib.request.Request(BASE + "/convert", data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={bound}"}, method="POST")
    try:
        urllib.request.build_opener(NoRedir).open(req, timeout=60)
    except Exception as e:
        print("post ->", type(e).__name__, getattr(e, "code", ""))
    html = urllib.request.urlopen(BASE + "/", timeout=15).read().decode("utf-8", "ignore")
    m = re.findall(r"job\d+_\d+", html)
    return m[-1] if m else None

def wait_done(jid, timeout_min=90):
    for i in range(timeout_min * 6):
        time.sleep(10)
        html = urllib.request.urlopen(BASE + "/", timeout=15).read().decode("utf-8", "ignore")
        m = re.search(re.escape(jid) + r" — (\d+)% ([^<]+)", html)
        st = (m.group(2).strip() if m else "?")
        if m and ("done" in st or "error" in st or "cancelled" in st):
            print(f"[{jid}] finished: {m.group(1)}% {st}")
            return True
        if i % 6 == 0:
            print(f"[{jid}] waiting... {i*10}s row={m.group(0)[:80] if m else None}")
    print(f"[{jid}] TIMEOUT")
    return False

if __name__ == "__main__":
    pdf = sys.argv[1]
    pages = sys.argv[2] if len(sys.argv) > 2 else ""
    if pages == "NONE":
        pages = ""
    out = sys.argv[3] if len(sys.argv) > 3 else None
    jid = upload(pdf, pages)
    print("JOB", jid)
    if jid and wait_done(jid):
        html = urllib.request.urlopen(BASE + "/", timeout=15).read().decode("utf-8", "ignore")
        m = re.search(re.escape(jid) + r"[\s\S]{0,3000}?완료: ([^\s<]+\.pdf)", html)
        print("OUTPUT:", m.group(1) if m else None)
        if m and out:
            from pathlib import Path as _P
            dl = urllib.request.urlopen(
                BASE + "/download/" + _P(m.group(1)).name, timeout=120).read()
            open(out, "wb").write(dl)
            print("saved", out, len(dl))
