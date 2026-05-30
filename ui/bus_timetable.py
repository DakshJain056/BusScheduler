"""
Per-bus timetable view — full timeline for each bus.
"""

from __future__ import annotations

import streamlit as st
import pandas as pd

from scheduler.models import ScheduleResult, Scenario


def _min_to_time(minutes: float) -> str:
    """Convert minutes since midnight to HH:MM format."""
    h = int(minutes // 60) % 24
    m = int(minutes % 60)
    # Handle next-day times
    day = int(minutes // (24 * 60))
    suffix = "" if day == 0 else f" (+{day}d)"
    return f"{h:02d}:{m:02d}{suffix}"


def render_bus_timetable(scenario: Scenario, result: ScheduleResult) -> None:
    """Display per-bus timeline with charging stops, waits, and arrival."""

    # ── Summary metrics ─────────────────────────────────────────────────
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Buses", len(result.bus_schedules))
    with col2:
        st.metric("Total Wait", f"{result.total_wait_min:.0f} min")
    with col3:
        st.metric("Max Individual Wait", f"{result.max_individual_wait_min:.0f} min")
    with col4:
        avg_wait = result.total_wait_min / max(len(result.bus_schedules), 1)
        st.metric("Avg Wait / Bus", f"{avg_wait:.1f} min")

    # ── Operator breakdown ──────────────────────────────────────────────
    if result.operator_avg_waits:
        st.markdown("##### Operator Average Wait Times")
        op_cols = st.columns(len(result.operator_avg_waits))
        for i, (op, avg) in enumerate(sorted(result.operator_avg_waits.items())):
            with op_cols[i]:
                st.metric(op.upper(), f"{avg:.1f} min")

    st.divider()

    # ── Direction filter ────────────────────────────────────────────────
    direction_filter = st.radio(
        "Filter by direction",
        ["All", "Bengaluru → Kochi", "Kochi → Bengaluru"],
        horizontal=True,
        key="bus_direction_filter",
    )

    # ── Per-bus timetables ──────────────────────────────────────────────
    schedules = sorted(
        result.bus_schedules.values(),
        key=lambda s: (s.bus.direction, s.departure_min),
    )

    for sched in schedules:
        # Apply direction filter
        if direction_filter == "Bengaluru → Kochi" and sched.bus.direction != "BK":
            continue
        if direction_filter == "Kochi → Bengaluru" and sched.bus.direction != "KB":
            continue

        dir_label = (
            "Bengaluru → Kochi" if sched.bus.direction == "BK"
            else "Kochi → Bengaluru"
        )
        wait_badge = ""
        if sched.total_wait_min > 0:
            wait_badge = f"  {sched.total_wait_min:.0f} min wait"

        with st.expander(
            f"**{sched.bus.id}** · {sched.bus.operator.upper()} · "
            f"{dir_label} · Depart {sched.bus.departure_time} · "
            f"Arrive {_min_to_time(sched.arrival_min)}{wait_badge}",
            expanded=False,
        ):
            # Summary row
            scol1, scol2, scol3, scol4 = st.columns(4)
            with scol1:
                st.metric("Charges at", " → ".join(sched.charging_plan) or "None")
            with scol2:
                st.metric("Total Trip", f"{sched.total_trip_min:.0f} min")
            with scol3:
                st.metric("Charging Time", f"{sched.total_charge_min:.0f} min")
            with scol4:
                st.metric("Wait Time", f"{sched.total_wait_min:.0f} min")

            # Timeline table
            timeline_rows = []
            for se in sched.stop_events:
                row = {
                    "Stop": se.stop_id,
                    "Arrival": _min_to_time(se.arrival_min),
                    "Departure": _min_to_time(se.departure_min),
                    "Action": "Charging" if se.is_charging else "Pass-through",
                    "Wait (min)": f"{se.wait_min:.0f}" if se.wait_min > 0 else "—",
                    "Range on Arrival (km)": f"{se.range_on_arrival_km:.0f}",
                }
                timeline_rows.append(row)

            if timeline_rows:
                df = pd.DataFrame(timeline_rows)
                st.dataframe(df, use_container_width=True, hide_index=True)

            # Charging detail
            if sched.charging_events:
                st.markdown("**Charging Details:**")
                for ce in sched.charging_events:
                    wait_text = (
                        f"waited **{ce.wait_min:.0f} min**"
                        if ce.wait_min > 0
                        else "no wait"
                    )
                    st.markdown(
                        f"- **Station {ce.station_id}**: "
                        f"arrived {_min_to_time(ce.arrival_time_min)}, "
                        f"{wait_text}, "
                        f"charged {_min_to_time(ce.charging_start_min)}–"
                        f"{_min_to_time(ce.charging_end_min)}"
                    )
