"""간단 웹 GUI (표준라이브러리만, 의존성 추가 없음).

실행: python src/app.py  (→ http://localhost:8000)
기능: PDF 업로드 → 자동분류(paper/slide) → 페이지 지정 → 변환 → outputs/*.pdf 다운로드
"""
from __future__ import annotations

import shutil
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src import config  # noqa: E402

UPLOAD_DIR = ROOT / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

JOBS: dict[str, dict] = {}
JOB_SEQ = [0]
TURN_LOCK = threading.Lock()
NEXT_TURN = [1]  # 다음에 실행할 작업 번호 (FIFO 순차 처리)
SKIPPED: set[int] = set()


HTML = """<!doctype html><html lang=ko><head><meta charset=utf-8>
<title>논문 한글화 (로컬 LLM)</title>
<style>body{font-family:'Malgun Gothic',sans-serif;max-width:760px;margin:32px auto;padding:0 16px}
.card{border:1px solid #ddd;border-radius:12px;padding:20px;margin:16px 0}
button{padding:10px 18px;font-size:15px}input,select{font-size:14px;padding:6px}
.log{background:#111;color:#0f0;padding:12px;border-radius:8px;white-space:pre-wrap;font-size:13px;height:320px;overflow-y:auto}
.scrollbox{max-height:180px;overflow-y:auto}</style>
</head><body>
<h2>논문/PPT 한글화 — 로컬 모델(local-model :8080)</h2>
<div class=card>모델 상태: {modelstat} <button onclick="location.reload()">새로고침</button></div>
<div class=card>
<form action="/convert" method=post enctype="multipart/form-data">
PDF 파일 (여러 개 선택 가능): <input type=file name=pdffile accept=".pdf" required multiple><br><br>
문서 종류: <select name=doctype><option value=auto>자동 판별 (Recommended)</option>
<option value=paper>논문</option><option value=slide>PPT/슬라이드</option></select><br><br>
페이지 (예: 0-1, 비우면 전체): <input name=pages size=12><br><br>
모델: <select name=provider><option value=local>로컬 (llama.cpp :8080)</option>
<option value=openai-compat>OpenAI 호환 (OpenAI/OpenRouter/Together/Groq…)</option>
<option value=anthropic>Anthropic Claude</option>
<option value=gemini>Google Gemini</option></select>
<input name=model size=18 placeholder="모델명(선택)">
<input name=baseurl size=26 placeholder="baseURL(호환전용)"><br><br>
API 키: <input type=password name=apikey size=36 placeholder="미입력 시 서버 환경변수 사용">
<span style=color:#666;font-size:12px>키는 메모리에만 보관, 디스크에 저장하지 않음</span><br><br>
원문 <select name=srclang><option>English</option><option>Korean</option><option>Japanese</option><option>Chinese (Simplified)</option><option>Chinese (Traditional)</option></select>
→ 번역 <select name=tgtlang><option>Korean</option><option>English</option><option>Japanese</option><option>Chinese (Simplified)</option><option>Chinese (Traditional)</option><option>Spanish</option><option>French</option><option>German</option><option>Vietnamese</option><option>Indonesian</option></select><br><br>
<button type=submit>한글화 시작</button>
</form></div>
<div class=card><h3>완료 파일</h3><div class=scrollbox>{files}</div></div>
<div class=card><h3>원문·결과 비교</h3><div class=scrollbox>{compares}</div></div>
<div class=card><h3>진행 상황</h3>{progress}</div>
<div class=card><h3>작업 로그</h3><div class=log id=logbox>{log}</div></div>
<script>var lb=document.getElementById('logbox');if(lb){lb.scrollTop=lb.scrollHeight;}</script>
<script>setInterval(function(){fetch('/ping',{method:'POST',keepalive:true});},5000);</script>
<p style=color:#666>레퍼런스 규칙: 본문·캡션만 한글화, 수식/표내부/그림 원문 유지, Table→표·Fig→그림·Section→절</p>
</body></html>"""


def run_job(job_id: str, src_pdf: str, doctype: str, pages: str | None,
            provider: str = "local", model: str = "", base_url: str = "",
            api_key: str = "", src_lang: str = "English", tgt_lang: str = "Korean"):
    from src.classifier import classify
    from src.extractor import chunk_paragraph, iter_blocks, merge_dangling, merge_line_fragments, merge_slide_vertical, ruling_lines, should_translate, table_skip_rects

    def log(s: str):
        JOBS[job_id]["log"] += s + "\n"
        print(f"[{job_id}] {s}", flush=True)

    try:
        JOBS[job_id]["status"] = "waiting"
        # FIFO 차례 대기 (넣은 순서대로 하나씩 실행)
        while True:
            if JOBS[job_id].get("cancel"):
                with TURN_LOCK:
                    SKIPPED.add(JOBS[job_id].get("seq", 0))
                JOBS[job_id].update(status="cancelled")
                JOBS[job_id]["log"] += "사용자가 작업을 중지했습니다.\n"
                return
            with TURN_LOCK:
                while NEXT_TURN[0] in SKIPPED:
                    NEXT_TURN[0] += 1
                if JOBS[job_id].get("seq", 0) == NEXT_TURN[0]:
                    break
            time.sleep(0.5)
        JOBS[job_id]["status"] = "running"
        from src.translator import configure as configure_provider
        try:
            p = configure_provider(provider, model=model, base_url=base_url, api_key=api_key,
                                   src_lang=src_lang, tgt_lang=tgt_lang)
        except Exception as e:
            JOBS[job_id].update(status="error")
            JOBS[job_id]["log"] += f"프로바이더 설정 오류: {e}\n"
            return
        log(f"프로바이더: {p.name} model={getattr(p, 'model', '')} {src_lang}>{tgt_lang}")
        total_pages = classify(src_pdf)["pages"]
        if pages:
            wanted: list[int] | None = []
            for part in pages.split(","):
                part = part.strip()
                if not part:
                    continue
                if "-" in part:
                    a, b = part.split("-", 1)
                    wanted.extend(range(int(a), int(b) + 1))
                else:
                    wanted.append(int(part))
            wanted = sorted(p for p in wanted if 0 <= p < total_pages)
        else:
            wanted = None
        info = classify(src_pdf)
        kind = doctype if doctype != "auto" else info["kind"]
        log(f"분류: {kind} (pages={info['pages']}, aspect={info['aspect']})")

        from src.extractor import merge_slide_vertical, slide_ruling_boxes, slide_rulings, split_row_blocks
        from src.extractor import table_regions
        _rul = slide_rulings(src_pdf, wanted)
        _regs = table_regions(src_pdf, wanted) if kind == "paper" else None
        from src.extractor import equation_bands as _eb2
        _ebands = _eb2(src_pdf, wanted) if kind == "paper" else None
        blocks = merge_line_fragments(iter_blocks(
            src_pdf, wanted,
            table_skip_rects(src_pdf, wanted) if kind == "paper" else None,
            ruling_lines(src_pdf, wanted), ruled_skip=(kind == "paper"),
            table_regs=_regs, eq_bands=_ebands),
            rulings=_rul)
        if kind == "slide":
            blocks = merge_slide_vertical(blocks, rulings=_rul)
            blocks = split_row_blocks(src_pdf, blocks, slide_ruling_boxes(src_pdf, wanted))
        else:
            from src.extractor import merge_dangling as _md
            from src.extractor import refilter as _rf
            from src.extractor import ruling_lines as _rl
            blocks = _md(blocks)
            blocks = split_row_blocks(src_pdf, blocks, col_gap=12.0,
                                      regs=_regs)
            blocks = _rf(blocks, table_skip_rects(src_pdf, wanted),
                         _rl(src_pdf, wanted), _regs)
            blocks = _md(blocks)
        from src.extractor import drop_contained
        blocks = drop_contained(blocks)
        cands = [b for b in blocks if should_translate(b.text, b.fontsize, kind, b.page)]
        cands.sort(key=lambda b: (b.page, b.bbox[1]))
        if kind == "paper":
            from src.extractor import REF_HEADERS as _RH
            from src.extractor import appendix_start as _ast
            cut = next((i for i, b in enumerate(cands) if b.text.strip().lower() in _RH), None)
            if cut is not None:
                _pos = _ast(src_pdf)
                if _pos is not None:
                    _pg, _yy = _pos
                    resume = next((i for i in range(cut + 1, len(cands))
                                   if (cands[i].page, cands[i].bbox[1]) >= (_pg, _yy - 1.0)), None)
                else:
                    resume = None
                if resume is None:
                    log(f"참고문헌 이후 {len(cands) - cut - 1} 블록 제외")
                    cands = cands[:cut + 1]
                else:
                    log(f"참고문헌 {len(cands[:cut + 1]) + len(cands) - resume} 블록 중 "
                        f"{resume - cut - 1} 블록 제외, 부록 재개")
                    cands = cands[:cut + 1] + cands[resume:]
        log(f"추출: 전체 {len(blocks)} 블록 중 번역 대상 {len(cands)}")
        if kind == "paper":
            from src.extractor import collect_fragments
            import pymupdf as _pmh
            _dh = _pmh.open(src_pdf)
            _ph = {p: _dh[p].rect.height for p in range(len(_dh))}
            _dh.close()
            _frags = collect_fragments(blocks, cands, _ph)
            if _frags:
                log(f"문장 꼬리 {len(_frags)}개 문맥 번역")
                cands += _frags
        from src.extractor import dedupe_cands, drop_contained
        cands = dedupe_cands(drop_contained(cands))
        from src.fontmatch import analyze_document
        style = analyze_document(src_pdf)  # 부분 번역이어도 전체 문서 기준
        log(f"서체: {'serif' if style.serif else 'sans'} 본문 {style.body_size}pt 자간 {style.leading}")

        from src.renderer import render_ko_pdf
        from src.translator import last_tps as _last_tps
        from src.translator import translate_fragment, translate_text
        from src.extractor import continuation_prev, reading_order
        import pymupdf as _pm
        _doc = _pm.open(src_pdf)
        _heights = {p: _doc[p].rect.height for p in range(len(_doc))}
        _doc.close()
        _ordered = reading_order(cands)
        _prev_of = {id(b): (_ordered[i - 1] if i > 0 else None)
                    for i, b in enumerate(_ordered)}
        translations = []
        t0 = time.time()
        for i, b in enumerate(cands):
            if JOBS[job_id].get("cancel"):
                JOBS[job_id].update(status="cancelled")
                log("사용자가 작업을 중지했습니다.")
                with TURN_LOCK:
                    NEXT_TURN[0] += 1
                return
            prev = continuation_prev(b, _prev_of.get(id(b)), _heights.get(b.page, 792.0))
            if prev is not None:
                ko = translate_fragment(b.text, prev.text)
            else:
                ko = " ".join(translate_text(p) for p in chunk_paragraph(b.text))
            translations.append({"page": b.page,
                                 "bbox": tuple(round(v, 1) for v in b.bbox),
                                 "text": ko, "fontsize": b.fontsize, "bold": b.is_bold,
                                 "line_rights": list(b.line_rights)})
            tps = _last_tps()
            tps_s = f" {tps:.0f} tok/s" if tps > 0 else ""
            log(f"[{i+1}/{len(cands)}] p{b.page} 번역 {len(b.text)}자 -> {len(ko)}자{tps_s}")
            JOBS[job_id]["tps"] = tps
            done = i + 1
            JOBS[job_id]["progress"] = done / max(1, len(cands))
            el = max(0.1, time.time() - t0)
            left = (len(cands) - done) * (el / done) if cands else 0
            JOBS[job_id]["eta"] = f"남은 약 {int(left // 60)}분 {int(left % 60)}초" if left >= 1 else "곧 완료"
        if kind == "paper":
            # redact 분리: 수식 밴드·참고문헌 zonas 원문 보존 (렌더 박스는 유지)
            from src.extractor import equation_bands as _eb3
            from src.extractor import refs_zone as _rz3
            from src.extractor import subtract_bands as _sb3
            _ebm = _eb3(src_pdf, wanted)
            _rzm = _rz3(src_pdf)
            _bm: dict[int, list] = {}
            for _p, _bl in list(_ebm.items()) + list(_rzm.items()):
                _bm.setdefault(_p, []).extend(_bl)
            for _it in translations:
                _pb = _bm.get(int(_it["page"]), [])
                _it["redact"] = [tuple(round(v, 1) for v in r)
                                 for r in _sb3(_it["bbox"], _pb)] if _pb else None
        out = str(config.OUTPUT_DIR / f"{Path(src_pdf).stem}_{config.LANG_SUFFIX.get(tgt_lang, 'ko')}.pdf")
        if Path(out).exists():
            stem = f"{Path(src_pdf).stem}_{config.LANG_SUFFIX.get(tgt_lang, 'ko')}"
            n = 1
            while (config.OUTPUT_DIR / f"{stem}_{n}.pdf").exists():
                n += 1
            out = str(config.OUTPUT_DIR / f"{stem}_{n}.pdf")
        render_ko_pdf(src_pdf, translations, out,
                      font_size_scale=1.0 if kind == "paper" else 0.9, style=style)
        JOBS[job_id].update(status="done", output=out, src=src_pdf, pages=info["pages"])
        log(f"완료: {out}")
        with TURN_LOCK:
            NEXT_TURN[0] += 1
    except Exception as e:
        JOBS[job_id].update(status="error")
        JOBS[job_id]["log"] += f"ERROR: {e}\n{traceback.format_exc()}\n"
        with TURN_LOCK:
            NEXT_TURN[0] += 1


def parse_multipart(handler: BaseHTTPRequestHandler):
    """최소 multipart/form-data 파서 (cgi 없이). → {name: (filename, bytes) | str}"""
    ctype = handler.headers.get("Content-Type", "")
    if "multipart/form-data" not in ctype or "boundary=" not in ctype:
        return {}
    boundary = ctype.split("boundary=")[-1].strip().strip('"').encode()
    try:
        length = int(handler.headers.get("Content-Length", 0))
    except ValueError:
        return {}
    body = handler.rfile.read(length)
    out: dict = {}
    for part in body.split(b"--" + boundary):
        if b"\r\n\r\n" not in part:
            continue
        head, data = part.split(b"\r\n\r\n", 1)
        if data.endswith(b"\r\n"):
            data = data[:-2]
        try:
            h = head.decode("utf-8", "ignore")
        except Exception:
            continue
        if 'name="pdffile"' in h:
            fn = "upload.pdf"
            if 'filename="' in h:
                fn = h.split('filename="', 1)[1].split('"', 1)[0].split("\\")[-1] or fn
            if not fn.lower().endswith(".pdf"):
                continue
            out.setdefault("pdffile", []).append((fn, data))
        elif 'name="doctype"' in h:
            out["doctype"] = data.decode("utf-8", "ignore").strip()
        elif 'name="pages"' in h:
            out["pages"] = data.decode("utf-8", "ignore").strip()
        elif 'name="provider"' in h:
            out["provider"] = data.decode("utf-8", "ignore").strip()
        elif 'name="model"' in h:
            out["model"] = data.decode("utf-8", "ignore").strip()
        elif 'name="baseurl"' in h:
            out["baseurl"] = data.decode("utf-8", "ignore").strip()
        elif 'name="apikey"' in h:
            out["apikey"] = data.decode("utf-8", "ignore").strip()
        elif 'name="srclang"' in h:
            out["srclang"] = data.decode("utf-8", "ignore").strip()
        elif 'name="tgtlang"' in h:
            out["tgtlang"] = data.decode("utf-8", "ignore").strip()
    return out


THUMBS: dict[tuple, bytes] = {}
LAST_PING: list[float] = [0.0]
WATCHDOG_STARTED = [False]

PING_SCRIPT = ("<script>setInterval(function(){"
               "fetch('/ping',{method:'POST',keepalive:true});},5000);</script>")


def _note_ping() -> None:
    import time as _t
    LAST_PING[0] = _t.time()
    if not WATCHDOG_STARTED[0]:
        WATCHDOG_STARTED[0] = True
        import threading as _th
        _th.Thread(target=_watchdog, daemon=True).start()


def _watchdog() -> None:
    """브라우저 탭이 전부 닫히면(60초 무응답) 서버 종료."""
    import os as _os
    import time as _t
    while True:
        _t.sleep(10)
        if _t.time() - LAST_PING[0] > 60:
            _os._exit(0)


def model_status() -> str:
    """llama.cpp 로컬 모델 연결 상태 (2초 타임아웃)."""
    import json as _json
    import urllib.request as _url
    try:
        with _url.urlopen("http://localhost:8080/health", timeout=2) as r:
            ok = _json.loads(r.read().decode("utf-8")).get("status") == "ok"
        return "로컬 모델 연결됨 (local-model :8080)" if ok else "로컬 모델 응답 이상"
    except Exception:
        return "로컬 모델 연결 안 됨 — llama.cpp 서버를 먼저 켜세요 (또는 상용 API 선택)"


COMPARE_HTML = """<!doctype html><html lang=ko><head><meta charset=utf-8>
<title>비교하기</title>
<style>
body{font-family:'Malgun Gothic',sans-serif;margin:12px}
.bar{position:sticky;top:0;background:#fff;padding:8px;border-bottom:1px solid #ddd;text-align:center}
button{padding:8px 18px;font-size:15px;margin:0 6px}
.wrap{display:flex;gap:8px;justify-content:center;align-items:flex-start}
.col{flex:1;max-width:49%}
.col h4{text-align:center;margin:6px}
img{width:100%;border:1px solid #ccc;background:#eee}
</style></head><body>
<div class=bar>
<a href="/">← 목록</a>
<button onclick="go(cur-1)">◀ 이전</button>
<span id=pg></span> / %%PAGES%% 페이지
<button onclick="go(cur+1)">다음 ▶</button>
<input id=jump size=4><button onclick="go(parseInt(document.getElementById('jump').value)-1)">이동</button>
</div>
<div class=wrap>
<div class=col><h4>원문</h4><img id=imgO></div>
<div class=col><h4>결과물</h4><img id=imgK></div>
</div>
<script>
var cur=0, total=%%PAGES%%, jid="%%JID%%";
function go(n){
  if(n<0)n=0; if(n>=total)n=total-1; cur=n;
  document.getElementById('imgO').src="/thumb?jid="+jid+"&side=orig&p="+n+"&t="+Date.now();
  document.getElementById('imgK').src="/thumb?jid="+jid+"&side=out&p="+n+"&t="+Date.now();
  document.getElementById('pg').textContent=(n+1);
}
document.addEventListener('keydown',function(e){
  if(e.key==='ArrowLeft')go(cur-1); if(e.key==='ArrowRight')go(cur+1);
});
go(0);
setInterval(function(){fetch('/ping',{method:'POST',keepalive:true});},5000);
</script></body></html>"""


class H(BaseHTTPRequestHandler):
    def _send(self, body: str | bytes, ctype="text/html; charset=utf-8"):
        b = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        _note_ping()
        u = urlparse(self.path)
        if u.path.startswith("/compare/"):
            jid = u.path.rsplit("/", 1)[-1]
            j = JOBS.get(jid)
            if not j or not j.get("output"):
                self._send("비교할 작업이 없습니다. <a href='/'>돌아가기</a>")
                return
            pages = j.get("pages") or 1
            self._send(COMPARE_HTML.replace("%%PAGES%%", str(pages)).replace("%%JID%%", jid))
            return
        if u.path == "/thumb":
            q = parse_qs(u.query)
            jid = (q.get("jid") or [""])[0]
            side = (q.get("side") or ["out"])[0]
            try:
                pno = int((q.get("p") or ["0"])[0])
            except ValueError:
                pno = 0
            j = JOBS.get(jid)
            if not j:
                self.send_response(404)
                self.end_headers()
                return
            key = (jid, side, pno)
            if key not in THUMBS:
                import pymupdf
                src = j.get("src") if side == "orig" else j.get("output")
                try:
                    doc = pymupdf.open(src)
                    if pno >= len(doc):
                        pno = len(doc) - 1
                    png = doc[pno].get_pixmap(dpi=110).tobytes("png")
                    doc.close()
                except Exception:
                    self.send_response(404)
                    self.end_headers()
                    return
                if len(THUMBS) > 80:
                    THUMBS.pop(next(iter(THUMBS)))
                THUMBS[key] = png
            data = THUMBS[key]
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if u.path.startswith("/download/"):
            name = Path(u.path.rsplit("/", 1)[-1]).name
            fp = config.OUTPUT_DIR / name
            if fp.exists():
                data = fp.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "application/pdf")
                self.send_header("Content-Disposition", f'attachment; filename="{name}"')
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            self.send_response(404)
            self.end_headers()
            return
        files = "".join(
            f'<div><a href="/download/{p.name}">{p.name}</a> ({p.stat().st_size//1024} KB)</div>'
            for p in sorted(config.OUTPUT_DIR.glob("*.pdf"), key=lambda x: x.stat().st_mtime, reverse=True)[:20]
        ) or "(아직 없음)"
        compares = "".join(
            f'<div><a href="/compare/{jid}">비교하기: {Path(j.get("output","")).name or jid}</a> '
            f'({j["status"]})</div>'
            for jid, j in list(JOBS.items())
            if j.get("output") and j.get("src")
        ) or "(변환 완료 후 표시)"
        prog_rows = []
        for jid, j in list(JOBS.items())[:10]:
            pct = int(round(j.get("progress", 0.0) * 100))
            if j["status"] == "waiting":
                eta = "대기 중"
            else:
                eta = j.get("eta", "") if j["status"] == "running" else j["status"]
            tps = j.get("tps", 0.0) or 0.0
            tps_s = f" · {tps:.0f} tok/s" if j["status"] == "running" and tps > 0 else ""
            name = Path(j.get("output") or j.get("src") or jid).name
            cancel = (f' <form action="/cancel/{jid}" method="post" style="display:inline">'
                      f'<button type="submit">중지</button></form>'
                      if j["status"] in ("queued", "running") else "")
            prog_rows.append(
                f'<div style="margin:6px 0">{name} — {pct}% {eta}{tps_s}{cancel}'
                f'<div style="background:#e5e5e5;border-radius:6px">'
                f'<div style="width:{pct}%;background:#3a7;height:12px;border-radius:6px"></div>'
                f"</div></div>")
        progress = "".join(prog_rows) or "(대기 중인 작업 없음)"
        active = any(j["status"] in ("queued", "running") for j in JOBS.values())
        head_extra = '<meta http-equiv="refresh" content="3">' if active else ""
        log = "\n".join(f"[{jid}] {j['status']} {j.get('output','')}\n{j['log'][-1500:]}" for jid, j in list(JOBS.items())[-5:])
        self._send(HTML.replace("<head>", "<head>" + head_extra).replace("{modelstat}", model_status()).replace("{files}", files).replace("{compares}", compares).replace("{progress}", progress).replace("{log}", log or "(대기)"))

    def do_POST(self):
        if self.path != "/ping":
            _note_ping()
        if self.path == "/ping":
            _note_ping()
            self.send_response(204)
            self.end_headers()
            return
        if self.path.startswith("/cancel/"):
            jid = self.path.rsplit("/", 1)[-1]
            j = JOBS.get(jid)
            if j and j["status"] in ("queued", "running"):
                j["cancel"] = True
                j["log"] += "중지 요청됨...\n"
            self.send_response(303)
            self.send_header("Location", "/")
            self.end_headers()
            return
        if self.path != "/convert":
            self.send_response(404)
            self.end_headers()
            return
        form = parse_multipart(self)
        ups = form.get("pdffile") or []
        ups = [(fn, fd) for fn, fd in ups if fd.startswith(b"%PDF")]
        if not ups:
            self._send("PDF 파일이 없습니다. <a href='/'>돌아가기</a>")
            return
        doctype = form.get("doctype", "auto") or "auto"
        pages = (form.get("pages", "") or "").strip() or None
        provider = form.get("provider", "local") or "local"
        model = (form.get("model", "") or "").strip()
        base_url = (form.get("baseurl", "") or "").strip()
        api_key = (form.get("apikey", "") or "").strip()
        src_lang = (form.get("srclang", "") or "English").strip()
        tgt_lang = (form.get("tgtlang", "") or "Korean").strip()
        queued = []
        for fname, fdata in ups:
            # 동명 파일 덮어쓰기 방지 (각 번역본은 항상 별도 파일)
            dest = UPLOAD_DIR / Path(fname).name
            n = 1
            while dest.exists():
                dest = UPLOAD_DIR / f"{Path(fname).stem}_{n}{Path(fname).suffix}"
                n += 1
            dest.write_bytes(fdata)
            JOB_SEQ[0] += 1
            jid = f"job{int(time.time())%100000}_{JOB_SEQ[0]}"
            JOBS[jid] = {"status": "queued", "log": f"업로드: {dest}\n", "progress": 0.0,
                         "output": "", "seq": JOB_SEQ[0]}
            threading.Thread(target=run_job, args=(jid, str(dest), doctype, pages,
                                                   provider, model, base_url, api_key,
                                                   src_lang, tgt_lang),
                             daemon=True).start()
            queued.append(Path(fname).name)
        self.send_response(303)
        self.send_header("Location", "/")
        self.end_headers()

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    import argparse as _ap
    _p = _ap.ArgumentParser(description="논문/PPT 한글화 웹 GUI")
    _p.add_argument("port", nargs="?", type=int, default=8000)
    _p.add_argument("--no-open", action="store_true", help="브라우저 자동 실행 안 함")
    _a = _p.parse_args()
    print(f"serve http://localhost:{_a.port}  (uploads/ outputs/)")
    if not _a.no_open:
        import threading as _th
        import webbrowser as _wb
        _th.Timer(1.2, lambda: _wb.open(f"http://localhost:{_a.port}")).start()
    ThreadingHTTPServer(("127.0.0.1", _a.port), H).serve_forever()
