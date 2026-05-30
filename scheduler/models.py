"""
Core data models for the Bus Charging Scheduler.

All domain objects are defined here as dataclasses. The scheduler engine,
loader, and UI all import from this single source of truth.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional


# ── Input Models ────────────────────────────────────────────────────────────


@dataclass
class Segment:
    """One leg of the route between two consecutive stops."""
    from_stop: str
    to_stop: str
    distance_km: float


@dataclass
class Route:
    """
    An ordered sequence of stops with distances between them.
    Stops include endpoints (Bengaluru, Kochi) and charging stations (A–D).
    """
    name: str
    stops: list[str]
    segments: list[Segment]

    # ── derived helpers ─────────────────────────────────────────────────

    def distance_between(self, stop_a: str, stop_b: str) -> float:
        """Compute the total distance between two stops on the route."""
        idx_a = self.stops.index(stop_a)
        idx_b = self.stops.index(stop_b)
        if idx_a > idx_b:
            idx_a, idx_b = idx_b, idx_a
        return sum(seg.distance_km for seg in self.segments[idx_a:idx_b])

    def stops_between(self, origin: str, destination: str) -> list[str]:
        """Return intermediate stops (exclusive) between origin and destination."""
        idx_o = self.stops.index(origin)
        idx_d = self.stops.index(destination)
        step = 1 if idx_d > idx_o else -1
        return self.stops[idx_o + step : idx_d : step]

    def ordered_stops(self, direction: str) -> list[str]:
        """Return all stops in travel order for the given direction code.
        
        Direction codes use first letters of endpoints, e.g. 'BK' for
        Bengaluru→Kochi, 'KB' for Kochi→Bengaluru.
        """
        if direction == "BK":
            return list(self.stops)
        else:
            return list(reversed(self.stops))

    @property
    def total_distance_km(self) -> float:
        return sum(seg.distance_km for seg in self.segments)

    @property
    def origin(self) -> str:
        return self.stops[0]

    @property
    def destination(self) -> str:
        return self.stops[-1]


@dataclass
class StationConfig:
    """Configuration for a single charging station."""
    id: str
    chargers: int = 1


@dataclass
class FleetConfig:
    """Physical constants shared by all buses."""
    battery_range_km: float = 240.0
    charging_time_min: float = 25.0
    speed_kmh: float = 60.0

    def travel_time_min(self, distance_km: float) -> float:
        """Minutes to travel a given distance at fleet speed."""
        return (distance_km / self.speed_kmh) * 60


@dataclass
class Weights:
    """
    Tunable weights for the scheduling cost function.
    
    - individual: penalise long waits for any single bus
    - operator:   penalise uneven wait distribution across an operator's fleet
    - overall:    penalise high total wait across the whole network
    """
    individual: float = 1.0
    operator: float = 1.0
    overall: float = 1.0


@dataclass
class Bus:
    """A single bus with its scheduled departure."""
    id: str
    operator: str
    direction: str          # e.g. "BK" or "KB"
    departure_time: str     # "HH:MM" format

    def departure_minutes(self, base_date: str = "2025-01-01") -> float:
        """Convert HH:MM departure to minutes since midnight."""
        h, m = map(int, self.departure_time.split(":"))
        return h * 60 + m


@dataclass
class Scenario:
    """
    Complete description of a scheduling problem.
    
    This is the single input object the scheduler needs. Everything — route
    geometry, fleet physics, station capacities, operator weights, and the
    bus timetable — lives here.
    """
    name: str
    description: str
    route: Route
    fleet: FleetConfig
    stations: list[StationConfig]
    weights: Weights
    buses: list[Bus]

    @property
    def charging_station_ids(self) -> list[str]:
        """IDs of stations that are part of the scheduling problem."""
        return [s.id for s in self.stations]

    @property
    def station_chargers(self) -> dict[str, int]:
        """Map station_id → number of chargers."""
        return {s.id: s.chargers for s in self.stations}


# ── Output Models ───────────────────────────────────────────────────────────


@dataclass
class ChargingEvent:
    """Record of one charging stop for a bus."""
    station_id: str
    arrival_time_min: float     # minutes since midnight
    queue_start_min: float      # when the bus joins the queue (= arrival)
    charging_start_min: float   # when charging actually begins
    charging_end_min: float     # when charging finishes
    wait_min: float             # time spent waiting for the charger

    @property
    def departure_min(self) -> float:
        return self.charging_end_min


@dataclass
class StopEvent:
    """A bus passing through or stopping at any point on the route."""
    stop_id: str
    arrival_min: float
    departure_min: float
    is_charging: bool
    wait_min: float = 0.0
    range_on_arrival_km: float = 0.0


@dataclass
class BusSchedule:
    """Complete scheduled timeline for one bus."""
    bus: Bus
    charging_plan: list[str]            # station IDs where bus charges
    stop_events: list[StopEvent]        # every stop in order
    charging_events: list[ChargingEvent]
    arrival_min: float                  # final arrival in minutes since midnight
    total_travel_min: float             # pure driving time
    total_wait_min: float               # total queuing time
    total_charge_min: float             # total charging time

    @property
    def total_trip_min(self) -> float:
        return self.total_travel_min + self.total_wait_min + self.total_charge_min

    @property
    def departure_min(self) -> float:
        return self.bus.departure_minutes()


@dataclass
class StationLog:
    """Charging log for one station — who charged, in what order."""
    station_id: str
    entries: list[StationLogEntry] = field(default_factory=list)


@dataclass
class StationLogEntry:
    """One bus's usage of a station charger."""
    bus_id: str
    operator: str
    direction: str
    arrival_min: float
    charging_start_min: float
    charging_end_min: float
    wait_min: float


@dataclass
class ScheduleResult:
    """Complete output of the scheduler."""
    scenario_name: str
    bus_schedules: dict[str, BusSchedule]    # bus_id → schedule
    station_logs: dict[str, StationLog]      # station_id → log
    total_wait_min: float
    max_individual_wait_min: float
    operator_avg_waits: dict[str, float]     # operator → avg wait
