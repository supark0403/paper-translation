# -*- coding: utf-8 -*-
"""페이지별 전부 검증: 한글 커버리지, LaTeX 잔재, 수식번호 보존, 박스 이탈, 미번역 장문."""
import sys, re
import pymupdf

LATEX_PAT = re.compile(r"\$|\\(text|mathrm|Delta|alpha|beta|gamma|sigma|lambda|pi|mu)\b|\\\ {0,1}\(|\\\[")
EQ_PAT = re.compile(r"\(\d+[a-c]?\)")

def check(orig_path, ko_path, name):
    orig = pymupdf.open(orig_path)
    ko = pymupdf.open(ko_path)
    print(f"=== {name}: orig={len(orig)}p ko={len(ko)}p ===")
    assert len(orig) == len(ko), "페이지 수 불일치!"
    ko_chars = sum(len(ch) for ch in [ko[i].get_text() for i in range(len(ko))])
    print(f"  total ko chars={ko_chars}")
    bad = 0
    for i in range(len(ko)):
        ot, kt = orig[i].get_text(), ko[i].get_text()
        # 1) LaTeX 잔재
        m = LATEX_PAT.search(kt)
        if m:
            print(f"  [p{i}] LATEX잔재: {m.group(0)!r} :: {kt[max(0,m.start()-30):m.start()+40]!r}")
            bad += 1
        # 2) 수식번호 보존 (원문에 있으면 번역본에도)
        for e in set(EQ_PAT.findall(ot)):
            if len(e) > 3 and e not in kt:
                print(f"  [p{i}] 수식번호 소실: {e}")
                bad += 1
        # 3) 한글 존재 (원문이 영문 장문인데 번역본에 한글 전무)
        en_words = re.findall(r"[A-Za-z]{4,}", ot)
        ko_chars_p = re.findall(r"[가-힣]", kt)
        if len(en_words) > 40 and len(ko_chars_p) < 5:
            print(f"  [p{i}] 한글 없음 의심 (en단어 {len(en_words)})")
            bad += 1
        # 4) 박스 이탈: 텍스트가 페이지 밖으로 삐졌는지
        for b in ko[i].get_text("dict")["blocks"]:
            if b["type"] != 0:
                continue
            x0, y0, x1, y1 = b["bbox"]
            R = ko[i].rect
            if x0 < -5 or y0 < -5 or x1 > R.width + 5 or y1 > R.height + 5:
                print(f"  [p{i}] 박스이탈: {b['bbox']}")
                bad += 1
                break
    print(f"  --> issues={bad}")
    return bad

if __name__ == "__main__":
    total = 0
    for a, b, n in [("test/4..pdf", "outputs/4._3_ko.pdf", "slide")]:
        try:
            total += check(a, b, n)
        except Exception as e:
            print("ERR", n, e)
    print("TOTAL ISSUES:", total)
