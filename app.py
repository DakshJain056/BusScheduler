"""
Bus Charging Scheduler — Streamlit Application

Single-page app: pick a scenario → see the input → see the schedule.
"""

import streamlit as st

from scheduler.loader import load_all_scenarios
from scheduler.engine import SchedulerEngine
from scheduler.rules import get_default_rules
from scheduler.validator import validate

from ui.scenario_view import render_scenario_input
from ui.bus_timetable import render_bus_timetable
from ui.station_view import render_station_view


# ── Page config ─────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Bus Charging Scheduler",
    page_icon="bus",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Custom styling ──────────────────────────────────────────────────────────

st.markdown("""
<style>
    /* Header gradient */
    .main-header {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
        padding: 1.5rem 2rem;
        border-radius: 12px;
        margin-bottom: 1.5rem;
        color: white;
    }
    .main-header h1 {
        margin: 0;
        font-size: 2rem;
        font-weight: 700;
        color: white;
    }
    .main-header p {
        margin: 0.25rem 0 0 0;
        opacity: 0.8;
        font-size: 0.95rem;
        color: #e0e0e0;
    }

    /* Metric cards */
    [data-testid="stMetric"] {
        background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);
        border: 1px solid #dee2e6;
        border-radius: 10px;
        padding: 0.75rem 1rem;
    }
    [data-testid="stMetricLabel"] {
        font-weight: 600;
        font-size: 0.8rem;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }

    /* Expander styling */
    .streamlit-expanderHeader {
        font-size: 0.95rem;
        font-weight: 500;
    }

    /* Tab styling */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
    }
    .stTabs [data-baseweb="tab"] {
        padding: 8px 20px;
        border-radius: 8px 8px 0 0;
    }

    /* Validation badge */
    .validation-pass {
        background: #d4edda;
        color: #155724;
        padding: 0.5rem 1rem;
        border-radius: 8px;
        border: 1px solid #c3e6cb;
        font-weight: 600;
    }
    .validation-fail {
        background: #f8d7da;
        color: #721c24;
        padding: 0.5rem 1rem;
        border-radius: 8px;
        border: 1px solid #f5c6cb;
        font-weight: 600;
    }
</style>
""", unsafe_allow_html=True)


# ── Header ──────────────────────────────────────────────────────────────────

st.markdown("""
<div class="main-header">
    <h1>Bus Charging Scheduler</h1>
    <p>Discrete-event simulation with tunable priority rules · Bengaluru ↔ Kochi corridor</p>
</div>
""", unsafe_allow_html=True)


# ── Load scenarios ──────────────────────────────────────────────────────────

@st.cache_data
def get_scenarios():
    return load_all_scenarios()

scenarios = get_scenarios()

if not scenarios:
    st.error("No scenarios found in `scenarios/` directory.")
    st.stop()


# ── Scenario dropdown ───────────────────────────────────────────────────────

scenario_names = list(scenarios.keys())
selected_name = st.selectbox(
    "Select a scenario",
    scenario_names,
    index=0,
    help="Choose a scenario to schedule. Each defines a different departure pattern and weight configuration.",
)

scenario = scenarios[selected_name]

# ── Run scheduler ───────────────────────────────────────────────────────────

@st.cache_data
def run_scheduler(scenario_name):
    """Run the scheduler (cached by scenario name)."""
    sc = scenarios[scenario_name]
    engine = SchedulerEngine(rules=get_default_rules())
    result = engine.run(sc)
    return result

result = run_scheduler(selected_name)

# ── Validation ──────────────────────────────────────────────────────────────

errors = validate(scenario, result)
if not errors:
    st.markdown(
        '<div class="validation-pass">Schedule valid — all hard constraints satisfied</div>',
        unsafe_allow_html=True,
    )
else:
    st.markdown(
        '<div class="validation-fail">Validation errors found</div>',
        unsafe_allow_html=True,
    )
    for err in errors:
        st.error(f"**{err.bus_id}**: {err.message}")

st.markdown("")

# ── Tabs ────────────────────────────────────────────────────────────────────

tab_input, tab_buses, tab_stations = st.tabs([
    "Scenario Input",
    "Per-Bus Timetable",
    "Per-Station View",
])

with tab_input:
    render_scenario_input(scenario)

with tab_buses:
    render_bus_timetable(scenario, result)

with tab_stations:
    render_station_view(scenario, result)
