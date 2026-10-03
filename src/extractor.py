"""PyMuPDF 기반 텍스트 블록 추출 + 번역 대상 판별.

원칙 (PLAN.md §1):
- 수식/표 내부/그림 라벨/짧은 단편은 스킵 (원문 유지)
- 서술형 본문·캡션·섹션 타이틀만 번역
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import pymupdf  # type: ignore

EQ_NUM = re.compile(r"\(\d+[a-c]?\)\s*$")
ONLY_MATH = re.compile(r"^[\d\s\.\,\;\:\+\-\=\*\/\(\)\[\]\{\}\<\>\_\^\|\~\→\←\∞\α-ωΑ-Ω]+$")
CITATION = re.compile(r"^(Figure|Fig\.|Table|Eq\.|Section|Step|Load|Initialize|Pre-compute|Calculating|Identifying|Updating|Starting|Start)\b")
MONO_HINTS = ("courier", "cmtt", "mono", "consolas", "menlo", "typewriter",
              "terminal", "fixed", "lucida console", "dejavu sans mono")

REF_HEADERS = {"references", "참고문헌", "bibliography"}

MATH_SINGLE_RE = re.compile(r"[A-Za-z0-9]")


def _dominant_is_mono(spans) -> bool:
    n = sum(len(s["text"]) for s in spans)
    m = sum(len(s["text"]) for s in spans
            if any(h in s["font"].lower() for h in MONO_HINTS))
    return n > 0 and m / n >= 0.6


def math_token_ratio(text: str) -> float:
    """한 글자 영숫 토큰 비율 (수식 빽빽 블록 판별)."""
    toks = text.split()
    if len(toks) < 8:
        return 0.0
    single = sum(1 for t in toks
                 if len(t.strip(".,:;()[]{}=+−-*/^_~|<>\"'")) <= 1)
    return single / len(toks)


@dataclass
class Block:
    page: int
    bbox: tuple[float, float, float, float]
    text: str
    fontsize: float
    is_bold: bool
    line_rights: tuple = ()  # 줄별 오른쪽 끝 x (양쪽정렬 판정용)


def _is_header_footer(page_no: int, n_pages: int, y0: float, h: float) -> bool:
    if y0 < h * 0.045:
        return True
    if y0 > h * 0.955:
        return True
    return False


KNOWN_HEADERS = {
    "abstract", "introduction", "related work", "preliminaries", "method", "methods",
    "experiments", "results", "discussion", "conclusion", "conclusions",
    "references", "acknowledgments", "acknowledgements", "appendix",
}

LAB_HEADER = re.compile(r"high performance.*computing lab", re.I)


def should_translate(text: str, fontsize: float = 10.0, kind: str = "paper", page: int = 0) -> bool:
    t = text.strip()
    if not t:
        return False
    # 공통 스킵: 연구실 헤더, 페이지 번호, 이메일/소속
    if LAB_HEADER.search(t):
        return False
    if re.fullmatch(r"\d{1,3}", t):
        return False
    if "@" in t and ("edu" in t or "mail" in t or "correspondence" in t.lower()):
        return False
    # 저자·소속 행 (길이에 무관, 본문 대비 짧은 블록 한정)
    if len(t) < 150 and re.search(
            r"(University|Institute|Laboratory|\bLAB\b|\bMIT\b|Technion|Northeastern|Cornell|"
            r"Stanford|Berkeley|FAIR|DeepMind|OpenAI|Microsoft|Google|Department)", t):
        # 단, 명백한 본문 문장(마침표 2개 이상 + 100자 이상)은 번역
        if not (t.count(".") >= 2 and len(t) >= 100):
            return False
    # 섹션 헤더는 짧아도 번역. 번호 있는 것(1, 5.1, B.2, C.1.2, F) + Appendix.
    # 번호 없는 ALL-CAPS(ETHICS STATEMENT 등)는 원문 유지 (Step/User-defined 규칙과 일관).
    if len(t) < 120:
        if re.match(r"^\d+(\.\d+)*\s+[A-Z0-9]", t):
            return True
        if re.match(r"^[A-Z](\.\d+)*\s+[A-Z0-9]", t):
            return True
        if re.match(r"^Appendix\s+[A-Z0-9]", t, re.I):
            return True
    if t.lower() in KNOWN_HEADERS:
        return True
    if kind == "slide":
        # 슬라이드: 제목·불릿은 짧아도 번역 (연구실 헤더/번호 제외)
        words = re.findall(r"[A-Za-z]{2,}", t)
        if len(t) >= 8 and len(words) >= 2 and not ONLY_MATH.match(t):
            # ALL-CAPS 라벨도 번역 (가독성 위해)
            return True
        return False
    # 논문 본문 (기존 규칙)
    if len(t) < 40:
        # 단, 첫 페이지 큰 폰트 타이틀은 번역
        if page == 0 and fontsize >= 13 and len(t) >= 20 and len(re.findall(r"[A-Za-z]{2,}", t)) >= 4:
            return True
        return False
    # NOTE: 수식 빽빽 블록도 번역한다 (Gemma는 기호 유지하며 번역, P9 폐지)
    # 첫 페이지 대제목: 마침표 없어도 번역
    if page == 0 and fontsize >= 14 and len(re.findall(r"[A-Za-z]{2,}", t)) >= 4 and len(t) < 200:
        return True
    # 수식 번호로 끝나는 한 줄 수식
    lines = [x.strip() for x in t.split("\n") if x.strip()]
    if len(lines) <= 2 and EQ_NUM.search(t):
        # 문장이 아니라 기호 나열이면 스킵
        alpha = sum(c.isalpha() for c in t)
        if alpha / max(1, len(t)) < 0.35:
            return False
    # 영문 단어 비율이 낮으면(기호 위주) 스킵
    words = re.findall(r"[A-Za-z]{2,}", t)
    if len(words) < 5:
        return False
    # 표 수치행 스킵: 영문 단어 적고 숫자·기호가 지배 (표 내부는 원문 유지)
    if len(words) < 8 and sum(c.isdigit() for c in t) > 15:
        return False
    # 수식 디스플레이 스킵 (문장 같지 않은 수식)
    if _is_equation_display(t):
        return False
    # 표 내부 명령문 패턴은 유지 (레퍼런스: 표 내부 미번역). 단, 긴 절차 문단은 본문.
    if CITATION.match(t) and len(t) < 150 and "\n" not in t.strip():
        # 단, Table/Figure 캡션과 Section 헤더는 번역한다
        if re.match(r"^(Table|Figure|Fig\.)\s+\d+", t):
            return True
        if re.match(r"^\d+(\.\d+)*\s+[A-Z]", t):
            return True
        return False
    # 불릿 정의문 (구두점 없어도 번역)
    if re.match(r"^\s*[•\-\*]\s+[A-Z]", t) and len(t) > 60 and len(words) >= 8:
        return True
    # 문장 부호가 전혀 없으면 라벨로 간주
    if "." not in t and "," not in t and len(t) < 150:
        return False
    return True


def ruling_lines(pdf_path: str, pages: list[int] | None = None) -> dict[int, tuple[list, list]]:
    """눈금선 수집: hlines=[(x0,x1,y)], vlines=[(x,y0,y1)]. 표·박스 경계 검출용."""
    import pymupdf as _pm
    doc = _pm.open(pdf_path)
    wanted = set(pages) if pages is not None else set(range(len(doc)))
    out: dict[int, tuple[list, list]] = {}
    for pno in sorted(wanted):
        if pno >= len(doc):
            continue
        hl, vl = [], []
        try:
            for d in doc[pno].get_drawings():
                r = d.get("rect")
                if not r:
                    continue
                if r.width > 80 and r.height < 3:
                    hl.append((r.x0, r.x1, (r.y0 + r.y1) / 2))
                elif r.height > 30 and r.width < 3:
                    vl.append(((r.x0 + r.x1) / 2, r.y0, r.y1))
        except Exception:
            pass
        out[pno] = (hl, vl)
    doc.close()
    return out


def in_ruled_cell(bbox, rulings: tuple[list, list]) -> bool:
    """확장 박스와 교차하는 가로선 2개 이상이면 표/박스 내부.
    (세로선 없는 표도 있으므로 가로선만으로 판정)"""
    x0, y0, x1, y1 = bbox
    ex0, ey0, ex1, ey1 = x0 - 3, y0 - 8, x1 + 3, y1 + 8
    hl, vl = rulings
    h = sum(1 for lx0, lx1, ly in hl
            if ey0 <= ly <= ey1 and min(lx1, ex1) - max(lx0, ex0) > 0)
    return h >= 2


def table_regions(pdf_path: str, pages: list[int] | None = None) -> dict[int, list]:
    """표 영역 검출: x가 겹치는 가로선 2개 이상이 이루는 구간.
    booktabs식(중간선 없음) 표의 중간 행까지 제외하기 위함."""
    import pymupdf as _pm
    doc = _pm.open(pdf_path)
    wanted = set(pages) if pages is not None else set(range(len(doc)))
    out: dict[int, list] = {}
    for pno in sorted(wanted):
        if pno >= len(doc):
            continue
        lines = []
        try:
            for d in doc[pno].get_drawings():
                r = d.get("rect")
                if r and r.width > 80 and r.height < 3:
                    lines.append((r.x0, r.x1, (r.y0 + r.y1) / 2))
        except Exception:
            pass
        lines.sort(key=lambda t: t[2])
        groups: list[list] = []
        for lx0, lx1, ly in lines:
            placed = False
            for g in groups:
                gx0 = min(t[0] for t in g)
                gx1 = max(t[1] for t in g)
                ov = min(lx1, gx1) - max(lx0, gx0)
                # x 겹침 + 세로 간격 제한 (멀리 떨어진 선은 다른 구조)
                if (ov > 0.5 * min(lx1 - lx0, gx1 - gx0)
                        and ly - max(t[2] for t in g) <= 120):
                    g.append((lx0, lx1, ly))
                    placed = True
                    break
            if not placed:
                groups.append([(lx0, lx1, ly)])
        regs = []
        for g in groups:
            if len(g) < 2:
                continue
            rx0 = min(t[0] for t in g)
            rx1 = max(t[1] for t in g)
            ry0 = min(t[2] for t in g) - 4
            ry1 = max(t[2] for t in g) + 4
            if rx1 - rx0 > 150 and ry1 - ry0 > 40:
                regs.append([rx0, ry0, rx1, ry1])
        # 아래로 확장: 규칙 없는 표 하단 행 흡수 (dict 줄 기준).
        # 표 x범위에 글자가 있는 밴드가 이어지면 표로 간주.
        # 숫자 시작(각주)·눈금선에서 중단.
        try:
            page = doc[pno]
            hls = sorted(t[2] for t in [l for g in groups for l in g])
            dlines = []
            for lb in page.get_text("dict")["blocks"]:
                if lb["type"] != 0:
                    continue
                for l in lb["lines"]:
                    tx = "".join(s["text"] for s in l["spans"])
                    dlines.append((l["bbox"][1], l["bbox"][3], l["bbox"][0],
                                   l["bbox"][2], tx, l["spans"]))
            dlines.sort(key=lambda t: (t[0], t[1]))
            for r in regs:
                if r[2] - r[0] >= page.rect.width * 0.6:
                    continue
                while True:
                    ext = []
                    for t in dlines:
                        if not (t[0] >= r[3] - 2 and t[0] - r[3] <= 30):
                            continue
                        nch = sum(len(s["text"]) for s in t[5]
                                  if r[0] - 10 <= (s["bbox"][0] + s["bbox"][2]) / 2 <= r[1] + 10)
                        if nch >= 5 and not any(r[3] - 2 <= qy <= t[0] + 2 for qy in hls):
                            ext.append(t)
                    if not ext:
                        break
                    if r[3] > page.rect.height - 20:
                        break
                    if any(re.match(r"^\d", (t[4] or "").strip()) for t in ext):
                        break
                    # 본문 문장 밴드에서 중단 (표 하단 행은 수치/짧은 라벨).
                    # reg x범위 내 텍스트의 소문자 개수로 판정 (줄 조각 대응).
                    body_hit = False
                    for t in ext:
                        inreg = "".join(s["text"] for s in t[5]
                                        if r[0] - 10 <= (s["bbox"][0] + s["bbox"][2]) / 2 <= r[1] + 10)
                        if sum(c.islower() for c in inreg) >= 15:
                            body_hit = True
                            break
                    if body_hit:
                        break
                    new_bottom = max(t[1] for t in ext) + 2
                    if new_bottom <= r[3] or new_bottom - r[1] > 250:
                        break
                    r[3] = new_bottom
        except Exception:
            pass
        if regs:
            out[pno] = regs
    doc.close()
    return out


def in_table_region(bbox, regs: list) -> bool:
    """박스가 표 영역과 겹치면 True (포함 또는 면적 50% 이상)."""
    x0, y0, x1, y1 = bbox
    area = max(1.0, (x1 - x0) * (y1 - y0))
    for rx0, ry0, rx1, ry1 in regs:
        if rx0 - 2 <= x0 and ry0 - 2 <= y0 and x1 <= rx1 + 2 and y1 <= ry1 + 2:
            return True
        iw = min(x1, rx1) - max(x0, rx0)
        ih = min(y1, ry1) - max(y0, ry0)
        if iw > 0 and ih > 0 and (iw * ih) / area > 0.5:
            return True
    return False


def table_skip_rects(pdf_path: str, pages: list[int] | None = None) -> dict[int, list]:
    """번역 제외 영역: 그림(이미지) 겹침. (표/박스는 눈금선 규칙이 처리)

    NOTE: 외곽 rect 규칙은 figure 패널이 캡션·본문까지 삼켜서 폐지.
    find_tables도 heatmap 오탐 위험으로 미사용.
    """
    import pymupdf as _pm
    doc = _pm.open(pdf_path)
    wanted = set(pages) if pages is not None else set(range(len(doc)))
    out: dict[int, list] = {}
    for pno in sorted(wanted):
        if pno >= len(doc):
            continue
        page = doc[pno]
        rects = []
        try:
            for d in page.get_drawings():
                r = d.get("rect")
                if not r:
                    continue
                # 외곽선 있는 상자만 (채우기 전용 배경 제외) + 면적 2~80%
                if d.get("color") is None:
                    continue
                if not (r.width > 50 and r.height > 20):
                    continue
                W, H = page.rect.width, page.rect.height
                a = r.width * r.height / (W * H)
                if 0.02 <= a <= 0.8:
                    rects.append(((r.x0, r.y0, r.x1, r.y1), "box"))
        except Exception:
            pass
        try:
            for img in page.get_images():
                try:
                    b = page.get_image_bbox(img)
                    rects.append(((b.x0, b.y0, b.x1, b.y1), "img"))
                except Exception:
                    continue
        except Exception:
            pass
        if rects:
            out[pno] = rects
    doc.close()
    return out


def _inside(x: float, y: float, rect, tol: float = 2.0) -> bool:
    x0, y0, x1, y1 = rect
    return x0 - tol <= x <= x1 + tol and y0 - tol <= y <= y1 + tol


def in_skip_rect(cx: float, cy: float, rects: list, text_len: int) -> bool:
    """box(긴 텍스트만) / img(항상) 판정."""
    for r, kind in rects:
        if not _inside(cx, cy, r):
            continue
        if kind == "img":
            return True
        if text_len > 100:
            return True
    return False


def iter_blocks(pdf_path: str, pages: list[int] | None = None,
                skip_rects: dict[int, list] | None = None,
                rulings: dict[int, tuple[list, list]] | None = None,
                ruled_skip: bool = True,
                table_regs: dict[int, list] | None = None) -> list[Block]:
    doc = pymupdf.open(pdf_path)
    out: list[Block] = []
    wanted = set(pages) if pages is not None else None
    drawings: dict[int, list] = {}
    for pno in range(len(doc)):
        if wanted is not None and pno not in wanted:
            continue
        page = doc[pno]
        H = page.rect.height
        try:
            drawings[pno] = [d["rect"] for d in page.get_drawings() if d.get("rect")]
        except Exception:
            drawings[pno] = []
        d = page.get_text("dict")
        for b in d["blocks"]:
            if b["type"] != 0:
                continue
            x0, y0, x1, y1 = b["bbox"]
            if _is_header_footer(pno, len(doc), y0, H):
                # ICLR/Published 헤더 같은 반복 요소 제거
                snippet = "".join(s["text"] for l in b["lines"] for s in l["spans"])
                if "Published as" in snippet or "conference paper" in snippet.lower():
                    continue
            spans = [s for l in b["lines"] for s in l["spans"]]
            if not spans:
                continue
            # 눈금선: 줄 단위로 표 내부를 제거 (본문+표 혼합 블록 대응)
            # 표 영역(table_regs) 내부 줄도 제거
            if ruled_skip and ((rulings and pno in rulings)
                               or (table_regs and pno in table_regs)):
                hl = rulings[pno][0] if (rulings and pno in rulings) else []
                regs = table_regs.get(pno, []) if table_regs else []
                kept_lines = []
                for l in b["lines"]:
                    lx0, ly0, lx1, ly1 = l["bbox"][0], l["bbox"][1], l["bbox"][2], l["bbox"][3]
                    if any(rx0 - 5 <= lx0 and ly0 >= ry0 - 5 and lx1 <= rx1 + 5 and ly1 <= ry1 + 5
                           for rx0, ry0, rx1, ry1 in regs):
                        continue
                    n = sum(1 for qx0, qx1, qy in hl
                            if ly0 - 4 <= qy <= ly1 + 4
                            and min(qx1, lx1) - max(qx0, lx0) > (lx1 - lx0) * 0.5)
                    if n < 2:
                        kept_lines.append(l)
                if not kept_lines:
                    continue
                if len(kept_lines) < len(b["lines"]):
                    b = {"bbox": [min(l["bbox"][0] for l in kept_lines),
                                  min(l["bbox"][1] for l in kept_lines),
                                  max(l["bbox"][2] for l in kept_lines),
                                  max(l["bbox"][3] for l in kept_lines)],
                         "lines": kept_lines, "type": 0}
                    x0, y0, x1, y1 = b["bbox"]
                    spans = [s for l in kept_lines for s in l["spans"]]
                    if not spans:
                        continue
            # monospace 지배 블록 (알고리즘/코드) 스킵
            if _dominant_is_mono(spans):
                continue
            # 세로 스탬프 (여백 arXiv 등) 스킵
            bw, bh = x1 - x0, y1 - y0
            if bw < 30 and bh > 100:
                continue
            # 벡터 그림 내부 짧은 라벨 스킵 (도형 밀집 + 150자 미만)
            if bw * bh > 0:
                hits = 0
                for dr in drawings.get(pno, []):
                    if dr.x0 <= x1 + 2 and dr.x1 >= x0 - 2 and dr.y0 <= y1 + 2 and dr.y1 >= y0 - 2:
                        hits += 1
                        if hits >= 12:
                            break
                # (추후 텍스트 길이 확정 후 판정하므로 플래그 저장)
                _fig_dense = hits >= 12
            else:
                _fig_dense = False
            text = ""
            for l in b["lines"]:
                line = "".join(s["text"] for s in l["spans"])
                text += line + "\n"
            text = dehyphenate(text).strip()
            text = normalize_ligatures(text)
            if not text:
                continue
            # 표 영역 내부는 통째로 스킵 (셀·병합 방지)
            if table_regs and pno in table_regs:
                if in_table_region((x0, y0, x1, y1), table_regs[pno]):
                    continue
            # 표·테두리상자·그림 내부 스킵 (중심점 판정; 상자는 긴 텍스트만)
            if skip_rects and pno in skip_rects:
                cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
                if in_skip_rect(cx, cy, skip_rects[pno], len(text)):
                    continue
            # 벡터 그림 내부 짧은 라벨 스킵
            if len(text) < 150 and _fig_dense:
                continue
            fs = sum(s["size"] * len(s["text"]) for s in spans) / max(1, sum(len(s["text"]) for s in spans))
            bold = any("bold" in s["font"].lower() or "black" in s["font"].lower() for s in spans)
            rights = tuple(round(l["bbox"][2], 1) for l in b["lines"])
            out.append(Block(page=pno, bbox=(x0, y0, x1, y1), text=text, fontsize=float(fs), is_bold=bold,
                             line_rights=rights))
    doc.close()
    # 읽기 순서: 페이지 내 y → x (2단은 근사: x 중심이 절반 기준)
    return out


def dehyphenate(text: str) -> str:
    # 학술 PDF의 줄끝 하이픈(trans- / former) 복원
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    text = text.replace("\n", " ")
    text = re.sub(r"\s{2,}", " ", text)
    return text


def merge_line_fragments(blocks: list[Block],
                           rulings: dict[int, list[float]] | None = None) -> list[Block]:
    """같은 줄에서 잘게 쪼개진 블록 병합 (PyMuPDF dict의 과분할 보정).

    조건: 같은 페이지 + 세로 중심 차이 < min(높이)/2 + 폰트 유사 → x 순으로 병합.
    2단 칼럼 오병합 방지를 위해 x-gap < 40pt 조건 추가.
    박스 경계(세로선)를跨는 병합 금지.
    """
    if not blocks:
        return blocks
    out: list[Block] = []
    # 페이지별 처리, y 중심 → x 순 정렬
    by_page: dict[int, list[Block]] = {}
    for b in blocks:
        by_page.setdefault(b.page, []).append(b)
    for pno in sorted(by_page):
        lst = sorted(by_page[pno], key=lambda b: ((b.bbox[1] + b.bbox[3]) / 2, b.bbox[0]))
        cur: Block | None = None
        for b in lst:
            if cur is None:
                cur = b
                continue
            cy0 = (cur.bbox[1] + cur.bbox[3]) / 2
            cy1 = (b.bbox[1] + b.bbox[3]) / 2
            hmin = min(cur.bbox[3] - cur.bbox[1], b.bbox[3] - b.bbox[1])
            xgap = b.bbox[0] - cur.bbox[2]
            same_font = abs(cur.fontsize - b.fontsize) <= 2.5
            cross = False
            if rulings and pno in rulings and xgap > 0:
                cross = any(cur.bbox[2] < x < b.bbox[0] for x in rulings[pno])
            if (abs(cy1 - cy0) <= max(3.0, hmin * 0.6) and -8 <= xgap <= 40
                    and same_font and not cross
                    and len(cur.text) + len(b.text) <= 600):
                x0 = min(cur.bbox[0], b.bbox[0])
                y0 = min(cur.bbox[1], b.bbox[1])
                x1 = max(cur.bbox[2], b.bbox[2])
                y1 = max(cur.bbox[3], b.bbox[3])
                sep = "" if cur.text.endswith("-") or b.text[:1] in ".,:;)%°" else " "
                cur = Block(page=pno, bbox=(x0, y0, x1, y1),
                            text=_join_texts(cur.text, b.text) if sep else (cur.text + b.text).strip(),
                            fontsize=(cur.fontsize + b.fontsize) / 2,
                            is_bold=cur.is_bold and b.is_bold,
                            line_rights=cur.line_rights + b.line_rights)
            else:
                out.append(cur)
                cur = b
        if cur is not None:
            out.append(cur)
    return out


def _slide_vlines(pdf_path: str, pages: list[int] | None = None) -> dict[int, list[tuple]]:
    """슬라이드 박스 세로 경계 [(x, y0, y1)]: 가는 선 + 채움 박스 모서리."""
    import pymupdf as _pm
    doc = _pm.open(pdf_path)
    wanted = set(pages) if pages is not None else set(range(len(doc)))
    out: dict[int, list[tuple]] = {}
    for pno in sorted(wanted):
        if pno >= len(doc):
            continue
        W, H = doc[pno].rect.width, doc[pno].rect.height
        xs: dict[float, list] = {}
        try:
            for d in doc[pno].get_drawings():
                r = d.get("rect")
                if not r:
                    continue
                if r.height > 30 and r.width < 3:
                    # 가는 세로선
                    x = round((r.x0 + r.x1) / 2, 1)
                    xs.setdefault(x, []).append((r.y0, r.y1))
                elif (r.width > 40 and r.height > 30
                        and r.width * r.height < W * H * 0.8):
                    # 채움 박스 모서리
                    for x in (round(r.x0, 1), round(r.x1, 1)):
                        xs.setdefault(x, []).append((r.y0, r.y1))
        except Exception:
            pass
        if xs:
            out[pno] = sorted((x, min(y[0] for y in v), max(y[1] for y in v))
                              for x, v in xs.items())
    doc.close()
    return out


def slide_rulings(pdf_path: str, pages: list[int] | None = None) -> dict[int, list[float]]:
    """슬라이드 박스 경계(세로선) x좌표 수집 — 경계越 병합 방지용."""
    return {p: [x for x, _, _ in v] for p, v in _slide_vlines(pdf_path, pages).items()}


def slide_ruling_boxes(pdf_path: str, pages: list[int] | None = None) -> dict[int, list[tuple]]:
    """세로 경계의 (x, y0, y1) — 행 블록 분할용."""
    return _slide_vlines(pdf_path, pages)


def split_row_blocks(pdf_path: str, blocks: list[Block],
                     boxes: dict[int, list[tuple]] | None = None,
                     col_gap: float = 0.0,
                     regs: dict[int, list] | None = None) -> list[Block]:
    """넓은 블록을 세로 경계에서 분할 (rawdict 줄 단위).

    - 슬라이드: 박스 경계(boxes) 사용.
    - 논문: col_gap>0이면 문자 공백 기준 (2단 나눔).
    경계는 해당 줄과 겹치고 높이가 비슷할 때만 유효.
    """
    import pymupdf as _pm
    doc = _pm.open(pdf_path)
    out: list[Block] = []
    for b in blocks:
        try:
            page = doc[b.page]
            W = page.rect.width
            # 논문 모드(col_gap)에서 좁은 블록은 분할 불필요
            if boxes is None and (b.bbox[2] - b.bbox[0]) < W * 0.5:
                out.append(b)
                continue
            # 블록과 겹치는 줄 수집
            lines = []
            for lb in page.get_text("rawdict")["blocks"]:
                if lb["type"] != 0:
                    continue
                for l in lb["lines"]:
                    spans = l["spans"]
                    if not spans:
                        continue
                    ly0 = min(s["bbox"][1] for s in spans)
                    ly1 = max(s["bbox"][3] for s in spans)
                    if ly1 < b.bbox[1] or ly0 > b.bbox[3]:
                        continue
                    cs = [c for s in spans for c in s["chars"]]
                    if cs:
                        lines.append((ly0, ly1, cs))
            # 이 블록에 유효한 경계만 (줄과 겹치고 높이 비슷)
            bh = b.bbox[3] - b.bbox[1]
            cuts = set()
            if boxes:
                for x, ry0, ry1 in boxes.get(b.page, []):
                    if not (b.bbox[0] + 5 < x < b.bbox[2] - 5):
                        continue
                    rh = ry1 - ry0
                    if rh < bh * 0.5 or rh > bh * 4:
                        continue
                    if min(ry1, b.bbox[3]) - max(ry0, b.bbox[1]) < bh * 0.5:
                        continue
                    cuts.add(x)
            if col_gap > 0 and not cuts:
                # (a) 표 영역 경계에서 절단
                if regs:
                    for rx0, ry0, rx1, ry1 in regs.get(b.page, []):
                        if ry1 < b.bbox[1] or ry0 > b.bbox[3]:
                            continue
                        for ex in (rx0, rx1):
                            if b.bbox[0] + 10 < ex < b.bbox[2] - 10:
                                cuts.add(round(ex, 1))
                # (b) 줄별 내부 공백 기준 절단
                for ly0, ly1, cs in lines:
                    xs = sorted((c["bbox"][0] + c["bbox"][2]) / 2 for c in cs)
                    for a, cc in zip(xs, xs[1:]):
                        mid = (a + cc) / 2
                        if cc - a > col_gap and b.bbox[0] + 10 < mid < b.bbox[2] - 10:
                            cuts.add(round(mid, 1))
                # (c) 절단 없음 + 넓은 블록: 줄 군집 분리 (수식 줄 제외)
                if not cuts and (b.bbox[2] - b.bbox[0]) > page.rect.width * 0.55:
                    W = page.rect.width

                    def _eqline(cs) -> bool:
                        s = "".join(c["c"] for c in sorted(cs, key=lambda c: c["bbox"][0])).strip()
                        if len(s) < 8:
                            return True
                        sym = sum(1 for c in s if not c.isalnum() and not c.isspace()
                                  and c not in ".,;:!?\"'“”‘’—–-")
                        return sym / max(1, len(s)) > 0.35

                    gl = [(ly0, ly1, cs) for ly0, ly1, cs in lines
                          if not _eqline(cs)
                          and sum(1 for c in cs if (c["bbox"][0] + c["bbox"][2]) / 2 < W / 2) >= len(cs) / 2]
                    gr = [(ly0, ly1, cs) for ly0, ly1, cs in lines
                          if not _eqline(cs)
                          and not any(cs is g[2] for g in gl)]

                    def _spaced(items):
                        s = ""
                        px = None
                        for _, _, cs in items:
                            for c in sorted(cs, key=lambda c: c["bbox"][0]):
                                if px is not None and c["bbox"][0] - px > 6:
                                    s += " "
                                s += c["c"]
                                px = c["bbox"][2]
                            s += " "
                        return re.sub(r"\s+", " ", s).strip()

                    g1, g2 = _spaced(gl), _spaced(gr)
                    if len(g1) >= 30 and len(g2) >= 30:
                        for gt, grp in ((g1, gl), (g2, gr)):
                            xs = [c["bbox"][0] for _, _, cs in grp for c in cs]
                            xe = [c["bbox"][2] for _, _, cs in grp for c in cs]
                            ys = [c["bbox"][1] for _, _, cs in grp for c in cs]
                            ye = [c["bbox"][3] for _, _, cs in grp for c in cs]
                            out.append(Block(page=b.page,
                                             bbox=(min(xs) - 2, min(ys) - 2, max(xe) + 2, max(ye) + 2),
                                             text=gt, fontsize=b.fontsize,
                                             is_bold=b.is_bold, line_rights=()))
                        continue
            cuts = sorted(cuts)
            cuts = sorted(cuts)
            if not cuts or not lines:
                out.append(b)
                continue
            bounds = [b.bbox[0]] + cuts + [b.bbox[2]]
            acc: dict[int, list[str]] = {i: [] for i in range(len(bounds) - 1)}
            accbox: dict[int, list] = {i: [] for i in range(len(bounds) - 1)}
            fs = max(6.0, b.fontsize)
            for ly0, ly1, cs in lines:
                cs.sort(key=lambda c: c["bbox"][0])
                cur = 0
                buckets: dict[int, list[str]] = {}
                px: dict[int, float] = {}
                for c in cs:
                    cx = (c["bbox"][0] + c["bbox"][2]) / 2
                    if cx < bounds[0] or cx >= bounds[-1]:
                        continue
                    while cur + 1 < len(bounds) and cx >= bounds[cur + 1]:
                        cur += 1
                    buckets.setdefault(cur, [])
                    if cur in px and c["bbox"][0] - px[cur] > fs * 0.22:
                        buckets[cur].append(" ")
                    buckets[cur].append(c["c"])
                    px[cur] = c["bbox"][2]
                for i, chs in buckets.items():
                    s = "".join(chs).strip()
                    if len(s) >= 2:
                        acc[i].append(s)
                        accbox[i].extend(
                            [c["bbox"] for c in cs
                             if bounds[i] <= (c["bbox"][0] + c["bbox"][2]) / 2 < bounds[i + 1]])
            parts = []
            for i in sorted(acc):
                if acc[i]:
                    tx = " ".join(acc[i])
                    xs = [bb[0] for bb in accbox[i]] + [bb[2] for bb in accbox[i]]
                    ys = [bb[1] for bb in accbox[i]] + [bb[3] for bb in accbox[i]]
                    parts.append((tx, (min(xs) - 2, min(min(ys), b.bbox[1]),
                                       max(xs) + 2, max(max(ys), b.bbox[3]))))
            if len(parts) >= 2:
                for tx, bb in parts:
                    x0, y0, x1, y1 = bb
                    out.append(Block(page=b.page, bbox=(x0, y0, x1, y1),
                                     text=tx, fontsize=b.fontsize,
                                     is_bold=b.is_bold, line_rights=()))
            else:
                out.append(b)
        except Exception:
            out.append(b)
    doc.close()
    return out


def merge_slide_vertical(blocks: list[Block], max_gap: float = 30.0,
                         rulings: dict[int, list[float]] | None = None) -> list[Block]:
    """슬라이드용: 세로로 쌓인 같은 박스/불릿 조각 병합 (union-find 클러스터링).

    PyMuPDF가 한 불릿·박스를 여러 블록으로 쪼개므로 (예: 'questio'/'ns',
    'Dialogue'/'turn'), pairwise 조건을 만족하는 블록들을 같은 클러스터로 묶는다.
    조건: 같은 페이지 + x 겹침 40% 이상 + 세로 간격 [-12, max_gap] + 폰트 유사.
    (번역 제외 블록(연구실 헤더·쪽번호)은 클러스터 방해 금지 → 미리 분리)
    """
    if not blocks:
        return blocks

    def _fixed(b: Block) -> bool:
        return bool(LAB_HEADER.search(b.text) or re.fullmatch(r"\d{1,3}", b.text.strip()))

    out: list[Block] = [b for b in blocks if _fixed(b)]
    cand = [b for b in blocks if not _fixed(b)]

    def _pair(a: Block, c: Block) -> bool:
        if a.page != c.page:
            return False
        # 박스 경계(세로선)를跨는 병합 금지
        if rulings and a.page in rulings:
            lo = min(a.bbox[2], c.bbox[2])
            hi = max(a.bbox[0], c.bbox[0])
            if any(lo < x < hi for x in rulings[a.page]):
                # 단, 같은 박스 안 조각(가로로 겹치면)은 허용
                x_overlap = min(a.bbox[2], c.bbox[2]) - max(a.bbox[0], c.bbox[0])
                if x_overlap <= 0:
                    return False
        x_overlap = min(a.bbox[2], c.bbox[2]) - max(a.bbox[0], c.bbox[0])
        wmin = min(a.bbox[2] - a.bbox[0], c.bbox[2] - c.bbox[0])
        if wmin <= 0 or x_overlap < wmin * 0.4:
            return False
        top, bot = (a, c) if a.bbox[1] <= c.bbox[1] else (c, a)
        ygap = bot.bbox[1] - top.bbox[3]
        if not (-12 <= ygap <= max_gap):
            return False
        return abs(a.fontsize - c.fontsize) <= 3.0

    parent = list(range(len(cand)))

    def _find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(cand)):
        for j in range(i + 1, len(cand)):
            if _pair(cand[i], cand[j]):
                ri, rj = _find(i), _find(j)
                if ri != rj:
                    parent[rj] = ri
    clusters: dict[int, list[Block]] = {}
    for i, b in enumerate(cand):
        clusters.setdefault(_find(i), []).append(b)
    for members in clusters.values():
        members.sort(key=lambda b: (b.bbox[1], b.bbox[0]))
        if len(members) == 1:
            out.append(members[0])
            continue
        x0 = min(b.bbox[0] for b in members)
        y0 = min(b.bbox[1] for b in members)
        x1 = max(b.bbox[2] for b in members)
        y1 = max(b.bbox[3] for b in members)
        out.append(Block(page=members[0].page, bbox=(x0, y0, x1, y1),
                         text=" ".join(b.text for b in members).strip(),
                         fontsize=sum(b.fontsize for b in members) / len(members),
                         is_bold=all(b.is_bold for b in members),
                         line_rights=tuple(x for b in members for x in b.line_rights)))
    return out


def _join_texts(a: str, b: str) -> str:
    """경계 중복 제거 병합 (겹치는 문장 조각 이중 번역 방지)."""
    import re as _re2
    aw = a.split()
    bw = b.split()

    def _nw(w: str) -> str:
        return _re2.sub(r"^[^A-Za-z0-9가-힣]+|[^A-Za-z0-9가-힣]+$", "", w).lower()

    an = [_nw(w) for w in aw]
    bn = [_nw(w) for w in bw]
    for k in range(min(len(bn), 30, len(an)), 0, -1):
        if bn[:k] == an[-k:]:
            return a + " " + " ".join(bw[k:])
    return a + " " + b


def merge_dangling(blocks: list[Block]) -> list[Block]:
    """짧은 매달림 조각을 이전 블록에 병합 (논문용).

    조건: 같은 페이지 + 이전 블록 바로 아래(간격 0~40) + x 겹침 40% + 폰트 유사.
    체크리스트·수식 잔줄 같은 짧은 조각이 통째로 번역되게 한다.
    """
    if not blocks:
        return blocks
    out: list[Block] = []
    by_page: dict[int, list[Block]] = {}
    for b in blocks:
        by_page.setdefault(b.page, []).append(b)
    for pno in sorted(by_page):
        lst = by_page[pno]
        page_w = max(b.bbox[2] for b in lst)

        def _col(b: Block) -> int:
            cx = (b.bbox[0] + b.bbox[2]) / 2
            if b.bbox[2] - b.bbox[0] > page_w * 0.55:
                return -1  # 전폭 블록 (제목·그림캡션)
            return 0 if cx < page_w / 2 else 1

        lst = sorted(lst, key=lambda b: (_col(b), b.bbox[1], b.bbox[0]))
        cur: Block | None = None
        for b in lst:
            if cur is not None:
                # 완전 중복 텍스트 제거 (PDF 이중 텍스트)
                if b.text and (b.text in cur.text or cur.text in b.text):
                    if len(b.text) >= len(cur.text):
                        cur = b
                    continue
            # 같은 열에서 문장 계속이면 병합 (길이 무관, 들여쓰기로 새 문단 구분)
            # 헤더/캡션/수식은 흡수하지도 당하지도 않음.
            # 열이 다르면 병합 금지 (전폭 슈퍼블록 방지). 중복은 NMS가 처리.
            if (cur is not None
                    and not _is_header_like(cur.text)
                    and not re.search(r"[.!?][\"')\]}»”。]*\s*$", cur.text)
                    and abs(cur.fontsize - b.fontsize) <= 1.5
                    and not _is_header_like(b.text)
                    and not _is_equation_display(b.text)
                    and b.text.lower() not in KNOWN_HEADERS
                    and re.search(r"[a-z]{3}", cur.text[-15:])
                    and (re.match(r"^[a-z가-힣]", b.text)
                         or b.bbox[0] <= cur.bbox[0] + 10)):
                gap = b.bbox[1] - cur.bbox[3]
                same_col = (_col(b) == _col(cur))
                # 짧은 조각은 가까울 때만 흡수 (먼 조각은 문맥 번역으로 별도 처리)
                # 겹침(음수 gap)은 하한 없이 병합 (같은 흐름 조각)
                max_gap = 25 if len(b.text) < 80 else 60
                # 크게 겹친 조각은 같은 내용 이중 추출 → 상한 완화 (경계 중복 제거됨)
                cap = 3000 if gap < -30 else 2500
                if (same_col and gap <= max_gap
                        # 병합 체인 길이 상한 (페이지 삼킴 방지, 장문단 허용)
                        and len(cur.text) + len(b.text) <= cap):
                    xov = min(cur.bbox[2], b.bbox[2]) - max(cur.bbox[0], b.bbox[0])
                    wmin = min(cur.bbox[2] - cur.bbox[0], b.bbox[2] - b.bbox[0])
                    if wmin > 0 and xov >= wmin * 0.3:
                        x0 = min(cur.bbox[0], b.bbox[0])
                        y0 = min(cur.bbox[1], b.bbox[1])
                        x1 = max(cur.bbox[2], b.bbox[2])
                        y1 = max(cur.bbox[3], b.bbox[3])
                        # 읽기 순서: 소문자 시작 조각이 뒤에 오게 (경계 중복 제거)
                        if (not re.match(r"^[a-z가-힣]", b.text)
                                and re.match(r"^[a-z가-힣]", cur.text)):
                            txt = _join_texts(b.text, cur.text)
                        else:
                            txt = _join_texts(cur.text, b.text)
                        cur = Block(
                            page=pno, bbox=(x0, y0, x1, y1),
                            text=txt,
                            fontsize=(cur.fontsize + b.fontsize) / 2,
                            is_bold=cur.is_bold and b.is_bold,
                            line_rights=cur.line_rights + b.line_rights)
                        continue
            if cur is not None:
                out.append(cur)
            cur = b
        if cur is not None:
            out.append(cur)
    return out


def _is_header_like(t: str) -> bool:
    s = t.strip()
    if re.match(r"^(\d+(\.\d+)*|[A-Z](\.\d+)*|Appendix)\s+[A-Z0-9]", s):
        return True
    if re.match(r"^(Table|Figure|Fig\.)\s+\d+", s):
        return True
    return s.lower() in KNOWN_HEADERS


def _is_equation_display(t: str) -> bool:
    """수식 디스플레이 여부 (병합 제외용)."""
    s = t.strip()
    if len(s) >= 200:
        return False
    sym = sum(1 for c in s if not c.isalnum() and not c.isspace()
              and c not in ".,;:!?\"'“”‘’—–-")
    if sym / max(1, len(s)) <= 0.3:
        return False
    if re.search(r"[.!?]\s+[A-Z]", s) or re.search(r"[.!?]$", s.strip()):
        return False
    return True


LIGATURES = str.maketrans({
    "ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl",
    "ﬅ": "st", "ﬆ": "st", "–": "-", "—": "-", "‐": "-",
    "‘": "'", "’": "'", "“": '"', "”": '"', "…": "...",
})


def normalize_ligatures(t: str) -> str:
    return t.translate(LIGATURES)


def reading_order(blocks: list[Block]) -> list[Block]:
    """열 기준 읽기 순서 정렬 (단 넘김 추적용)."""
    by_page: dict[int, list[Block]] = {}
    for b in blocks:
        by_page.setdefault(b.page, []).append(b)
    out: list[Block] = []
    for pno in sorted(by_page):
        lst = by_page[pno]
        page_w = max(b.bbox[2] for b in lst)

        def _col(b: Block) -> int:
            cx = (b.bbox[0] + b.bbox[2]) / 2
            if b.bbox[2] - b.bbox[0] > page_w * 0.55:
                return -1
            return 0 if cx < page_w / 2 else 1

        out.extend(sorted(lst, key=lambda b: (_col(b), b.bbox[1], b.bbox[0])))
    return out


def merge_overlaps(blocks: list[Block]) -> list[Block]:
    """박스가 겹치고 문장이 이어지면 병합 (열 무관, 읽기 순서로 연결)."""
    if not blocks:
        return blocks
    out: list[Block] = []
    by_page: dict[int, list[Block]] = {}
    for b in blocks:
        by_page.setdefault(b.page, []).append(b)
    for pno in sorted(by_page):
        lst = sorted(by_page[pno], key=lambda b: (b.bbox[1], b.bbox[0]))
        cur: Block | None = None
        for b in lst:
            if (cur is not None
                    and not _is_header_like(cur.text)
                    and not re.search(r"[.!?][\"')\]}»”。]*\s*$", cur.text)
                    and abs(cur.fontsize - b.fontsize) <= 1.5
                    and not _is_header_like(b.text)
                    and not _is_equation_display(b.text)
                    and b.text.lower() not in KNOWN_HEADERS
                    and len(cur.text) + len(b.text) <= 900
                    and re.search(r"[a-z]{3}", cur.text[-15:])):
                xov = min(cur.bbox[2], b.bbox[2]) - max(cur.bbox[0], b.bbox[0])
                yov = min(cur.bbox[3], b.bbox[3]) - max(cur.bbox[1], b.bbox[1])
                wmin = min(cur.bbox[2] - cur.bbox[0], b.bbox[2] - b.bbox[0])
                hmin = min(cur.bbox[3] - cur.bbox[1], b.bbox[3] - b.bbox[1])
                if (wmin > 0 and hmin > 0 and xov >= wmin * 0.3 and yov >= hmin * 0.3):
                    # 짧은 조각 흡수로 박스가 과도 확장되면 별도 처리 (문맥 번역)
                    _ny0 = min(cur.bbox[1], b.bbox[1])
                    _ny1 = max(cur.bbox[3], b.bbox[3])
                    if len(b.text) < 80 and (_ny1 - _ny0) - (cur.bbox[3] - cur.bbox[1]) > 40:
                        pass
                    else:
                        # 읽기 순서: 대문자 시작이 head (경계 중복 제거)
                        if (not re.match(r"^[a-z가-힣]", b.text)
                                and re.match(r"^[a-z가-힣]", cur.text)):
                            txt = _join_texts(b.text, cur.text)
                        else:
                            txt = _join_texts(cur.text, b.text)
                        cur = Block(
                            page=pno,
                            bbox=(min(cur.bbox[0], b.bbox[0]), _ny0,
                                  max(cur.bbox[2], b.bbox[2]), _ny1),
                            text=txt,
                            fontsize=(cur.fontsize + b.fontsize) / 2,
                            is_bold=cur.is_bold and b.is_bold,
                            line_rights=cur.line_rights + b.line_rights)
                        continue
            if cur is not None:
                out.append(cur)
            cur = b
        if cur is not None:
            out.append(cur)
    return out


def is_continuation_frag(b: Block, prev: Block | None) -> bool:
    """단 넘김 꼬리 여부 (문맥 번역 대상)."""
    if prev is None or b.page != prev.page or len(b.text) >= 60:
        return False
    if re.search(r"[.!?][\"')\]}»”。]*\s*$", prev.text):
        return False
    if abs(prev.fontsize - b.fontsize) > 1.5:
        return False
    if re.match(r"^(\d+(\.\d+)*|[A-Z](\.\d+)*|Appendix)\s+[A-Z0-9]", b.text):
        return False
    return True


def continuation_prev(b: Block, prev: Block | None, page_h: float) -> Block | None:
    """문맥 번역용 이전 블록 (위치까지 검증)."""
    if not is_continuation_frag(b, prev):
        return None
    gap = b.bbox[1] - prev.bbox[3]
    if -50 <= gap <= 120:
        return prev
    # 단 넘김: 이전 블록이 왼쪽에 있고 더 아래까지 내려오면 계속 문장
    if prev.bbox[2] <= b.bbox[0] and prev.bbox[3] >= b.bbox[1]:
        return prev
    return None


def collect_fragments(blocks: list[Block], cands: list[Block],
                        page_h: dict[int, float] | None = None) -> list[Block]:
    """문장 꼬리 조각 수집 (그림 라벨 제외: 문맥상 이전 블록이 있어야 함).

    조건: 15~60자 + 산문(소문자 단어, '=' 없음, 숫자 2개 이하) + 헤더 아님 +
    읽기 순서상 이전 번역 블록이 continuation_prev를 만족.
    """
    in_cands = {id(b) for b in cands}
    order = reading_order(blocks)
    out: list[Block] = []
    for b in order:
        if id(b) in in_cands:
            continue
        t = b.text.strip()
        if not (15 <= len(t) < 60):
            continue
        if not re.search(r"[a-z]{3,}", t):
            continue
        if "=" in t or len(re.findall(r"\d", t)) > 2:
            continue
        # 수식 조각 제외 (기호 밀도, 괄호·숫자 시작)
        sym = sum(1 for c in t if not c.isalnum() and not c.isspace()
                  and c not in ".,;:!?\"'“”‘’—–-")
        if sym / max(1, len(t)) > 0.2:
            continue
        if re.match(r"^[\s\[\({<\$0-9]", t):
            continue
        if re.match(r"^(\d+(\.\d+)*|[A-Z](\.\d+)*|Appendix)\s+[A-Z0-9]", t):
            continue
        if t.lower() in KNOWN_HEADERS:
            continue
        # 읽기 순서상 가장 가까운 이전 번역 블록
        prev = None
        for c in reversed(order[:order.index(b)]):
            if id(c) in in_cands:
                prev = c
                break
        h = (page_h or {}).get(b.page, 792.0)
        if continuation_prev(b, prev, h) is not None:
            out.append(b)
    return out


def drop_contained(blocks: list[Block]) -> list[Block]:
    """포함 중복 제거 (박스 포함 + 텍스트 공유 시 작은 쪽 제거)."""
    if not blocks:
        return blocks
    out: list[Block] = []
    by_page: dict[int, list[Block]] = {}
    for b in blocks:
        by_page.setdefault(b.page, []).append(b)
    for pno in sorted(by_page):
        lst = by_page[pno]
        drop: set[int] = set()
        for i in range(len(lst)):
            for j in range(len(lst)):
                if i == j or i in drop or j in drop:
                    continue
                a, c = lst[i], lst[j]
                ax0, ay0, ax1, ay1 = a.bbox
                cx0, cy0, cx1, cy1 = c.bbox
                # 박스 포함: 작은 쪽 제거 (캡션 안 조각 등).
                # 텍스트 무관. 단, 길이 차이가 3배 미만이면 텍스트 공유 확인.
                if ((cx0 - 2 <= ax0 and cy0 - 2 <= ay0 and ax1 <= cx1 + 2 and ay1 <= cy1 + 2)
                        and (ax1 - ax0) * (ay1 - ay0) < (cx1 - cx0) * (cy1 - cy0)):
                    at = a.text.strip()
                    ct = c.text
                    if len(ct) > 3 * len(at) or (len(at) >= 10 and (at[:20] in ct or at[-20:] in ct)):
                        drop.add(i)
                        continue
                if len(a.text) < 30 or len(a.text) >= len(c.text):
                    continue
                na = normalize_ligatures(a.text).lower()
                nc = normalize_ligatures(c.text).lower()
                if na not in nc:
                    continue
                iw = min(ax1, cx1) - max(ax0, cx0)
                ih = min(ay1, cy1) - max(ay0, cy0)
                if iw <= 0 or ih <= 0:
                    continue
                if (iw * ih) / max(1.0, (ax1 - ax0) * (ay1 - ay0)) >= 0.5:
                    drop.add(i)
        out.extend(b for i, b in enumerate(lst) if i not in drop)
    return out


def dedupe_cands(cands: list[Block]) -> list[Block]:
    """번역 후보 중복 제거 (레이아웃 NMS + 텍스트 공유).

    1차: 박스 겹침 NMS - 작은 쪽 면적 기준 40% 이상 겹치면 긴 쪽만 유지.
         PyMuPDF 이중 블록/분할 중복 원천 차단 (텍스트 무관, 하드코딩 없음).
    2차: 30% 겹침 + 텍스트 공유 시 짧은 쪽 제거.
    """
    if not cands:
        return cands

    def _norm(t: str) -> str:
        t = normalize_ligatures(t).lower()
        return re.sub(r"[^a-z0-9가-힣]+", "", t)

    def _shared(a: str, b: str, n: int = 20) -> bool:
        na, nb = _norm(a), _norm(b)
        if len(na) < n:
            return na in nb
        for i in range(0, len(na) - n + 1, 10):
            if na[i:i + n] in nb:
                return True
        return False

    def _overlap(a: Block, c: Block) -> float:
        ax0, ay0, ax1, ay1 = a.bbox
        cx0, cy0, cx1, cy1 = c.bbox
        iw = min(ax1, cx1) - max(ax0, cx0)
        ih = min(ay1, cy1) - max(ay0, cy0)
        if iw <= 0 or ih <= 0:
            return 0.0
        inter = iw * ih
        small = min((ax1 - ax0) * (ay1 - ay0), (cx1 - cx0) * (cy1 - cy0))
        return inter / max(1.0, small)

    # 1차: 레이아웃 NMS - 65% 이상 겹치면 긴 텍스트만 유지 (텍스트 무관).
    # 40~65% 겹침은 2차 텍스트 공유 검사에 맡김 (별개 문단 삭제 방지).
    keep = [True] * len(cands)
    order = sorted(range(len(cands)), key=lambda i: len(cands[i].text), reverse=True)
    for ii in range(len(order)):
        i = order[ii]
        if not keep[i]:
            continue
        for jj in range(ii + 1, len(order)):
            j = order[jj]
            if not keep[j] or cands[i].page != cands[j].page:
                continue
            if _overlap(cands[i], cands[j]) >= 0.65:
                keep[j] = False
    cands = [b for b, k in zip(cands, keep) if k]
    if not cands:
        return cands

    keep = [True] * len(cands)
    norms = [_norm(b.text) for b in cands]
    for i in range(len(cands)):
        if not keep[i]:
            continue
        for j in range(len(cands)):
            if i == j or not keep[j]:
                continue
            a, c = cands[i], cands[j]
            if a.page != c.page or len(a.text) < 30:
                continue
            ax0, ay0, ax1, ay1 = a.bbox
            cx0, cy0, cx1, cy1 = c.bbox
            iw = min(ax1, cx1) - max(ax0, cx0)
            ih = min(ay1, cy1) - max(ay0, cy0)
            if iw <= 0 or ih <= 0:
                continue
            if (iw * ih) / max(1.0, (ax1 - ax0) * (ay1 - ay0)) < 0.3:
                continue
            # 완전 동일 텍스트 → 중복 렌더 (뒤쪽 유지)
            if norms[i] == norms[j]:
                keep[i] = False
                break
            if len(a.text) >= len(c.text) - 20:
                continue
            # 짧은 쪽 전체가 정규화 후 긴 쪽에 포함될 때만 삭제.
            # (20자 부분一致는 수식 반복 문단에서 오탐 → 내용 소실)
            if a.text not in c.text and norms[i] not in norms[j]:
                continue
            keep[i] = False
            break
    cands = [b for b, k in zip(cands, keep) if k]
    return deoverlap_cands(cands)


def deoverlap_cands(cands: list[Block]) -> list[Block]:
    """후보 박스 겹침 해소: 같은 페이지·같은 열에서 세로로 겹치면 경계에서 나눔.

    PyMuPDF 박스에 패딩이 있어 별개 문단이 겹쳐 잡힌다. 텍스트는 유지하고
    박스만 반씩 나눠 렌더 겹침을 없앤다 (하드코딩 없음, 순수 레이아웃).
    """
    if not cands:
        return cands
    by_page: dict[int, list[Block]] = {}
    for b in cands:
        by_page.setdefault(b.page, []).append(b)
    out: list[Block] = []
    for pno in sorted(by_page):
        lst = sorted(by_page[pno], key=lambda b: (b.bbox[1], b.bbox[0]))
        boxes = [list(b.bbox) for b in lst]
        for i in range(len(lst)):
            for j in range(i + 1, len(lst)):
                ax0, ay0, ax1, ay1 = boxes[i]
                cx0, cy0, cx1, cy1 = boxes[j]
                iw = min(ax1, cx1) - max(ax0, cx0)
                if iw <= 0:
                    continue
                wmin = min(ax1 - ax0, cx1 - cx0)
                if wmin <= 0 or iw < wmin * 0.5:
                    continue
                ih = min(ay1, cy1) - max(ay0, cy0)
                if ih <= 0:
                    continue
                hmin = min(ay1 - ay0, cy1 - cy0)
                if hmin <= 0 or ih >= hmin * 0.65:
                    continue
                # 겹침을 반씩 나눔 (위 블록 아래를 올리고, 아래 블록 위를 내림)
                mid = (max(ay0, cy0) + min(ay1, cy1)) / 2
                if ay0 <= cy0:
                    boxes[i][3] = min(ay1, mid - 1)
                    boxes[j][1] = max(cy0, mid + 1)
                else:
                    boxes[j][3] = min(cy1, mid - 1)
                    boxes[i][1] = max(ay0, mid + 1)
        for b, bx in zip(lst, boxes):
            x0, y0, x1, y1 = bx
            if y1 - y0 < 8 or x1 - x0 < 8:
                continue
            out.append(Block(page=b.page, bbox=(x0, y0, x1, y1),
                             text=b.text, fontsize=b.fontsize,
                             is_bold=b.is_bold, line_rights=b.line_rights))
    return out


def refilter(blocks: list[Block], skip_rects: dict[int, list] | None = None,
             rulings: dict[int, tuple[list, list]] | None = None,
             table_regs: dict[int, list] | None = None) -> list[Block]:
    """분할 조각 재검사: 표/박스/그림 내부는 제거 (논문용)."""
    out: list[Block] = []
    for b in blocks:
        x0, y0, x1, y1 = b.bbox
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        drop = False
        if table_regs and b.page in table_regs:
            if in_table_region((x0, y0, x1, y1), table_regs[b.page]):
                drop = True
        if not drop and skip_rects and b.page in skip_rects:
            if in_skip_rect(cx, cy, skip_rects[b.page], len(b.text)):
                drop = True
        if not drop and rulings and b.page in rulings:
            if in_ruled_cell((x0, y0, x1, y1), rulings[b.page]):
                # 캡션 등 긴 블록은 살리고 짧은 셀만 제거
                if len(b.text) < 150:
                    drop = True
        if not drop:
            out.append(b)
    return out


def chunk_paragraph(text: str, max_chars: int = 1100) -> list[str]:
    """문장 경계에서 청크 분할."""
    sents = re.split(r"(?<=[\.\?\!])\s+(?=[A-Z0-9\(\"])", text)
    chunks: list[str] = []
    cur = ""
    for s in sents:
        if len(cur) + len(s) + 1 <= max_chars:
            cur = (cur + " " + s).strip()
        else:
            if cur:
                chunks.append(cur)
            cur = s
    if cur:
        chunks.append(cur)
    return chunks or [text]
