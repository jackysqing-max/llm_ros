#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Exercise the installed chat demo, launch lifecycle, conversation, and failures."""

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

from llm_ros.mock_server import MockHandler


class RecordingMock(MockHandler):
    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.requests.append(payload)
        prompt = payload["messages"][-1]["content"]
        if prompt == "TRIGGER_DEMO_HTTP_ERROR":
            self._send(503, {"error": "provider-body-must-not-be-printed"})
            return
        if prompt == "TRIGGER_DEMO_TIMEOUT":
            time.sleep(0.6)
        self._send(200, {"model": payload["model"], "choices": [{
            "finish_reason": "stop", "message": {"role": "assistant", "content": f"MOCK: {prompt}"},
        }]})


def stop(process):
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGINT)
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", help="An existing real Chat Completions endpoint; omitted starts a mock")
    parser.add_argument("--model", help="Model name; defaults to mock-llm or Qwen/Qwen3-4B")
    parser.add_argument("--domain-id", type=int, default=97)
    args = parser.parse_args()
    model = args.model or ("Qwen/Qwen3-4B" if args.endpoint else "mock-llm")
    server = None
    if not args.endpoint:
        server = ThreadingHTTPServer(("127.0.0.1", 0), RecordingMock)
        server.requests = []
        threading.Thread(target=server.serve_forever, daemon=True).start()
    endpoint = args.endpoint or f"http://127.0.0.1:{server.server_port}/v1/chat/completions"
    try:
        with tempfile.TemporaryDirectory(prefix="llm-demo-smoke-") as directory:
            environment = dict(os.environ, ROS_DOMAIN_ID=str(args.domain_id),
                               ROS_LOCALHOST_ONLY="1", ROS_LOG_DIR=directory)

            def run(command, *, stdin=None, expected_code=0):
                process = subprocess.Popen(command, env=environment, start_new_session=True,
                                           stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                           stderr=subprocess.STDOUT, text=True)
                try:
                    output, _ = process.communicate(stdin, timeout=60)
                finally:
                    stop(process)
                assert process.returncode == expected_code, output
                for line in output.splitlines():
                    if "[LLM]" in line or "[ERROR]" in line:
                        print(line, flush=True)
                return output

            launch = ["ros2", "launch", "llm_ros", "chat_demo.launch.py",
                      f"api_base_url:={endpoint}", f"model:={model}"]
            output = run(launch + ["prompt:=Reply with READY."])
            assert "[LLM]" in output, output
            if server:
                output = run(launch + ["prompt:=TRIGGER_DEMO_HTTP_ERROR"], expected_code=1)
                assert "HTTP 503" in output and "provider-body-must-not-be-printed" not in output

            bridge_log = Path(directory) / "bridge.log"
            with bridge_log.open("w") as log:
                bridge = subprocess.Popen(
                    ["ros2", "launch", "llm_ros", "llm.launch.py", f"api_base_url:={endpoint}", f"model:={model}"],
                    stdout=log, stderr=subprocess.STDOUT, env=environment, start_new_session=True,
                )
                demo = ["ros2", "run", "llm_ros", "llm_chat_demo"]
                try:
                    if server:
                        first = len(server.requests)
                        output = run(demo, stdin="Remember demo-token.\nWhat did I say?\n:reset\nAfter reset.\n:quit\n")
                        turns = server.requests[first:]
                        assert len(turns) == 3 and output.count("[LLM]") == 3, output
                        assert [len(item["messages"]) for item in turns] == [2, 4, 2]
                        assert turns[1]["messages"][1]["content"] == "Remember demo-token."
                        assert turns[1]["messages"][2]["role"] == "assistant"
                        first = len(server.requests)
                        run(demo + ["--history-turns", "0"], stdin="First.\nSecond.\n:quit\n")
                        assert [len(item["messages"]) for item in server.requests[first:]] == [2, 2]
                        output = run(demo + ["--once", "TRIGGER_DEMO_HTTP_ERROR"], expected_code=1)
                        assert "HTTP 503" in output and "provider-body-must-not-be-printed" not in output
                        output = run(demo + ["--once", "TRIGGER_DEMO_TIMEOUT", "--timeout", "0.1"], expected_code=1)
                        assert "Timed out waiting for the correlated LLM reply" in output
                    else:
                        output = run(demo, stdin=(
                            "Remember the token ros-demo-42. Reply with ACK.\n"
                            "What token did I ask you to remember? Reply with the token only.\n:quit\n"
                        ))
                        replies = [line for line in output.splitlines() if "[LLM]" in line]
                        assert len(replies) == 2 and "ros-demo-42" in replies[-1], output
                    output = run(demo + ["--once", "Missing bridge", "--discovery-timeout", "0.2",
                                         "--ros-args", "-p", "request_topic:=/llm_demo_missing/request",
                                         "-p", "response_json_topic:=/llm_demo_missing/result"], expected_code=1)
                    assert "Timed out waiting for the ROS LLM bridge" in output
                except Exception:
                    print(bridge_log.read_text(), flush=True)
                    raise
                finally:
                    stop(bridge)
            print(f"PASS: installed chat demo, backend={'real' if args.endpoint else 'mock'}", flush=True)
    finally:
        if server:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    main()
