# -*- coding: utf-8 -*-
"""출력 PDF 자동 검수: 겹침/이탈/영문잔류/LaTeX/수식번호."""
import sys, re
import pymupdf

LATEX_PAT = re.compile(r"\$|\\(text|mathrm|Delta|alpha|beta|gamma|sigma|lambda|pi|mu)\b|\\\ {0,1}\(|\\\[")
EQ_PAT = re.compile(r"\(\d+[a-c]?\)")

def check(orig_path, ko_path, ref_pages=frozenset()):
    orig = pymupdf.open(orig_path)
    ko = pymupdf.open(ko_path)
    assert len(orig) == len(ko), "페이지 수 불일치"
    # 참고문헌 시작 페이지 자동 제외 (원문 기준, 헤더 이후 원문 유지가 정책)
    for i in range(len(orig)):
        t = orig[i].get_text().strip().split("\n")
        if any(x.strip().lower() in ("references", "bibliography") for x in t[:10]):
            ref_pages = ref_pages | frozenset(range(i, len(ko)))
            break
    issues = []
    for i in range(len(ko)):
        if i in ref_pages:
            continue
        R = ko[i].rect
        koblocks = []
        for b in ko[i].get_text("dict")["blocks"]:
            if b["type"] != 0:
                continue
            t = "".join(s["text"] for l in b["lines"] for s in l["spans"])
            koblocks.append((b["bbox"], t))
        # a) 겹침
        for a in range(len(koblocks)):
            for c in range(a + 1, len(koblocks)):
                (x0, y0, x1, y1), ta = koblocks[a]
                (u0, v0, u1, v1), tc = koblocks[c]
                if not (any("가" <= ch <= "힣" for ch in ta) and any("가" <= ch <= "힣" for ch in tc)):
                    continue
                iw = min(x1, u1) - max(x0, u0)
                ih = min(y1, v1) - max(y0, v0)
                if iw > 20 and ih > 6:
                    area = iw * ih
                    small = min((x1 - x0) * (y1 - y0), (u1 - u0) * (v1 - v0))
                    if small > 0 and area / small > 0.15:
                        issues.append((i, "OVERLAP", f"{ta[:25]!r} X {tc[:25]!r}"))
                        break
        ot = orig[i].get_text()
        kt = ko[i].get_text()
        # b) 이탈
        for (x0, y0, x1, y1), t in koblocks:
            if x0 < -5 or y0 < -5 or x1 > R.width + 5 or y1 > R.height + 5:
                issues.append((i, "OUT-OF-PAGE", t[:30]))
                break
        # c) LaTeX 잔재
        m = LATEX_PAT.search(kt)
        if m:
            issues.append((i, "LATEX", m.group(0)))
        # d) 수식번호 소실 (4자리 연도 인용은 제외)
        for e in set(EQ_PAT.findall(ot)):
            if len(e) > 3 and e not in kt and not re.fullmatch(r"\((19|20)\d{2}[a-c]?\)", e):
                issues.append((i, "EQ-LOST", e))
                break
        # e) 긴 영문 잔류 (번역 누락 의심)
        for (x0, y0, x1, y1), t in koblocks:
            en = re.findall(r"[A-Za-z]{4,}", t)
            kok = re.findall(r"[가-힣]", t)
            if len(en) > 25 and len(kok) < 5 and len(t) > 150:
                issues.append((i, "EN-LEFTOVER", t[:60]))
                break
    return issues

if __name__ == "__main__":
    import sys as _s
    a = _s.argv[1]
    b = _s.argv[2]
    n = _s.argv[3] if len(_s.argv) > 3 else "doc"
    print(f"=== {n} ===")
    for i, kind, detail in check(a, b):
        print(f"  p{i} {kind}: {detail}")
