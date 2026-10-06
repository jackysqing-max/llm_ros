# SPDX-License-Identifier: Apache-2.0
"""Verify real local HTTP transport, protocol formats, and error handling."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from llm_ros.http_client import (
    LlmHttpClient, LlmTransportError, build_payload, extract_json_object, extract_text,
)
from llm_ros.mock_server import MockHandler


@pytest.fixture
def endpoint():
    server = ThreadingHTTPServer(("127.0.0.1", 0), MockHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


@pytest.mark.parametrize("protocol,path", [
    ("chat_completions", "/v1/chat/completions"), ("responses", "/v1/responses"),
])
def test_real_http_protocol_round_trip(endpoint, protocol, path):
    payload = build_payload(protocol=protocol, model="mock", messages=[{"role": "user", "content": "hello"}])
    result = LlmHttpClient(endpoint + path).send(payload)
    assert extract_text(result, protocol) == "MOCK: hello"


def test_responses_payload_and_schema():
    schema = {"type": "object", "properties": {"name": {"type": "string"}}}
    payload = build_payload(
        protocol="responses", model="model", messages=[{"role": "user", "content": "test"}],
        max_output_tokens=128, reasoning_effort="low", response_schema=schema,
        extra_body={"store": False},
    )
    assert payload["input"][0]["content"] == "test"
    assert payload["max_output_tokens"] == 128
    assert payload["text"]["format"]["schema"] == schema
    assert payload["reasoning"] == {"effort": "low"}
    assert payload["store"] is False
    assert "temperature" not in payload and "messages" not in payload


@pytest.mark.parametrize("extra", [{"stream": True}, {"model": "override"}, {"input": []}, {"messages": []}])
def test_protected_extra_fields(extra):
    with pytest.raises(ValueError):
        build_payload(protocol="chat_completions", model="model",
                      messages=[{"role": "user", "content": "test"}], extra_body=extra)


@pytest.mark.parametrize("messages", [[], "text", [{}], [{"role": "unknown", "content": "text"}]])
def test_invalid_message_request(messages):
    with pytest.raises(ValueError):
        build_payload(protocol="chat_completions", model="model", messages=messages)


@pytest.mark.parametrize("text", [
    '{"name":"cup"}', '```json\n{"name":"cup"}\n```',
    '<think>reasoning {not JSON}</think>\n{"name":"cup"}',
    'Answer: {"name":"cup", "nested":{"brace":"}"}} done',
])
def test_model_json_extraction(text):
    assert extract_json_object(text)["name"] == "cup"


def test_missing_json_raises():
    with pytest.raises(ValueError):
        extract_json_object("No result")


def test_responses_combines_text_and_ignores_reasoning():
    result = {"output": [
        {"type": "reasoning", "content": [{"text": "hidden"}]},
        {"type": "message", "content": [{"text": "hello"}, {"text": " world"}]},
    ]}
    assert extract_text(result, "responses") == "hello world"


def test_chat_text_blocks():
    result = {"choices": [{"message": {"content": [{"text": "hello"}, {"text": " world"}]}}]}
    assert extract_text(result, "chat_completions") == "hello world"


@pytest.mark.parametrize("result,protocol", [
    ({"status": "incomplete", "output_text": "partial"}, "responses"),
    ({"choices": [{"finish_reason": "length", "message": {"content": "partial"}}]}, "chat_completions"),
    ({"choices": [{"message": {"refusal": "refused"}}]}, "chat_completions"),
])
def test_incomplete_or_missing_text_is_not_success(result, protocol):
    with pytest.raises(ValueError):
        extract_text(result, protocol)


def test_key_required_without_network(endpoint, monkeypatch):
    monkeypatch.delenv("TEST_LLM_KEY", raising=False)
    with pytest.raises(LlmTransportError, match="Missing API key"):
        LlmHttpClient(endpoint, api_key_env_var="TEST_LLM_KEY", api_key_required=True).send({})


def test_response_size_limit(endpoint):
    with pytest.raises(LlmTransportError, match="max_response_bytes"):
        LlmHttpClient(endpoint + "/v1/chat/completions", max_response_bytes=5).send({"model": "mock"})


@pytest.mark.parametrize("endpoint", ["file:///tmp/test", "https://user:password@example.com/v1"])
def test_invalid_endpoint(endpoint):
    with pytest.raises(ValueError):
        LlmHttpClient(endpoint)


def test_http_error_body_is_not_exposed_and_redirect_is_not_followed(monkeypatch):
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            seen.append((self.path, self.headers.get("Authorization")))
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            self.send_response(307 if self.path == "/redirect" else 401)
            if self.path == "/redirect":
                self.send_header("Location", "/target")
            self.end_headers()
            self.wfile.write(b"secret-provider-body")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("TEST_LLM_KEY", "test-key")
    try:
        for path in ("/error", "/redirect"):
            with pytest.raises(LlmTransportError) as error:
                LlmHttpClient(f"http://127.0.0.1:{server.server_port}{path}", api_key_env_var="TEST_LLM_KEY").send({})
            assert "secret-provider-body" not in str(error.value)
            assert "test-key" not in str(error.value)
        assert seen == [("/error", "Bearer test-key"), ("/redirect", "Bearer test-key")]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
