#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Usage: setup.sh [workspace]
set -eo pipefail
workspace="${1:-$HOME/llm_ws}"
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
ros_distro="${ROS_DISTRO:-humble}"
venv_dir="${LLM_ROS_VENV:-$workspace/.venv}"
if [[ ! -f "/opt/ros/$ros_distro/setup.bash" ]]; then
  echo "Install ROS 2 $ros_distro first; see README.md." >&2
  exit 1
fi
source "/opt/ros/$ros_distro/setup.bash"
mkdir -p "$workspace/src"
package_path="$workspace/src/llm_ros"
if [[ -e "$package_path" || -L "$package_path" ]]; then
  if [[ "$(realpath "$package_path")" != "$repo_dir" ]]; then
    echo "$package_path belongs to another checkout; choose a different workspace." >&2
    exit 1
  fi
else
  ln -s "$repo_dir" "$package_path"
fi
"${LLM_ROS_PYTHON:-/usr/bin/python3}" -m venv --system-site-packages "$venv_dir"
"$venv_dir/bin/python" -c 'import rclpy'
cd "$workspace"
"$venv_dir/bin/python" -m colcon build --symlink-install --packages-select llm_ros
echo "Built llm_ros. In each new terminal:"
printf 'source /opt/ros/%s/setup.bash\n' "$ros_distro"
printf 'source %q/bin/activate\n' "$venv_dir"
printf 'source %q/install/local_setup.bash\n' "$workspace"
