"""프로바이더 스텁 테스트 (실제 API 키 불필요).

각 상용 규격을 흉내내는 로컬 HTTP 스텁을 띄워 요청 형식·응답 파싱·에러 처리를 검증.
실행: python -m pytest tests/  (또는)  python tests/test_providers.py
"""
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.providers import (AnthropicProvider, ChatRequest, GeminiProvider,
                           LocalProvider, OpenAICompatProvider, ProviderError,
                           build_provider)

REQ = ChatRequest(system="sys", user="Hello.", max_tokens=50, temperature=0.0)
seen: dict = {}


def stub(handler_cls):
    srv = HTTPServer(("127.0.0.1", 0), handler_cls)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_port}"


class OpenAIStub(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        seen["openai"] = {"path": self.path, "auth": self.headers.get("Authorization"),
                          "model": body.get("model"),
                          "n_msg": len(body.get("messages", []))}
        if self.path.startswith("/bad"):
            self.send_response(401)
            self.end_headers()
            self.wfile.write(b'{"error":{"message":"invalid key"}}')
            return
        resp = {"choices": [{"message": {"content": "안녕."}}]}
        out = json.dumps(resp).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


class AnthropicStub(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        seen["anthropic"] = {"version": self.headers.get("anthropic-version"),
                             "has_key": bool(self.headers.get("x-api-key")),
                             "model": body.get("model"),
                             "has_system": "system" in body}
        resp = {"content": [{"type": "text", "text": "안녕."}],
                "stop_reason": "end_turn"}
        out = json.dumps(resp).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


class GeminiStub(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        seen["gemini"] = {"has_key": self.headers.get("x-goog-api-key") == "GK",
                          "has_sys": "system_instruction" in body}
        resp = {"candidates": [{"content": {"parts": [{"text": "안녕."}]}}]}
        out = json.dumps(resp).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


def test_openai_compat():
    _, url = stub(OpenAIStub)
    p = OpenAICompatProvider(url, "gpt-4o", "sk-test")
    assert p.complete(REQ, 10) == "안녕."
    assert seen["openai"]["auth"] == "Bearer sk-test"
    assert seen["openai"]["model"] == "gpt-4o"
    assert seen["openai"]["path"] == "/chat/completions"
    # 401 에러 메시지
    bad = OpenAICompatProvider(url + "/bad", "gpt-4o", "wrong")
    try:
        bad.complete(REQ, 10)
        raise AssertionError("401이어야 함")
    except ProviderError as e:
        assert "401" in str(e) and "API 키" in str(e)
    print("openai-compat OK")


def test_anthropic():
    _, url = stub(AnthropicStub)
    p = AnthropicProvider("claude-sonnet-4-6", "ak-test", api_url=url)
    assert p.complete(REQ, 10) == "안녕."
    assert seen["anthropic"]["version"] == "2023-06-01"
    assert seen["anthropic"]["has_key"] and seen["anthropic"]["has_system"]
    try:
        AnthropicProvider("m", "")
        raise AssertionError("키 없이 생성되면 안 됨")
    except ProviderError:
        pass
    print("anthropic OK")


def test_gemini():
    _, url = stub(GeminiStub)
    p = GeminiProvider("gemini-2.0-flash", "GK", api_url=url)
    assert p.complete(REQ, 10) == "안녕."
    assert seen["gemini"]["has_key"] and seen["gemini"]["has_sys"]
    print("gemini OK")


def test_local_no_think():
    _, url = stub(OpenAIStub)
    p = LocalProvider(url, "local-model")
    assert p.complete(REQ, 10) == "안녕."
    print("local OK")


def test_aliases():
    assert build_provider("openrouter", base_url="https://x").name == "openai-compat"
    assert build_provider("groq", base_url="https://x").name == "openai-compat"
    assert build_provider("LOCAL").name == "local"
    try:
        build_provider("nope")
        raise AssertionError("unknown이어야 함")
    except ProviderError:
        pass
    print("aliases OK")


if __name__ == "__main__":
    test_openai_compat()
    test_anthropic()
    test_gemini()
    test_local_no_think()
    test_aliases()
    print("ALL PROVIDER TESTS PASSED")
