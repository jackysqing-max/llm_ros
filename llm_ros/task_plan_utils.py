# SPDX-License-Identifier: Apache-2.0
"""Common task-plan schema and validation helpers for LLM execution."""

from __future__ import annotations

import json
import re


SUPPORTED_ACTIONS = ("hover_target", "wait", "grasp_target", "release_gripper")
DEFAULT_ACTIONS = ("hover_target", "wait")
GRASP_ACTIONS = ("grasp_target", "release_gripper")
SURGICAL_RCM_ACTIONS = (
    "localize_rcm_port",
    "align_tool_axis",
    "establish_rcm",
    "execute_rcm_circle",
)
SURGICAL_RCM_TERMINAL_OPERATIONS = (
    "localize_only",
    "establish_rcm",
    "execute_rcm_circle",
    "hold",
    "retract",
    "stop",
)
SURGICAL_RCM_STEP_DEFAULTS = {
    "localize_rcm_port": {
        "description": "Locate and lock the circular port center and insertion axis.",
        "dwell_sec": 0.5,
        "insertion_depth_m": 0.0,
        "trajectory_radius_m": 0.0,
        "trajectory_cycles": 0.0,
    },
    "align_tool_axis": {
        "description": "Align the surgical tool axis with the locked insertion axis.",
        "dwell_sec": 0.5,
        "insertion_depth_m": 0.0,
        "trajectory_radius_m": 0.0,
        "trajectory_cycles": 0.0,
    },
    "establish_rcm": {
        "description": (
            "Insert through the port and establish the port center as "
            "the fixed RCM point."
        ),
        "dwell_sec": 0.8,
        "insertion_depth_m": 0.077,
        "trajectory_radius_m": 0.0,
        "trajectory_cycles": 0.0,
    },
    "execute_rcm_circle": {
        "description": (
            "Follow a circular tool-tip trajectory while keeping the "
            "RCM point fixed."
        ),
        "dwell_sec": 0.0,
        "insertion_depth_m": 0.077,
        "trajectory_radius_m": 0.020,
        "trajectory_cycles": 1.0,
    },
}
SUPPORTED_TARGET_PROMPTS = (
    "red cube",
    "green cube",
    "blue cube",
    "yellow cube",
)


PLAN_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "task_summary": {"type": "string"},
        "planning_notes": {"type": "string"},
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "step_index": {"type": "integer"},
                    "action": {
                        "type": "string",
                        "enum": list(SUPPORTED_ACTIONS),
                    },
                    "target_prompt": {"type": "string"},
                    "description": {"type": "string"},
                    "success_radius_m": {"type": "number"},
                    "dwell_sec": {"type": "number"},
                    "wait_sec": {"type": "number"},
                },
                "required": [
                    "step_index",
                    "action",
                    "target_prompt",
                    "description",
                    "success_radius_m",
                    "dwell_sec",
                    "wait_sec",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": ["task_summary", "planning_notes", "steps"],
    "additionalProperties": False,
}

LEGACY_SURGICAL_RCM_PLAN_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "task_summary": {"type": "string"},
        "planning_notes": {"type": "string"},
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "step_index": {"type": "integer"},
                    "action": {
                        "type": "string",
                        "enum": list(SURGICAL_RCM_ACTIONS),
                    },
                },
                "required": [
                    "step_index",
                    "action",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": ["task_summary", "planning_notes", "steps"],
    "additionalProperties": False,
}

SURGICAL_RCM_TASK_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "instruction": {"type": "string"},
        "objective_text": {"type": "string"},
        "selected_candidate_id": {"type": ["string", "null"]},
        "exclusions": {
            "type": "array",
            "items": {"type": "string"},
        },
        "allow_alternative": {"type": "boolean"},
        "terminal_operation": {
            "type": "string",
            "enum": list(SURGICAL_RCM_TERMINAL_OPERATIONS),
        },
        "requested_insertion_depth_m": {"type": "number"},
        "approach_preference": {"type": "string"},
        "approach_constraint": {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["auto_closest_reachable", "preferred_cone_angle"],
                },
                "cone_half_angle_deg": {"type": "number"},
                "preferred_tilt_deg": {"type": ["number", "null"]},
                "preferred_azimuth_deg": {"type": ["number", "null"]},
            },
            "required": [
                "mode",
                "cone_half_angle_deg",
                "preferred_tilt_deg",
                "preferred_azimuth_deg",
            ],
            "additionalProperties": False,
        },
        "verification": {
            "type": "object",
            "additionalProperties": True,
        },
    },
    "required": [
        "instruction",
        "objective_text",
        "allow_alternative",
        "terminal_operation",
        "approach_constraint",
    ],
    "additionalProperties": False,
}


_TARGET_SYNONYMS = {
    "red cube": ("red cube", "red", "red block", "红", "红色", "红色方块", "红色方块儿"),
    "green cube": ("green cube", "green", "green block", "绿", "绿色", "绿色方块"),
    "blue cube": ("blue cube", "blue", "blue block", "蓝", "蓝色", "蓝色方块"),
    "yellow cube": ("yellow cube", "yellow", "yellow block", "黄", "黄色", "黄色方块"),
}

_ALIAS_TO_CANONICAL = {
    alias.lower(): canonical
    for canonical, aliases in _TARGET_SYNONYMS.items()
    for alias in aliases
}
_TARGET_PATTERN = re.compile(
    "|".join(
        re.escape(alias)
        for alias in sorted(_ALIAS_TO_CANONICAL, key=len, reverse=True)
    ),
    flags=re.IGNORECASE,
)
_OPEN_VOCAB_PREFIX_PATTERN = re.compile(
    r"^(?:the|a|an|this|that|these|those|my|your)\s+",
    flags=re.IGNORECASE,
)
_OPEN_VOCAB_CN_PREFIX_PATTERN = re.compile(
    r"^(?:一个|一把|一只|一台|一本|一部|一张|这个|那个|这把|那把|我的|你的)",
    flags=re.IGNORECASE,
)
_OPEN_VOCAB_CLAUSE_SPLIT_PATTERN = re.compile(
    r"\s*(?:\bthen\b|\band then\b|之后|然后|接着|再|；|;)\s*",
    flags=re.IGNORECASE,
)
_OPEN_VOCAB_LIST_SPLIT_PATTERN = re.compile(
    r"\s*(?:,|，|、|\band\b|和)\s*",
    flags=re.IGNORECASE,
)
_OPEN_VOCAB_WAIT_PATTERN = re.compile(
    r"(?:\bwait\b|等待|停留|暂停)",
    flags=re.IGNORECASE,
)
_OPEN_VOCAB_GRASP_PATTERN = re.compile(
    r"(?:\bgrasp\b|\bgrab\b|\bpick up\b|\bpick\b|\bhold\b|\bclamp\b|抓取|抓住|夹住|夹取|拿起)",
    flags=re.IGNORECASE,
)
_OPEN_VOCAB_RELEASE_PATTERN = re.compile(
    r"(?:\brelease\b|\bopen\b|\bdrop\b|\bput down\b|释放|松开|放下|张开)",
    flags=re.IGNORECASE,
)
_OPEN_VOCAB_WAIT_SECONDS_PATTERN = re.compile(
    r"(?P<value>\d+(?:\.\d+)?)\s*(?:seconds?|secs?|s|秒)",
    flags=re.IGNORECASE,
)
_OPEN_VOCAB_TARGET_PATTERNS = (
    re.compile(
        r"(?:hover above|hover over|move above|move over|go to|move to|approach|track|follow|"
        r"find|locate|look for|search for|target|grasp|grab|pick up|pick|"
        r"hold|clamp)\s+(?P<target>.+)$",
        flags=re.IGNORECASE,
    ),
    re.compile(
        r"(?:移动到|移到|去到|去|悬停到|悬停在|跟踪|追踪|找到|寻找|查找|定位|抓取|抓住|夹住|夹取|拿起)\s*(?P<target>.+)$",
        flags=re.IGNORECASE,
    ),
)
_OPEN_VOCAB_PLACE_PATTERNS = (
    re.compile(
        r"^(?:pick up|pick|grasp|grab|hold|clamp)\s+(?P<object>.+?)\s+"
        r"(?:and\s+)?(?:then\s+)?(?:place|put|move)\s+"
        r"(?:it|them|the object|the item)?\s*"
        r"(?:in|into|onto|on|to)\s+(?P<destination>.+)$",
        flags=re.IGNORECASE,
    ),
    re.compile(
        r"^(?:put|place|move)\s+(?P<object>.+?)\s+(?:in|into|onto|on|to)\s+(?P<destination>.+)$",
        flags=re.IGNORECASE,
    ),
    re.compile(
        r"^(?:把)?(?P<object>.+?)(?:放到|放进|放入|放在|放至|移到|移动到)(?P<destination>.+?)(?:里|中|上|内)?$",
        flags=re.IGNORECASE,
    ),
)
_OPEN_VOCAB_GRASP_RELEASE_PATTERN = re.compile(
    r"^(?:pick up|pick|grasp|grab|hold|clamp)\s+(?P<object>.+?)\s+"
    r"(?:(?:and\s+)?then\s+|and\s+)?(?:release|drop|put down)\s*"
    r"(?:it|them|the object|the item)?$",
    flags=re.IGNORECASE,
)
_OPEN_VOCAB_SPECIAL_PROMPTS = {
    "剪刀": "left silver surgical instrument",
    "左边剪刀": "left silver surgical instrument",
    "左侧剪刀": "left silver surgical instrument",
    "左边的剪刀": "left silver surgical instrument",
    "左侧的剪刀": "left silver surgical instrument",
    "器械": "left silver surgical instrument",
    "手术器械": "left silver surgical instrument",
    "左边手术器械": "left silver surgical instrument",
    "左边的手术器械": "left silver surgical instrument",
    "盘子": "white sorting tray center",
    "盘": "white sorting tray center",
    "托盘": "white sorting tray center",
    "白色托盘": "white sorting tray center",
    "盘子中心": "white sorting tray center",
    "托盘中心": "white sorting tray center",
    "tray": "white sorting tray center",
    "plate": "white sorting tray center",
    "sorting tray": "white sorting tray center",
    "white sorting tray": "white sorting tray center",
    "tray center": "white sorting tray center",
    "sorting tray center": "white sorting tray center",
}


def _canonicalize_open_prompt(raw_prompt: str) -> str:
    """Reduce a free-form object description to a concise prompt string."""
    text = (raw_prompt or "").strip().lower()
    text = text.strip(" \t\r\n,.;:!?\"'`")
    text = re.sub(r"\s+", " ", text)
    text = _OPEN_VOCAB_PREFIX_PATTERN.sub("", text)
    text = _OPEN_VOCAB_CN_PREFIX_PATTERN.sub("", text)
    text = text.strip(" \t\r\n,.;:!?\"'`里中上内")
    if text in _OPEN_VOCAB_SPECIAL_PROMPTS:
        return _OPEN_VOCAB_SPECIAL_PROMPTS[text]
    return text.strip()


def _renumber_steps(steps: list[dict]) -> list[dict]:
    for index, step in enumerate(steps, start=1):
        step["step_index"] = index
    return steps


def _looks_like_release_destination(prompt: str) -> bool:
    text = (prompt or "").strip().lower()
    if not text:
        return False
    return any(
        token in text
        for token in (
            "tray",
            "plate",
            "container",
            "bowl",
            "dish",
            "盘",
            "托盘",
        )
    )


def _repair_release_destination_order(steps: list[dict]) -> list[dict]:
    """Move an early release after the following destination hover step."""
    repaired = []
    pending_release = None
    holding_object = False

    for step in steps:
        action = step.get("action")
        if action == "grasp_target":
            if pending_release is not None:
                repaired.append(pending_release)
                pending_release = None
                holding_object = False
            repaired.append(step)
            holding_object = True
            continue

        if action == "release_gripper" and holding_object:
            if pending_release is None:
                pending_release = step
            else:
                repaired.append(pending_release)
                pending_release = step
            continue

        if pending_release is not None and action == "hover_target":
            repaired.append(step)
            repaired.append(pending_release)
            pending_release = None
            holding_object = False
            continue

        if pending_release is not None and action == "wait":
            repaired.append(step)
            continue

        if pending_release is not None:
            repaired.append(pending_release)
            pending_release = None
            holding_object = False
        repaired.append(step)

    if pending_release is not None:
        repaired.append(pending_release)

    return _renumber_steps(repaired)


def _is_medical_grasp_target(prompt: str) -> bool:
    text = (prompt or "").strip().lower()
    return any(token in text for token in ("surgical instrument", "scissors", "剪刀", "器械"))


def _insert_default_medical_release_destination(steps: list[dict]) -> list[dict]:
    """Treat a bare medical grasp+release as release into the default tray."""
    out = []
    holding_medical_target = False
    for step in steps:
        action = step.get("action")
        if action == "grasp_target":
            holding_medical_target = _is_medical_grasp_target(step.get("target_prompt", ""))
            out.append(step)
            continue
        if action == "hover_target":
            holding_medical_target = False
            out.append(step)
            continue
        if action == "release_gripper" and holding_medical_target:
            out.append(
                {
                    "step_index": int(step.get("step_index", len(out) + 1)),
                    "action": "hover_target",
                    "target_prompt": "white sorting tray center",
                    "description": "move above white sorting tray center",
                    "success_radius_m": 0.0,
                    "dwell_sec": 0.8,
                    "wait_sec": 0.0,
                }
            )
            out.append(step)
            holding_medical_target = False
            continue
        out.append(step)
    return _renumber_steps(out)


def normalize_target_prompt(raw_prompt: str, *, allow_open_vocabulary: bool = False) -> str:
    """Normalize target prompts for either closed-set or open-vocabulary demos."""
    text = _canonicalize_open_prompt(raw_prompt)
    if allow_open_vocabulary:
        return text
    for canonical, aliases in _TARGET_SYNONYMS.items():
        if any(alias in text for alias in aliases):
            return canonical
    if text in SUPPORTED_TARGET_PROMPTS:
        return text
    return ""


def _positive_float(value, default: float) -> float:
    try:
        value = float(value)
    except Exception:
        return float(default)
    if value < 0.0:
        return float(default)
    return value


def _positive_or_default(value, default: float) -> float:
    """Use the RCM primitive default when a positive field was sanitized to zero."""
    try:
        value = float(value)
    except Exception:
        return float(default)
    default = float(default)
    if value < 0.0:
        return default
    if value == 0.0 and default > 0.0:
        return default
    return value


def _normalize_terminal_operation(value: str) -> str:
    operation = str(value or "").strip().lower()
    aliases = {
        "localize": "localize_only",
        "localize_rcm_port": "localize_only",
        "locate": "localize_only",
        "establish": "establish_rcm",
        "align_tool_axis": "establish_rcm",
        "execute": "execute_rcm_circle",
        "execute_circle": "execute_rcm_circle",
        "execute_rcm": "execute_rcm_circle",
        "execute_rcm_trajectory": "execute_rcm_circle",
        "circle": "execute_rcm_circle",
        "execute_rcm_circle": "execute_rcm_circle",
        "hold": "hold",
        "retract": "retract",
        "stop": "stop",
    }
    operation = aliases.get(operation, operation)
    if operation not in SURGICAL_RCM_TERMINAL_OPERATIONS:
        return "execute_rcm_circle"
    return operation


def sanitize_rcm_task_request(raw_task: dict, *, fallback_instruction: str = "") -> dict:
    """Normalize an open semantic RCM request without expanding it into stages."""
    task = raw_task if isinstance(raw_task, dict) else {}
    instruction = str(
        task.get(
            "instruction",
            task.get("original_instruction", task.get("task_summary", fallback_instruction)),
        )
    ).strip()
    objective_text = str(task.get("objective_text", instruction)).strip() or instruction
    exclusions = task.get("exclusions", [])
    if not isinstance(exclusions, list):
        exclusions = []
    verification = task.get("verification", {})
    if not isinstance(verification, dict):
        verification = {}
    selected_candidate_id = task.get("selected_candidate_id", None)
    if selected_candidate_id is not None:
        selected_candidate_id = str(selected_candidate_id).strip() or None
    raw_constraint = task.get("approach_constraint", {})
    if not isinstance(raw_constraint, dict):
        raw_constraint = {}
    mode = str(
        raw_constraint.get("mode", "auto_closest_reachable")
    ).strip()
    if mode not in {"auto_closest_reachable", "preferred_cone_angle"}:
        mode = "auto_closest_reachable"
    half_angle_deg = min(
        max(_positive_float(raw_constraint.get("cone_half_angle_deg", 20.0), 20.0), 1.0),
        45.0,
    )
    preferred_tilt = raw_constraint.get("preferred_tilt_deg", None)
    preferred_azimuth = raw_constraint.get("preferred_azimuth_deg", None)
    try:
        preferred_tilt = None if preferred_tilt is None else float(preferred_tilt)
        preferred_azimuth = None if preferred_azimuth is None else float(preferred_azimuth)
    except (TypeError, ValueError):
        preferred_tilt = None
        preferred_azimuth = None
    if (
        mode != "preferred_cone_angle"
        or preferred_tilt is None
        or preferred_azimuth is None
    ):
        mode = "auto_closest_reachable"
        preferred_tilt = None
        preferred_azimuth = None
    else:
        preferred_tilt = min(max(preferred_tilt, 0.0), half_angle_deg)
        preferred_azimuth = preferred_azimuth % 360.0
    return {
        "instruction": instruction,
        "objective_text": objective_text,
        "selected_candidate_id": selected_candidate_id,
        "exclusions": [str(item).strip() for item in exclusions if str(item).strip()],
        "allow_alternative": bool(task.get("allow_alternative", False)),
        "terminal_operation": _normalize_terminal_operation(
            task.get("terminal_operation", "execute_rcm_circle")
        ),
        "requested_insertion_depth_m": _positive_float(
            task.get("requested_insertion_depth_m", 0.0),
            0.0,
        ),
        "approach_preference": str(task.get("approach_preference", "")).strip(),
        "approach_constraint": {
            "mode": mode,
            "cone_half_angle_deg": half_angle_deg,
            "preferred_tilt_deg": preferred_tilt,
            "preferred_azimuth_deg": preferred_azimuth,
        },
        "verification": verification,
    }


def rcm_task_request_to_json(task: dict) -> str:
    return json.dumps(sanitize_rcm_task_request(task), ensure_ascii=False)


def rcm_task_request_from_json(text: str) -> dict:
    return sanitize_rcm_task_request(json.loads(text))


def _canonicalize_surgical_rcm_steps(steps: list[dict]) -> list[dict]:
    if not steps:
        return []

    by_action = {
        str(step.get("action", "")).strip().lower(): step
        for step in steps
        if isinstance(step, dict)
    }
    canonical = []
    for index, action in enumerate(SURGICAL_RCM_ACTIONS, start=1):
        default = SURGICAL_RCM_STEP_DEFAULTS[action]
        source = by_action.get(action, {})
        source_prompt = str(source.get("target_prompt", "") or "").strip()
        source_description = str(source.get("description", "") or "").strip()
        canonical.append(
            {
                "step_index": index,
                "action": action,
                "target_prompt": (
                    (source_prompt or "circular hole")
                    if action != "execute_rcm_circle"
                    else ""
                ),
                "description": source_description or default["description"],
                "success_radius_m": _positive_or_default(
                    source.get("success_radius_m", 0.006),
                    0.006,
                ),
                "dwell_sec": _positive_or_default(
                    source.get("dwell_sec", default["dwell_sec"]),
                    default["dwell_sec"],
                ),
                "wait_sec": 0.0,
                "insertion_depth_m": _positive_or_default(
                    source.get("insertion_depth_m", default["insertion_depth_m"]),
                    default["insertion_depth_m"],
                ),
                "trajectory_radius_m": _positive_or_default(
                    source.get("trajectory_radius_m", default["trajectory_radius_m"]),
                    default["trajectory_radius_m"],
                ),
                "trajectory_cycles": _positive_or_default(
                    source.get("trajectory_cycles", default["trajectory_cycles"]),
                    default["trajectory_cycles"],
                ),
            }
        )
    return canonical


def sanitize_plan(
    raw_plan: dict,
    *,
    allow_open_vocabulary: bool = False,
    allow_grasp_actions: bool = False,
    allow_rcm_actions: bool = False,
) -> dict:
    """Normalize model output into a predictable execution plan."""
    plan = raw_plan if isinstance(raw_plan, dict) else {}
    allowed_actions = (
        set(SURGICAL_RCM_ACTIONS)
        if allow_rcm_actions
        else set(DEFAULT_ACTIONS)
    )
    if allow_grasp_actions and not allow_rcm_actions:
        allowed_actions.update(GRASP_ACTIONS)

    steps = []
    for fallback_index, raw_step in enumerate(plan.get("steps", []), start=1):
        if not isinstance(raw_step, dict):
            continue

        action = str(raw_step.get("action", "hover_target")).strip().lower()
        if action not in allowed_actions:
            action = (
                "localize_rcm_port"
                if allow_rcm_actions
                else "hover_target"
            )

        description = str(raw_step.get("description", "")).strip()
        step_index = raw_step.get("step_index", fallback_index)
        try:
            step_index = int(step_index)
        except Exception:
            step_index = fallback_index
        if step_index < 1:
            step_index = fallback_index

        target_prompt = normalize_target_prompt(
            str(raw_step.get("target_prompt", "")),
            allow_open_vocabulary=(
                allow_open_vocabulary or allow_rcm_actions
            ),
        )
        success_radius_m = _positive_float(raw_step.get("success_radius_m", 0.0), 0.0)
        dwell_sec = _positive_float(raw_step.get("dwell_sec", 1.0), 1.0)
        wait_sec = _positive_float(raw_step.get("wait_sec", 1.0), 1.0)

        if action in SURGICAL_RCM_ACTIONS:
            if action == "execute_rcm_circle":
                target_prompt = ""
            elif not target_prompt:
                target_prompt = "circular hole"
        elif action == "wait":
            target_prompt = ""
            success_radius_m = 0.0
            dwell_sec = 0.0
        elif action == "release_gripper":
            release_destination_prompt = target_prompt
            if _looks_like_release_destination(release_destination_prompt):
                steps.append(
                    {
                        "step_index": step_index,
                        "action": "hover_target",
                        "target_prompt": release_destination_prompt,
                        "description": f"move above {release_destination_prompt}",
                        "success_radius_m": 0.0,
                        "dwell_sec": max(dwell_sec, 0.8),
                        "wait_sec": 0.0,
                    }
                )
            target_prompt = ""
            success_radius_m = 0.0
            dwell_sec = 0.0
        elif not target_prompt:
            # Drop malformed target steps instead of sending the robot to nowhere.
            continue

        sanitized_step = {
            "step_index": step_index,
            "action": action,
            "target_prompt": target_prompt,
            "description": description or f"{action} {target_prompt}".strip(),
            "success_radius_m": success_radius_m,
            "dwell_sec": dwell_sec,
            "wait_sec": wait_sec,
        }
        if allow_rcm_actions:
            sanitized_step.update(
                {
                    "insertion_depth_m": _positive_float(
                        raw_step.get("insertion_depth_m", 0.0),
                        0.0,
                    ),
                    "trajectory_radius_m": _positive_float(
                        raw_step.get("trajectory_radius_m", 0.0),
                        0.0,
                    ),
                    "trajectory_cycles": _positive_float(
                        raw_step.get("trajectory_cycles", 0.0),
                        0.0,
                    ),
                }
            )
        steps.append(sanitized_step)

    steps.sort(key=lambda item: item["step_index"])
    if allow_rcm_actions:
        steps = _canonicalize_surgical_rcm_steps(steps)
    else:
        steps = _repair_release_destination_order(steps)
    if allow_open_vocabulary and allow_grasp_actions and not allow_rcm_actions:
        steps = _insert_default_medical_release_destination(steps)
    return {
        "task_summary": str(plan.get("task_summary", "LLM task")).strip() or "LLM task",
        "planning_notes": str(plan.get("planning_notes", "")).strip(),
        "steps": steps,
    }


def _extract_wait_seconds(clause_text: str) -> float:
    match = _OPEN_VOCAB_WAIT_SECONDS_PATTERN.search(clause_text or "")
    if not match:
        return 1.0
    return _positive_float(match.group("value"), 1.0)


def _split_open_target_list(raw_target_text: str) -> list[str]:
    pieces = []
    for raw_piece in _OPEN_VOCAB_LIST_SPLIT_PATTERN.split(raw_target_text or ""):
        prompt = _canonicalize_open_prompt(raw_piece)
        if prompt:
            pieces.append(prompt)
    return pieces


def _extract_open_vocab_targets_from_clause(clause_text: str) -> list[str]:
    normalized_clause = _canonicalize_open_prompt(clause_text)
    if not normalized_clause:
        return []

    for pattern in _OPEN_VOCAB_TARGET_PATTERNS:
        match = pattern.search(normalized_clause)
        if not match:
            continue
        return _split_open_target_list(match.group("target"))

    if len(normalized_clause.split()) <= 5:
        return [normalized_clause]
    return []


def _extract_open_vocab_place_targets(instruction_text: str):
    text = (instruction_text or "").strip()
    if not text:
        return None
    normalized_text = re.sub(r"\s+", " ", text.strip().lower())
    for pattern in _OPEN_VOCAB_PLACE_PATTERNS:
        match = pattern.search(normalized_text)
        if not match:
            continue
        object_prompt = _canonicalize_open_prompt(match.group("object"))
        destination_prompt = _canonicalize_open_prompt(match.group("destination"))
        if object_prompt and destination_prompt:
            return object_prompt, destination_prompt
    return None


def _infer_open_vocabulary_plan_from_instruction(
    instruction_text: str,
    *,
    allow_grasp_actions: bool = False,
) -> dict:
    """Build a best-effort hover plan from open-vocabulary object phrases."""
    text = (instruction_text or "").strip()
    if not text:
        return {
            "task_summary": "Fallback task",
            "planning_notes": "The instruction was empty.",
            "steps": [],
        }

    clauses = [
        clause.strip()
        for clause in _OPEN_VOCAB_CLAUSE_SPLIT_PATTERN.split(text)
        if clause.strip()
    ]
    if not clauses:
        clauses = [text]

    if allow_grasp_actions:
        place_targets = _extract_open_vocab_place_targets(text)
        if place_targets is not None:
            object_prompt, destination_prompt = place_targets
            return sanitize_plan(
                {
                    "task_summary": text,
                    "planning_notes": "Generated locally as a pick-and-place sequence.",
                    "steps": [
                        {
                            "step_index": 1,
                            "action": "grasp_target",
                            "target_prompt": object_prompt,
                            "description": f"grasp {object_prompt}",
                            "success_radius_m": 0.0,
                            "dwell_sec": 1.0,
                            "wait_sec": 0.0,
                        },
                        {
                            "step_index": 2,
                            "action": "hover_target",
                            "target_prompt": destination_prompt,
                            "description": f"move above {destination_prompt}",
                            "success_radius_m": 0.0,
                            "dwell_sec": 0.8,
                            "wait_sec": 0.0,
                        },
                        {
                            "step_index": 3,
                            "action": "release_gripper",
                            "target_prompt": "",
                            "description": "release gripper at destination",
                            "success_radius_m": 0.0,
                            "dwell_sec": 0.0,
                            "wait_sec": 0.8,
                        },
                    ],
                },
                allow_open_vocabulary=True,
                allow_grasp_actions=True,
            )

        grasp_release_match = _OPEN_VOCAB_GRASP_RELEASE_PATTERN.search(
            re.sub(r"\s+", " ", text.strip().lower())
        )
        if grasp_release_match:
            object_prompt = _canonicalize_open_prompt(grasp_release_match.group("object"))
            return sanitize_plan(
                {
                    "task_summary": text,
                    "planning_notes": "Generated locally as a grasp-and-release sequence.",
                    "steps": [
                        {
                            "step_index": 1,
                            "action": "grasp_target",
                            "target_prompt": object_prompt,
                            "description": f"grasp {object_prompt}",
                            "success_radius_m": 0.0,
                            "dwell_sec": 1.0,
                            "wait_sec": 0.0,
                        },
                        {
                            "step_index": 2,
                            "action": "release_gripper",
                            "target_prompt": "",
                            "description": "release gripper",
                            "success_radius_m": 0.0,
                            "dwell_sec": 0.0,
                            "wait_sec": 0.8,
                        },
                    ],
                },
                allow_open_vocabulary=True,
                allow_grasp_actions=True,
            )

    steps = []
    step_index = 1

    for clause in clauses:
        if allow_grasp_actions and _OPEN_VOCAB_RELEASE_PATTERN.search(clause):
            steps.append(
                {
                    "step_index": step_index,
                    "action": "release_gripper",
                    "target_prompt": "",
                    "description": "release gripper",
                    "success_radius_m": 0.0,
                    "dwell_sec": 0.0,
                    "wait_sec": 1.0,
                }
            )
            step_index += 1
            continue

        if _OPEN_VOCAB_WAIT_PATTERN.search(clause):
            steps.append(
                {
                    "step_index": step_index,
                    "action": "wait",
                    "target_prompt": "",
                    "description": f"wait for {_extract_wait_seconds(clause):.1f} seconds",
                    "success_radius_m": 0.0,
                    "dwell_sec": 0.0,
                    "wait_sec": _extract_wait_seconds(clause),
                }
            )
            step_index += 1
            continue

        action = "hover_target"
        if allow_grasp_actions and _OPEN_VOCAB_GRASP_PATTERN.search(clause):
            action = "grasp_target"

        targets = _extract_open_vocab_targets_from_clause(clause)
        for target_prompt in targets:
            steps.append(
                {
                    "step_index": step_index,
                    "action": action,
                    "target_prompt": target_prompt,
                    "description": (
                        f"grasp {target_prompt}"
                        if action == "grasp_target"
                        else f"hover above {target_prompt}"
                    ),
                    "success_radius_m": 0.0,
                    "dwell_sec": 1.0,
                    "wait_sec": 0.0,
                }
            )
            step_index += 1

    if not steps:
        return {
            "task_summary": text,
            "planning_notes": "No target object phrase could be extracted from the instruction.",
            "steps": [],
        }

    return sanitize_plan(
        {
            "task_summary": text,
            "planning_notes": "Generated locally from open-vocabulary object phrases.",
            "steps": steps,
        },
        allow_open_vocabulary=True,
        allow_grasp_actions=allow_grasp_actions,
    )


def _infer_surgical_rcm_plan_from_instruction(
    instruction_text: str,
) -> dict:
    text = (instruction_text or "").strip()
    if not text:
        return sanitize_rcm_task_request(
            {
                "instruction": "",
                "objective_text": "",
                "terminal_operation": "stop",
                "verification": {"decision": "REJECT", "reason": "empty_instruction"},
            }
        )
    return sanitize_rcm_task_request(
        {
            "instruction": text,
            "objective_text": text,
            "allow_alternative": False,
            "terminal_operation": "execute_rcm_circle",
            "verification": {"decision": "PENDING"},
        }
    )


def infer_plan_from_instruction(
    instruction_text: str,
    *,
    allow_open_vocabulary: bool = False,
    allow_grasp_actions: bool = False,
    allow_rcm_actions: bool = False,
) -> dict:
    """
    Build a deterministic plan from a natural-language instruction.

    This fallback keeps the demo usable when the remote planner is unavailable.
    """
    if allow_rcm_actions:
        return _infer_surgical_rcm_plan_from_instruction(instruction_text)
    if allow_open_vocabulary:
        return _infer_open_vocabulary_plan_from_instruction(
            instruction_text,
            allow_grasp_actions=allow_grasp_actions,
        )

    text = (instruction_text or "").strip()
    lowered = text.lower()
    matches = []
    for match in _TARGET_PATTERN.finditer(lowered):
        canonical = _ALIAS_TO_CANONICAL.get(match.group(0).lower())
        if canonical:
            matches.append((match.start(), canonical))

    ordered_targets = [canonical for _pos, canonical in sorted(matches, key=lambda item: item[0])]
    if not ordered_targets:
        return {
            "task_summary": "Fallback task",
            "planning_notes": "No supported tabletop target was found in the instruction.",
            "steps": [],
        }

    steps = []
    for step_index, target_prompt in enumerate(ordered_targets, start=1):
        steps.append(
            {
                "step_index": step_index,
                "action": "hover_target",
                "target_prompt": target_prompt,
                "description": f"hover above {target_prompt}",
                "success_radius_m": 0.0,
                "dwell_sec": 1.0,
                "wait_sec": 0.0,
            }
        )

    return sanitize_plan(
        {
            "task_summary": text if text else "Fallback task",
            "planning_notes": "Generated locally from ordered color mentions.",
            "steps": steps,
        },
        allow_open_vocabulary=False,
        allow_grasp_actions=allow_grasp_actions,
    )


def plan_to_json(plan: dict) -> str:
    return json.dumps(plan, ensure_ascii=False)


def plan_from_json(
    text: str,
    *,
    allow_open_vocabulary: bool = False,
    allow_grasp_actions: bool = False,
    allow_rcm_actions: bool = False,
) -> dict:
    if allow_rcm_actions:
        return rcm_task_request_from_json(text)
    return sanitize_plan(
        json.loads(text),
        allow_open_vocabulary=allow_open_vocabulary,
        allow_grasp_actions=allow_grasp_actions,
        allow_rcm_actions=allow_rcm_actions,
    )


def scene_registry_from_json(text: str) -> dict:
    """Parse the scene registry JSON published by the object-registry node."""
    try:
        data = json.loads(text)
    except Exception:
        return {"target_frame": "world", "updated_at_sec": 0.0, "objects": []}

    if not isinstance(data, dict):
        return {"target_frame": "world", "updated_at_sec": 0.0, "objects": []}

    objects = data.get("objects", [])
    if not isinstance(objects, list):
        objects = []

    return {
        "target_frame": str(data.get("target_frame", "world")),
        "updated_at_sec": _positive_float(data.get("updated_at_sec", 0.0), 0.0),
        "objects": [obj for obj in objects if isinstance(obj, dict)],
    }


def scene_registry_summary(scene_registry: dict, max_objects: int = 8) -> str:
    """Render a compact scene summary for planner prompts."""
    objects = [obj for obj in scene_registry.get("objects", []) if isinstance(obj, dict)]
    if not objects:
        return "No scene objects have been observed yet."

    visible_objects = [obj for obj in objects if bool(obj.get("visible", False))]
    hidden_objects = [obj for obj in objects if not bool(obj.get("visible", False))]

    def _format_object(obj: dict) -> str:
        label = str(obj.get("label", "object")).strip() or "object"
        score = _positive_float(obj.get("confidence", 0.0), 0.0)
        world = obj.get("position_world") if isinstance(obj.get("position_world"), dict) else {}
        if {"x", "y", "z"} <= set(world):
            try:
                return (
                    f"{label} at "
                    f"({float(world['x']):.2f}, {float(world['y']):.2f}, {float(world['z']):.2f}) "
                    f"score={score:.2f}"
                )
            except Exception:
                pass
        age_sec = _positive_float(obj.get("last_seen_age_sec", 0.0), 0.0)
        return f"{label} score={score:.2f} age={age_sec:.1f}s"

    parts = []
    if visible_objects:
        visible_text = "; ".join(_format_object(obj) for obj in visible_objects[:max_objects])
        parts.append(f"Visible objects: {visible_text}.")
    else:
        parts.append("Visible objects: none.")

    if hidden_objects:
        hidden_text = ", ".join(
            str(obj.get("label", "object")).strip() or "object"
            for obj in hidden_objects[:max_objects]
        )
        parts.append(f"Previously observed objects: {hidden_text}.")

    return " ".join(parts)
