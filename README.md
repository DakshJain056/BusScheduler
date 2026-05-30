# Bus Charging Scheduler

A discrete-event simulation scheduler for electric bus charging on the Bengaluru–Kochi corridor. Built with Python + Streamlit.

## Live Demo

[Hosted on Streamlit Community Cloud](#) *(update with your hosted link)*

## Project Structure

```
BusScheduler/
├── app.py                          # Streamlit entry point
├── requirements.txt                # Python dependencies
├── README.md
├── ARCHITECTURE.md                 # Design decisions & extensibility
├── scheduler/
│   ├── models.py                   # Core data models (dataclasses)
│   ├── loader.py                   # YAML → Scenario loader
│   ├── planner.py                  # Valid charging plan enumeration
│   ├── engine.py                   # Discrete-event simulation engine
│   ├── rules.py                    # Pluggable priority rules
│   └── validator.py                # Hard-constraint validation
├── scenarios/                      # 5 scenario data files (YAML)
│   ├── scenario_1_even_spacing.yaml
│   ├── scenario_2_bunched_start.yaml
│   ├── scenario_3_asymmetric_load.yaml
│   ├── scenario_4_operator_heavy.yaml
│   └── scenario_5_worst_case.yaml
└── ui/                             # Streamlit UI components
    ├── scenario_view.py            # Input display
    ├── bus_timetable.py            # Per-bus timeline
    └── station_view.py             # Per-station charging log
```

## Running Locally

```bash
# 1. Clone
git clone https://github.com/<your-username>/BusScheduler.git
cd BusScheduler

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run
streamlit run app.py
```

The app opens at `http://localhost:8501`.

## How to Change a Weight

Weights live in each scenario's YAML file under the `weights:` key:

```yaml
# scenarios/scenario_4_operator_heavy.yaml
weights:
  individual: 1.0
  operator: 2.0      # ← change this value
  overall: 1.0
```

Change a number, reload the app — the scheduler re-runs with the new weights. No code changes needed.

**Programmatically:**

```python
from scheduler.loader import load_scenario
from scheduler.engine import SchedulerEngine

scenario = load_scenario("scenarios/scenario_1_even_spacing.yaml")
scenario.weights.operator = 3.0  # boost operator fairness
result = SchedulerEngine().run(scenario)
```

## How to Add a New Rule

1. Create a new `Rule` subclass in `scheduler/rules.py`:

```python
class PriorityBusRule(Rule):
    """Give priority buses (e.g. express services) higher charging priority."""

    def name(self) -> str:
        return "priority_bus"

    def priority_score(self, bus_id, operator, wait_at_station_min, context):
        # Buses marked as priority get a large bonus
        return 100.0 if context.bus_priorities.get(bus_id) else 0.0
```

2. Add the weight to your scenario YAML:

```yaml
weights:
  individual: 1.0
  operator: 1.0
  overall: 1.0
  priority_bus: 2.0     # new weight
```

3. Register the rule when creating the engine:

```python
from scheduler.rules import get_default_rules, PriorityBusRule

rules = get_default_rules() + [PriorityBusRule()]
engine = SchedulerEngine(rules=rules)
```

That's it — no changes to the engine, simulation, or UI code.

## Validation

The scheduler automatically validates every result against hard constraints:
- No bus exceeds 240 km between charges
- No two buses overlap on the same charger
- Stations are visited in route order (no backtracking)

Validation results are shown in the UI and can be run programmatically:

```python
from scheduler.validator import validate
errors = validate(scenario, result)
assert len(errors) == 0
```
