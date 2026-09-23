"""Route each microservice to its own forecast model."""

from __future__ import annotations

from typing import Any


class MicroserviceModelMap:
    """Default predictor, overridden per microservice id.

    ``predictor_for`` is what sensing calls. A missing id uses the default,
    so a single-MS run can keep ``model_dir`` and leave the map empty.
    """

    def __init__(self, default: Any, by_ms: dict[str, Any]) -> None:
        self._default = default
        self._by_ms = dict(by_ms)

    def predictor_for(self, ms_id: str) -> Any:
        return self._by_ms.get(ms_id, self._default)
