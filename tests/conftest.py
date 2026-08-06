from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def project_root() -> Path:
    return ROOT


@pytest.fixture
def tiny_config_path(project_root: Path) -> Path:
    return project_root / "configs" / "tiny.yaml"


@pytest.fixture
def demo_trace_path(project_root: Path) -> Path:
    return project_root / "traces" / "demo" / "api.csv"
