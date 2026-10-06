# ROS interfaces

## General communication node

Executable: `ros2 run llm_ros llm_client_node`.

| Direction | Default topic | Type | Meaning |
| --- | --- | --- | --- |
| Input | `/llm/prompt` | `std_msgs/msg/String` | Plain text; the configured system prompt is prepended. JSON-looking text remains a prompt. |
| Input | `/llm/request_json` | `std_msgs/msg/String` | JSON envelope with a caller-defined request ID and either prompt or messages. |
| Output | `/llm/response` | `std_msgs/msg/String` | Successful assistant text only. |
| Output | `/llm/response_json` | `std_msgs/msg/String` | Correlated success/error envelope. |
| Output | `/llm/status` | `std_msgs/msg/String` | JSON state: `queued`, `running`, `completed`, or `error`, with the request ID. |

All client topics use reliable, volatile QoS, depth 10. No past response is replayed
to a late subscriber. Separate DDS topics do not provide cross-topic ordering;
use `response_json` and its request ID to match a result to an input.

Request examples:

```json
{"request_id": "query-1", "prompt": "Explain this ROS topic in one sentence."}
```

```json
{
  "request_id": "query-2",
  "messages": [
    {"role": "system", "content": "Answer concisely."},
    {"role": "user", "content": "What is a ROS node?"}
  ]
}
```

Supported envelope fields are `request_id`, `prompt`, `messages`, and optional
`response_schema`. Use exactly one of `prompt` and `messages`. An omitted/empty
request ID is generated. Caller-defined IDs are correlation labels, not a duplicate
suppression mechanism. Explicit `messages` replace the automatically constructed
system/user messages. Supported roles are system, developer, user, and assistant;
content may be a string or a protocol-specific list of content blocks.

`response_schema` is passed to the provider's JSON-schema format option. The client
does not independently validate returned text against that schema. Vision-capable
providers may accept image content blocks through `messages`; there is no camera
subscriber or image encoding/conversion node in this package.

Successful result:

```json
{
  "request_id": "query-1",
  "ok": true,
  "text": "A ROS topic carries messages between nodes.",
  "model": "Qwen/Qwen3-4B",
  "usage": {"prompt_tokens": 20, "completion_tokens": 12}
}
```

Failed result:

```json
{"request_id": "query-1", "ok": false, "error": "LLM endpoint returned HTTP 401"}
```

One worker sends one HTTP request at a time. Pending requests use a bounded FIFO;
full queues return an explicit error. Pending work is held in memory and is not
restored after shutdown. There are no automatic retries or conversation history;
include prior messages explicitly for multi-turn use. Non-streaming text output is
supported; tool-call-only, refused, incomplete, and truncated responses produce errors.

### Client startup parameters

All are read-only after startup. Update YAML and restart to change configuration.

| Parameter | Node default | Meaning |
| --- | --- | --- |
| `prompt_topic`, `request_topic`, `response_topic`, `response_json_topic`, `status_topic` | Topics above | Configurable topic names. |
| `api_protocol` | `chat_completions` | `chat_completions` or `responses`. |
| `api_base_url` | `http://127.0.0.1:8000/v1/chat/completions` | Complete endpoint URL, not just the `/v1` prefix. |
| `model` | `Qwen/Qwen3-4B` | Name registered by the model service. |
| `api_key_env_var` | `LLM_API_KEY` | Environment variable for the optional bearer key. |
| `api_key_required` | `false` | Fail requests if the configured key is missing. |
| `system_prompt` | `You are a helpful assistant.` | System message for plain prompts. |
| `temperature`, `top_p` | `0.7`, `0.8` | Chat Completions generation settings. Not added automatically to Responses requests. |
| `max_output_tokens` | `512` | Positive output budget; mapped to Chat Completions `max_tokens`. |
| `reasoning_effort` | empty | Optional Responses reasoning setting. |
| `extra_request_body_json` | `{}` | Provider options such as Qwen `chat_template_kwargs`; cannot override model/input or enable streaming. |
| `request_timeout_sec` | `45.0` | HTTP socket timeout, not a strict total wall-clock deadline. |
| `max_pending_requests` | `4` | Pending FIFO capacity, excluding the active HTTP request. |
| `max_request_bytes` | `65536` | Maximum received UTF-8 ROS request size. |
| `max_response_bytes` | `8388608` | Maximum HTTP JSON response bytes. |

## Extracted task planner

Executable: `ros2 run llm_ros llm_task_planner_node`.

| Direction | Default topic | Type | QoS / meaning |
| --- | --- | --- | --- |
| Input | `/llm_task/instruction` | `std_msgs/msg/String` | Reliable, volatile, depth 10; task text. |
| Input | `/scene/objects_json` | `std_msgs/msg/String` | Reliable, volatile, depth 10; optional scene registry. |
| Output | `/llm_task/plan_json` | `std_msgs/msg/String` | Reliable, transient local, depth 1; latest normalized task plan/request. |
| Output | `/llm_task/status` | `std_msgs/msg/String` | Reliable, volatile, depth 10; original plain-text status format. |

The original planner makes its HTTP request in the instruction callback and handles
instructions serially; scene updates wait while that callback runs. Use the general
client for a responsive, queued communication interface. The plan topic retains
the latest published output; a failed subsequent instruction may leave that output
latched. Use current status and your application's execution policy when consuming plans.

Typical statuses are `planning`, `planned: N steps`,
`planned_fallback: N steps`, `planning_failed: no_steps`, and
`planned: rcm_task_request`.

Task-plan output has `task_summary`, `planning_notes`, and `steps`. Each step has
`step_index`, `action`, `target_prompt`, `description`, `success_radius_m`,
`dwell_sec`, and `wait_sec`. The default actions are `hover_target` and `wait`,
with red/green/blue/yellow cube targets. `enable_grasp_actions` permits
`grasp_target` and `release_gripper`; `open_vocabulary_targets` permits arbitrary
object phrases. This is the source application's format, not a universal robot
execution interface. The original normalization and multilingual parser are retained.

With `enable_rcm_actions: true`, output is a high-level semantic request instead
of steps. Fields include `instruction`, `objective_text`, candidate preference,
`exclusions`, `allow_alternative`, `terminal_operation`, insertion-depth preference,
approach constraints, and `verification`. RCM requests are not controller trajectories.
The RCM schema includes an open verification object and is sent without strict
Responses schema mode; normal tabletop plans use the source's strict schema mode.

Planner startup settings use the same names as the original source:

| Parameter group | Defaults / notes |
| --- | --- |
| `instruction_topic`, `plan_topic`, `status_topic`, `scene_topic` | Topics above. |
| `api_protocol`, `model`, `api_base_url` | Bare node defaults: `responses`, `gpt-5-mini`, `https://api.openai.com/v1/responses`; launch selects the chosen profile. |
| `api_key_env_var`, `api_key_required` | Bare node: `OPENAI_API_KEY`, `true`. Qwen profile: `LLM_API_KEY`, `false`. |
| `api_key` | Empty; compatibility parameter from source. Prefer the environment variable because ROS parameter values are inspectable. |
| `reasoning_effort` | Bare node `low`; empty in Qwen profiles. |
| `temperature`, `top_p`, `max_output_tokens` | Bare node `0.0`, `1.0`, `512`; Qwen profile uses `0.7`, `0.8`, `512`. |
| `extra_request_body_json` | JSON provider options for the selected protocol. |
| `request_timeout_sec` | Bare node `45.0`; supplied profiles `90.0`. |
| `open_vocabulary_targets`, `enable_grasp_actions`, `enable_rcm_actions` | Bare node `false`; enabled explicitly by selected profiles/YAML. |
| `allow_local_fallback` | Bare node preserves source default `true`; every supplied launch profile sets `false`. Fallback is a deterministic parser, not LLM inference. |

Planner parameters are read-only after startup. Plan helper definitions and JSON
schemas are in [task_plan_utils.py](../llm_ros/task_plan_utils.py).

## Launch and namespaces

`llm.launch.py` chooses `mode:=client|planner` and `backend:=qwen3|responses`.
`params_file:=/absolute/path/config.yaml` overrides the chosen profile. Optional
launch overrides are `api_base_url`, `api_protocol`, `model`, `api_key_env_var`,
`api_key_required`, and `request_timeout_sec`; unspecified values remain from YAML.

Default topics are absolute. A namespace changes the node name scope, not these
topics. Configure separate topic names or relative topic names in YAML when
running multiple instances.
