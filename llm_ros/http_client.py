# SPDX-License-Identifier: Apache-2.0
"""Dependency-free HTTP transport and response parsing for LLM endpoints.

Response parsing is adapted from vla_simu_workspace's LLM planner (2026).
"""

from __future__ import annotations

import json
import math
import os
import re
import urllib.error
import urllib.parse
import urllib.request


class LlmTransportError(RuntimeError):
    """An HTTP failure with a message that excludes credentials and server bodies."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class LlmHttpClient:
    """POST bounded JSON responses using Chat Completions or Responses APIs."""

    def __init__(self, endpoint, *, timeout=45.0, api_key_env_var="",
                 api_key_required=False, api_key="", max_response_bytes=8 * 1024 * 1024):
        url = urllib.parse.urlsplit(endpoint)
        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password:
            raise ValueError("endpoint must be an HTTP(S) URL without embedded credentials")
        if not math.isfinite(timeout) or timeout <= 0 or max_response_bytes < 1:
            raise ValueError("timeout and max_response_bytes must be positive")
        self.endpoint = endpoint
        self.timeout = timeout
        self.api_key_env_var = api_key_env_var
        self.api_key_required = api_key_required
        self.api_key = api_key
        self.max_response_bytes = max_response_bytes
        self.opener = urllib.request.build_opener(_NoRedirect())

    def send(self, payload: dict) -> dict:
        """Send once, with no retry, redirect, streaming, or server-body logging."""
        if payload.get("stream"):
            raise ValueError("Streaming is not supported")
        key = self.api_key or os.environ.get(self.api_key_env_var, "")
        if self.api_key_required and not key.strip():
            raise LlmTransportError(f"Missing API key in environment variable {self.api_key_env_var}")
        headers = {"Content-Type": "application/json"}
        if key.strip():
            headers["Authorization"] = f"Bearer {key.strip()}"
        request = urllib.request.Request(
            self.endpoint, data=json.dumps(payload, allow_nan=False).encode("utf-8"),
            headers=headers, method="POST",
        )
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                data = response.read(self.max_response_bytes + 1)
        except urllib.error.HTTPError as exc:
            raise LlmTransportError(f"LLM endpoint returned HTTP {exc.code}") from None
        except (TimeoutError, urllib.error.URLError, OSError):
            raise LlmTransportError("LLM endpoint connection failed or timed out") from None
        if len(data) > self.max_response_bytes:
            raise LlmTransportError("LLM response exceeded max_response_bytes")
        try:
            result = json.loads(data)
        except (ValueError, UnicodeDecodeError):
            raise LlmTransportError("LLM endpoint returned invalid JSON") from None
        if not isinstance(result, dict):
            raise LlmTransportError("LLM endpoint response must be a JSON object")
        if result.get("error"):
            raise LlmTransportError("LLM endpoint returned an error object")
        return result


def extract_response_text(response_json):
    """Join text blocks from completed Responses API assistant messages."""
    if response_json.get("status") in {"failed", "incomplete", "cancelled"}:
        raise ValueError("Responses API result is not complete")
    output_text = response_json.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text
    parts = []
    for item in response_json.get("output", []):
        if not isinstance(item, dict) or item.get("type", "message") != "message":
            continue
        for content in item.get("content", []):
            if not isinstance(content, dict):
                continue
            text = content.get("text")
            if isinstance(text, str) and text.strip():
                parts.append(text)
    if parts:
        return "".join(parts)
    raise ValueError("No assistant text found in Responses API result")


def extract_chat_completion_text(response_json):
    """Extract the first assistant choice, accepting string or text blocks."""
    for choice in response_json.get("choices", []):
        if choice.get("finish_reason") in {"length", "content_filter"}:
            raise ValueError("Chat completion is truncated or filtered")
        content = choice.get("message", {}).get("content")
        if isinstance(content, str) and content.strip():
            return content
        if isinstance(content, list):
            parts = [item["text"] for item in content
                     if isinstance(item, dict) and isinstance(item.get("text"), str)]
            text = "".join(parts).strip()
            if text:
                return text
    raise ValueError("No assistant text found in chat completion result")


def extract_text(response_json, protocol):
    """Select the parser for the configured endpoint protocol."""
    if protocol == "responses":
        return extract_response_text(response_json)
    if protocol == "chat_completions":
        return extract_chat_completion_text(response_json)
    raise ValueError("api_protocol must be chat_completions or responses")


def extract_json_object(text: str) -> dict:
    """Extract a JSON object from plain, fenced, or Qwen thinking-prefixed text."""
    cleaned = re.sub(r"<think>.*?</think>", "", text or "", flags=re.DOTALL).strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z0-9_-]*\s*\n?", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    decoder = json.JSONDecoder()
    try:
        result = json.loads(cleaned)
        if isinstance(result, dict):
            return result
    except ValueError:
        pass
    for match in re.finditer(r"\{", cleaned):
        try:
            result, _ = decoder.raw_decode(cleaned[match.start():])
            if isinstance(result, dict):
                return result
        except ValueError:
            continue
    raise ValueError("No valid JSON object found in model text")


def build_payload(*, protocol, model, messages, max_output_tokens=512,
                  temperature=0.7, top_p=0.8, reasoning_effort="",
                  extra_body=None, response_schema=None):
    """Create a provider payload without a Python model or vendor SDK dependency."""
    if not model.strip() or not isinstance(messages, list) or not messages:
        raise ValueError("model and messages must not be empty")
    for message in messages:
        if not isinstance(message, dict) or message.get("role") not in {
            "system", "developer", "user", "assistant",
        } or not isinstance(message.get("content"), (str, list)):
            raise ValueError("Each message requires a supported role and string/list content")
    extra = dict(extra_body or {})
    if extra.get("stream") or any(key in extra for key in ("model", "messages", "input")):
        raise ValueError("extra body cannot override model, messages, input, or enable streaming")
    payload = dict(extra, model=model, stream=False)
    if protocol == "chat_completions":
        payload.update(messages=messages, temperature=temperature, top_p=top_p)
        if max_output_tokens > 0:
            payload["max_tokens"] = max_output_tokens
        if response_schema is not None:
            payload["response_format"] = {
                "type": "json_schema", "json_schema": {
                    "name": "llm_result", "schema": response_schema,
                },
            }
    elif protocol == "responses":
        payload["input"] = messages
        if max_output_tokens > 0:
            payload["max_output_tokens"] = max_output_tokens
        if reasoning_effort:
            payload["reasoning"] = {"effort": reasoning_effort}
        if response_schema is not None:
            payload["text"] = {"format": {
                "type": "json_schema", "name": "llm_result", "schema": response_schema,
                "strict": False,
            }}
    else:
        raise ValueError("api_protocol must be chat_completions or responses")
    return payload
