#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Interactive CLI for sending natural-language robot tasks."""

from __future__ import annotations

import argparse
import threading
import time
import sys

import rclpy
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from std_msgs.msg import String


class LlmTaskCli(Node):
    """Publish free-form task text and print planner/executor status updates."""

    def __init__(
        self,
        instruction_topic: str,
        status_topic: str,
        echo_status: bool,
        wait_prefixes: list[str] | None = None,
        fail_prefixes: list[str] | None = None,
    ):
        super().__init__("llm_task_cli")
        self.echo_status = echo_status
        self.wait_prefixes = [prefix for prefix in (wait_prefixes or []) if prefix]
        self.fail_prefixes = [prefix for prefix in (fail_prefixes or []) if prefix]
        self.status_event = threading.Event()
        self.matched_status = ""
        self.failed_status = False
        self.pub_instruction = self.create_publisher(String, instruction_topic, 10)
        self.sub_status = self.create_subscription(
            String,
            status_topic,
            self.on_status,
            10,
        )

    def on_status(self, msg: String):
        if self.echo_status:
            print(f"[status] {msg.data}", flush=True)
        if self.fail_prefixes and any(msg.data.startswith(prefix) for prefix in self.fail_prefixes):
            self.matched_status = msg.data
            self.failed_status = True
            self.status_event.set()
            return
        if self.wait_prefixes and any(msg.data.startswith(prefix) for prefix in self.wait_prefixes):
            self.matched_status = msg.data
            self.failed_status = False
            self.status_event.set()

    def wait_for_instruction_subscriber(self, timeout_sec: float) -> bool:
        deadline = time.time() + max(timeout_sec, 0.0)
        while time.time() < deadline:
            if self.pub_instruction.get_subscription_count() > 0:
                return True
            time.sleep(0.05)
        return self.pub_instruction.get_subscription_count() > 0

    def send_instruction(self, text: str, repeat_sec: float = 0.0):
        msg = String()
        msg.data = text
        deadline = time.time() + max(repeat_sec, 0.0)
        self.pub_instruction.publish(msg)
        print(f"[sent] {text}", flush=True)
        while time.time() < deadline:
            time.sleep(0.1)
            self.pub_instruction.publish(msg)

    def wait_for_status(self, timeout_sec: float) -> tuple[bool, str]:
        if not (self.wait_prefixes or self.fail_prefixes):
            return True, ""
        if self.status_event.wait(timeout=max(timeout_sec, 0.0)):
            return (not self.failed_status), self.matched_status
        return False, ""


def build_parser():
    parser = argparse.ArgumentParser(description="Send natural-language tabletop tasks")
    parser.add_argument(
        "--instruction-topic",
        default="/llm_task/instruction",
        help="Topic that accepts natural-language instructions",
    )
    parser.add_argument(
        "--status-topic",
        default="/llm_task/status",
        help="Topic used by the planner/executor to report progress",
    )
    parser.add_argument(
        "--once",
        default="",
        help="Send one instruction and exit",
    )
    parser.add_argument(
        "--listen-only",
        action="store_true",
        help="Do not publish an instruction; only print and optionally wait on status updates.",
    )
    parser.add_argument(
        "--no-status",
        action="store_true",
        help="Do not print planner/executor status updates",
    )
    parser.add_argument(
        "--wait-status-prefix",
        action="append",
        default=[],
        help="Wait until a status message starts with this prefix. Can be used multiple times.",
    )
    parser.add_argument(
        "--fail-status-prefix",
        action="append",
        default=[],
        help="Treat a matching status prefix as failure. Can be used multiple times.",
    )
    parser.add_argument(
        "--timeout-sec",
        type=float,
        default=120.0,
        help="Maximum time to wait for a matching status when --wait-status-prefix is used.",
    )
    parser.add_argument(
        "--publish-warmup-sec",
        type=float,
        default=2.0,
        help="Maximum time to wait for an instruction subscriber before --once publishes.",
    )
    parser.add_argument(
        "--publish-repeat-sec",
        type=float,
        default=1.0,
        help="Duration for repeating the --once instruction publish to avoid ROS discovery loss.",
    )
    return parser


def run_interactive(node: LlmTaskCli):
    print("LLM task shell is ready.", flush=True)
    print("Type a natural-language instruction and press Enter.", flush=True)
    print("Commands: :quit, :exit, :help", flush=True)

    while True:
        try:
            line = input("task> ").strip()
        except EOFError:
            print("", flush=True)
            break
        except KeyboardInterrupt:
            print("", flush=True)
            break

        if not line:
            continue
        if line in {":quit", ":exit"}:
            break
        if line == ":help":
            print("Example: Hover above the red cube, then the blue cube, then the yellow cube.", flush=True)
            continue
        node.send_instruction(line)


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.listen_only and args.once:
        parser.error("--listen-only cannot be combined with --once")

    rclpy.init()
    node = LlmTaskCli(
        instruction_topic=args.instruction_topic,
        status_topic=args.status_topic,
        echo_status=not args.no_status,
        wait_prefixes=args.wait_status_prefix,
        fail_prefixes=args.fail_status_prefix,
    )
    executor = SingleThreadedExecutor()
    executor.add_node(node)

    spin_thread = threading.Thread(target=executor.spin, daemon=True)
    spin_thread.start()

    # Give ROS discovery a brief moment so the first publish is not dropped.
    time.sleep(0.2)

    try:
        if args.listen_only:
            print(f"[watching] {args.status_topic}", flush=True)
            if args.wait_status_prefix or args.fail_status_prefix:
                ok, matched_status = node.wait_for_status(args.timeout_sec)
                if not ok and not matched_status:
                    print(
                        f"[error] timed out after {args.timeout_sec:.1f}s waiting for status",
                        file=sys.stderr,
                        flush=True,
                    )
                    raise SystemExit(1)
                if matched_status and node.failed_status:
                    print(f"[error] {matched_status}", file=sys.stderr, flush=True)
                    raise SystemExit(2)
            else:
                while rclpy.ok():
                    time.sleep(0.2)
        elif args.once:
            subscriber_ready = node.wait_for_instruction_subscriber(args.publish_warmup_sec)
            repeat_sec = 0.0
            if not subscriber_ready:
                print(
                    "[warn] no instruction subscriber discovered before publishing",
                    file=sys.stderr,
                    flush=True,
                )
                repeat_sec = args.publish_repeat_sec
            node.send_instruction(args.once, repeat_sec=repeat_sec)
            if args.wait_status_prefix or args.fail_status_prefix:
                ok, matched_status = node.wait_for_status(args.timeout_sec)
                if not ok and not matched_status:
                    print(
                        f"[error] timed out after {args.timeout_sec:.1f}s waiting for status",
                        file=sys.stderr,
                        flush=True,
                    )
                    raise SystemExit(1)
                if matched_status and node.failed_status:
                    print(f"[error] {matched_status}", file=sys.stderr, flush=True)
                    raise SystemExit(2)
            else:
                time.sleep(0.5)
        else:
            run_interactive(node)
    finally:
        executor.shutdown()
        node.destroy_node()
        rclpy.shutdown()
        spin_thread.join(timeout=1.0)


if __name__ == "__main__":
    main()
