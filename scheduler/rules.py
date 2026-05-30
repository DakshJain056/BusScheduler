"""
Pluggable scheduling rules.

Each Rule contributes a priority score when the engine must decide which
waiting bus charges next.  Rules are additive: the engine computes

    total_priority = Σ  weight_i × rule_i.priority(bus, context)

and the bus with the highest total charges first.

To add a new rule:
  1. Subclass Rule
  2. Implement `name` and `priority_score`
  3. Register it in the engine's rule list
  4. Add a corresponding weight to the scenario's weights dict
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class SchedulingContext:
    """
    Snapshot of the simulation state, passed to rules for decision-making.
    """
    bus_total_waits: dict[str, float] = field(default_factory=dict)
    """bus_id → cumulative wait minutes so far"""

    operator_total_waits: dict[str, float] = field(default_factory=dict)
    """operator → cumulative wait minutes across all their buses"""

    operator_bus_counts: dict[str, int] = field(default_factory=dict)
    """operator → number of buses belonging to this operator"""

    current_time_min: float = 0.0
    """Simulation clock in minutes since midnight"""

    total_system_wait: float = 0.0
    """Sum of all wait minutes across all buses"""


class Rule(ABC):
    """
    Base class for scheduling priority rules.

    Higher priority_score → bus charges sooner when multiple buses
    are waiting at the same station.
    """

    @abstractmethod
    def name(self) -> str:
        """Unique name matching the weight key in Weights."""
        ...

    @abstractmethod
    def priority_score(
        self,
        bus_id: str,
        operator: str,
        wait_at_station_min: float,
        context: SchedulingContext,
    ) -> float:
        """Compute a priority contribution for the given bus."""
        ...


# ── Built-in rules ──────────────────────────────────────────────────────────


class IndividualFairnessRule(Rule):
    """
    Prioritise buses that have already waited the most.

    Effect: no single bus accumulates an outsized delay — the bus
    with the worst day so far gets bumped to the front.
    """

    def name(self) -> str:
        return "individual"

    def priority_score(
        self, bus_id, operator, wait_at_station_min, context
    ) -> float:
        return context.bus_total_waits.get(bus_id, 0.0)


class OperatorFairnessRule(Rule):
    """
    Prioritise buses from operators whose fleet has the highest
    average wait.

    Effect: one operator's buses don't get systematically starved
    when another operator dominates the fleet.
    """

    def name(self) -> str:
        return "operator"

    def priority_score(
        self, bus_id, operator, wait_at_station_min, context
    ) -> float:
        total = context.operator_total_waits.get(operator, 0.0)
        count = context.operator_bus_counts.get(operator, 1)
        return total / count


class OverallEfficiencyRule(Rule):
    """
    Prioritise buses by how long they've waited at *this* station
    (essentially FIFO).

    Effect: minimises total idle time across the system — classic
    first-come-first-served is optimal for average wait in a
    single-server queue.
    """

    def name(self) -> str:
        return "overall"

    def priority_score(
        self, bus_id, operator, wait_at_station_min, context
    ) -> float:
        return wait_at_station_min


# ── Rule registry ───────────────────────────────────────────────────────────

DEFAULT_RULES: list[Rule] = [
    IndividualFairnessRule(),
    OperatorFairnessRule(),
    OverallEfficiencyRule(),
]


def get_default_rules() -> list[Rule]:
    """Return a fresh copy of the default rule set."""
    return list(DEFAULT_RULES)
