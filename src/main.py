"""CLI 배치 변환기.

예:
  python -m src.main --input test/4..pdf --pages 0-5
  python -m src.main --input test/1.ROME-locating-and-editing-factual-associations-in-gpt-Paper-Conference.pdf --pages 0-1 --type paper
  python -m src.main --input test/2.MEMIT.pdf --pages 0 --mock   # LLM 없이 레이아웃만
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config  # noqa: E402
from src.classifier import classify  # noqa: E402
from src.extractor import (chunk_paragraph, collect_fragments, iter_blocks, merge_dangling,  # noqa: E402
                         merge_line_fragments, merge_slide_vertical, should_translate,
                         table_skip_rects)


def drop_references(cands, blocks=None, pdf_path=None) -> list:
    """References 범위만 제외 (헤더 자체는 번역, 이후 부록이 나오면 재개).
    부록 시작은 PDF 원시 텍스트 기준으로 찾음 (그룹핑 무관)."""
    from src.extractor import REF_HEADERS as _RH
    from src.extractor import appendix_start as _ast
    cut = next((i for i, b in enumerate(cands) if b.text.strip().lower() in _RH), None)
    if cut is None:
        return cands
    resume = None
    pos = _ast(pdf_path if pdf_path else blocks)
    if pos is not None:
        pg, yy = pos
        resume = next((i for i in range(cut + 1, len(cands))
                       if (cands[i].page, cands[i].bbox[1]) >= (pg, yy - 1.0)), None)
    if resume is None:
        return cands[:cut + 1]
    return cands[:cut + 1] + cands[resume:]


def parse_pages(s: str | None, total: int) -> list[int] | None:
    if not s:
        return None
    out: set[int] = set()
    for part in s.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            out.update(range(int(a), int(b) + 1))
        else:
            out.add(int(part))
    return sorted(p for p in out if 0 <= p < total)


def main() -> None:
    ap = argparse.ArgumentParser(description="논문/PPT 한글화 (로컬 LLM)")
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", default=None)
    ap.add_argument("--type", default="auto", choices=["auto", "paper", "slide"])
    ap.add_argument("--pages", default=None, help="예: 0-1, 0,2,4")
    ap.add_argument("--mock", action="store_true", help="LLM 호출 없이 [MOCK] 박스만 덮어 레이아웃 검증")
    ap.add_argument("--limit-chars", type=int, default=0, help="번역할 총 영문 글자 상한 (테스트용). 0=무제한")
    ap.add_argument("--provider", default="", help="local|openai-compat|anthropic|gemini (기본: 환경변수 TRANSLATE_PROVIDER 또는 local)")
    ap.add_argument("--model", default="", help="모델명 (예: gpt-4o, claude-sonnet-4-6, gemini-2.0-flash)")
    ap.add_argument("--base-url", default="", help="OpenAI 호환 baseURL (예: https://api.openai.com/v1)")
    ap.add_argument("--api-key", default="", help="API 키 (미지정 시 환경변수 TRANSLATE_API_KEY 등 사용)")
    ap.add_argument("--src-lang", default="", help="원문 언어 (기본 English)")
    ap.add_argument("--tgt-lang", default="", help="번역 언어 (기본 Korean)")
    args = ap.parse_args()

    from src.translator import configure as configure_provider
    try:
        p = configure_provider(args.provider, model=args.model,
                               base_url=args.base_url, api_key=args.api_key,
                               src_lang=args.src_lang, tgt_lang=args.tgt_lang)
        print(f"[provider] {p.name} model={getattr(p, 'model', '')}")
    except Exception as e:
        print(f"[provider] 설정 오류: {e}")
        raise SystemExit(2)

    info = classify(args.input)
    kind = args.type if args.type != "auto" else info["kind"]
    print(f"[classify] kind={kind} pages={info['pages']} aspect={info['aspect']} "
          f"avg_blocks={info['avg_blocks']} avg_fs={info['avg_fontsize']}")

    pages = parse_pages(args.pages, info["pages"])
    from src.extractor import ruling_lines, slide_rulings, table_regions, table_skip_rects
    # 표/박스 제외는 논문만 (슬라이드는 박스째 번역)
    skip = table_skip_rects(args.input, pages) if kind == "paper" else None
    rules = ruling_lines(args.input, pages)
    regs = table_regions(args.input, pages) if kind == "paper" else None
    vrul = slide_rulings(args.input, pages)
    from src.extractor import equation_bands as _eb
    ebands = _eb(args.input, pages) if kind == "paper" else None
    blocks = merge_line_fragments(iter_blocks(args.input, pages, skip, rules,
                                              ruled_skip=(kind == "paper"),
                                              table_regs=regs, eq_bands=ebands),
                                  rulings=vrul)
    if kind == "slide":
        from src.extractor import slide_ruling_boxes, split_row_blocks
        blocks = merge_slide_vertical(blocks, rulings=vrul)
        blocks = split_row_blocks(args.input, blocks, slide_ruling_boxes(args.input, pages))
    else:
        from src.extractor import merge_dangling as _md
        blocks = _md(blocks)
        from src.extractor import refilter, split_row_blocks
        blocks = split_row_blocks(args.input, blocks, col_gap=12.0, regs=regs)
        blocks = refilter(blocks, skip, rules, regs)
        blocks = _md(blocks)
    from src.extractor import drop_contained
    blocks = drop_contained(blocks)
    cands = [b for b in blocks if should_translate(b.text, b.fontsize, kind, b.page)]
    cands.sort(key=lambda b: (b.page, b.bbox[1]))
    if kind == "paper":
        before = len(cands)
        cands = drop_references(cands, pdf_path=args.input)
        if len(cands) < before:
            print(f"[refs] {before - len(cands)} blocks skipped after References")
        # 문장 꼬리 조각 수집 (문맥 번역)
        import pymupdf as _pmh
        _dh = _pmh.open(args.input)
        _ph = {p: _dh[p].rect.height for p in range(len(_dh))}
        _dh.close()
        frags = collect_fragments(blocks, cands, _ph)
        if frags:
            print(f"[frag] {len(frags)} continuation fragments")
            cands += frags
    from src.extractor import dedupe_cands, drop_contained
    cands = dedupe_cands(drop_contained(cands))
    from src.fontmatch import analyze_document
    style = analyze_document(args.input)  # 부분 번역이어도 전체 문서 기준
    print(f"[style] {'serif' if style.serif else 'sans'} body={style.body_size}pt "
          f"leading={style.leading} (conf={style.serif_conf})")
    print(f"[extract] total_blocks={len(blocks)} translatable={len(cands)} "
          f"pages={pages if pages else 'all'}")

    if args.limit_chars:
        acc = 0
        cut = []
        for b in cands:
            cut.append(b)
            acc += len(b.text)
            if acc >= args.limit_chars:
                break
        cands = cut
        print(f"[limit] chars<= {args.limit_chars}: {len(cands)} blocks")

    translations: dict = {}
    if args.mock:
        for b in cands:
            key = (b.page, tuple(round(v, 1) for v in b.bbox))
            translations[key] = "[MOCK] " + b.text[:120]
    else:
        from src.translator import translate_fragment, translate_text
        from src.extractor import continuation_prev, reading_order
        import pymupdf as _pm
        _doc = _pm.open(args.input)
        _heights = {p: _doc[p].rect.height for p in range(len(_doc))}
        _doc.close()
        ordered = reading_order(cands)
        _prev_of = {}
        for i, b in enumerate(ordered):
            _prev_of[id(b)] = ordered[i - 1] if i > 0 else None
        total_chars = sum(len(b.text) for b in cands)
        done = 0
        translations_list: list[dict] = []
        for i, b in enumerate(cands):
            prev = continuation_prev(b, _prev_of.get(id(b)), _heights.get(b.page, 792.0))
            if prev is not None:
                # 단 넘김 꼬리: 문맥을 주고 꼬리만 번역
                ko = translate_fragment(b.text, prev.text)
            else:
                # 긴 블록은 문장 청크로 나눠 번역 후 합침
                parts = chunk_paragraph(b.text, max_chars=config.CHUNK_CHARS)
                ko_parts = []
                for p in parts:
                    ko_parts.append(translate_text(p))
                ko = " ".join(ko_parts)
            translations_list.append({
                "page": b.page,
                "bbox": tuple(round(v, 1) for v in b.bbox),
                "text": ko, "fontsize": b.fontsize, "bold": b.is_bold,
                "line_rights": list(b.line_rights),
            })
            done += len(b.text)
            print(f"[{i+1}/{len(cands)}] p{b.page} en={len(b.text)} ko={len(ko)} "
                  f"({done}/{total_chars}) :: {b.text[:70]!r} -> {ko[:70]!r}")
        translations = translations_list  # type: ignore[assignment]
    if kind == "paper" and isinstance(translations, list):
        # redact 분리: 수식 밴드·참고문헌 zonas 원문 보존 (렌더 박스는 유지)
        from src.extractor import equation_bands, refs_zone, subtract_bands
        _eb = equation_bands(args.input, pages)
        _rz = refs_zone(args.input)
        _bands: dict[int, list] = {}
        for _p, _bl in list(_eb.items()) + list(_rz.items()):
            _bands.setdefault(_p, []).extend(_bl)
        for _it in translations:
            _pb = _bands.get(int(_it["page"]), [])
            _it["redact"] = [tuple(round(v, 1) for v in r)
                             for r in subtract_bands(_it["bbox"], _pb)] if _pb else None

    # 렌더: bbox 키 소수점 이슈 — renderer가 같은 좌표계를 쓰므로 그대로 전달
    # (iter_blocks bbox를 round한 값과 동일해야 함에 주의)
    from src.renderer import render_ko_pdf
    from src.translator import target_lang
    inp = Path(args.input)
    suffix = config.LANG_SUFFIX.get(target_lang(), "ko")
    out = args.output or str(config.OUTPUT_DIR / f"{inp.stem}_{suffix}.pdf")
    render_ko_pdf(args.input, translations, out,
                  font_size_scale=1.0 if kind == "paper" else 0.9, style=style)
    print(f"[done] -> {out}")


if __name__ == "__main__":
    main()
