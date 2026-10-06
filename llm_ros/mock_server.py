# SPDX-License-Identifier: Apache-2.0
"""A deterministic local endpoint for transport tests; this is not an LLM."""

import argparse
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def mock_reply(payload):
    """Return predictable chat or task-plan text without a model download."""
    messages = payload.get("messages", payload.get("input", []))
    instruction = messages[-1].get("content", "") if messages else ""
    schema = payload.get("response_format", {}).get("json_schema", {}).get("schema")
    schema = schema or payload.get("text", {}).get("format", {}).get("schema", {})
    properties = schema.get("properties", {})
    if "steps" in properties:
        return json.dumps({
            "task_summary": str(instruction), "planning_notes": "Deterministic mock response",
            "steps": [{
                "step_index": 1, "action": "hover_target", "target_prompt": "red cube",
                "description": "Inspect the red cube", "success_radius_m": 0.0,
                "dwell_sec": 1.0, "wait_sec": 0.0,
            }],
        })
    if "terminal_operation" in properties:
        from .task_plan_utils import sanitize_rcm_task_request
        return json.dumps(sanitize_rcm_task_request({
            "instruction": str(instruction), "terminal_operation": "localize_only",
        }))
    return f"MOCK: {instruction}"


class MockHandler(BaseHTTPRequestHandler):
    """Serve both provider envelopes for local acceptance tests."""

    def log_message(self, format, *args):
        pass

    def do_GET(self):
        self._send(200, {"data": [{"id": "mock-llm"}]})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length > 1024 * 1024:
            self._send(413, {"error": "Mock request limit"})
            return
        try:
            payload = json.loads(self.rfile.read(length))
            text = mock_reply(payload)
            if self.path.endswith("/responses"):
                result = {
                    "model": payload["model"], "status": "completed",
                    "output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}],
                    "usage": {"input_tokens": 1, "output_tokens": 1},
                }
            else:
                result = {
                    "model": payload["model"], "choices": [{
                        "finish_reason": "stop", "message": {"role": "assistant", "content": text},
                    }], "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                }
            time.sleep(getattr(self.server, "response_delay", 0.0))
            self._send(200, result)
        except (ValueError, KeyError, TypeError):
            self._send(400, {"error": "Invalid mock payload"})

    def _send(self, code, payload):
        data = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), MockHandler)
    print(f"Mock endpoint listening on {args.host}:{args.port}; responses are deterministic.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
