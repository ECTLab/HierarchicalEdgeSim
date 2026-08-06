"""Run Part A environment end-to-end (no autoscaler)."""

from __future__ import annotations

import argparse

from hierarchical_edge_sim.env.config import load_yaml
from hierarchical_edge_sim.env.engine import run_ticks
from hierarchical_edge_sim.env.metrics_log import make_run_id, write_run_outputs
from hierarchical_edge_sim.env.traces import load_traces
from hierarchical_edge_sim.env.validate import validate_or_raise
from hierarchical_edge_sim.env.world import build_world


def run(config_path: str) -> str:
    raw = load_yaml(config_path)
    spec = validate_or_raise(raw)
    world = build_world(spec)
    traces = load_traces(spec)
    run_ticks(world=world, traces=traces, world_spec=spec)

    run_id = make_run_id(spec.sim.seed)
    run_dir = write_run_outputs(world=world, world_spec=spec, traces=traces, run_id=run_id)
    return str(run_dir)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Part A environment only.")
    parser.add_argument("config_path", help="Path to YAML config file")
    args = parser.parse_args()

    run_dir = run(args.config_path)
    print(f"Run complete. Outputs written to: {run_dir}")


if __name__ == "__main__":
    main()
