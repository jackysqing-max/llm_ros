#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check a configured LLM endpoint with one explicit, small inference request."""

import argparse
from llm_ros.http_client import LlmHttpClient, build_payload, extract_text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default="http://127.0.0.1:8000/v1/chat/completions")
    parser.add_argument("--protocol", choices=["chat_completions", "responses"], default="chat_completions")
    parser.add_argument("--model", default="Qwen/Qwen3-4B")
    parser.add_argument("--api-key-env", default="LLM_API_KEY")
    parser.add_argument("--require-key", action="store_true")
    args = parser.parse_args()
    extra = {"chat_template_kwargs": {"enable_thinking": False}} if args.protocol == "chat_completions" else {"store": False}
    payload = build_payload(
        protocol=args.protocol, model=args.model,
        messages=[{"role": "user", "content": "Reply with READY."}],
        max_output_tokens=128, extra_body=extra,
    )
    result = LlmHttpClient(
        args.endpoint, timeout=90, api_key_env_var=args.api_key_env,
        api_key_required=args.require_key,
    ).send(payload)
    print(extract_text(result, args.protocol))


if __name__ == "__main__":
    main()
