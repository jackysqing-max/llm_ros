# Deployment

## Native ROS installation

Follow [README](../README.md). The tested baseline is Ubuntu 22.04, ROS 2 Humble,
and system Python 3.10. `scripts/setup.sh [workspace]` defaults to `$HOME/llm_ws`.
`LLM_ROS_VENV` overrides the ROS venv directory; `LLM_ROS_PYTHON` overrides
`/usr/bin/python3`. Keep the Python ABI compatible with the installed ROS build.

The ROS client uses `urllib`, JSON, and threading from the Python standard library.
`requirements.txt` records that no third-party HTTP/model dependency is required.
The `--system-site-packages` venv can reuse ROS and colcon from the system.
Build through its `python -m colcon` so installed executable shebangs use that
interpreter. Model-serving packages belong in a different environment.

## Qwen3 / vLLM

The supplied recipe targets vLLM **0.19.0** and `Qwen/Qwen3-4B`, matching the source
project. Install [requirements-server.txt](../requirements-server.txt) in a separate
venv, then run `scripts/start_qwen3_vllm.sh` from the repository root.

| Environment variable | Default | Purpose |
| --- | --- | --- |
| `QWEN_MODEL` | `Qwen/Qwen3-4B` | Hub model ID or local model directory. |
| `QWEN_SERVED_MODEL_NAME` | Same as `QWEN_MODEL` | Model name exposed by `/v1/models`; match ROS `model`. |
| `QWEN3_HOST` | `127.0.0.1` | Server bind address. |
| `QWEN3_PORT` | `8000` | HTTP port. |
| `QWEN3_VLLM_BIN` | `vllm` | Executable in the serving environment. |
| `QWEN3_TENSOR_PARALLEL_SIZE` | `1` | GPU parallelism. |
| `QWEN3_GPU_MEMORY_UTILIZATION` | `0.65` | GPU allocation fraction; tune for other workloads. |
| `QWEN3_MAX_MODEL_LEN` | `4096` | Maximum context length, including input and output. |
| `HF_HOME` | Hugging Face library default | Model cache location. |

The helper includes Qwen3's reasoning parser and structured-output options. It
selects the `xgrammar` backend and sets `disable_any_whitespace=True` to constrain
JSON to compact output; unrestricted
whitespace caused repeated whitespace and truncated plans in local Qwen3 validation.
It forwards additional CLI arguments such as `--enforce-eager`. The ROS Qwen profiles
disable thinking through `chat_template_kwargs`. This helper is specifically for
Qwen3; another model may require a different parser/template or server command.
The general ROS client can use an already-running compatible endpoint instead.

Wait for readiness before starting ROS requests:

```bash
curl --fail http://127.0.0.1:8000/health
curl --fail http://127.0.0.1:8000/v1/models
```

For offline serving, download the model separately, then use a local directory:

```bash
QWEN_MODEL="$HOME/models/Qwen3-4B" \
QWEN_SERVED_MODEL_NAME=Qwen/Qwen3-4B \
HF_HUB_OFFLINE=1 ./scripts/start_qwen3_vllm.sh
```

An endpoint check sends one inference request:

```bash
# In the sourced ROS environment:
python scripts/check_endpoint.py --endpoint http://127.0.0.1:8000/v1/chat/completions
```

## Remote APIs and credentials

Choose `backend:=responses` for the supplied Responses profile, or use custom YAML
for another compatible endpoint. `api_base_url` must include `/v1/responses` or
`/v1/chat/completions`. Match `api_protocol` to that endpoint. A model server's
registered name must match the `model` setting.

```bash
export OPENAI_API_KEY="YOUR_API_KEY"
ros2 launch llm_ros llm.launch.py backend:=responses model:=gpt-5-mini
```

Keys are resolved from the configured environment variable at request time. The
general node exposes no inline key parameter. The planner retains its original
optional `api_key` parameter for compatibility, but environment-based keys avoid
putting credentials in inspectable ROS parameters. HTTP errors report status codes
without printing server error bodies. HTTP redirects are rejected.

The supplied Responses profiles set `store: false` in the request body. This is
a provider request option, not a statement about all provider data policies.
No remote credential or paid API request was used for this extraction's acceptance.

## Docker client on Linux

Build the ROS-only image; it contains no model runtime or weights:

```bash
docker build -t llm-ros:0.1.0 .
docker run --rm --init --network host --ipc host \
  -e ROS_DOMAIN_ID=0 -e RMW_IMPLEMENTATION=rmw_fastrtps_cpp \
  llm-ros:0.1.0 ros2 launch llm_ros llm.launch.py \
  api_base_url:=http://127.0.0.1:8000/v1/chat/completions
```

Match the ROS domain and RMW implementation with other ROS processes. Host
networking/IPC recipes target native Linux. For a Responses service, pass the key
environment and selected backend:

```bash
docker run --rm --init --network host --ipc host -e OPENAI_API_KEY \
  llm-ros:0.1.0 ros2 launch llm_ros llm.launch.py backend:=responses
```

## Compose: optional local model service

The Compose file always supports the ROS client with an external endpoint. Its
optional `local-model` profile starts the separate vLLM GPU service. The GPU profile
needs NVIDIA Container Toolkit and Compose 2.30+ for
[`gpus: all`](https://docs.docker.com/reference/compose-file/services/#gpus).

```bash
docker compose build
# Use an already running model service:
docker compose up ros
# Or start the optional local GPU model first:
docker compose --profile local-model up -d qwen3
curl --fail http://127.0.0.1:8000/health
docker compose up ros
```

Model loading can take time; rerun the readiness check until it succeeds before
publishing prompts. The vLLM service stores downloaded weights in a named cache
volume. The Compose file does not set an automatic model-readiness dependency.

Configure `LLM_MODE=planner`, `LLM_BACKEND=responses`, `LLM_ENDPOINT`, or `LLM_MODEL`
as needed. The default mode is the general client. For a remote service with no
local model container:

```bash
LLM_BACKEND=responses docker compose up ros
docker compose down
```

Docker is unavailable on the local validation host. These container recipes have
not been built or run there; native ROS and local model results are recorded in
[validation](validation.md).

## Troubleshooting

| Symptom | Action |
| --- | --- |
| `rclpy` import fails | Source ROS and use its Python ABI; use a system-compatible venv. |
| Connection fails | Check the full endpoint, `/health`, the host/port, and whether the service is ready. |
| HTTP 401/403 | Set the authorized credential through the selected key environment variable. |
| HTTP 404 / model not found | Match `/v1/models` and the selected API protocol/route. |
| Queue-full result | Reduce publisher rate, increase queue capacity if appropriate, or use a faster service. |
| Truncated response error | Increase output tokens/context budget; partial text is not treated as a successful result. |
| JSON generation repeats whitespace | Use the supplied serving helper's `--structured-outputs-config.disable_any_whitespace=True` setting. |
| Planner produces no plan | Inspect `/llm_task/status` and target/action settings; provided profiles disable fallback. |
| No ROS input | Match topic, domain, QoS, and RMW; absolute topics are not isolated by namespace alone. |
| vLLM GPU memory failure | Tune utilization/context length and competing workloads; model server memory is separate from the ROS client. |

Technical references: [vLLM server](https://docs.vllm.ai/en/v0.19.0/serving/openai_compatible_server/),
[Qwen3 reasoning](https://docs.vllm.ai/en/v0.19.0/features/reasoning_outputs/),
[vLLM structured outputs](https://docs.vllm.ai/en/v0.19.0/features/structured_outputs/),
[OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses).
