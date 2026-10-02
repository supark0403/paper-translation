"""번역 오케스트레이션: 프로바이더 호출 + 캐시 + 분할 재시도.

프로바이더 선택: configure() / CLI --provider / TRANSLATE_PROVIDER 환경변수.
기본값 local (llama.cpp, /no_think).
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from . import config
from .providers import BaseProvider, ChatRequest, build_provider

def build_system_prompt(src: str, tgt: str) -> str:
    base = (
        f"You are an academic {src}-to-{tgt} translator. "
        f"Translate body sentences to natural academic {tgt}. "
        "Rules: keep equation/table/figure/section numbers, math symbols, abbreviations, "
        "proper nouns, model names, numbers and units unchanged. "
        "Output ONLY the translation, no explanation."
    )
    if tgt == "Korean":
        base = (
            "You are an academic English-to-Korean translator. "
            "Translate body sentences to natural academic Korean (plain style, ~이다/~된다). "
            "Rules: keep Eq./Fig./Table/Section numbers, math symbols, abbreviations "
            "(MDPS, BLAC, FE, ROM, off-line, on-line), proper nouns, model names, numbers and units unchanged. "
            "Localize only the prefix words like Table->표, Figure/Fig.->그림, Section->절 (e.g. 'in Section 4' -> '4절에서는'). "
            "Eq. may stay as Eq. or 식, both allowed. Keep Boolean localization matrix (L), User-defined as-is. "
            "Never wrap math in $ or LaTeX commands (no \\text, \\(, \\), \\[); "
            "keep original notation exactly as-is (e.g. ΔW(s), W(base)). "
            "Output ONLY the Korean translation, no explanation."
        )
    else:
        base += (" Never wrap math in $ or LaTeX commands; "
                 "keep original notation exactly as-is.")
    return base


SYSTEM_PROMPT = build_system_prompt("English", "Korean")

_provider: BaseProvider | None = None
_src_lang = config.SRC_LANG
_tgt_lang = config.TGT_LANG


def configure(provider: str = "", model: str = "", base_url: str = "",
              api_key: str = "", src_lang: str = "", tgt_lang: str = "") -> BaseProvider:
    """프로바이더·언어 지정 (CLI/웹에서 호출). 빈 값은 config/환경변수 사용."""
    global _provider, _src_lang, _tgt_lang
    _provider = build_provider(provider or config.PROVIDER,
                               model=model, base_url=base_url, api_key=api_key)
    _src_lang = src_lang or config.SRC_LANG
    _tgt_lang = tgt_lang or config.TGT_LANG
    config.TGT_LANG = _tgt_lang  # 렌더러 폰트 선택용
    return _provider


def target_lang() -> str:
    return _tgt_lang


LATEX_SYMBOLS = {
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε",
    "zeta": "ζ", "eta": "η", "theta": "θ", "iota": "ι", "kappa": "κ",
    "lambda": "λ", "mu": "μ", "nu": "ν", "xi": "ξ", "pi": "π",
    "rho": "ρ", "sigma": "σ", "tau": "τ", "upsilon": "υ", "phi": "φ",
    "chi": "χ", "psi": "ψ", "omega": "ω",
    "Alpha": "Α", "Beta": "Β", "Gamma": "Γ", "Delta": "Δ", "Epsilon": "Ε",
    "Zeta": "Ζ", "Eta": "Η", "Theta": "Θ", "Iota": "Ι", "Kappa": "Κ",
    "Lambda": "Λ", "Mu": "Μ", "Nu": "Ν", "Xi": "Ξ", "Pi": "Π",
    "Rho": "Ρ", "Sigma": "Σ", "Tau": "Τ", "Upsilon": "Υ", "Phi": "Φ",
    "Chi": "Χ", "Psi": "Ψ", "Omega": "Ω",
    "times": "×", "cdot": "·", "leq": "≤", "geq": "≥", "neq": "≠",
    "infty": "∞", "rightarrow": "→", "leftarrow": "←", "approx": "≈",
    "sum": "∑", "prod": "∏", "int": "∫", "partial": "∂", "sqrt": "√",
}


def sanitize_math(t: str) -> str:
    """모델이 덧씌운 LaTeX 기호 제거 ($, \\text{}, \\Delta 등)."""
    import re as _re
    t = t.replace("$", "")
    t = _re.sub(r"\\(text|mathrm|mathit|mathbf|boldsymbol|operatorname|emph)\{([^{}]*)\}",
                r"\2", t)
    for tok in ("\\(", "\\)", "\\[", "\\]", "\\,", "\\;", "\\!"):
        t = t.replace(tok, "")

    def _cmd(m: "_re.Match") -> str:
        return LATEX_SYMBOLS.get(m.group(1), m.group(1))
    t = _re.sub(r"\\([a-zA-Z]+)", _cmd, t)
    # 수식 기호 뒤 공백 제거 (Δ W(s) → ΔW(s), 원문 표기 복원)
    t = _re.sub(r"([Δα-ωΑ-Ω×·≤≥≠∞→←≈∑∏∫∂√]) ([A-Za-z(])", r"\1\2", t)
    t = _re.sub(r"[ \t]{2,}", " ", t)
    return t.strip()


def last_tps() -> float:
    try:
        return float(getattr(active_provider(), "last_tps", 0.0) or 0.0)
    except Exception:
        return 0.0


def active_provider() -> BaseProvider:
    global _provider
    if _provider is None:
        _provider = build_provider(config.PROVIDER)
    return _provider


def _cache_path(text: str, tag: str) -> Path:
    h = hashlib.sha256(f"{tag}\x00{text}".encode("utf-8")).hexdigest()[:32]
    return config.CACHE_DIR / f"{h}.json"


def _provider_tag() -> str:
    p = active_provider()
    return f"{p.name}:{getattr(p, 'model', '')}:{_src_lang}>{_tgt_lang}"


def translate_once(text: str, max_tokens: int = config.MAX_TOKENS) -> str:
    p = active_provider()
    system = build_system_prompt(_src_lang, _tgt_lang)
    user = f"Translate to {_tgt_lang}. Output ONLY {_tgt_lang}.\n" + text
    last_err = ""
    for attempt in range(config.RETRY):
        try:
            content = p.complete(ChatRequest(system=system, user=user,
                                             max_tokens=max_tokens,
                                             temperature=config.TEMPERATURE),
                                 timeout=config.TIMEOUT_SEC)
            if content:
                return content
            last_err = "empty content"
        except Exception as e:  # noqa: BLE001
            last_err = str(e)
            if "API 키" in last_err or "HTTP 401" in last_err or "HTTP 403" in last_err:
                raise  # 키 문제는 재시도 무의미
        time.sleep(1.0 * (attempt + 1))
    raise RuntimeError(f"LLM empty response after retry: {last_err}")


def translate_text(text: str) -> str:
    """캐시(프로바이더+모델별) + 빈 응답 시 분할 재시도."""
    text = text.strip()
    if not text:
        return ""
    tag = _provider_tag()
    cp = _cache_path(text, tag)
    if cp.exists():
        try:
            ko = json.loads(cp.read_text(encoding="utf-8"))["ko"]
            return sanitize_math(ko)  # 구 캐시의 LaTeX 잔재도 정화
        except Exception:
            pass
    try:
        ko = sanitize_math(translate_once(text))
    except RuntimeError:
        # 반으로 나눠 재시도 (thinking 토큰 초과 등 대비)
        mid = len(text) // 2
        cut = text.rfind(". ", 0, mid)
        cut = cut + 2 if cut > 0 else mid
        ko = sanitize_math(translate_text(text[:cut]) + " " + translate_text(text[cut:]))
    cp.write_text(json.dumps({"en": text, "ko": ko}, ensure_ascii=False), encoding="utf-8")
    return ko
