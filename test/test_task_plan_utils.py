# SPDX-License-Identifier: Apache-2.0
"""Tests for deterministic task-plan safety normalization."""

import pytest

from llm_ros.task_plan_utils import (
    SURGICAL_RCM_TERMINAL_OPERATIONS,
    infer_plan_from_instruction,
    sanitize_rcm_task_request,
    scene_registry_from_json,
    scene_registry_summary,
)


def test_rcm_fallback_uses_high_level_task_request():
    task = infer_plan_from_instruction(
        "locate the port and execute a circle",
        allow_rcm_actions=True,
    )

    assert task["instruction"] == "locate the port and execute a circle"
    assert task["objective_text"] == task["instruction"]
    assert task["terminal_operation"] == "execute_rcm_circle"
    assert task["allow_alternative"] is False
    assert "steps" not in task


def test_rcm_task_sanitizer_rejects_motion_plan_shape():
    task = sanitize_rcm_task_request(
        {
            "instruction": "use the safest port",
            "objective_text": "maximize clearance",
            "terminal_operation": "execute_rcm_circle",
            "selected_candidate_id": "H4",
            "joint_positions": [1, 2, 3],
            "steps": [{"action": "execute_rcm_circle"}],
        }
    )

    assert task["instruction"] == "use the safest port"
    assert task["selected_candidate_id"] == "H4"
    assert task["terminal_operation"] in SURGICAL_RCM_TERMINAL_OPERATIONS
    assert "steps" not in task
    assert "joint_positions" not in task


def test_empty_rcm_instruction_does_not_start_motion():
    task = infer_plan_from_instruction("", allow_rcm_actions=True)

    assert task["terminal_operation"] == "stop"
    assert task["verification"]["decision"] == "REJECT"


def test_rcm_approach_constraint_is_numeric_and_bounded():
    task = sanitize_rcm_task_request(
        {
            "instruction": "use tilt 18 degrees and azimuth 450 degrees",
            "objective_text": "specified approach",
            "allow_alternative": False,
            "terminal_operation": "establish_rcm",
            "approach_constraint": {
                "mode": "preferred_cone_angle",
                "cone_half_angle_deg": 15.0,
                "preferred_tilt_deg": 18.0,
                "preferred_azimuth_deg": 450.0,
            },
        }
    )

    constraint = task["approach_constraint"]
    assert constraint["mode"] == "preferred_cone_angle"
    assert constraint["preferred_tilt_deg"] == 15.0
    assert constraint["preferred_azimuth_deg"] == 90.0


@pytest.mark.parametrize("text", ["[]", "null", "1", '"text"'])
def test_non_object_scene_input_recovers_to_empty_registry(text):
    registry = scene_registry_from_json(text)
    assert registry["objects"] == []
    assert "No scene objects" in scene_registry_summary(registry)


def test_scene_context_contains_visible_label_and_position():
    registry = scene_registry_from_json(
        '{"objects":[{"label":"red cube","visible":true,"confidence":1.0,'
        '"position_world":{"x":0.4,"y":0.0,"z":0.1}}]}'
    )
    assert "Visible objects: red cube at (0.40, 0.00, 0.10)" in scene_registry_summary(registry)
