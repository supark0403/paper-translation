"""전역 설정. 사용자 제공 연결 정보 반영."""
import os
from pathlib import Path

BASE_URL = "http://localhost:8080"
MODEL = "local-model"
CONTEXT_LIMIT = 90000
OUTPUT_LIMIT = 16384

# 프로바이더 선택: local | openai-compat | anthropic | gemini
# (환경변수로도 지정 가능, CLI --provider가 우선)
PROVIDER = os.environ.get("TRANSLATE_PROVIDER", "local")

# OpenAI 호환 (OpenAI/OpenRouter/Together/Groq/DeepSeek/xAI/vLLM)
OPENAI_COMPAT_BASE_URL = os.environ.get("TRANSLATE_BASE_URL", "")
OPENAI_COMPAT_MODEL = os.environ.get("TRANSLATE_MODEL", "")
OPENAI_COMPAT_API_KEY = os.environ.get("TRANSLATE_API_KEY", "")

# Anthropic Claude / Google Gemini (모델 기본값만; 키는 필수)
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

# 번역 호출 기본값 (Qwen3 thinking 대응: /no_think 필수)
USE_NO_THINK_PREFIX = True
TEMPERATURE = 0.1
MAX_TOKENS = 2000
TIMEOUT_SEC = 180
RETRY = 3

# 청킹
CHUNK_CHARS = 1100
CHUNK_OVERLAP_SENT = 1

# 분류 임계값
SLIDE_MIN_ASPECT = 1.2  # w/h
SLIDE_MAX_AVG_BLOCKS = 18
SLIDE_MIN_AVG_FONTSIZE = 14.0

# 한글 폰트 (Windows 기본). 존재하는 첫 번째 사용.
FONT_CANDIDATES = [
    r"C:\Windows\Fonts\malgun.ttf",
    r"C:\Windows\Fonts\NotoSansKR-VF.ttf",
    r"C:\Windows\Fonts\batang.ttc",
]
FONT_BOLD_CANDIDATES = [
    r"C:\Windows\Fonts\malgunbd.ttf",
]

# 번역 언어 (기본 영→한). CLI --src-lang/--tgt-lang 또는 환경변수.
SRC_LANG = os.environ.get("SRC_LANG", "English")
TGT_LANG = os.environ.get("TGT_LANG", "Korean")

SUPPORTED_LANGS = ["English", "Korean", "Japanese", "Chinese (Simplified)",
                   "Chinese (Traditional)", "Spanish", "French", "German",
                   "Vietnamese", "Indonesian"]

LANG_SUFFIX = {"English": "en", "Korean": "ko", "Japanese": "ja",
               "Chinese (Simplified)": "zh-CN", "Chinese (Traditional)": "zh-TW",
               "Spanish": "es", "French": "fr", "German": "de",
               "Vietnamese": "vi", "Indonesian": "id"}

# 타깃 언어별 폰트 [(path, subfontIndex)] — 존재하는 첫 번째 사용
FONT_MAP = {
    "Korean": [
        (r"C:\Windows\Fonts\batang.ttc", 0),
        (r"C:\Windows\Fonts\NotoSerifKR-VF.ttf", 0),
        (r"C:\Windows\Fonts\malgun.ttf", 0),
    ],
    "Japanese": [
        (r"C:\Windows\Fonts\msgothic.ttc", 0),
        (r"C:\Windows\Fonts\NotoSansKR-VF.ttf", 0),
    ],
    "Chinese (Simplified)": [
        (r"C:\Windows\Fonts\msyh.ttc", 1),
        (r"C:\Windows\Fonts\simsun.ttc", 0),
    ],
    "Chinese (Traditional)": [
        (r"C:\Windows\Fonts\mingliub.ttc", 0),
        (r"C:\Windows\Fonts\msyh.ttc", 0),
    ],
}
LATIN_FONT = [
    (r"C:\Windows\Fonts\arial.ttf", 0),
    (r"C:\Windows\Fonts\calibri.ttf", 0),
]
BOLD_MAP = {
    "Korean": [(r"C:\Windows\Fonts\batang.ttc", 0)],
    "Chinese (Simplified)": [(r"C:\Windows\Fonts\msyhbd.ttc", 0)],
}


def fonts_for_lang(lang: str) -> list[tuple[str, int]]:
    if lang in FONT_MAP:
        return FONT_MAP[lang]
    # CJK 외: 수식·한자 혼재 대비 라틴 뒤에 CJK 폴백
    return LATIN_FONT + FONT_MAP["Chinese (Simplified)"]


def bold_for_lang(lang: str) -> list[tuple[str, int]]:
    return BOLD_MAP.get(lang, fonts_for_lang(lang))

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = PROJECT_ROOT / ".cache"
OUTPUT_DIR = PROJECT_ROOT / "outputs"
for d in (CACHE_DIR, OUTPUT_DIR):
    d.mkdir(parents=True, exist_ok=True)
