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


@dataclass
class Block:
    page: int
    bbox: tuple[float, float, float, float]
    text: str
    fontsize: float
    is_bold: bool


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
    if re.search(r"(University|Institute|Laboratory|LAB|MIT|Technion|Northeastern)", t) and len(t) < 80:
        # 저자명 단독 블록도 함께 스킵 (대문자 1-3단어)
        if len(t) < 60:
            return False
    # 섹션 헤더·타이틀은 짧아도 번역 (레퍼런스: 5. Experimental result → 5. 실험 결과)
    if re.match(r"^\d+(\.\d+)*\s+[A-Z]", t) and len(t) < 120:
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


def iter_blocks(pdf_path: str, pages: list[int] | None = None) -> list[Block]:
    doc = pymupdf.open(pdf_path)
    out: list[Block] = []
    wanted = set(pages) if pages is not None else None
    for pno in range(len(doc)):
        if wanted is not None and pno not in wanted:
            continue
        page = doc[pno]
        H = page.rect.height
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
            text = ""
            for l in b["lines"]:
                line = "".join(s["text"] for s in l["spans"])
                text += line + "\n"
            text = dehyphenate(text).strip()
            if not text:
                continue
            fs = sum(s["size"] * len(s["text"]) for s in spans) / max(1, sum(len(s["text"]) for s in spans))
            bold = any("bold" in s["font"].lower() or "black" in s["font"].lower() for s in spans)
            out.append(Block(page=pno, bbox=(x0, y0, x1, y1), text=text, fontsize=float(fs), is_bold=bold))
    doc.close()
    # 읽기 순서: 페이지 내 y → x (2단은 근사: x 중심이 절반 기준)
    return out


def dehyphenate(text: str) -> str:
    # 학술 PDF의 줄끝 하이픈(trans- / former) 복원
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    text = text.replace("\n", " ")
    text = re.sub(r"\s{2,}", " ", text)
    return text


def merge_line_fragments(blocks: list[Block]) -> list[Block]:
    """같은 줄에서 잘게 쪼개진 블록 병합 (PyMuPDF dict의 과분할 보정).

    조건: 같은 페이지 + 세로 중심 차이 < min(높이)/2 + 폰트 유사 → x 순으로 병합.
    2단 칼럼 오병합 방지를 위해 x-gap < 40pt 조건 추가.
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
            if abs(cy1 - cy0) <= max(3.0, hmin * 0.6) and -8 <= xgap <= 40 and same_font:
                x0 = min(cur.bbox[0], b.bbox[0])
                y0 = min(cur.bbox[1], b.bbox[1])
                x1 = max(cur.bbox[2], b.bbox[2])
                y1 = max(cur.bbox[3], b.bbox[3])
                sep = "" if cur.text.endswith("-") or b.text[:1] in ".,:;)%°" else " "
                cur = Block(page=pno, bbox=(x0, y0, x1, y1),
                            text=(cur.text + sep + b.text).strip(),
                            fontsize=(cur.fontsize + b.fontsize) / 2,
                            is_bold=cur.is_bold and b.is_bold)
            else:
                out.append(cur)
                cur = b
        if cur is not None:
            out.append(cur)
    return out


def merge_slide_vertical(blocks: list[Block], max_gap: float = 30.0) -> list[Block]:
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
                         is_bold=all(b.is_bold for b in members)))
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
