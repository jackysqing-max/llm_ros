# SPDX-License-Identifier: Apache-2.0
"""Bridge ROS prompts and structured message requests to an HTTP LLM server."""

from __future__ import annotations

import json
import math
import queue
import threading
import uuid

import rclpy
from rcl_interfaces.msg import ParameterDescriptor
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from std_msgs.msg import String

from .http_client import LlmHttpClient, build_payload, extract_text


class LlmClientNode(Node):
    """Run one HTTP request at a time while keeping ROS callbacks responsive."""

    def __init__(self):
        super().__init__("llm_client_node")
        defaults = {
            "prompt_topic": "/llm/prompt", "request_topic": "/llm/request_json",
            "response_topic": "/llm/response", "response_json_topic": "/llm/response_json",
            "status_topic": "/llm/status", "api_protocol": "chat_completions",
            "api_base_url": "http://127.0.0.1:8000/v1/chat/completions",
            "model": "Qwen/Qwen3-4B", "api_key_env_var": "LLM_API_KEY",
            "api_key_required": False, "system_prompt": "You are a helpful assistant.",
            "temperature": 0.7, "top_p": 0.8, "max_output_tokens": 512,
            "reasoning_effort": "", "extra_request_body_json": "{}",
            "request_timeout_sec": 45.0, "max_pending_requests": 4,
            "max_request_bytes": 65536, "max_response_bytes": 8388608,
        }
        for name, default in defaults.items():
            self.declare_parameter(name, default, ParameterDescriptor(read_only=True))
            setattr(self, name, self.get_parameter(name).value)
        self.extra_body = json.loads(self.extra_request_body_json)
        if not isinstance(self.extra_body, dict):
            raise ValueError("extra_request_body_json must be a JSON object")
        if self.max_pending_requests < 1 or self.max_request_bytes < 1:
            raise ValueError("Queue and request byte limits must be positive")
        if self.max_output_tokens < 1 or not math.isfinite(self.temperature) or self.temperature < 0:
            raise ValueError("max_output_tokens must be positive and temperature nonnegative")
        if not math.isfinite(self.top_p) or not 0 < self.top_p <= 1:
            raise ValueError("top_p must be in (0, 1]")
        self.client = LlmHttpClient(
            self.api_base_url, timeout=self.request_timeout_sec,
            api_key_env_var=self.api_key_env_var, api_key_required=self.api_key_required,
            max_response_bytes=self.max_response_bytes,
        )
        self._payload([{"role": "user", "content": "Validate configuration"}])
        self.pub_text = self.create_publisher(String, self.response_topic, 10)
        self.pub_result = self.create_publisher(String, self.response_json_topic, 10)
        self.pub_status = self.create_publisher(String, self.status_topic, 10)
        self.sub_prompt = self.create_subscription(String, self.prompt_topic, self.on_prompt, 10)
        self.sub_request = self.create_subscription(String, self.request_topic, self.on_request, 10)
        self.requests = queue.Queue(maxsize=self.max_pending_requests)
        self._enqueue_lock = threading.Lock()
        self._stop = threading.Event()
        self.worker = threading.Thread(target=self._work, daemon=True)
        self.worker.start()
        self.get_logger().info(f"LLM client ready: protocol={self.api_protocol}, model={self.model}")

    def _payload(self, messages, schema=None):
        return build_payload(
            protocol=self.api_protocol, model=self.model, messages=messages,
            max_output_tokens=self.max_output_tokens, temperature=self.temperature,
            top_p=self.top_p, reasoning_effort=self.reasoning_effort,
            extra_body=self.extra_body, response_schema=schema,
        )

    def _status(self, request_id, state):
        if not self._stop.is_set():
            self.pub_status.publish(String(data=json.dumps({"request_id": request_id, "state": state})))

    def _error(self, request_id, error):
        if not self._stop.is_set():
            self.pub_result.publish(String(data=json.dumps({
                "request_id": request_id, "ok": False, "error": error,
            })))
            self._status(request_id, "error")

    def _enqueue(self, request):
        request_id = str(request.get("request_id") or uuid.uuid4().hex)
        try:
            schema = request.get("response_schema")
            if schema is not None and not isinstance(schema, dict):
                raise ValueError("response_schema must be a JSON object")
            if "messages" in request:
                if "prompt" in request:
                    raise ValueError("Use either prompt or messages, not both")
                messages = request["messages"]
            else:
                prompt = request.get("prompt")
                if not isinstance(prompt, str) or not prompt.strip():
                    raise ValueError("prompt must be a nonempty string")
                messages = []
                if self.system_prompt:
                    messages.append({"role": "system", "content": self.system_prompt})
                messages.append({"role": "user", "content": prompt.strip()})
            payload = self._payload(messages, schema)
            with self._enqueue_lock:
                self.requests.put_nowait((request_id, payload))
                self._status(request_id, "queued")
        except queue.Full:
            self._error(request_id, "Request queue is full")
        except (TypeError, ValueError) as exc:
            self._error(request_id, str(exc))

    def on_prompt(self, msg):
        """Accept plain text without interpreting JSON-looking user prompts."""
        if len(msg.data.encode("utf-8")) > self.max_request_bytes:
            self._error(uuid.uuid4().hex, "Prompt exceeded max_request_bytes")
            return
        self._enqueue({"prompt": msg.data})

    def on_request(self, msg):
        """Accept a JSON envelope carrying a request ID, messages, or prompt."""
        request_id = uuid.uuid4().hex
        try:
            if len(msg.data.encode("utf-8")) > self.max_request_bytes:
                raise ValueError("Request exceeded max_request_bytes")
            request = json.loads(msg.data)
            if not isinstance(request, dict):
                raise ValueError("Request must be a JSON object")
            request_id = str(request.get("request_id") or request_id)
            if set(request) - {"request_id", "prompt", "messages", "response_schema"}:
                raise ValueError("Unsupported request fields")
            self._enqueue(dict(request, request_id=request_id))
        except (TypeError, ValueError):
            self._error(request_id, "Invalid request JSON or unsupported fields")

    def _work(self):
        while not self._stop.is_set():
            try:
                request_id, payload = self.requests.get(timeout=0.2)
            except queue.Empty:
                continue
            with self._enqueue_lock:
                self._status(request_id, "running")
            try:
                raw = self.client.send(payload)
                text = extract_text(raw, self.api_protocol)
                if self._stop.is_set():
                    break
                result = {
                    "request_id": request_id, "ok": True, "text": text,
                    "model": raw.get("model", self.model), "usage": raw.get("usage", {}),
                }
                self.pub_text.publish(String(data=text))
                self.pub_result.publish(String(data=json.dumps(result, ensure_ascii=False)))
                self._status(request_id, "completed")
            except Exception as exc:
                self._error(request_id, str(exc))
            finally:
                self.requests.task_done()

    def destroy_node(self):
        self._stop.set()
        self.worker.join(timeout=2.0)
        return super().destroy_node()


def main(args=None):
    """Run the transport bridge."""
    rclpy.init(args=args)
    node = None
    try:
        node = LlmClientNode()
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
