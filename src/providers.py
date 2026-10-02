"""번역 LLM 프로바이더.

- local: llama.cpp 서버 (OpenAI 호환, Qwen3 thinking 대응 /no_think)
- openai-compat: OpenAI / OpenRouter / Together / Groq / DeepSeek / vLLM 등
  (`/chat/completions` 규격이면 전부 사용 가능)
- anthropic: Claude Messages API (`/v1/messages`)
- gemini: Google AI `models:generateContent`

공통: 모두 표준라이브러리(urllib)만 사용, SDK 의존성 없음.
API 키는 환경변수 또는 CLI/웹 입력으로만 전달 (파일에 저장하지 않음).
"""
from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass


class ProviderError(RuntimeError):
    pass


def _post_json(url: str, payload: dict, headers: dict, timeout: int) -> tuple[int, dict | str]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", "ignore")
            try:
                return e.code, json.loads(body)
            except ValueError:
                return e.code, body
        except Exception:
            return e.code, ""
    except Exception as e:  # 연결 실패 등
        raise ProviderError(f"연결 실패 ({url}): {e}") from e


def _api_error(provider: str, status: int, body) -> ProviderError:
    msg = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)[:500]
    hint = ""
    if status in (401, 403):
        hint = " — API 키를 확인하세요."
    elif status == 429:
        hint = " — 요청 한도 초과/요금제 확인."
    elif status == 404:
        hint = " — 모델명 또는 baseURL을 확인하세요."
    return ProviderError(f"[{provider}] HTTP {status}: {msg}{hint}")


@dataclass
class ChatRequest:
    system: str
    user: str
    max_tokens: int
    temperature: float


class BaseProvider:
    name = "base"
    last_tps: float = 0.0

    def complete(self, req: ChatRequest, timeout: int) -> str:
        raise NotImplementedError


class LocalProvider(BaseProvider):
    """llama.cpp 로컬 서버. Qwen3 thinking 대응으로 /no_think 접두."""

    name = "local"

    def __init__(self, base_url: str, model: str, no_think: bool = True):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.no_think = no_think

    def complete(self, req: ChatRequest, timeout: int) -> str:
        user = ("/no_think " if self.no_think else "") + req.user
        system = ("/no_think " if self.no_think else "") + req.system
        status, body = _post_json(
            f"{self.base_url}/v1/chat/completions",
            {"model": self.model,
             "messages": [{"role": "system", "content": system},
                          {"role": "user", "content": user}],
             "max_tokens": req.max_tokens, "temperature": req.temperature},
            {"Content-Type": "application/json"}, timeout)
        if status != 200 or not isinstance(body, dict):
            raise _api_error(self.name, status, body)
        try:
            return (body["choices"][0]["message"].get("content") or "").strip()
        except (KeyError, IndexError, AttributeError) as e:
            raise ProviderError(f"[{self.name}] 응답 파싱 실패: {str(body)[:300]}") from e


class OpenAICompatProvider(BaseProvider):
    """OpenAI 규격. OpenAI/OpenRouter/Together/Groq/DeepSeek/xAI/vLLM 공용."""

    name = "openai-compat"

    def __init__(self, base_url: str, model: str, api_key: str = ""):
        if not base_url:
            raise ProviderError("[openai-compat] baseURL이 필요합니다. "
                                "(예: https://api.openai.com/v1, https://openrouter.ai/api/v1)")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key

    def complete(self, req: ChatRequest, timeout: int) -> str:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        status, body = _post_json(
            f"{self.base_url}/chat/completions",
            {"model": self.model,
             "messages": [{"role": "system", "content": req.system},
                          {"role": "user", "content": req.user}],
             "max_tokens": req.max_tokens, "temperature": req.temperature},
            headers, timeout)
        if status != 200 or not isinstance(body, dict):
            raise _api_error(self.name, status, body)
        try:
            return (body["choices"][0]["message"].get("content") or "").strip()
        except (KeyError, IndexError, AttributeError) as e:
            raise ProviderError(f"[{self.name}] 응답 파싱 실패: {str(body)[:300]}") from e


class AnthropicProvider(BaseProvider):
    """Claude Messages API. system은 별도 필드."""

    name = "anthropic"
    API_URL = "https://api.anthropic.com/v1/messages"
    VERSION = "2023-06-01"

    def __init__(self, model: str, api_key: str, api_url: str = ""):
        if not api_key:
            raise ProviderError("[anthropic] API 키가 필요합니다. (ANTHROPIC_API_KEY)")
        self.model = model
        self.api_key = api_key
        self.api_url = api_url or self.API_URL

    def complete(self, req: ChatRequest, timeout: int) -> str:
        status, body = _post_json(
            self.api_url,
            {"model": self.model, "max_tokens": req.max_tokens,
             "system": req.system,
             "messages": [{"role": "user", "content": req.user}]},
            {"Content-Type": "application/json", "x-api-key": self.api_key,
             "anthropic-version": self.VERSION}, timeout)
        if status != 200 or not isinstance(body, dict):
            raise _api_error(self.name, status, body)
        try:
            texts = [b.get("text", "") for b in body.get("content", [])
                     if isinstance(b, dict) and b.get("type") == "text"]
            return "".join(texts).strip()
        except AttributeError as e:
            raise ProviderError(f"[{self.name}] 응답 파싱 실패: {str(body)[:300]}") from e


class GeminiProvider(BaseProvider):
    """Google AI generateContent. 키는 x-goog-api-key 헤더."""

    name = "gemini"

    def __init__(self, model: str, api_key: str, api_url: str = ""):
        if not api_key:
            raise ProviderError("[gemini] API 키가 필요합니다. (GEMINI_API_KEY)")
        self.model = model
        self.api_key = api_key
        self.api_url = api_url  # 테스트용 오버라이드 (비우면 기본 URL)

    def complete(self, req: ChatRequest, timeout: int) -> str:
        url = self.api_url or (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent")
        status, body = _post_json(
            url,
            {"system_instruction": {"parts": {"text": req.system}},
             "contents": {"parts": {"text": req.user}},
             "generationConfig": {"temperature": req.temperature,
                                  "maxOutputTokens": req.max_tokens}},
            {"Content-Type": "application/json",
             "x-goog-api-key": self.api_key}, timeout)
        if status != 200 or not isinstance(body, dict):
            raise _api_error(self.name, status, body)
        try:
            parts = body["candidates"][0]["content"]["parts"]
            return "".join(p.get("text", "") for p in parts
                           if isinstance(p, dict)).strip()
        except (KeyError, IndexError, TypeError) as e:
            raise ProviderError(f"[{self.name}] 응답 파싱 실패: {str(body)[:300]}") from e


def build_provider(name: str, model: str = "", base_url: str = "",
                   api_key: str = "", no_think: bool = True) -> BaseProvider:
    from . import config
    name = (name or "local").lower()
    if name == "local":
        return LocalProvider(base_url or config.BASE_URL,
                             model or config.MODEL, no_think=no_think)
    if name in ("openai-compat", "openai", "openrouter", "together",
                "groq", "deepseek", "xai", "vllm", "compat"):
        return OpenAICompatProvider(
            base_url or config.OPENAI_COMPAT_BASE_URL, model or config.OPENAI_COMPAT_MODEL,
            api_key or config.OPENAI_COMPAT_API_KEY)
    if name == "anthropic":
        return AnthropicProvider(model or config.ANTHROPIC_MODEL,
                                 api_key or config.ANTHROPIC_API_KEY)
    if name == "gemini":
        return GeminiProvider(model or config.GEMINI_MODEL,
                              api_key or config.GEMINI_API_KEY)
    raise ProviderError(f"알 수 없는 프로바이더: {name} "
                        "(local|openai-compat|anthropic|gemini)")
