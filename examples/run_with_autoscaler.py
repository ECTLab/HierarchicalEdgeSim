"""Run environment with an optional autoscaler selected from YAML."""

from __future__ import annotations

import argparse

from hierarchical_edge_sim.autoscaler.common.load import load_autoscaler_from_yaml
from hierarchical_edge_sim.env.api import Env


def run(config_path: str) -> str:
    env = Env.from_config(config_path)
    scaler = load_autoscaler_from_yaml(config_path)
    run_dir = env.run(autoscaler=scaler)
    return str(run_dir)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run env with autoscaler from YAML (if enabled).")
    parser.add_argument("config_path", help="Path to YAML config file")
    args = parser.parse_args()
    run_dir = run(args.config_path)
    print(f"Run complete. Outputs written to: {run_dir}")


if __name__ == "__main__":
    main()
