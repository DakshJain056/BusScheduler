"""
Core scheduling engine — discrete-event simulation.

The engine:
  1. Assigns each bus a charging plan (which stations to use)
  2. Simulates all buses moving through the route chronologically
  3. Resolves charger conflicts using the weighted rule system
  4. Produces a complete ScheduleResult
"""

from __future__ import annotations

import heapq
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from .models import (
    Bus, BusSchedule, ChargingEvent, FleetConfig, Route,
    Scenario, ScheduleResult, StationLog, StationLogEntry,
    StopEvent, Weights,
)
from .planner import enumerate_valid_plans, rank_plans
from .rules import Rule, SchedulingContext, get_default_rules


# ── Event types for the simulation ──────────────────────────────────────────

ARRIVE_STATION = "arrive_station"
FINISH_CHARGING = "finish_charging"


@dataclass(order=True)
class SimEvent:
    """A single event in the discrete-event simulation."""
    time_min: float
    seq: int = field(compare=True)       # tie-breaker for heap stability
    kind: str = field(compare=False)
    bus_id: str = field(compare=False)
    station_id: str = field(compare=False, default="")
    data: dict = field(compare=False, default_factory=dict)


# ── Bus state tracker ───────────────────────────────────────────────────────

@dataclass
class BusState:
    """Mutable state for one bus during simulation."""
    bus: Bus
    plan: list[str]                  # stations where this bus will charge
    plan_index: int = 0              # next station in the plan to visit
    current_stop_idx: int = 0        # index in the ordered stop list
    range_km: float = 0.0            # remaining range
    departure_min: float = 0.0       # departure from origin
    total_wait_min: float = 0.0
    total_charge_min: float = 0.0
    stop_events: list = field(default_factory=list)
    charging_events: list = field(default_factory=list)
    finished: bool = False


# ── Station state tracker ───────────────────────────────────────────────────

@dataclass
class StationState:
    """Mutable state for one charging station during simulation."""
    station_id: str
    chargers: int = 1
    busy_until: float = 0.0          # when the current charge finishes
    queue: list = field(default_factory=list)  # [(arrival_min, bus_id)]
    log: list = field(default_factory=list)    # StationLogEntry list


# ── Engine ──────────────────────────────────────────────────────────────────

class SchedulerEngine:
    """
    Discrete-event simulation scheduler.

    Usage:
        engine = SchedulerEngine(rules=get_default_rules())
        result = engine.run(scenario)
    """

    def __init__(self, rules: Optional[list[Rule]] = None):
        self.rules = rules or get_default_rules()

    def run(self, scenario: Scenario) -> ScheduleResult:
        """Execute the full scheduling pipeline for a scenario."""
        route = scenario.route
        fleet = scenario.fleet
        weights = scenario.weights
        station_ids = scenario.charging_station_ids

        # ── 1. Assign charging plans ────────────────────────────────────
        bus_plans = self._assign_plans(scenario)

        # ── 2. Initialise simulation state ──────────────────────────────
        bus_states: dict[str, BusState] = {}
        for bus in scenario.buses:
            dep = bus.departure_minutes()
            bs = BusState(
                bus=bus,
                plan=bus_plans[bus.id],
                range_km=fleet.battery_range_km,
                departure_min=dep,
            )
            bus_states[bus.id] = bs

        station_states: dict[str, StationState] = {}
        for sc in scenario.stations:
            station_states[sc.id] = StationState(
                station_id=sc.id, chargers=sc.chargers
            )

        # ── 3. Seed initial events ──────────────────────────────────────
        event_heap: list[SimEvent] = []
        seq = 0

        for bus in scenario.buses:
            bs = bus_states[bus.id]
            ordered = route.ordered_stops(bus.direction)
            origin = ordered[0]
            # Record departure event
            bs.stop_events.append(StopEvent(
                stop_id=origin,
                arrival_min=bs.departure_min,
                departure_min=bs.departure_min,
                is_charging=False,
                range_on_arrival_km=fleet.battery_range_km,
            ))
            bs.current_stop_idx = 0
            # Schedule arrival at next stop
            next_stop = ordered[1]
            travel_dist = route.distance_between(origin, next_stop)
            travel_time = fleet.travel_time_min(travel_dist)
            arrival = bs.departure_min + travel_time

            heapq.heappush(event_heap, SimEvent(
                time_min=arrival, seq=seq,
                kind=ARRIVE_STATION, bus_id=bus.id,
                station_id=next_stop,
                data={"travel_dist": travel_dist},
            ))
            seq += 1

        # ── 4. Run simulation ───────────────────────────────────────────
        context = SchedulingContext()
        # Populate operator bus counts
        op_counts: dict[str, int] = defaultdict(int)
        for bus in scenario.buses:
            op_counts[bus.operator] += 1
        context.operator_bus_counts = dict(op_counts)

        while event_heap:
            event = heapq.heappop(event_heap)
            bs = bus_states[event.bus_id]
            if bs.finished:
                continue

            if event.kind == ARRIVE_STATION:
                ordered = route.ordered_stops(bs.bus.direction)
                stop_idx = ordered.index(event.station_id)
                bs.current_stop_idx = stop_idx
                travel_dist = event.data.get("travel_dist", 0)
                bs.range_km -= travel_dist

                # Is this the final destination?
                if event.station_id == ordered[-1]:
                    bs.stop_events.append(StopEvent(
                        stop_id=event.station_id,
                        arrival_min=event.time_min,
                        departure_min=event.time_min,
                        is_charging=False,
                        range_on_arrival_km=bs.range_km,
                    ))
                    bs.finished = True
                    continue

                # Does this bus charge here?
                needs_charge = (
                    bs.plan_index < len(bs.plan)
                    and bs.plan[bs.plan_index] == event.station_id
                )

                if needs_charge:
                    ss = station_states[event.station_id]
                    # Add to station queue
                    ss.queue.append((event.time_min, bs.bus.id))

                    # Try to start charging immediately
                    self._process_station_queue(
                        ss, event.time_min, bus_states, weights,
                        context, fleet, route, event_heap, seq,
                    )
                    seq += len(ss.queue) + 1

                    # Record stop event (will update departure later)
                    bs.stop_events.append(StopEvent(
                        stop_id=event.station_id,
                        arrival_min=event.time_min,
                        departure_min=event.time_min,  # placeholder
                        is_charging=True,
                        range_on_arrival_km=bs.range_km,
                    ))
                else:
                    # Just passing through
                    bs.stop_events.append(StopEvent(
                        stop_id=event.station_id,
                        arrival_min=event.time_min,
                        departure_min=event.time_min,
                        is_charging=False,
                        range_on_arrival_km=bs.range_km,
                    ))
                    # Schedule next leg
                    if stop_idx + 1 < len(ordered):
                        next_stop = ordered[stop_idx + 1]
                        dist = route.distance_between(
                            event.station_id, next_stop
                        )
                        arr = event.time_min + fleet.travel_time_min(dist)
                        heapq.heappush(event_heap, SimEvent(
                            time_min=arr, seq=seq,
                            kind=ARRIVE_STATION, bus_id=bs.bus.id,
                            station_id=next_stop,
                            data={"travel_dist": dist},
                        ))
                        seq += 1

            elif event.kind == FINISH_CHARGING:
                ss = station_states[event.station_id]
                bs.range_km = fleet.battery_range_km
                bs.plan_index += 1
                charge_time = fleet.charging_time_min
                bs.total_charge_min += charge_time

                # Update the stop event's departure time and wait
                last_ce = bs.charging_events[-1] if bs.charging_events else None
                for se in reversed(bs.stop_events):
                    if se.stop_id == event.station_id and se.is_charging:
                        se.departure_min = event.time_min
                        if last_ce and last_ce.station_id == event.station_id:
                            se.wait_min = last_ce.wait_min
                        break

                # Schedule next leg
                ordered = route.ordered_stops(bs.bus.direction)
                stop_idx = ordered.index(event.station_id)
                if stop_idx + 1 < len(ordered):
                    next_stop = ordered[stop_idx + 1]
                    dist = route.distance_between(
                        event.station_id, next_stop
                    )
                    arr = event.time_min + fleet.travel_time_min(dist)
                    heapq.heappush(event_heap, SimEvent(
                        time_min=arr, seq=seq,
                        kind=ARRIVE_STATION, bus_id=bs.bus.id,
                        station_id=next_stop,
                        data={"travel_dist": dist},
                    ))
                    seq += 1

                # Process next bus in queue
                self._process_station_queue(
                    ss, event.time_min, bus_states, weights,
                    context, fleet, route, event_heap, seq,
                )
                seq += 10

        # ── 5. Build results ────────────────────────────────────────────
        return self._build_result(scenario, bus_states, station_states)

    # ── Plan assignment ─────────────────────────────────────────────────

    def _assign_plans(self, scenario: Scenario) -> dict[str, list[str]]:
        """
        Assign a charging plan to each bus.

        Strategy:
          - For each bus, enumerate valid plans and rank them
          - Track station load and prefer plans that balance usage
        """
        route = scenario.route
        fleet = scenario.fleet
        station_ids = scenario.charging_station_ids

        # Pre-compute valid plans per direction
        plans_by_dir: dict[str, list[tuple[list[str], float]]] = {}
        for direction in ("BK", "KB"):
            valid = enumerate_valid_plans(route, direction, fleet, station_ids)
            ranked = rank_plans(valid, route, direction, fleet)
            plans_by_dir[direction] = ranked

        # Sort buses by departure time for greedy assignment
        sorted_buses = sorted(scenario.buses, key=lambda b: b.departure_minutes())

        station_load: dict[str, int] = defaultdict(int)
        assignments: dict[str, list[str]] = {}

        # Track estimated arrival times at each station for contention analysis
        station_arrivals: dict[str, list[float]] = defaultdict(list)

        for bus in sorted_buses:
            ranked = plans_by_dir[bus.direction]
            dep_min = bus.departure_minutes()
            best_plan = None
            best_score = float("inf")

            for plan, base_score in ranked:
                # 1. Load penalty — strongly prefer under-used stations
                load_penalty = sum(
                    station_load[s] * 15.0 for s in plan
                )

                # 2. Contention penalty — penalise plans where this bus
                #    would arrive near other buses already assigned
                contention = 0.0
                ordered = route.ordered_stops(bus.direction)
                origin = ordered[0]
                time_cursor = dep_min
                prev_stop = origin
                for stop in ordered[1:]:
                    dist = route.distance_between(prev_stop, stop)
                    time_cursor += fleet.travel_time_min(dist)
                    if stop in plan:
                        # Check how close other buses arrive
                        for other_arr in station_arrivals.get(stop, []):
                            gap = abs(time_cursor - other_arr)
                            if gap < fleet.charging_time_min * 2:
                                contention += max(0, fleet.charging_time_min * 2 - gap)
                        time_cursor += fleet.charging_time_min  # charging
                    prev_stop = stop

                total_score = base_score + load_penalty + contention * 0.5
                if total_score < best_score:
                    best_score = total_score
                    best_plan = plan

            # Record assignment and estimated arrival times
            assignments[bus.id] = best_plan
            for s in best_plan:
                station_load[s] += 1

            # Compute estimated arrival times at planned stations
            ordered = route.ordered_stops(bus.direction)
            origin = ordered[0]
            time_cursor = dep_min
            prev_stop = origin
            for stop in ordered[1:]:
                dist = route.distance_between(prev_stop, stop)
                time_cursor += fleet.travel_time_min(dist)
                if stop in best_plan:
                    station_arrivals[stop].append(time_cursor)
                    time_cursor += fleet.charging_time_min
                prev_stop = stop

        return assignments

    # ── Queue processing ────────────────────────────────────────────────

    def _process_station_queue(
        self,
        ss: StationState,
        current_time: float,
        bus_states: dict[str, BusState],
        weights: Weights,
        context: SchedulingContext,
        fleet: FleetConfig,
        route: Route,
        event_heap: list,
        seq: int,
    ) -> None:
        """
        Check if a bus in the station queue can start charging.
        If the charger is free and buses are waiting, pick the
        highest-priority bus and start it.
        """
        if not ss.queue:
            return

        effective_free = max(ss.busy_until, current_time)
        if ss.busy_until > current_time:
            # Charger still in use — buses must wait
            return

        # ── Pick highest-priority bus from queue ────────────────────
        best_idx = 0
        best_priority = -float("inf")

        for i, (arrival_min, bus_id) in enumerate(ss.queue):
            bs = bus_states[bus_id]
            wait_at_station = current_time - arrival_min

            total_priority = 0.0
            weight_map = {
                "individual": weights.individual,
                "operator": weights.operator,
                "overall": weights.overall,
            }
            for rule in self.rules:
                w = weight_map.get(rule.name(), 0.0)
                if w > 0:
                    score = rule.priority_score(
                        bus_id, bs.bus.operator,
                        wait_at_station, context,
                    )
                    total_priority += w * score

            # Tiny tie-breaker: earlier arrival wins
            total_priority += (1.0 / (1.0 + arrival_min)) * 0.001

            if total_priority > best_priority:
                best_priority = total_priority
                best_idx = i

        # Remove chosen bus from queue
        arrival_min, bus_id = ss.queue.pop(best_idx)
        bs = bus_states[bus_id]

        wait = current_time - arrival_min
        bs.total_wait_min += wait

        # Update context
        context.bus_total_waits[bus_id] = bs.total_wait_min
        op = bs.bus.operator
        context.operator_total_waits[op] = context.operator_total_waits.get(op, 0) + wait
        context.total_system_wait += wait

        # Start charging
        charge_end = current_time + fleet.charging_time_min
        ss.busy_until = charge_end

        # Record charging event
        ce = ChargingEvent(
            station_id=ss.station_id,
            arrival_time_min=arrival_min,
            queue_start_min=arrival_min,
            charging_start_min=current_time,
            charging_end_min=charge_end,
            wait_min=wait,
        )
        bs.charging_events.append(ce)

        # Record station log
        ss.log.append(StationLogEntry(
            bus_id=bus_id,
            operator=bs.bus.operator,
            direction=bs.bus.direction,
            arrival_min=arrival_min,
            charging_start_min=current_time,
            charging_end_min=charge_end,
            wait_min=wait,
        ))

        # Schedule finish event
        heapq.heappush(event_heap, SimEvent(
            time_min=charge_end, seq=seq,
            kind=FINISH_CHARGING, bus_id=bus_id,
            station_id=ss.station_id,
        ))

    # ── Result building ─────────────────────────────────────────────────

    def _build_result(
        self,
        scenario: Scenario,
        bus_states: dict[str, BusState],
        station_states: dict[str, StationState],
    ) -> ScheduleResult:
        """Assemble the final ScheduleResult from simulation state."""
        fleet = scenario.fleet
        route = scenario.route

        bus_schedules: dict[str, BusSchedule] = {}
        total_wait = 0.0
        max_wait = 0.0
        op_waits: dict[str, list[float]] = defaultdict(list)

        for bus_id, bs in bus_states.items():
            arrival = bs.stop_events[-1].arrival_min if bs.stop_events else 0
            travel = route.total_distance_km
            travel_min = fleet.travel_time_min(travel)

            sched = BusSchedule(
                bus=bs.bus,
                charging_plan=bs.plan,
                stop_events=bs.stop_events,
                charging_events=bs.charging_events,
                arrival_min=arrival,
                total_travel_min=travel_min,
                total_wait_min=bs.total_wait_min,
                total_charge_min=bs.total_charge_min,
            )
            bus_schedules[bus_id] = sched
            total_wait += bs.total_wait_min
            max_wait = max(max_wait, bs.total_wait_min)
            op_waits[bs.bus.operator].append(bs.total_wait_min)

        station_logs: dict[str, StationLog] = {}
        for sid, ss in station_states.items():
            station_logs[sid] = StationLog(
                station_id=sid,
                entries=sorted(ss.log, key=lambda e: e.charging_start_min),
            )

        op_avg = {
            op: sum(ws) / len(ws) if ws else 0.0
            for op, ws in op_waits.items()
        }

        return ScheduleResult(
            scenario_name=scenario.name,
            bus_schedules=bus_schedules,
            station_logs=station_logs,
            total_wait_min=total_wait,
            max_individual_wait_min=max_wait,
            operator_avg_waits=op_avg,
        )
