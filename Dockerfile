FROM ros:humble-ros-base-jammy
SHELL ["/bin/bash", "-c"]
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-colcon-common-extensions ros-humble-launch-ros \
    ros-humble-ament-index-python ros-humble-std-msgs \
    && rm -rf /var/lib/apt/lists/*
COPY . /ws/src/llm_ros
WORKDIR /ws
RUN source /opt/ros/humble/setup.bash && python3 -m colcon build --packages-select llm_ros
COPY docker/entrypoint.sh /usr/local/bin/llm-entrypoint
RUN chmod +x /usr/local/bin/llm-entrypoint
ENTRYPOINT ["/usr/local/bin/llm-entrypoint"]
CMD ["ros2", "launch", "llm_ros", "llm.launch.py"]
