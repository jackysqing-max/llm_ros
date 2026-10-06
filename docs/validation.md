# Validation record

Validated on **October 6, 2026** during extraction from `vla_simu_workspace`,
source commit `07e5c1e1968104af92a0ee6deabe260ac1ccb341`.

## Environment

| Component | Validated version |
| --- | --- |
| OS / ROS | Ubuntu 22.04 / ROS 2 Humble |
| ROS Python | 3.10.12, fresh system-site-packages venv |
| Test runner | pytest 9.0.2 |
| Local model service | Separate pre-existing venv: vLLM 0.19.0, Torch 2.10.0, Transformers 4.57.6 |
| Model | `Qwen/Qwen3-4B`, cached revision `1cfa9a7208912126459214e8b04321603b3df60c` |
| GPU | NVIDIA GeForce RTX 5080 Laptop GPU, 16 GiB |

The fresh ROS environment imports `rclpy` and has no Torch, Transformers, vLLM,
or OpenAI SDK installed. ROS package installation and model serving were isolated.
The server used the repository helper, a local cached model directory, port 18080,
`HF_HUB_OFFLINE=1`, and `--enforce-eager`. No model weights are included in the repo.

## Acceptance results

| Check | Result |
| --- | --- |
| Pure transport and task-normalization tests | 35 passed; no model downloads or remote API calls. |
| Native `scripts/setup.sh` into a fresh workspace | Passed; source link, venv, symlink build, and three installed executables. |
| Independent non-symlink colcon installation | Passed; installed launch and CLI discovery. |
| `colcon test` / `colcon test-result` | Passed, zero failures. |
| Python syntax and shell syntax | Passed. |
| Mock installed general client, Chat Completions and Responses | Passed; invalid JSON recovery, text input, correlated message input, bounded-queue rejection, and subsequent successful results. |
| Mock installed tabletop planner, both protocols | Passed; normalized red-cube hover step and `planned` status with fallback disabled. |
| Mock installed semantic RCM planner, both protocols | Passed; high-level request and `localize_only` intent, with fallback disabled. |
| Real local Qwen3 endpoint | Passed; assistant text returned from a real inference. |
| Real installed general client | Passed; plain prompt and correlated explicit messages returned `READY.` and `SECOND.`. |
| Real installed tabletop planner | Passed; visible red-cube scene input produced a normalized `hover_target` step and `planned` status. |
| Real installed semantic RCM planner | Passed; port-localization instruction produced `localize_only`, without controller steps. |

The initial Qwen3 structured-output configuration allowed repeated whitespace
until the output budget was exhausted. Selecting `xgrammar` and
`disable_any_whitespace=True` in the serving helper and Compose recipe resolved
that failure in the acceptance run. The fixed-target planner requires scene context;
the acceptance probe publishes a visible red cube before its instruction.

## Reproduce

From the sourced ROS environment and repository root:

```bash
python -m pip install -r requirements-test.txt
python -m pytest -q
python -m compileall -q llm_ros launch scripts setup.py
bash -n scripts/setup.sh scripts/start_qwen3_vllm.sh docker/entrypoint.sh
python scripts/smoke_test.py
python scripts/smoke_test.py --protocol responses
python scripts/smoke_test.py --mode planner
python scripts/smoke_test.py --mode planner --protocol responses
python scripts/smoke_test.py --mode rcm
python scripts/smoke_test.py --mode rcm --protocol responses
```

For a separately running Qwen3 service, replace the port if necessary:

```bash
python scripts/smoke_test.py \
  --endpoint http://127.0.0.1:8000/v1/chat/completions --model Qwen/Qwen3-4B
python scripts/smoke_test.py --mode planner \
  --endpoint http://127.0.0.1:8000/v1/chat/completions --model Qwen/Qwen3-4B
python scripts/smoke_test.py --mode rcm \
  --endpoint http://127.0.0.1:8000/v1/chat/completions --model Qwen/Qwen3-4B
```

The smoke test uses domain 96 by default and cleans up its own launch processes.
It sends inference requests when given a real endpoint. It never stops that endpoint.

## Limits

Responses support was checked against official protocol documentation and a mock
HTTP endpoint. No live OpenAI credential or paid API request was used. Mock success
does not establish behavior of every remote model/provider. Docker is unavailable
on the validation host, so the Dockerfile and Compose deployment were not built or
run there. Other ROS distributions, other GPUs/models, image inputs, sustained-load
performance, and downstream robot execution have not been validated.

GitHub Actions repeats unit tests, a fresh Humble build, and all six mock ROS smoke
tests. It does not download weights, run GPU inference, or require API credentials.
