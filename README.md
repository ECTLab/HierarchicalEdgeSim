# HierarchicalEdgeSim

In-process hierarchical edge autoscaling simulator (Part A: environment).

Catalog: [docs/README.md](docs/README.md) (numbered, later = higher).
Configs: [configs/README.md](configs/README.md).
Plans: [docs/03-implementation-plan.md](docs/03-implementation-plan.md),
[docs/04-part-a-implementation-steps.md](docs/04-part-a-implementation-steps.md).
How to run: [docs/00-how-to-rerun-tests-and-graphs.md](docs/00-how-to-rerun-tests-and-graphs.md).

```bash
python3.14 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```
