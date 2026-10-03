"""한글 PDF 렌더러 (V2): 원문 redact + ReportLab 오버레이 합성.

왜 ReportLab인가: PyMuPDF insert_textbox(fontfile=맑은고딕)은 한글을 '?'로
출력한다(실측). ReportLab TTFont는 한글 임베딩이 정상 동작한다.

- 레이아웃 유지: 같은 bbox에 한글 단락 삽입 (CJK 줄바꿈, shrink-to-fit)
- 표/수식 내부는 extractor에서 이미 제외됨
"""
from __future__ import annotations

import io
import os
from pathlib import Path

import pymupdf  # type: ignore

from . import config

_KR = "KRFont"
_KR_BOLD = "KRFont-Bold"
_registered = ""
_registered_lang = ""


def _register_fonts(serif: bool = True) -> str:
    """타깃 언어+스타일 폰트 등록 후 보통체 이름 반환 (.ttc subfontIndex 지원)."""
    global _registered, _registered_lang
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    lang = getattr(config, "TGT_LANG", "Korean")
    key = (lang, serif)
    if _registered and _registered_lang == key:
        return _KR
    regular = next(((c, i) for c, i in config.fonts_for_lang(lang, serif)
                    if os.path.exists(c)), None)
    if regular is None:
        raise RuntimeError(f"[{lang}] 사용 가능한 폰트를 찾을 수 없습니다.")
    path, idx = regular
    pdfmetrics.registerFont(TTFont(_KR, path, subfontIndex=idx))
    bold = next(((c, i) for c, i in config.bold_for_lang(lang, serif)
                 if os.path.exists(c)), regular)
    try:
        # bold가 regular와 같아도 별도 이름으로 등록해야 <b> 조회가 성공한다
        bpath, bidx = bold
        pdfmetrics.registerFont(TTFont(_KR_BOLD, bpath, subfontIndex=bidx))
        pdfmetrics.registerFontFamily(_KR, normal=_KR, bold=_KR_BOLD,
                                      italic=_KR, boldItalic=_KR_BOLD)
    except Exception:
        pass
    _registered, _registered_lang = True, key
    return _KR


def _norm_items(translations) -> list[dict]:
    """구/신 포맷 모두 수용 → [{page, bbox, text, fontsize, bold}]."""
    items: list[dict] = []
    if isinstance(translations, dict):
        for (pg, bb), ko in translations.items():
            items.append({"page": pg, "bbox": tuple(bb), "text": ko,
                          "fontsize": 10.5, "bold": False})
    else:
        items = list(translations)
    return items


def render_ko_pdf(pdf_path: str, translations, out_path: str,
                  font_size_scale: float = 0.96, style=None) -> str:
    from reportlab.lib.enums import TA_JUSTIFY, TA_LEFT
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Paragraph

    items = _norm_items(translations)
    from .fontmatch import DocStyle, block_alignment
    style = style or DocStyle()
    _register_fonts(serif=style.serif)
    import os as _os
    _debug = _os.environ.get("RENDER_DEBUG", "") == "1"
    if _debug:
        for it in items:
            print(f"[render] p{it['page']} y={it['bbox'][1]:.0f}-{it['bbox'][3]:.0f} "
                  f"x={it['bbox'][0]:.0f}-{it['bbox'][2]:.0f} len={len(it['text'])} "
                  f"{it['text'][:45]!r}")

    doc = pymupdf.open(pdf_path)
    by_page: dict[int, list[dict]] = {}
    for it in items:
        by_page.setdefault(int(it["page"]), []).append(it)

    # 0) 빈 공간 실측 (아래로 박스 확장용): 원본 전체 텍스트 블록 (redact 전)
    occupancy: dict[int, list] = {}
    for pno in by_page:
        try:
            occupancy[pno] = [b[:4] for b in doc[pno].get_text("blocks")
                              if b[4].strip()]
        except Exception:
            occupancy[pno] = []

    # 1) 원문 제거 (텍스트 레이어까지 삭제 → 복사/추출이 한글만)
    for pno, lst in by_page.items():
        page = doc[pno]
        for it in lst:
            page.add_redact_annot(pymupdf.Rect(*it["bbox"]), fill=(1, 1, 1))
        page.apply_redactions()

    # 2) ReportLab 오버레이 생성 (전체 페이지 수 동일, 번역 없는 페이지는 빈칸)
    buf = io.BytesIO()
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(buf)
    for pno in range(len(doc)):
        W, H = doc[pno].rect.width, doc[pno].rect.height
        c.setPageSize((W, H))
        for it in by_page.get(pno, []):
            x0, y0, x1, y1 = it["bbox"]
            w, h = max(10.0, x1 - x0), max(10.0, y1 - y0)
            ko = it["text"]
            is_paper = W < H
            cap = 15.0 if is_paper else 32.0
            base = min(float(it.get("fontsize", style.body_size)), cap)
            base = max(6.0, base * font_size_scale)
            # 정렬: CJK는 양쪽정렬 시 글자 겹침 버그 → 좌측 고정.
            # 라틴 타깃만 원문 정렬 추종.
            align = it.get("align")
            if align is None:
                cjk = getattr(config, "TGT_LANG", "Korean") in (
                    "Korean", "Japanese", "Chinese (Simplified)", "Chinese (Traditional)")
                if cjk or not is_paper:
                    align = TA_LEFT
                else:
                    rights = it.get("line_rights") or ()
                    key = block_alignment(list(rights), x1)
                    align = TA_JUSTIFY if key == "justify" else TA_LEFT
            # 아래 빈 공간만큼 박스 확장 허용 (캡션 넘침 방지, 최대 3배)
            clear = _clearance_below(it["bbox"], occupancy.get(pno, []), H)
            max_h = h + max(0.0, min(clear - 2.0, h * 3))
            _draw_paragraph(c, Paragraph, ParagraphStyle, ko, x0, H - y1, w, h,
                            base, bool(it.get("bold", False)), align,
                            leading_factor=style.leading, max_h=max_h)
        c.showPage()
    c.save()
    buf.seek(0)
    overlay = pymupdf.open(stream=buf.read(), filetype="pdf")

    # 3) 합성
    for pno, lst in by_page.items():
        if lst:
            doc[pno].show_pdf_page(doc[pno].rect, overlay, pno)

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    doc.save(out_path, garbage=4, deflate=True)
    doc.close()
    overlay.close()
    return out_path


def _clearance_below(bbox, others, page_h: float) -> float:
    """박스 아래 빈 공간 (같은 열 텍스트까지 거리)."""
    x0, y0, x1, y1 = bbox
    best = page_h - y1
    for ox0, oy0, ox1, oy1 in others:
        if oy0 < y1 - 1:
            continue
        if min(x1, ox1) - max(x0, ox0) <= max(20.0, (x1 - x0) * 0.2):
            continue
        best = min(best, oy0 - y1)
    return max(0.0, best)


def _draw_paragraph(c, Paragraph, ParagraphStyle, text: str,
                    x: float, y_bottom: float, w: float, h: float,
                    start_size: float, bold: bool, align=0,
                    leading_factor: float = 1.32, max_h: float | None = None) -> None:
    font = _KR  # 굵기는 <b> 태그로 표현 (family 등록됨)
    size = start_size
    # XML 이스케이프 (ReportLab Paragraph는 < > &를 마크업으로 해석)
    esc = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    if bold:
        esc = f"<b>{esc}</b>"
    limit = max_h if max_h else h
    while size >= 6.0:
        style = ParagraphStyle(f"ko{size:.1f}", fontName=font, fontSize=size,
                               leading=size * leading_factor, wordWrap="CJK", alignment=align)
        p = Paragraph(esc, style)
        need_w, need_h = p.wrap(w, h * 4)
        # 높이뿐 아니라 폭 넘침(꺾이지 않는 라틴 장치가 옆 열/표를 침범)도 축소
        if need_h <= limit + 0.5 and need_w <= w + 1.0:
            # 확장 시 윗변 고정 (아래로만 늘어남)
            p.drawOn(c, x, y_bottom + h - need_h)
            return
        size -= 0.7
    # 최소 폰트로도 넘치면 일단 그리고 경고 (원인 추적용)
    import sys as _sys2
    print(f"[overflow] box_h={h:.0f} limit={limit:.0f} text={text[:60]!r}", file=_sys2.stderr, flush=True)
    # 최소 폰트로도 넘치면 잘라서라도 기록
    style = ParagraphStyle("ko_min", fontName=font, fontSize=6.0,
                           leading=6.0 * leading_factor, wordWrap="CJK", alignment=align)
    p = Paragraph(esc, style)
    need_w, need_h = p.wrap(w, h * 4)
    p.drawOn(c, x, y_bottom)
