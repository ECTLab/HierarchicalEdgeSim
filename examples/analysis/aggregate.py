"""Aggregation helpers for multi-container / multi-app analysis."""

from __future__ import annotations

from collections import defaultdict

from .io import ContainerSeries


def sum_series(series_list: list[list[float]]) -> list[float]:
    if not series_list:
        return []
    n = len(series_list[0])
    return [sum(series[i] for series in series_list) for i in range(n)]


def group_containers_by_app(containers: list[ContainerSeries]) -> dict[str, list[ContainerSeries]]:
    grouped: dict[str, list[ContainerSeries]] = defaultdict(list)
    for container in containers:
        grouped[container.app_id].append(container)
    return dict(sorted(grouped.items(), key=lambda item: item[0]))


def group_containers_by_microservice(
    containers: list[ContainerSeries],
) -> dict[str, list[ContainerSeries]]:
    grouped: dict[str, list[ContainerSeries]] = defaultdict(list)
    for container in containers:
        grouped[container.microservice_id].append(container)
    return dict(sorted(grouped.items(), key=lambda item: item[0]))
