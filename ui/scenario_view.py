"""
Scenario input display — shows raw data and a readable table.
"""

from __future__ import annotations

import streamlit as st
import pandas as pd

from scheduler.models import Scenario


def render_scenario_input(scenario: Scenario) -> None:
    """Display the scenario's input data in a readable format."""

    # ── Description ─────────────────────────────────────────────────────
    st.markdown(f"*{scenario.description}*")

    # ── Route info ──────────────────────────────────────────────────────
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("##### Route")
        segments_text = ""
        for seg in scenario.route.segments:
            segments_text += f"- **{seg.from_stop} → {seg.to_stop}**: {seg.distance_km:.0f} km\n"
        segments_text += f"\n**Total: {scenario.route.total_distance_km:.0f} km**"
        st.markdown(segments_text)

    with col2:
        st.markdown("##### Fleet Config")
        st.markdown(f"""
- **Battery range**: {scenario.fleet.battery_range_km:.0f} km
- **Charging time**: {scenario.fleet.charging_time_min:.0f} min
- **Speed**: {scenario.fleet.speed_kmh:.0f} km/h
""")

    with col3:
        st.markdown("##### Weights")
        st.markdown(f"""
- **Individual**: {scenario.weights.individual}
- **Operator**: {scenario.weights.operator}
- **Overall**: {scenario.weights.overall}
""")
        st.markdown("##### Stations")
        for s in scenario.stations:
            st.markdown(f"- **{s.id}**: {s.chargers} charger(s)")

    # ── Bus table ───────────────────────────────────────────────────────
    st.markdown("##### Departure Schedule")
    
    rows = []
    for bus in scenario.buses:
        direction_label = (
            "Bengaluru → Kochi" if bus.direction == "BK"
            else "Kochi → Bengaluru"
        )
        rows.append({
            "Bus ID": bus.id,
            "Operator": bus.operator.upper(),
            "Direction": direction_label,
            "Departure": bus.departure_time,
        })

    df = pd.DataFrame(rows)
    
    # Split by direction for side-by-side display
    bk = df[df["Direction"] == "Bengaluru → Kochi"].reset_index(drop=True)
    kb = df[df["Direction"] == "Kochi → Bengaluru"].reset_index(drop=True)
    
    col_bk, col_kb = st.columns(2)
    with col_bk:
        st.markdown("**Bengaluru → Kochi**")
        st.dataframe(
            bk[["Bus ID", "Operator", "Departure"]],
            use_container_width=True,
            hide_index=True,
        )
    with col_kb:
        st.markdown("**Kochi → Bengaluru**")
        st.dataframe(
            kb[["Bus ID", "Operator", "Departure"]],
            use_container_width=True,
            hide_index=True,
        )
