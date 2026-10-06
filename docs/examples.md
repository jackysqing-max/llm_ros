# Examples

Run commands from a terminal with ROS and the package's install environment sourced.

For a complete application node with one-shot and interactive conversation modes,
see the [ROS 2 chat demo](chat_demo.md) and [source code](../llm_ros/llm_chat_demo.py).

## Plain prompt and correlated request

```bash
ros2 launch llm_ros llm.launch.py
# Another terminal: inspect both output formats.
ros2 topic echo /llm/response_json std_msgs/msg/String
```

Publish plain text:

```bash
ros2 topic pub --once /llm/prompt std_msgs/msg/String "{data: 'Explain ROS in one sentence.'}"
```

Publish a JSON envelope inside `std_msgs/String`:

```bash
ros2 topic pub --once /llm/request_json std_msgs/msg/String \
  '{"data": "{\"request_id\": \"example-1\", \"prompt\": \"Say hello.\"}"}'
```

Both plain prompts and explicit requests produce a result on `/llm/response_json`.
The explicit request retains `example-1` for correlation.

## Planning with scene context

```bash
ros2 launch llm_ros llm.launch.py mode:=planner
# Another terminal:
ros2 topic pub --once /scene/objects_json std_msgs/msg/String \
  '{"data": "{\"target_frame\": \"world\", \"objects\": [{\"label\": \"red cube\", \"visible\": true, \"confidence\": 1.0}]}"}'
ros2 run llm_ros llm_task_cli --once "Hover above the red cube, then wait 2 seconds." \
  --wait-status-prefix planned --fail-status-prefix planning_failed
```

The scene registry is optional context. Plan normalization is specific to the
source application's format; inspect [interfaces](interfaces.md) before connecting
an executor in another application.

## Open-vocabulary and semantic RCM profiles

Copy `config/planner_qwen3.yaml` and set `open_vocabulary_targets: true` to produce
object phrases for text-guided perception. Configure your own consumer to use those
phrases, for example publishing the selected `target_prompt` to a SAM3 prompt topic.
This package does not automatically start or connect a robot executor.

For the original semantic RCM request format:

```bash
ros2 launch llm_ros llm.launch.py mode:=planner \
  params_file:="$PWD/config/planner_rcm.yaml"
ros2 run llm_ros llm_task_cli --once "Locate the circular port without inserting." \
  --wait-status-prefix planned --fail-status-prefix planning_failed
```

The result is a task request, not a list of controller stages.

## Pure Python HTTP use

After sourcing the install environment, the client can also be imported without ROS:

```python
from llm_ros.http_client import LlmHttpClient, build_payload, extract_text

payload = build_payload(
    protocol="chat_completions",
    model="Qwen/Qwen3-4B",
    messages=[{"role": "user", "content": "Say hello."}],
    extra_body={"chat_template_kwargs": {"enable_thinking": False}},
)
result = LlmHttpClient("http://127.0.0.1:8000/v1/chat/completions").send(payload)
print(extract_text(result, "chat_completions"))
```
