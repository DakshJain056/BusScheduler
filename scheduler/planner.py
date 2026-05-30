"""
Charging plan enumeration.

Given a route, direction, and battery range, enumerate every valid subset
of charging stations a bus could use to complete the trip.
"""

from __future__ import annotations

from itertools import combinations
from typing import Iterator

from .models import Route, FleetConfig


def enumerate_valid_plans(
    route: Route,
    direction: str,
    fleet: FleetConfig,
    charging_station_ids: list[str],
) -> list[list[str]]:
    """
    Return all valid charging plans for a bus travelling in `direction`.

    A plan is a list of station IDs (in route order) where the bus stops
    to charge.  A plan is valid iff no segment between consecutive charge
    points (including start → first charge and last charge → end) exceeds
    the battery range.

    Plans are returned sorted by number of stops (fewest first).
    """
    ordered_stops = route.ordered_stops(direction)
    origin = ordered_stops[0]
    destination = ordered_stops[-1]

    # Filter to only stations that are on the route in this direction
    station_set = set(charging_station_ids)
    stations_in_order = [s for s in ordered_stops if s in station_set]

    valid: list[list[str]] = []

    # Try every subset size from min required to all stations
    for r in range(1, len(stations_in_order) + 1):
        for combo in combinations(stations_in_order, r):
            plan = list(combo)  # already in route order
            if _is_valid_plan(route, origin, destination, plan, fleet):
                valid.append(plan)

    # Sort by number of stops (prefer fewer), then alphabetically for stability
    valid.sort(key=lambda p: (len(p), p))
    return valid


def _is_valid_plan(
    route: Route,
    origin: str,
    destination: str,
    plan: list[str],
    fleet: FleetConfig,
) -> bool:
    """Check that no leg exceeds battery range."""
    checkpoints = [origin] + plan + [destination]
    for i in range(len(checkpoints) - 1):
        leg_dist = route.distance_between(checkpoints[i], checkpoints[i + 1])
        if leg_dist > fleet.battery_range_km:
            return False
    return True


def rank_plans(
    plans: list[list[str]],
    route: Route,
    direction: str,
    fleet: FleetConfig,
) -> list[tuple[list[str], float]]:
    """
    Score each plan.  Lower score = better.

    Scoring considers:
      - Number of stops (fewer = less total charging time)
      - Balance of leg distances (prefer even legs to keep range margin)
    """
    ordered_stops = route.ordered_stops(direction)
    origin = ordered_stops[0]
    destination = ordered_stops[-1]

    scored: list[tuple[list[str], float]] = []
    for plan in plans:
        checkpoints = [origin] + plan + [destination]
        legs = []
        for i in range(len(checkpoints) - 1):
            legs.append(route.distance_between(checkpoints[i], checkpoints[i + 1]))

        # Cost = num_stops * charging_time + variance penalty
        num_stops = len(plan)
        charge_cost = num_stops * fleet.charging_time_min
        avg_leg = sum(legs) / len(legs)
        variance = sum((l - avg_leg) ** 2 for l in legs) / len(legs)
        # Normalize variance relative to range
        variance_penalty = (variance / (fleet.battery_range_km ** 2)) * 10

        score = charge_cost + variance_penalty
        scored.append((plan, score))

    scored.sort(key=lambda x: x[1])
    return scored
