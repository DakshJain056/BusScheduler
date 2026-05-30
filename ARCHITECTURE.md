# Architecture

## Scheduling Approach

### Why Discrete-Event Simulation + Pluggable Cost Functions

The scheduler is a **greedy discrete-event simulation** with a **pluggable cost-function system** for conflict resolution.

**Why this is the right fit:**

| Alternative | Why I didn't use it |
|---|---|
| **ILP / constraint solver** | Correct for small instances but brittle: every new rule = new constraint formulation. Doesn't scale gracefully when the problem shape changes (new station types, variable charging speeds, etc.). |
| **Genetic / metaheuristic** | Overkill for 20 buses, unpredictable runtime, hard to explain results in an operational setting. |
| **Pure FIFO simulation** | Too rigid — no room for fairness weights or operator-level optimization. |
| **DES + cost functions** | Naturally handles time, queuing, and resource contention. Adding a new rule = writing one class. Changing a weight = editing one number. Scales linearly with buses. Results are deterministic and explainable. |

### Algorithm

The scheduler runs in two phases:

#### Phase 1: Plan Assignment (which stations each bus uses)
For each bus, the engine:
1. Enumerates all valid subsets of charging stations (respecting the 240 km range constraint)
2. Scores each plan on:
   - **Charging overhead**: fewer stops = less total time (25 min × stops)
   - **Leg balance**: prefer evenly-spaced stops for range margin
   - **Station load**: strongly penalise plans that use already-busy stations
   - **Contention forecast**: estimate arrival times and penalise plans where this bus would arrive close to other buses already scheduled at the same station
3. Picks the lowest-cost plan

Buses are processed in departure order. As each bus is assigned, the station load and estimated arrival times are updated, so later buses naturally gravitate toward under-used stations and time slots.

#### Phase 2: Simulation (conflict resolution and timeline computation)
A priority-queue-driven event loop processes:
- `ARRIVE_STATION`: bus arrives at a stop. If it needs to charge and the charger is free, it starts immediately. If the charger is busy, it joins the station queue.
- `FINISH_CHARGING`: bus finishes. The engine picks the next bus from the queue using the **weighted priority function** and starts it.

**Priority function** (who charges next among waiting buses):

```
urgency(bus) = w_individual × bus.accumulated_wait
             + w_operator  × avg_wait(bus.operator)
             + w_overall   × wait_at_this_station(bus)
```

The bus with the **highest urgency** charges first.

- **High `w_individual`** → no single bus gets starved; the one who's waited the most overall gets priority
- **High `w_operator`** → fleets are treated equitably; an operator whose buses have been delayed gets a boost
- **High `w_overall`** → FIFO-like; minimises total system idle time

---

## Data Structure Design

### Scenario Format (YAML)

A scenario file is the **single source of truth** for one scheduling problem. It contains everything the scheduler needs:

```yaml
meta:
  name: "Scenario 1 — Even Spacing"
  description: "Baseline: 15-min spacing"

route:
  name: "Bengaluru-Kochi"
  stops: [Bengaluru, A, B, C, D, Kochi]    # ordered, any length
  segments:
    - { from: Bengaluru, to: A, distance_km: 100 }
    - { from: A, to: B, distance_km: 120 }
    # ... any number of segments

fleet:
  battery_range_km: 240
  charging_time_min: 25
  speed_kmh: 60

stations:
  - { id: A, chargers: 1 }     # charger count is per-station
  - { id: B, chargers: 1 }
  # ...

weights:
  individual: 1.0
  operator: 1.0
  overall: 1.0
  # add any new weight keys here

buses:
  - { id: bus-BK-01, operator: kpn, direction: BK, departure: "19:00" }
  # ...
```

### Why YAML
- Human-readable and diff-friendly (version control)
- Easy to edit without tooling
- Maps directly to Python dicts/dataclasses
- Supports comments for documentation

### Internal Models

All data flows through typed dataclasses in `scheduler/models.py`:

**Input**: `Scenario` → `Route`, `FleetConfig`, `StationConfig`, `Weights`, `Bus`
**Output**: `ScheduleResult` → `BusSchedule` (per-bus timeline), `StationLog` (per-station charging order)

---

## Anticipated Future Changes

This is the list of changes I considered when designing the data structure, and how the current design handles each **without code changes**:

### 1. More stations on the route
**How it's handled**: `route.stops` is a list; `stations` is a list. Add entries to both. The planner automatically enumerates valid plans for any number of stations via combinatorial enumeration. No code changes.

### 2. More chargers per station
**How it's handled**: Each station has a `chargers` field. The engine's `StationState` already tracks `busy_until` per charger slot. Extending to N chargers requires a small change to track N `busy_until` values (currently tracks 1). The data model is already ready.

### 3. Different battery ranges per bus
**How it's handled**: Move `battery_range_km` from `FleetConfig` to `Bus`. The planner and engine read range per-bus. Data model change only.

### 4. Variable charging speeds / partial charging
**How it's handled**: Add `charging_speed_kw` to `StationConfig` and `battery_capacity_kwh` to `Bus`. Charging time becomes `capacity / speed`. The 25-minute fixed time becomes a computed value. The engine's charging logic is isolated in one place.

### 5. Multiple routes sharing stations
**How it's handled**: The `Route` model already supports arbitrary stop sequences. Two routes could share stations (e.g., station B on both a Bengaluru-Kochi and a Bengaluru-Mysore route). The engine resolves conflicts at the station level — it doesn't care which route a bus is on.

### 6. More operators
**How it's handled**: `operator` is a free-form string on `Bus`. Add any operator name. The `OperatorFairnessRule` dynamically groups by operator — no registration needed.

### 7. Priority buses (express, emergency)
**How it's handled**: Add a `priority: int` field to `Bus` in YAML. Write a `PriorityBusRule` (~10 lines). Add a `priority_bus` weight. No engine changes. See README for code example.

### 8. Time-of-day electricity pricing
**How it's handled**: Add a pricing schedule to the scenario. Write a `CostAwareRule` that gives priority to buses charging during off-peak hours (lower priority = "come back later if you can"). Add a weight for it. The rule checks `context.current_time_min` against the pricing schedule.

### 9. Driver shift constraints
**How it's handled**: Add `max_trip_duration_min` to `Bus`. Write a validation rule or a `DriverShiftRule` that penalises plans pushing a bus past its shift limit. The validator already runs post-simulation.

### 10. Different speeds per segment (traffic, terrain)
**How it's handled**: Add `speed_kmh` to `Segment`. The `FleetConfig.travel_time_min()` method becomes segment-aware. All other code reads travel time through this single function.

### 11. Bidirectional routes with different segment distances
**How it's handled**: The `Route.distance_between()` method computes distance from the segment list. If distances differ by direction, model the route with direction-specific segments or two Route objects.

### 12. Real-time rescheduling (bus breakdown, delay)
**How it's handled**: The engine is stateless — call `engine.run(modified_scenario)` with updated departure times or removed buses. The simulation re-runs in milliseconds. No state to corrupt or roll back.

### 13. Weighted preferences per operator (SLAs)
**How it's handled**: Add per-operator weight overrides to the scenario. The `OperatorFairnessRule` can read operator-specific multipliers from the context.

### 14. Station maintenance windows
**How it's handled**: Add `unavailable_windows: [{from: "22:00", to: "06:00"}]` to `StationConfig`. The engine checks availability before allowing charging. Buses arriving during maintenance wait until the window ends.

---

## How to Change a Weight

**In a YAML file** (the intended way):

```yaml
# scenarios/scenario_4_operator_heavy.yaml
weights:
  individual: 1.0
  operator: 2.0      # ← change this single value
  overall: 1.0
```

Reload the Streamlit app. The scheduler re-runs with the new weights.

**Programmatically:**

```python
scenario = load_scenario("scenarios/scenario_1_even_spacing.yaml")
scenario.weights.operator = 3.0
result = SchedulerEngine().run(scenario)
```

Weights affect the **priority function** in the conflict-resolution queue. Higher weight → that rule has more influence over who charges first.

---

## How to Add a New Rule

1. **Define the rule** in `scheduler/rules.py`:

```python
class PriorityBusRule(Rule):
    """Express/emergency buses get charging priority."""

    def name(self) -> str:
        return "priority_bus"

    def priority_score(self, bus_id, operator, wait_at_station_min, context):
        # Assume context has been extended with bus priority data
        is_priority = bus_id.startswith("bus-EX")  # or read from context
        return 50.0 if is_priority else 0.0
```

2. **Add a weight** to the scenario YAML:

```yaml
weights:
  individual: 1.0
  operator: 1.0
  overall: 1.0
  priority_bus: 2.0    # ← new weight
```

3. **Register** when creating the engine:

```python
rules = get_default_rules() + [PriorityBusRule()]
engine = SchedulerEngine(rules=rules)
```

The engine dynamically looks up `weight_map[rule.name()]`. No changes to the simulation loop.

**Lines of code to add a rule**: ~15 (class definition + registration).

---

## Assumptions

1. **Speed is constant**: All buses travel at 60 km/h with no traffic variation. This is configurable in `fleet.speed_kmh`.

2. **Charging is always to full**: No partial charging. The 25-minute fixed duration is a simplification; the data model supports variable charging via station/bus attributes.

3. **No queuing capacity limit**: Stations can hold unlimited waiting buses. In practice, physical space limits would need a capacity field.

4. **Departure times are fixed**: A bus departs at its scheduled time regardless of conditions. No delay propagation from upstream.

5. **Endpoints charge for free**: Bengaluru and Kochi have slow chargers that aren't part of the scheduling problem. Buses always start with full charge.

6. **Single route**: All buses share one route (Bengaluru ↔ Kochi). The data model supports multiple routes but the current UI assumes one.

7. **No overtaking**: Buses on the same route don't interact except at charging stations. A faster bus can't pass a slower one (all same speed anyway).

8. **Time is in minutes since midnight**: Events occurring after midnight are represented as minutes > 1440 (e.g., 01:00 = 1500 min for a 19:00 base). The UI handles day-rollover display.

9. **Plan assignment is greedy**: The scheduler assigns plans in departure order. This is a heuristic — a global optimizer might find slightly better assignments, but the greedy approach is fast, deterministic, and produces good results.

10. **Queue priority is evaluated at dequeue time**: When a charger becomes free, the engine evaluates all waiting buses' priority scores at that moment. This means a bus's priority can change while waiting (e.g., if its operator's total wait increases from other stations).
