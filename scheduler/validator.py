"""
Schedule validator.

Checks hard constraints after the scheduler runs:
  - No bus exceeds battery range between charges
  - No two buses overlap on the same charger
  - Every bus visits stations in route order
"""

from __future__ import annotations

from dataclasses import dataclass
from .models import ScheduleResult, Scenario


@dataclass
class ValidationError:
    bus_id: str
    message: str


def validate(scenario: Scenario, result: ScheduleResult) -> list[ValidationError]:
    """Run all hard-constraint checks. Returns empty list if valid."""
    errors: list[ValidationError] = []
    errors.extend(_check_range(scenario, result))
    errors.extend(_check_charger_overlap(scenario, result))
    errors.extend(_check_route_order(scenario, result))
    return errors


def _check_range(scenario: Scenario, result: ScheduleResult) -> list[ValidationError]:
    """Verify no bus exceeds battery range between charges."""
    errors = []
    route = scenario.route
    fleet = scenario.fleet

    for bus_id, sched in result.bus_schedules.items():
        ordered = route.ordered_stops(sched.bus.direction)
        origin = ordered[0]
        destination = ordered[-1]

        checkpoints = [origin] + sched.charging_plan + [destination]
        for i in range(len(checkpoints) - 1):
            dist = route.distance_between(checkpoints[i], checkpoints[i + 1])
            if dist > fleet.battery_range_km:
                errors.append(ValidationError(
                    bus_id=bus_id,
                    message=(
                        f"Leg {checkpoints[i]}→{checkpoints[i+1]} is {dist} km, "
                        f"exceeds range {fleet.battery_range_km} km"
                    ),
                ))
    return errors


def _check_charger_overlap(
    scenario: Scenario, result: ScheduleResult
) -> list[ValidationError]:
    """Verify no two buses charge at the same station at overlapping times."""
    errors = []

    for sid, log in result.station_logs.items():
        entries = sorted(log.entries, key=lambda e: e.charging_start_min)
        for i in range(len(entries) - 1):
            curr = entries[i]
            nxt = entries[i + 1]
            if curr.charging_end_min > nxt.charging_start_min + 0.01:
                errors.append(ValidationError(
                    bus_id=curr.bus_id,
                    message=(
                        f"Charger overlap at {sid}: {curr.bus_id} ends at "
                        f"{curr.charging_end_min:.1f}, {nxt.bus_id} starts at "
                        f"{nxt.charging_start_min:.1f}"
                    ),
                ))
    return errors


def _check_route_order(
    scenario: Scenario, result: ScheduleResult
) -> list[ValidationError]:
    """Verify buses visit stations in route order (no backtracking)."""
    errors = []
    route = scenario.route

    for bus_id, sched in result.bus_schedules.items():
        ordered = route.ordered_stops(sched.bus.direction)
        station_set = set(scenario.charging_station_ids)
        charging_stations_in_order = [s for s in ordered if s in station_set]

        plan = sched.charging_plan
        prev_idx = -1
        for s in plan:
            if s not in charging_stations_in_order:
                errors.append(ValidationError(
                    bus_id=bus_id,
                    message=f"Station {s} not on route for direction {sched.bus.direction}",
                ))
                continue
            idx = charging_stations_in_order.index(s)
            if idx <= prev_idx:
                errors.append(ValidationError(
                    bus_id=bus_id,
                    message=f"Station {s} visited out of order (backtracking)",
                ))
            prev_idx = idx

    return errors
