"""One-step LSTM RPS predictor (PyTorch + sklearn MinMaxScaler)."""

from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
import torch
import torch.nn as nn
from sklearn.preprocessing import MinMaxScaler

# Defaults match microservice-workload-predictor train_lstm.FEATURE_WINDOW=10.
DEFAULT_FEATURE_WINDOW = 10
DEFAULT_HIDDEN_SIZE = 16


def default_model_dir() -> Path:
    """``HierarchicalEdgeSim/models/rps_lstm_v1`` (repo root relative to this file)."""
    # predictors/ -> ... -> src/ -> HierarchicalEdgeSim/
    return Path(__file__).resolve().parents[5] / "models" / "rps_lstm_v1"


class WorkloadPredictor(nn.Module):
    """Same architecture as microservice-workload-predictor.WorkloadPredictor."""

    def __init__(self, input_size: int = 1, hidden_size: int = DEFAULT_HIDDEN_SIZE, output_size: int = 1):
        super().__init__()
        self.lstm = nn.LSTM(input_size, hidden_size, batch_first=True)
        self.linear = nn.Linear(hidden_size, output_size)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        lstm_out, _ = self.lstm(x)
        last_time_step = lstm_out[:, -1, :]
        return self.linear(last_time_step)


class LstmTorchPredictor:
    """``predict_next``: MinMax-normalize → LSTM → inverse MinMax → float RPS/count.

    Durable history stays in real units. Normalization uses the **train-time**
    ``sklearn.preprocessing.MinMaxScaler`` pickle (standard Option B).
    """

    def __init__(
        self,
        *,
        model_path: str | Path,
        scaler_path: str | Path,
        meta_path: str | Path | None = None,
        feature_window: int | None = None,
        hidden_size: int = DEFAULT_HIDDEN_SIZE,
    ) -> None:
        model_path = Path(model_path)
        scaler_path = Path(scaler_path)
        if not model_path.is_file():
            raise FileNotFoundError(f"LSTM weights not found: {model_path}")
        if not scaler_path.is_file():
            raise FileNotFoundError(f"MinMaxScaler pickle not found: {scaler_path}")

        scaler = joblib.load(scaler_path)
        if not isinstance(scaler, MinMaxScaler):
            raise TypeError(
                f"expected sklearn MinMaxScaler at {scaler_path}, got {type(scaler).__name__}"
            )
        self._scaler: MinMaxScaler = scaler

        meta_feature_window: int | None = None
        meta_hidden = hidden_size
        resolved_meta = _resolve_meta_path(meta_path, model_path.parent)
        if resolved_meta is not None:
            meta = json.loads(resolved_meta.read_text(encoding="utf-8"))
            meta_feature_window = int(meta["feature_window"])
            meta_hidden = int(meta.get("hidden_size", hidden_size))

        if feature_window is None:
            self.feature_window = meta_feature_window or DEFAULT_FEATURE_WINDOW
        else:
            self.feature_window = int(feature_window)
            if meta_feature_window is not None and self.feature_window != meta_feature_window:
                raise ValueError(
                    f"feature_window={self.feature_window} does not match "
                    f"meta.json feature_window={meta_feature_window}"
                )

        self._model = WorkloadPredictor(hidden_size=meta_hidden)
        state = torch.load(model_path, map_location=torch.device("cpu"), weights_only=True)
        self._model.load_state_dict(state)
        self._model.eval()

    def predict_next(self, x: list[float]) -> float:
        if len(x) != self.feature_window:
            raise ValueError(f"expected feature_window={self.feature_window}, got len={len(x)}")

        raw = np.asarray(x, dtype=np.float64).reshape(-1, 1)
        # Standard train/infer path: MinMaxScaler to [0, 1], then inverse after the net.
        scaled = self._scaler.transform(raw)
        tensor_in = torch.tensor(scaled, dtype=torch.float32).unsqueeze(0)

        with torch.no_grad():
            y_scaled = self._model(tensor_in)

        y = float(self._scaler.inverse_transform(y_scaled.numpy())[0][0])
        if not np.isfinite(y):
            raise RuntimeError(f"non-finite LSTM prediction: {y}")
        return max(0.0, y)


def build_lstm_predictor(
    *,
    feature_window: int,
    model_path: str | None = None,
    scaler_path: str | None = None,
    meta_path: str | None = None,
) -> LstmTorchPredictor:
    base = default_model_dir()
    return LstmTorchPredictor(
        model_path=model_path or str(base / "lstm_edge_weights.pth"),
        scaler_path=scaler_path or str(base / "traffic_scaler.pkl"),
        meta_path=meta_path or str(base / "meta.json"),
        feature_window=feature_window,
    )


def _resolve_meta_path(meta_path: str | Path | None, model_dir: Path) -> Path | None:
    if meta_path is None:
        candidate = model_dir / "meta.json"
        return candidate if candidate.is_file() else None
    path = Path(meta_path)
    if path.is_file():
        return path
    fallback = model_dir / "meta.json"
    return fallback if fallback.is_file() else None
