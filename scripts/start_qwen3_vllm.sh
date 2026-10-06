#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Adapted from vla_simu_workspace; uses an independent model-serving environment.
set -euo pipefail
model="${QWEN_MODEL:-Qwen/Qwen3-4B}"
served_name="${QWEN_SERVED_MODEL_NAME:-$model}"
host="${QWEN3_HOST:-127.0.0.1}"
port="${QWEN3_PORT:-8000}"
vllm_bin="${QWEN3_VLLM_BIN:-vllm}"
if ! command -v "$vllm_bin" >/dev/null 2>&1; then
  echo "vllm unavailable; activate the environment installed from requirements-server.txt." >&2
  exit 1
fi
exec "$vllm_bin" serve "$model" \
  --served-model-name "$served_name" --host "$host" --port "$port" \
  --tensor-parallel-size "${QWEN3_TENSOR_PARALLEL_SIZE:-1}" \
  --gpu-memory-utilization "${QWEN3_GPU_MEMORY_UTILIZATION:-0.65}" \
  --max-model-len "${QWEN3_MAX_MODEL_LEN:-4096}" \
  --generation-config vllm --reasoning-parser qwen3 \
  --structured-outputs-config.backend=xgrammar \
  --structured-outputs-config.enable_in_reasoning=True \
  --structured-outputs-config.disable_any_whitespace=True "$@"
