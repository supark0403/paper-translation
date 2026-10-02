"""문서별 서체 분석 → 번역 폰트 자동 매칭.

단일 레퍼런스에 하드코딩하지 않고, 들어온 PDF마다 본문 서체(serif/sans,
크기, 자간)를 측정해 가장 이질감 없는 한글(CJK) 폰트를 선택한다.
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import median

import pymupdf  # type: ignore

SERIF_HINTS = (
    "times", "nimbusrom", "cmr", "modern", "garamond", "palatino", "georgia",
    "minion", "stix", "charter", "baskerville", "didot", "schoolbook",
    "roman", "serif", "batang", "gungsuh", "mincho", "ming", "simsun",
    "song", "msjh", "jhenghei", "kai", "myeongjo",
)
SANS_HINTS = (
    "helvet", "nimbussan", "arial", "verdana", "tahoma", "calibri", "gulim",
    "dotum", "malgun", "gothic", "sans", "freesans", "lato", "inter",
)


def classify_font(fontname: str) -> str:
    """'serif' | 'sans' | 'unknown'"""
    f = fontname.lower().replace(" ", "")
    for h in SANS_HINTS:
        if h in f:
            # 'sans'가 'nimbusrom...' 같은 serif 이름에 들어가는 경우 방지:
            # 정확히 sans 계열 키워드면 sans 확정 (ms gothic 등)
            return "sans"
    for h in SERIF_HINTS:
        if h in f:
            return "serif"
    return "unknown"


@dataclass
class DocStyle:
    serif: bool = True
    body_size: float = 10.0
    leading: float = 1.32
    serif_conf: float = 0.0  # serif 판정 근거 문자 비율


def analyze_document(pdf_path: str, pages: list[int] | None = None,
                     sample_pages: int = 5) -> DocStyle:
    doc = pymupdf.open(pdf_path)
    total = len(doc)
    if pages is None:
        step = max(1, total // sample_pages)
        pages = list(range(0, total, step))[:sample_pages]
    serif_chars = sans_chars = 0
    sizes: list[float] = []
    pitches: list[float] = []
    for pno in pages:
        if pno >= total:
            continue
        for b in doc[pno].get_text("dict")["blocks"]:
            if b["type"] != 0:
                continue
            txt = "".join(s["text"] for l in b["lines"] for s in l["spans"])
            if len(txt.strip()) < 100:  # 본문 단락만 집계
                continue
            for l in b["lines"]:
                for s in l["spans"]:
                    n = len(s["text"])
                    c = classify_font(s["font"])
                    if c == "serif":
                        serif_chars += n
                    elif c == "sans":
                        sans_chars += n
                    sizes.extend([s["size"]] * min(n, 20))
            lines = b["lines"]
            if len(lines) >= 3:
                fs = sum(s["size"] * len(s["text"]) for l in lines for s in l["spans"])
                fs /= max(1, sum(len(s["text"]) for l in lines for s in l["spans"]))
                tops = sorted(l["bbox"][1] for l in lines)
                for a, cc in zip(tops, tops[1:]):
                    r = (cc - a) / fs if fs > 0 else 0
                    # 정상 행간만 집계 (수식·첨자 줄의 이상치 제외)
                    if 1.0 <= r <= 1.8:
                        pitches.append(r)
    doc.close()
    voted = serif_chars + sans_chars
    serif_conf = (serif_chars / voted) if voted else 0.0
    serif = serif_chars >= sans_chars  # 동점·정보없음 → 학술 기본 serif
    body = float(median(sizes)) if sizes else 10.0
    lead = float(median(pitches)) if pitches else 1.32
    lead = max(1.12, min(1.7, lead))
    return DocStyle(serif=serif, body_size=round(body, 1),
                    leading=round(lead, 2), serif_conf=round(serif_conf, 2))


def block_alignment(line_rights: list[float], box_x1: float) -> str:
    """줄 끝 x좌표들로 양쪽정렬 여부 판정."""
    if len(line_rights) < 3:
        return "left"
    body = line_rights[:-1]
    full = sum(1 for x in body if box_x1 - x <= 6.0)
    return "justify" if full / max(1, len(body)) >= 0.6 else "left"
