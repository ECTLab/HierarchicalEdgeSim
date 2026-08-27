"""Option A TCN: 60×2 (normalized load, time/720) → 5-step delta → absolute RPS."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .window import (
    build_option_a_window,
    count_to_rps,
    denormalize_load,
    rps_to_count,
    time_window,
)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[5]


def _build_tcn_module(
    *,
    input_size: int,
    num_channels: list[int],
    kernel_size: int,
    output_size: int,
) -> Any:
    """Same dilated-causal stack as alibaba-trace ``train_tcn.TCNPredictor``."""
    import torch.nn as nn

    class TCNPredictor(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            layers: list[nn.Module] = []
            for i, out_channels in enumerate(num_channels):
                dilation_size = 2**i
                in_channels = input_size if i == 0 else num_channels[i - 1]
                padding = (kernel_size - 1) * dilation_size
                layers.append(
                    nn.Conv1d(
                        in_channels,
                        out_channels,
                        kernel_size,
                        padding=padding,
                        dilation=dilation_size,
                    )
                )
                layers.append(nn.ReLU())
            self.network = nn.Sequential(*layers)
            self.fc = nn.Linear(num_channels[-1], output_size)

        def forward(self, x):
            x_t = x.transpose(1, 2)
            out = self.network(x_t)
            out = out[:, :, : x_t.size(2)]
            out = out[:, :, -1]
            return self.fc(out)

    return TCNPredictor()


class TcnDeltaPredictor:
    """Load ``models/tcn_delta_v1`` and emit H absolute RPS values."""

    def __init__(self, meta: dict[str, Any], weights_path: Path) -> None:
        import torch

        self.meta = dict(meta)
        self.lookback = int(meta["lookback"])
        self.forecast_horizon = int(meta["horizon"])
        self.time_scale = float(meta["time_scale"])
        self.tick_sec = float(meta["tick_sec"])
        self.load_min = float(meta["load_min"])
        self.load_max = float(meta["load_max"])
        arch = dict(meta.get("arch") or {})
        module = _build_tcn_module(
            input_size=int(arch.get("input_size", 2)),
            num_channels=list(arch.get("num_channels") or [32, 64]),
            kernel_size=int(arch.get("kernel_size", 3)),
            output_size=int(arch.get("output_size", self.forecast_horizon)),
        )
        module.load_state_dict(_load_state_dict(weights_path))
        module.eval()
        self._module = module
        self._torch = torch

    @classmethod
    def from_model_dir(cls, model_dir: str | Path | None = None) -> "TcnDeltaPredictor":
        root = _project_root()
        directory = Path(model_dir) if model_dir else root / "models" / "tcn_delta_v1"
        if not directory.is_absolute():
            directory = (root / directory).resolve()
        meta_path = directory / "meta.json"
        if not meta_path.is_file():
            raise FileNotFoundError(f"missing TCN meta: {meta_path}")
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        weights = directory / str(meta.get("weights_file") or "tcn_delta_weights.pth")
        if not weights.is_file():
            raise FileNotFoundError(f"missing TCN weights: {weights}")
        return cls(meta=meta, weights_path=weights)

    def predict_horizon(
        self,
        history_rps: list[float],
        *,
        time_ticks: list[int] | None = None,
        counts: list[float] | None = None,
    ) -> list[float]:
        if counts is None:
            counts = [
                rps_to_count(rps, tick_sec=self.tick_sec, ticks_per_window=1) for rps in history_rps
            ]
        if len(counts) != self.lookback:
            raise ValueError(f"TCN lookback is {self.lookback}, got {len(counts)} samples")
        if time_ticks is None:
            time_ticks = time_window(self.lookback - 1, self.lookback)
        if len(time_ticks) != self.lookback:
            raise ValueError(f"expected {self.lookback} time_ticks, got {len(time_ticks)}")

        window = build_option_a_window(
            counts,
            time_ticks,
            load_min=self.load_min,
            load_max=self.load_max,
            time_scale=self.time_scale,
        )
        x = self._torch.tensor([window], dtype=self._torch.float32)
        with self._torch.no_grad():
            deltas = self._module(x).squeeze(0).tolist()
        last_norm = window[-1][0]
        rps_out: list[float] = []
        for delta in deltas:
            abs_norm = last_norm + float(delta)
            abs_count = max(0.0, denormalize_load(abs_norm, self.load_min, self.load_max))
            rps_out.append(count_to_rps(abs_count, tick_sec=self.tick_sec, ticks_per_window=1))
        return rps_out


def _load_state_dict(path: Path) -> dict[str, Any]:
    import torch

    try:
        return torch.load(path, map_location="cpu", weights_only=True)
    except TypeError:
        return torch.load(path, map_location="cpu")
