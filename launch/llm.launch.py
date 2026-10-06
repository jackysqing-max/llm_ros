# SPDX-License-Identifier: Apache-2.0
"""Launch either the generic LLM client or the original task planner."""

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    """Resolve a mode-specific configuration, preserving custom YAML settings."""
    arguments = [
        DeclareLaunchArgument("mode", default_value="client", choices=["client", "planner"]),
        DeclareLaunchArgument("backend", default_value="qwen3", choices=["qwen3", "responses"]),
        DeclareLaunchArgument("params_file", default_value=""),
        DeclareLaunchArgument("namespace", default_value=""),
    ]
    overrides = {
        "api_base_url": str, "api_protocol": str, "model": str,
        "api_key_env_var": str, "api_key_required": bool, "request_timeout_sec": float,
    }
    arguments += [DeclareLaunchArgument(name, default_value="") for name in overrides]

    def launch_node(context):
        mode = LaunchConfiguration("mode").perform(context)
        backend = LaunchConfiguration("backend").perform(context)
        config = LaunchConfiguration("params_file").perform(context)
        if not config:
            config = get_package_share_directory("llm_ros") + f"/config/{mode}_{backend}.yaml"
        parameters = {}
        for name, value_type in overrides.items():
            if LaunchConfiguration(name).perform(context):
                parameters[name] = ParameterValue(LaunchConfiguration(name), value_type=value_type)
        executable = "llm_client_node" if mode == "client" else "llm_task_planner_node"
        return [Node(
            package="llm_ros", executable=executable, name=executable, output="screen",
            namespace=LaunchConfiguration("namespace"), parameters=[config, parameters],
        )]

    return LaunchDescription(arguments + [OpaqueFunction(function=launch_node)])
