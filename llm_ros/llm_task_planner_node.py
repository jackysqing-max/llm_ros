#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Use an LLM to decompose a natural-language instruction into executable steps."""

from __future__ import annotations

import json
import os
import urllib.error

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from rcl_interfaces.msg import ParameterDescriptor
from std_msgs.msg import String

from llm_ros.http_client import (
    LlmHttpClient,
    extract_response_text as _extract_response_text,
    extract_chat_completion_text as _extract_chat_completion_text,
    extract_json_object as _extract_json_object,
)

from llm_ros.task_plan_utils import (
    PLAN_JSON_SCHEMA,
    SURGICAL_RCM_TASK_JSON_SCHEMA,
    SUPPORTED_TARGET_PROMPTS,
    infer_plan_from_instruction,
    plan_to_json,
    rcm_task_request_to_json,
    scene_registry_from_json,
    scene_registry_summary,
    sanitize_rcm_task_request,
    sanitize_plan,
)


class LlmTaskPlanner(Node):
    """Convert user instructions into a sanitized JSON step plan."""

    def __init__(self):
        super().__init__("llm_task_planner_node")

        self._declare_startup_parameter("instruction_topic", "/llm_task/instruction")
        self._declare_startup_parameter("plan_topic", "/llm_task/plan_json")
        self._declare_startup_parameter("status_topic", "/llm_task/status")
        self._declare_startup_parameter("scene_topic", "/scene/objects_json")
        self._declare_startup_parameter("api_protocol", "responses")
        self._declare_startup_parameter("model", "gpt-5-mini")
        self._declare_startup_parameter("reasoning_effort", "low")
        self._declare_startup_parameter("api_base_url", "https://api.openai.com/v1/responses")
        self._declare_startup_parameter("api_key", "")
        self._declare_startup_parameter("api_key_env_var", "OPENAI_API_KEY")
        self._declare_startup_parameter("api_key_required", True)
        self._declare_startup_parameter("temperature", 0.0)
        self._declare_startup_parameter("top_p", 1.0)
        self._declare_startup_parameter("max_output_tokens", 512)
        self._declare_startup_parameter("extra_request_body_json", "{}")
        self._declare_startup_parameter("request_timeout_sec", 45.0)
        self._declare_startup_parameter("open_vocabulary_targets", False)
        self._declare_startup_parameter("enable_grasp_actions", False)
        self._declare_startup_parameter("enable_rcm_actions", False)
        self._declare_startup_parameter("allow_local_fallback", True)

        self.instruction_topic = str(self.get_parameter("instruction_topic").value)
        self.plan_topic = str(self.get_parameter("plan_topic").value)
        self.status_topic = str(self.get_parameter("status_topic").value)
        self.scene_topic = str(self.get_parameter("scene_topic").value)
        self.api_protocol = str(self.get_parameter("api_protocol").value).strip().lower()
        self.model = str(self.get_parameter("model").value)
        self.reasoning_effort = str(self.get_parameter("reasoning_effort").value)
        self.api_base_url = str(self.get_parameter("api_base_url").value)
        self.api_key = str(self.get_parameter("api_key").value)
        self.api_key_env_var = str(self.get_parameter("api_key_env_var").value)
        self.api_key_required = bool(self.get_parameter("api_key_required").value)
        self.temperature = float(self.get_parameter("temperature").value)
        self.top_p = float(self.get_parameter("top_p").value)
        self.max_output_tokens = int(self.get_parameter("max_output_tokens").value)
        self.extra_request_body = self._parse_extra_request_body(
            str(self.get_parameter("extra_request_body_json").value)
        )
        self.request_timeout_sec = float(self.get_parameter("request_timeout_sec").value)
        self.open_vocabulary_targets = bool(
            self.get_parameter("open_vocabulary_targets").value
        )
        self.enable_grasp_actions = bool(self.get_parameter("enable_grasp_actions").value)
        self.enable_rcm_actions = bool(
            self.get_parameter("enable_rcm_actions").value
        )
        self.allow_local_fallback = bool(
            self.get_parameter("allow_local_fallback").value
        )
        self.latest_scene_registry = {
            "target_frame": "world",
            "updated_at_sec": 0.0,
            "objects": [],
        }

        plan_qos = QoSProfile(
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        self.pub_plan = self.create_publisher(
            String,
            self.plan_topic,
            plan_qos,
        )
        self.pub_status = self.create_publisher(String, self.status_topic, 10)
        self.sub_instruction = self.create_subscription(
            String,
            self.instruction_topic,
            self.on_instruction,
            10,
        )
        self.sub_scene = self.create_subscription(
            String,
            self.scene_topic,
            self.on_scene_registry,
            10,
        )

        self.get_logger().info(
            "llm_task_planner_node started. "
            f"instruction_topic={self.instruction_topic}, "
            f"api_protocol={self.api_protocol}, "
            f"model={self.model}"
        )

    def _publish_status(self, text: str):
        msg = String()
        msg.data = text
        self.pub_status.publish(msg)

    def _declare_startup_parameter(self, name, default):
        return self.declare_parameter(name, default, ParameterDescriptor(read_only=True))

    def _parse_extra_request_body(self, raw_text: str) -> dict:
        text = (raw_text or "").strip()
        if not text:
            return {}
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"extra_request_body_json is not valid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError("extra_request_body_json must decode to a JSON object")
        return payload

    def _resolve_api_key(self) -> str:
        inline_key = self.api_key.strip()
        if inline_key:
            return inline_key

        env_key = ""
        if self.api_key_env_var:
            env_key = os.environ.get(self.api_key_env_var, "").strip()
        if env_key:
            return env_key

        if self.api_key_required:
            if self.api_key_env_var:
                raise RuntimeError(
                    "Missing API key: set parameter api_key or environment variable "
                    f"{self.api_key_env_var}"
                )
            raise RuntimeError("Missing API key: set parameter api_key")
        return ""

    def _request_headers(self, api_key: str) -> dict:
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        return headers

    def _messages_for_instruction(self, instruction_text: str) -> list[dict]:
        scene_summary = scene_registry_summary(self.latest_scene_registry)
        return [
            {"role": "system", "content": self._system_prompt()},
            {"role": "user", "content": f"Current scene summary: {scene_summary}"},
            {"role": "user", "content": instruction_text},
        ]

    def _build_responses_payload(self, instruction_text: str) -> dict:
        plan_schema = (
            SURGICAL_RCM_TASK_JSON_SCHEMA
            if self.enable_rcm_actions
            else PLAN_JSON_SCHEMA
        )
        payload = {
            "model": self.model,
            "input": self._messages_for_instruction(instruction_text),
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "robot_task_plan",
                    "schema": plan_schema,
                    "strict": not self.enable_rcm_actions,
                }
            },
        }
        if self.reasoning_effort:
            payload["reasoning"] = {"effort": self.reasoning_effort}
        if self.max_output_tokens > 0:
            payload["max_output_tokens"] = self.max_output_tokens
        if self.extra_request_body:
            payload.update(self.extra_request_body)
        return payload

    def _build_chat_completions_payload(self, instruction_text: str) -> dict:
        plan_schema = (
            SURGICAL_RCM_TASK_JSON_SCHEMA
            if self.enable_rcm_actions
            else PLAN_JSON_SCHEMA
        )
        payload = {
            "model": self.model,
            "messages": self._messages_for_instruction(instruction_text),
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "robot_task_plan",
                    "schema": plan_schema,
                },
            },
            "temperature": self.temperature,
            "top_p": self.top_p,
        }
        if self.max_output_tokens > 0:
            payload["max_tokens"] = self.max_output_tokens
        if self.extra_request_body:
            payload.update(self.extra_request_body)
        return payload

    def on_scene_registry(self, msg: String):
        self.latest_scene_registry = scene_registry_from_json(msg.data)

    def _system_prompt(self) -> str:
        if self.enable_rcm_actions:
            return (
                "You are a semantic task-request generator for a laparoscopic "
                "RCM access demo. Convert the user's instruction into one high-level "
                "JSON task request. "
                "Return JSON only, with no markdown or extra prose. "
                "The task request may describe the desired port, preferences, "
                "exclusions, whether alternatives are allowed, and the requested "
                "terminal operation. Use terminal_operation only as an execution "
                "intent: localize_only, establish_rcm, execute_rcm_circle, hold, "
                "retract, or stop. Do not expand the task into controller stages. "
                "Do not output joint angles, torques, Cartesian poses, tool paths, "
                "or arbitrary executable robot commands. The dynamic port candidate "
                "selection will be grounded later by a Qwen-VL semantic grounder "
                "using the marked camera image and candidate geometry. For "
                "approach_constraint use auto_closest_reachable unless the user "
                "explicitly supplies both a numerical tilt and azimuth. Then use "
                "preferred_cone_angle and preserve those values. Tilt is measured "
                "away from the detected inward hole axis; azimuth is in the "
                "controller's port-local cone frame. Never infer joint angles or "
                "a Cartesian robot pose from directional words."
            )
        if self.open_vocabulary_targets:
            if self.enable_grasp_actions:
                return (
                    "You are a tabletop robot task planner. "
                    "Convert the user's instruction into a short executable JSON task plan. "
                    "Return JSON only, with no markdown and no extra prose. "
                    "The robot can do four things: "
                    "1) hover above one visible tabletop object, "
                    "2) grasp one target object by closing a parallel gripper, "
                    "3) release the gripper, "
                    "4) wait for a short duration. "
                    "Use action='hover_target' when the robot should move above or "
                    "inspect an object. "
                    "Use action='grasp_target' when the robot should pick up or hold an object. "
                    "Use action='release_gripper' when the robot should open the gripper "
                    "or drop/release. "
                    "Use action='wait' when the robot should pause. "
                    "For pick-and-place or sorting tasks, always use this order: "
                    "grasp_target for the object, then hover_target for the destination "
                    "container/tray center, "
                    "then release_gripper. Never release before moving above the destination. "
                    "For hover_target and grasp_target steps, set target_prompt to a "
                    "concise object phrase "
                    "that can be sent directly to a text-conditioned segmentation model, such as "
                    "left silver surgical instrument, right silver surgical instrument, "
                    "silver surgical instrument, white sorting tray center, gauze pad, "
                    "curved needle, or red entry point. "
                    "Preserve spatial qualifiers such as left, middle, right, front, and "
                    "back when the user includes them. "
                    "Every step must include step_index starting at 1, target_prompt, "
                    "description, "
                    "success_radius_m, dwell_sec, and wait_sec. "
                    "For grasp_target steps, keep dwell_sec around 1.0 and wait_sec=0.0. "
                    "For release_gripper and wait steps, set target_prompt='' and "
                    "success_radius_m=0.0. "
                    "Use the scene summary as helpful context, but if it is empty or "
                    "does not yet list the requested object, still create target steps "
                    "from the user's object phrase because "
                    "perception will ground the prompt during execution. "
                    "Do not invent fine manipulation or cutting actions; represent them "
                    "as hover, grasp, "
                    "release, and wait primitives."
                )
            return (
                "You are a tabletop robot task planner. "
                "Convert the user's instruction into a short executable JSON task plan. "
                "Return JSON only, with no markdown and no extra prose. "
                "The robot can only do two things: "
                "1) hover above one visible tabletop object, "
                "2) wait for a short duration. "
                "Use action='hover_target' when the step should move above an object. "
                "Use action='wait' when the robot should pause. "
                "For hover steps, set target_prompt to a concise object phrase that can be sent "
                "directly to a text-conditioned segmentation model, such as mug, "
                "scissors, bottle, "
                "phone, book, or blue cup. "
                "Every hover_target step must include step_index starting at 1, "
                "description, success_radius_m=0.0, dwell_sec=1.0, and wait_sec=0.0. "
                "Every wait step must include target_prompt='', success_radius_m=0.0, "
                "dwell_sec=0.0, and wait_sec set to the pause duration. "
                "Prefer short noun phrases, usually one to four words, and avoid full sentences. "
                "Use the scene summary as helpful context, but if it is empty or does not yet "
                "list the requested object, still create a hover_target step from the user's "
                "object phrase because perception will ground the prompt during execution. "
                "If the user asks for unsupported actions like grasping or stacking, "
                "decompose only the observable hover sequence and mention the limitation "
                "in planning_notes. "
            )

        supported_targets = ", ".join(SUPPORTED_TARGET_PROMPTS)
        return (
            "You are a tabletop robot task planner. "
            "Convert the user's instruction into a short executable JSON task plan. "
            "The robot can only do two things: "
            "1) hover above one visible cube, "
            "2) wait for a short duration. "
            "The only valid hover targets are: "
            f"{supported_targets}. "
            "Use action='hover_target' when the step should move above an object. "
            "Use action='wait' when the robot should pause. "
            "If the user asks for unsupported actions like grasping or stacking, "
            "decompose only the observable hover sequence and mention the limitation "
            "in planning_notes. "
            "Use the scene summary to decide which objects are currently visible and grounded. "
            "Return JSON only."
        )

    def _request_plan(self, instruction_text: str) -> dict:
        api_key = self._resolve_api_key()

        if self.api_protocol == "responses":
            payload = self._build_responses_payload(instruction_text)
        elif self.api_protocol == "chat_completions":
            payload = self._build_chat_completions_payload(instruction_text)
        else:
            raise ValueError(
                f"Unsupported api_protocol={self.api_protocol!r}; use 'responses' or "
                "'chat_completions'"
            )

        client = LlmHttpClient(
            self.api_base_url, timeout=self.request_timeout_sec,
            api_key=api_key, api_key_required=self.api_key_required,
        )
        response_json = client.send(payload)

        if self.api_protocol == "responses":
            plan_text = _extract_response_text(response_json)
        else:
            plan_text = _extract_chat_completion_text(response_json)

        parsed = _extract_json_object(plan_text)
        if self.enable_rcm_actions:
            return sanitize_rcm_task_request(
                parsed,
                fallback_instruction=instruction_text,
            )
        return sanitize_plan(
            parsed,
            allow_open_vocabulary=self.open_vocabulary_targets,
            allow_grasp_actions=self.enable_grasp_actions,
            allow_rcm_actions=False,
        )

    def _plan_with_fallback(self, instruction: str) -> tuple[dict, bool]:
        try:
            plan = self._request_plan(instruction)
            if self.enable_rcm_actions:
                if plan["instruction"]:
                    return plan, False
                if not self.allow_local_fallback:
                    self.get_logger().error(
                        "[PLAN] LLM returned an empty RCM task request; local "
                        "fallback is disabled"
                    )
                    return plan, False
            if not self.enable_rcm_actions and plan["steps"]:
                return plan, False
            if not self.allow_local_fallback:
                if self.enable_rcm_actions:
                    return sanitize_rcm_task_request(
                        {
                            "instruction": instruction,
                            "objective_text": instruction,
                            "terminal_operation": "stop",
                            "verification": {
                                "decision": "REJECT",
                                "reason": "llm_returned_no_task_request",
                            },
                        }
                    ), False
                self.get_logger().error(
                    "[PLAN] LLM returned no executable steps after sanitization; local "
                    "fallback is disabled"
                )
                return {
                    "task_summary": instruction,
                    "planning_notes": (
                        "LLM returned no executable steps and local fallback is disabled."
                    ),
                    "steps": [],
                }, False
            self.get_logger().warning(
                "[PLAN] LLM returned no executable steps after sanitization; trying local fallback"
            )
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            self.get_logger().error(f"[PLAN] HTTPError {exc.code}: {detail}")
            if not self.allow_local_fallback:
                if self.enable_rcm_actions:
                    return sanitize_rcm_task_request(
                        {
                            "instruction": instruction,
                            "objective_text": instruction,
                            "terminal_operation": "stop",
                            "verification": {
                                "decision": "REJECT",
                                "reason": f"llm_http_error_{exc.code}",
                            },
                        }
                    ), False
                return {
                    "task_summary": instruction,
                    "planning_notes": f"LLM HTTPError {exc.code}; local fallback is disabled.",
                    "steps": [],
                }, False
        except Exception as exc:
            self.get_logger().error(f"[PLAN] failed: {exc}")
            if not self.allow_local_fallback:
                if self.enable_rcm_actions:
                    return sanitize_rcm_task_request(
                        {
                            "instruction": instruction,
                            "objective_text": instruction,
                            "terminal_operation": "stop",
                            "verification": {
                                "decision": "REJECT",
                                "reason": f"llm_failed:{exc}",
                            },
                        }
                    ), False
                return {
                    "task_summary": instruction,
                    "planning_notes": f"LLM planning failed: {exc}; local fallback is disabled.",
                    "steps": [],
                }, False

        fallback_plan = infer_plan_from_instruction(
            instruction,
            allow_open_vocabulary=self.open_vocabulary_targets,
            allow_grasp_actions=self.enable_grasp_actions,
            allow_rcm_actions=self.enable_rcm_actions,
        )
        if self.enable_rcm_actions:
            self.get_logger().warning("[PLAN] using local RCM task-request fallback")
            return fallback_plan, True
        if fallback_plan["steps"]:
            self.get_logger().warning(
                f"[PLAN] using local fallback with {len(fallback_plan['steps'])} steps"
            )
            return fallback_plan, True
        return fallback_plan, True

    def on_instruction(self, msg: String):
        instruction = msg.data.strip()
        if not instruction:
            return

        self.get_logger().info(f"[PLAN] instruction={instruction}")
        self._publish_status("planning")

        plan, used_fallback = self._plan_with_fallback(instruction)

        if self.enable_rcm_actions:
            if not plan.get("instruction", ""):
                self.get_logger().warning("[PLAN] empty RCM task request returned")
                self._publish_status("planning_failed: empty_rcm_task_request")
                return
            out = String()
            out.data = rcm_task_request_to_json(plan)
            self.pub_plan.publish(out)
            status = "planned_fallback" if used_fallback else "planned"
            self._publish_status(f"{status}: rcm_task_request")
            return

        if not plan["steps"]:
            self.get_logger().warning("[PLAN] no executable steps returned")
            self._publish_status("planning_failed: no_steps")
            return

        out = String()
        out.data = plan_to_json(plan)
        self.pub_plan.publish(out)
        if used_fallback:
            self._publish_status(f"planned_fallback: {len(plan['steps'])} steps")
        else:
            self._publish_status(f"planned: {len(plan['steps'])} steps")
        self.get_logger().info(f"[PLAN] published {len(plan['steps'])} steps")


def main(args=None):
    rclpy.init(args=args)
    node = None
    try:
        node = LlmTaskPlanner()
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
