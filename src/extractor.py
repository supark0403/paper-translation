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
            r"(University|Institute|Laboratory|\bLAB\b|MIT|Technion|Northeastern|Cornell|"
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
    # 수식 빽빽 블록 스킵 (한 글자 토큰 비율)
    if len(t) > 60 and math_token_ratio(t) > 0.3:
        return False
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
    # 표 내부 명령문 패턴은 유지 (레퍼런스: 표 내부 미번역)
    if CITATION.match(t) and len(t) < 220 and "\n" not in t.strip():
        # 단, Table/Figure 캡션과 Section 헤더는 번역한다
        if re.match(r"^(Table|Figure|Fig\.)\s+\d+", t):
            return True
        if re.match(r"^\d+(\.\d+)*\s+[A-Z]", t):
            return True
        return False
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


def table_skip_rects(pdf_path: str, pages: list[int] | None = None) -> dict[int, list]:
    """번역 제외 영역: 표(find_tables 2x2+)·테두리 상자·그림(이미지)."""
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
            for tb in page.find_tables():
                if tb.row_count >= 2 and tb.col_count >= 2:
                    rects.append(tb.bbox)
        except Exception:
            pass
        try:
            W, H = page.rect.width, page.rect.height
            for d in page.get_drawings():
                r = d.get("rect")
                if not r:
                    continue
                # stroked 사각 테두리 (면적 < 페이지 80%)
                if (r.width > 50 and r.height > 20
                        and r.width * r.height < W * H * 0.8):
                    rects.append((r.x0, r.y0, r.x1, r.y1))
        except Exception:
            pass
        try:
            for img in page.get_images():
                try:
                    b = page.get_image_bbox(img)
                    rects.append((b.x0, b.y0, b.x1, b.y1))
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


def iter_blocks(pdf_path: str, pages: list[int] | None = None,
                skip_rects: dict[int, list] | None = None,
                rulings: dict[int, tuple[list, list]] | None = None,
                ruled_skip: bool = True) -> list[Block]:
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
            # monospace 지배 블록 (알고리즘/코드) 스킵
            if _dominant_is_mono(spans):
                continue
            # 세로 스탬프 (여백 arXiv 등) 스킵
            bw, bh = x1 - x0, y1 - y0
            if bw < 30 and bh > 100:
                continue
            # 표·테두리상자·그림 내부 스킵 (중심점 판정)
            if skip_rects and pno in skip_rects:
                cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
                if any(_inside(cx, cy, r) for r in skip_rects[pno]):
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
            if not text:
                continue
            # 벡터 그림 내부 짧은 라벨 스킵
            if len(text) < 150 and _fig_dense:
                continue
            # 눈금선 표/박스 내부 스킵 (논문만; 슬라이드는 박스째 번역)
            if ruled_skip and rulings and pno in rulings:
                if in_ruled_cell((x0, y0, x1, y1), rulings[pno]):
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
                    and same_font and not cross):
                x0 = min(cur.bbox[0], b.bbox[0])
                y0 = min(cur.bbox[1], b.bbox[1])
                x1 = max(cur.bbox[2], b.bbox[2])
                y1 = max(cur.bbox[3], b.bbox[3])
                sep = "" if cur.text.endswith("-") or b.text[:1] in ".,:;)%°" else " "
                cur = Block(page=pno, bbox=(x0, y0, x1, y1),
                            text=(cur.text + sep + b.text).strip(),
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
                     boxes: dict[int, list[tuple]] | None = None) -> list[Block]:
    """행 전체를 묶은 블록을 박스 경계에서 분할 (rawdict 문자 좌표 기준, 슬라이드용).

    조건: 블록 안에 세로 경계가 있고, 경계 높이가 블록 높이의 0.5~4배 (같은 행 박스).
    """
    import pymupdf as _pm
    if boxes is None:
        return blocks
    doc = _pm.open(pdf_path)
    out: list[Block] = []
    for b in blocks:
        try:
            page = doc[b.page]
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
            for x, ry0, ry1 in boxes.get(b.page, []):
                if not (b.bbox[0] + 5 < x < b.bbox[2] - 5):
                    continue
                rh = ry1 - ry0
                if rh < bh * 0.5 or rh > bh * 4:
                    continue
                if min(ry1, b.bbox[3]) - max(ry0, b.bbox[1]) < bh * 0.5:
                    continue
                cuts.add(x)
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
        lst = sorted(by_page[pno], key=lambda b: (b.bbox[1], b.bbox[0]))
        cur: Block | None = None
        for b in lst:
            if (cur is not None and len(b.text) < 60
                    and 0 <= b.bbox[1] - cur.bbox[3] <= 40
                    and abs(cur.fontsize - b.fontsize) <= 1.5
                    and not re.match(r"^(\d+(\.\d+)*|[A-Z](\.\d+)*|Appendix)\s+[A-Z0-9]", b.text)
                    and b.text.lower() not in KNOWN_HEADERS):
                xov = min(cur.bbox[2], b.bbox[2]) - max(cur.bbox[0], b.bbox[0])
                wmin = min(cur.bbox[2] - cur.bbox[0], b.bbox[2] - b.bbox[0])
                if wmin > 0 and xov >= wmin * 0.4:
                    cur = Block(
                        page=pno,
                        bbox=(min(cur.bbox[0], b.bbox[0]), min(cur.bbox[1], b.bbox[1]),
                              max(cur.bbox[2], b.bbox[2]), max(cur.bbox[3], b.bbox[3])),
                        text=(cur.text + " " + b.text).strip(),
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
