"""CLI 배치 변환기.

예:
  python -m src.main --input test/4..pdf --pages 0-5
  python -m src.main --input test/1.ROME-locating-and-editing-factual-associations-in-gpt-Paper-Conference.pdf --pages 0-1 --type paper
  python -m src.main --input test/2.MEMIT.pdf --pages 0 --mock   # LLM 없이 레이아웃만
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config  # noqa: E402
from src.classifier import classify  # noqa: E402
from src.extractor import chunk_paragraph, iter_blocks, merge_line_fragments, merge_slide_vertical, should_translate  # noqa: E402


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
    blocks = merge_line_fragments(iter_blocks(args.input, pages))
    if kind == "slide":
        blocks = merge_slide_vertical(blocks)
    cands = [b for b in blocks if should_translate(b.text, b.fontsize, kind, b.page)]
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
        from src.translator import translate_text
        total_chars = sum(len(b.text) for b in cands)
        done = 0
        translations_list: list[dict] = []
        for i, b in enumerate(cands):
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
            })
            done += len(b.text)
            print(f"[{i+1}/{len(cands)}] p{b.page} en={len(b.text)} ko={len(ko)} "
                  f"({done}/{total_chars}) :: {b.text[:70]!r} -> {ko[:70]!r}")
        translations = translations_list  # type: ignore[assignment]

    # 렌더: bbox 키 소수점 이슈 — renderer가 같은 좌표계를 쓰므로 그대로 전달
    # (iter_blocks bbox를 round한 값과 동일해야 함에 주의)
    from src.renderer import render_ko_pdf
    from src.translator import target_lang
    inp = Path(args.input)
    suffix = config.LANG_SUFFIX.get(target_lang(), "ko")
    out = args.output or str(config.OUTPUT_DIR / f"{inp.stem}_{suffix}.pdf")
    render_ko_pdf(args.input, translations, out,
                  font_size_scale=1.0 if kind == "paper" else 0.9)
    print(f"[done] -> {out}")


if __name__ == "__main__":
    main()
