# SPDX-License-Identifier: Apache-2.0
"""Talk to an LLM through ROS topics, either once or in an interactive terminal."""

import argparse
import json
import math
import sys
import time
import uuid

import rclpy
from rcl_interfaces.msg import ParameterDescriptor
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.utilities import remove_ros_args
from std_msgs.msg import String


DEFAULT_SYSTEM_PROMPT = "You are a helpful assistant. Respond in English."


class LlmChatDemo(Node):
    """An application node; llm_client_node owns HTTP transport and credentials."""

    def __init__(self, *, system_prompt=DEFAULT_SYSTEM_PROMPT, history_turns=4):
        super().__init__("llm_chat_demo")
        topics = {
            "request_topic": "/llm/request_json",
            "response_json_topic": "/llm/response_json",
            "status_topic": "/llm/status",
        }
        for name, default in topics.items():
            self.declare_parameter(name, default, ParameterDescriptor(read_only=True))
            topics[name] = self.get_parameter(name).value
        self.publisher = self.create_publisher(String, topics["request_topic"], 10)
        self.result_subscription = self.create_subscription(
            String, topics["response_json_topic"], self.on_result, 10,
        )
        self.status_subscription = self.create_subscription(
            String, topics["status_topic"], self.on_status, 10,
        )
        self.system_prompt = system_prompt
        self.history_turns = history_turns
        self.history = []
        self.request_id = None
        self.result = None

    def on_result(self, message):
        """Only consume the reply for this node's currently pending request."""
        try:
            result = json.loads(message.data)
        except ValueError:
            return
        if isinstance(result, dict) and result.get("request_id") == self.request_id:
            if self.request_id is not None:
                self.result = result

    def on_status(self, message):
        try:
            status = json.loads(message.data)
        except ValueError:
            return
        if isinstance(status, dict) and status.get("request_id") == self.request_id:
            if self.request_id is not None:
                print(f"[STATUS] {status.get('state', 'unknown')}", flush=True)

    def wait_until(self, predicate, timeout, description):
        deadline = time.monotonic() + timeout
        while rclpy.ok():
            if predicate():
                return
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"Timed out waiting for {description}")
            rclpy.spin_once(self, timeout_sec=min(0.1, remaining))
        raise ExternalShutdownException()

    def chat(self, prompt, *, timeout=120.0, discovery_timeout=10.0):
        """Publish one correlated request, then spin until its reply or timeout."""
        self.wait_until(
            lambda: self.publisher.get_subscription_count() > 0
            and self.count_publishers(self.result_subscription.topic_name) > 0,
            discovery_timeout, "the ROS LLM bridge (request subscriber and response publisher)",
        )
        messages = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        messages.extend(self.history)
        messages.append({"role": "user", "content": prompt})
        self.request_id = uuid.uuid4().hex
        self.result = None
        try:
            print(f"[USER] {prompt}\n[REQUEST] {self.request_id}", flush=True)
            self.publisher.publish(String(data=json.dumps({
                "request_id": self.request_id, "messages": messages,
            }, ensure_ascii=False)))
            self.wait_until(lambda: self.result is not None, timeout, "the correlated LLM reply")
            if self.result.get("ok") is not True:
                raise RuntimeError(str(self.result.get("error", "Invalid response envelope")))
            text = self.result.get("text")
            if not isinstance(text, str) or not text.strip():
                raise RuntimeError("The LLM bridge returned no assistant text")
            print(f"[LLM] {text}", flush=True)
            if self.history_turns:
                self.history.extend([
                    {"role": "user", "content": prompt}, {"role": "assistant", "content": text},
                ])
                self.history = self.history[-2 * self.history_turns:]
            return text
        finally:
            # Late responses from a timed-out request must not satisfy the next turn.
            self.request_id = None


def positive_seconds(value):
    seconds = float(value)
    if not math.isfinite(seconds) or seconds <= 0:
        raise argparse.ArgumentTypeError("Timeout must be positive and finite")
    return seconds


def main(args=None):
    argv = sys.argv if args is None else ["llm_chat_demo", *args]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", metavar="PROMPT", help="Send one prompt and exit")
    parser.add_argument("--timeout", type=positive_seconds, default=120.0,
                        help="Reply timeout in seconds, including time in the bridge queue")
    parser.add_argument("--discovery-timeout", type=positive_seconds, default=10.0,
                        help="Time allowed for ROS topic discovery before publishing")
    parser.add_argument("--system-prompt", default=DEFAULT_SYSTEM_PROMPT,
                        help="System instruction; requests English replies by default")
    parser.add_argument("--history-turns", type=int, default=4,
                        help="Successful conversation turns to retain; 0 disables history")
    options = parser.parse_args(remove_ros_args(argv)[1:])
    if options.history_turns < 0:
        parser.error("--history-turns must be nonnegative")
    if options.once is not None and not options.once.strip():
        parser.error("--once requires a nonempty prompt")
    rclpy.init(args=argv)
    node = None
    try:
        node = LlmChatDemo(system_prompt=options.system_prompt, history_turns=options.history_turns)

        def send(prompt):
            node.chat(prompt, timeout=options.timeout, discovery_timeout=options.discovery_timeout)

        if options.once is not None:
            send(options.once.strip())
        else:
            print("ROS 2 LLM chat. Type a prompt, :reset to clear history, or :quit to exit.", flush=True)
            while rclpy.ok():
                try:
                    prompt = input("you> ").strip()
                except EOFError:
                    break
                if prompt in {":quit", ":exit"}:
                    break
                if prompt == ":reset":
                    node.history.clear()
                    print("Conversation history cleared.", flush=True)
                elif prompt:
                    try:
                        send(prompt)
                    except (RuntimeError, TimeoutError) as exc:
                        print(f"[ERROR] {exc}", file=sys.stderr, flush=True)
        return 0
    except (RuntimeError, TimeoutError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr, flush=True)
        return 1
    except (KeyboardInterrupt, ExternalShutdownException):
        return 130
    finally:
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
