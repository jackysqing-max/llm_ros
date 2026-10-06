# Contributing

Include your ROS distribution, Python version, endpoint protocol, model server
version, reproduction steps, and expected behavior in issues or pull requests.

Run `python -m pytest -q` for transport and normalization changes. Build the package
and run the installed-node mock smoke tests for ROS changes. Tests against real
models require your own service or authorized account and are recorded separately.

Keep documentation and comments in English. Multilingual parser data may remain
in its original language. Do not commit credentials, model weights, ROS bags, or
experiment datasets. Contributions use Apache-2.0.
