# SPDX-License-Identifier: Apache-2.0
"""Start an isolated ROS LLM bridge and a one-shot chat application."""

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, EmitEvent, OpaqueFunction, RegisterEventHandler
from launch.event_handlers import OnProcessExit
from launch.events import Shutdown
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    arguments = [
        DeclareLaunchArgument("prompt", default_value="Explain what a ROS 2 node is in one sentence."),
        DeclareLaunchArgument("params_file", default_value=(
            get_package_share_directory("llm_ros") + "/config/client_qwen3.yaml"
        )),
        DeclareLaunchArgument("api_base_url", default_value=""),
        DeclareLaunchArgument("model", default_value=""),
        DeclareLaunchArgument("topic_prefix", default_value="/llm_demo"),
        DeclareLaunchArgument("response_timeout_sec", default_value="120.0"),
        DeclareLaunchArgument("discovery_timeout_sec", default_value="10.0"),
    ]

    def start_demo(context):
        prefix = LaunchConfiguration("topic_prefix").perform(context).rstrip("/")
        if not prefix.startswith("/") or prefix == "":
            raise ValueError("topic_prefix must be an absolute, non-root ROS topic prefix")
        topics = {name: f"{prefix}/{suffix}" for name, suffix in {
            "prompt_topic": "prompt", "request_topic": "request_json",
            "response_topic": "response", "response_json_topic": "response_json", "status_topic": "status",
        }.items()}
        bridge_parameters = dict(topics)
        for name in ("api_base_url", "model"):
            if LaunchConfiguration(name).perform(context):
                bridge_parameters[name] = ParameterValue(LaunchConfiguration(name), value_type=str)
        bridge = Node(
            package="llm_ros", executable="llm_client_node", name="llm_demo_bridge", output="screen",
            parameters=[LaunchConfiguration("params_file"), bridge_parameters],
        )
        demo = Node(
            package="llm_ros", executable="llm_chat_demo", name="llm_chat_demo", output="screen",
            parameters=[{name: topics[name] for name in ("request_topic", "response_json_topic", "status_topic")}],
            arguments=["--once", LaunchConfiguration("prompt"),
                       "--timeout", LaunchConfiguration("response_timeout_sec"),
                       "--discovery-timeout", LaunchConfiguration("discovery_timeout_sec")],
        )

        def finish(event, _context):
            if event.returncode != 0:
                raise RuntimeError(f"ROS LLM demo failed with exit code {event.returncode}")
            return [EmitEvent(event=Shutdown(reason="ROS LLM demo completed"))]

        return [RegisterEventHandler(OnProcessExit(target_action=demo, on_exit=finish)), bridge, demo]

    return LaunchDescription(arguments + [OpaqueFunction(function=start_demo)])
