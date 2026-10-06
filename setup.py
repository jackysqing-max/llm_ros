# SPDX-License-Identifier: Apache-2.0
"""Install the standalone llm_ros ament Python package."""

from glob import glob
from setuptools import find_packages, setup

setup(
    name="llm_ros", version="0.1.0", packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/llm_ros"]),
        ("share/llm_ros", ["package.xml", "LICENSE", "NOTICE", "README.md"]),
        ("share/llm_ros/launch", glob("launch/*.launch.py")),
        ("share/llm_ros/config", glob("config/*.yaml")),
    ],
    install_requires=["setuptools"], zip_safe=True,
    maintainer="siqin", maintainer_email="jackysqing@gmail.com",
    description="Reusable ROS 2 HTTP LLM communication and task-planning module",
    license="Apache-2.0", url="https://github.com/jackysqing-max/llm_ros",
    extras_require={"test": ["pytest"]},
    entry_points={"console_scripts": [
        "llm_client_node = llm_ros.llm_client_node:main",
        "llm_task_planner_node = llm_ros.llm_task_planner_node:main",
        "llm_task_cli = llm_ros.llm_task_cli:main",
        "llm_chat_demo = llm_ros.llm_chat_demo:main",
    ]},
)
