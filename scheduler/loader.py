"""
Scenario loader — reads YAML files into Scenario objects.
"""

from __future__ import annotations

import os
import glob
from pathlib import Path
from typing import Optional

import yaml

from .models import (
    Bus, FleetConfig, Route, Scenario, Segment, StationConfig, Weights,
)


SCENARIOS_DIR = Path(__file__).parent.parent / "scenarios"


def load_scenario(path: str | Path) -> Scenario:
    """Load a single scenario from a YAML file."""
    with open(path, "r") as f:
        data = yaml.safe_load(f)

    meta = data["meta"]

    # Route
    route_data = data["route"]
    segments = [
        Segment(
            from_stop=seg["from"],
            to_stop=seg["to"],
            distance_km=seg["distance_km"],
        )
        for seg in route_data["segments"]
    ]
    route = Route(
        name=route_data["name"],
        stops=route_data["stops"],
        segments=segments,
    )

    # Fleet config
    fleet_data = data["fleet"]
    fleet = FleetConfig(
        battery_range_km=fleet_data["battery_range_km"],
        charging_time_min=fleet_data["charging_time_min"],
        speed_kmh=fleet_data["speed_kmh"],
    )

    # Stations
    stations = [
        StationConfig(id=s["id"], chargers=s.get("chargers", 1))
        for s in data["stations"]
    ]

    # Weights
    w = data.get("weights", {})
    weights = Weights(
        individual=w.get("individual", 1.0),
        operator=w.get("operator", 1.0),
        overall=w.get("overall", 1.0),
    )

    # Buses
    buses = [
        Bus(
            id=b["id"],
            operator=b["operator"],
            direction=b["direction"],
            departure_time=b["departure"],
        )
        for b in data["buses"]
    ]

    return Scenario(
        name=meta["name"],
        description=meta.get("description", ""),
        route=route,
        fleet=fleet,
        stations=stations,
        weights=weights,
        buses=buses,
    )


def load_all_scenarios(
    directory: Optional[str | Path] = None,
) -> dict[str, Scenario]:
    """
    Load all YAML scenarios from a directory.
    Returns a dict mapping scenario name → Scenario.
    """
    d = Path(directory) if directory else SCENARIOS_DIR
    scenarios: dict[str, Scenario] = {}

    for fpath in sorted(d.glob("*.yaml")):
        scenario = load_scenario(fpath)
        scenarios[scenario.name] = scenario

    return scenarios
