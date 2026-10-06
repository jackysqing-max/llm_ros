#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Exercise installed ROS nodes against a mock or a separately running real LLM."""

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import threading
import time
from http.server import ThreadingHTTPServer

import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile
from std_msgs.msg import String

from llm_ros.mock_server import MockHandler


class Probe(Node):
    def __init__(self, mode):
        super().__init__("llm_smoke_probe")
        self.messages = []
        self.statuses = []
        input_topic = "/llm_smoke/prompt" if mode == "client" else "/llm_smoke/instruction"
        output_topic = "/llm_smoke/result" if mode == "client" else "/llm_smoke/plan"
        self.pub = self.create_publisher(String, input_topic, 10)
        self.pub_json = self.create_publisher(String, "/llm_smoke/request", 10)
        self.pub_scene = self.create_publisher(String, "/llm_smoke/scene", 10)
        qos = 10 if mode == "client" else QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.sub = self.create_subscription(String, output_topic, self.receive, qos)
        self.sub_status = self.create_subscription(String, "/llm_smoke/status", self.statuses.append, 10)

    def receive(self, msg):
        self.messages.append(json.loads(msg.data))

    def wait(self, predicate, deadline, process):
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"Installed launch exited with code {process.returncode}")
            rclpy.spin_once(self, timeout_sec=0.1)
            failures = [msg.data for msg in self.statuses if msg.data.startswith("planning_failed:")]
            if failures:
                raise RuntimeError(failures[-1])
            if predicate():
                return
        raise TimeoutError("Timed out waiting for ROS LLM result")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["client", "planner", "rcm"], default="client")
    parser.add_argument("--protocol", choices=["chat_completions", "responses"], default="chat_completions")
    parser.add_argument("--endpoint", help="A real endpoint; omitted starts a deterministic mock")
    parser.add_argument("--model", default="mock-llm")
    parser.add_argument("--domain-id", type=int, default=96)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--api-key-env", default="LLM_API_KEY")
    parser.add_argument("--require-key", action="store_true")
    args = parser.parse_args()
    os.environ["ROS_DOMAIN_ID"] = str(args.domain_id)
    os.environ["ROS_LOCALHOST_ONLY"] = "1"
    server, server_thread = None, None
    endpoint = args.endpoint
    if not endpoint:
        server = ThreadingHTTPServer(("127.0.0.1", 0), MockHandler)
        server.response_delay = 0.1
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        path = "responses" if args.protocol == "responses" else "chat/completions"
        endpoint = f"http://127.0.0.1:{server.server_port}/v1/{path}"
    launch_mode = "client" if args.mode == "client" else "planner"
    parameters = {
        "api_base_url": endpoint, "api_protocol": args.protocol, "model": args.model,
        "api_key_env_var": args.api_key_env, "api_key_required": args.require_key,
        "reasoning_effort": "", "max_output_tokens": 512, "request_timeout_sec": args.timeout,
        "status_topic": "/llm_smoke/status",
        "extra_request_body_json": json.dumps({"chat_template_kwargs": {"enable_thinking": False}})
        if args.protocol == "chat_completions" else "{}",
    }
    if args.mode == "client":
        parameters.update({
            "prompt_topic": "/llm_smoke/prompt", "request_topic": "/llm_smoke/request",
            "response_topic": "/llm_smoke/text", "response_json_topic": "/llm_smoke/result",
            "max_pending_requests": 1,
        })
    else:
        parameters.update({
            "instruction_topic": "/llm_smoke/instruction", "plan_topic": "/llm_smoke/plan",
            "scene_topic": "/llm_smoke/scene", "allow_local_fallback": False,
            "enable_rcm_actions": args.mode == "rcm",
        })
    try:
        with tempfile.TemporaryDirectory(prefix="llm-ros-smoke-") as directory:
            directory = Path(directory)
            config = directory / "params.yaml"
            config.write_text("/**:\n  ros__parameters:\n" + "".join(
                f"    {key}: {json.dumps(value)}\n" for key, value in parameters.items()
            ))
            log_path = directory / "launch.log"
            with log_path.open("w") as log:
                process = subprocess.Popen(
                    ["ros2", "launch", "llm_ros", "llm.launch.py", f"mode:={launch_mode}", f"params_file:={config}"],
                    stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                    env=dict(os.environ, ROS_LOG_DIR=str(directory)),
                )
                probe = None
                rclpy.init()
                try:
                    probe = Probe(args.mode)
                    deadline = time.monotonic() + args.timeout
                    probe.wait(lambda: probe.pub.get_subscription_count() > 0, deadline, process)
                    if args.mode == "client":
                        probe.wait(lambda: probe.pub_json.get_subscription_count() > 0, deadline, process)
                        probe.pub_json.publish(String(data="{invalid"))
                        probe.wait(lambda: any(not item["ok"] for item in probe.messages), deadline, process)
                        probe.pub.publish(String(data="Reply with READY."))
                        probe.wait(lambda: any(item.get("ok") and item.get("text") for item in probe.messages), deadline, process)
                        text_result = next(item for item in probe.messages if item.get("ok"))
                        probe.pub_json.publish(String(data=json.dumps({
                            "request_id": "smoke-correlated", "messages": [{"role": "user", "content": "Reply with SECOND."}],
                        })))
                        probe.wait(lambda: any(item["request_id"] == "smoke-correlated" for item in probe.messages), deadline, process)
                        correlated = next(item for item in probe.messages if item["request_id"] == "smoke-correlated")
                        assert correlated["ok"] and correlated["text"]
                        print(f"Client text: {text_result['text']!r}; correlated reply: {correlated['text']!r}")
                        if not args.endpoint:
                            request_ids = {f"overload-{index}" for index in range(8)}
                            for request_id in sorted(request_ids):
                                probe.pub_json.publish(String(data=json.dumps({
                                    "request_id": request_id, "prompt": "Queue stress check",
                                })))
                            probe.wait(
                                lambda: request_ids.issubset({item["request_id"] for item in probe.messages}),
                                deadline, process,
                            )
                            overloaded = [item for item in probe.messages if item["request_id"] in request_ids]
                            assert any(not item["ok"] and "queue is full" in item["error"] for item in overloaded)
                            assert any(item["ok"] for item in overloaded)
                            print("Bounded queue: every request returned success or an explicit queue-full error")
                    else:
                        if args.mode == "planner":
                            probe.wait(lambda: probe.pub_scene.get_subscription_count() > 0, deadline, process)
                            probe.pub_scene.publish(String(data=json.dumps({
                                "target_frame": "world", "objects": [{
                                    "label": "red cube", "visible": True, "confidence": 1.0,
                                    "position_world": {"x": 0.4, "y": 0.0, "z": 0.1},
                                }],
                            })))
                            # Allow independent scene and instruction DDS topics to arrive.
                            settle_until = time.monotonic() + 0.3
                            while time.monotonic() < settle_until:
                                rclpy.spin_once(probe, timeout_sec=0.1)
                        instruction = "Locate the port without inserting." if args.mode == "rcm" else "Hover above the red cube."
                        probe.pub.publish(String(data=instruction))
                        probe.wait(lambda: bool(probe.messages), deadline, process)
                        plan = probe.messages[-1]
                        if args.mode == "planner":
                            assert plan["steps"] and plan["steps"][0]["target_prompt"] == "red cube"
                            assert plan["steps"][0]["action"] == "hover_target"
                        else:
                            assert plan["instruction"] and "steps" not in plan
                            assert plan["terminal_operation"] == "localize_only"
                        probe.wait(lambda: any(msg.data.startswith("planned:") for msg in probe.statuses), deadline, process)
                        print(f"Planner output: {json.dumps(plan, ensure_ascii=False)}")
                    print(f"PASS: installed {args.mode} node, protocol={args.protocol}, backend={'real' if args.endpoint else 'mock'}", flush=True)
                except Exception:
                    print(log_path.read_text(), flush=True)
                    raise
                finally:
                    if probe is not None:
                        probe.destroy_node()
                    if rclpy.ok():
                        rclpy.shutdown()
                    if process.poll() is None:
                        os.killpg(process.pid, signal.SIGINT)
                        try:
                            process.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            os.killpg(process.pid, signal.SIGKILL)
                            process.wait(timeout=5)
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=2)


if __name__ == "__main__":
    main()
