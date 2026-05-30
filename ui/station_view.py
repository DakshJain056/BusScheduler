"""
Per-station view — shows the charging order at each station.
"""

from __future__ import annotations

import streamlit as st
import pandas as pd

from scheduler.models import ScheduleResult, Scenario


def _min_to_time(minutes: float) -> str:
    """Convert minutes since midnight to HH:MM format."""
    h = int(minutes // 60) % 24
    m = int(minutes % 60)
    day = int(minutes // (24 * 60))
    suffix = "" if day == 0 else f" (+{day}d)"
    return f"{h:02d}:{m:02d}{suffix}"


def render_station_view(scenario: Scenario, result: ScheduleResult) -> None:
    """Display per-station charging order and utilisation."""

    station_ids = scenario.charging_station_ids

    # ── Station utilisation summary ─────────────────────────────────────
    cols = st.columns(len(station_ids))
    for i, sid in enumerate(station_ids):
        log = result.station_logs.get(sid)
        n_charges = len(log.entries) if log else 0
        total_busy = n_charges * scenario.fleet.charging_time_min
        with cols[i]:
            st.metric(f"Station {sid}", f"{n_charges} charges")
            if log and log.entries:
                first = log.entries[0].charging_start_min
                last = log.entries[-1].charging_end_min
                span = last - first
                util = (total_busy / span * 100) if span > 0 else 0
                st.caption(f"Utilisation: {util:.0f}%")

    st.divider()

    # ── Per-station charging log ────────────────────────────────────────
    for sid in station_ids:
        log = result.station_logs.get(sid)
        if not log or not log.entries:
            st.markdown(f"#### Station {sid}")
            st.info("No buses charged here.")
            continue

        st.markdown(f"#### Station {sid}")

        rows = []
        for idx, entry in enumerate(log.entries, 1):
            dir_label = (
                "BK (→ Kochi)" if entry.direction == "BK"
                else "KB (→ Bengaluru)"
            )
            rows.append({
                "#": idx,
                "Bus ID": entry.bus_id,
                "Operator": entry.operator.upper(),
                "Direction": dir_label,
                "Arrived": _min_to_time(entry.arrival_min),
                "Charge Start": _min_to_time(entry.charging_start_min),
                "Charge End": _min_to_time(entry.charging_end_min),
                "Wait (min)": f"{entry.wait_min:.0f}" if entry.wait_min > 0 else "—",
            })

        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True, hide_index=True)

        # Visual timeline (simple text-based Gantt)
        if len(log.entries) > 1:
            _render_station_gantt(log.entries, scenario.fleet.charging_time_min)


def _render_station_gantt(entries, charge_min: float) -> None:
    """Render a simple visual timeline for a station's charger usage."""
    if not entries:
        return

    # Build a compact timeline view
    min_time = min(e.arrival_min for e in entries)
    max_time = max(e.charging_end_min for e in entries)

    chart_data = []
    for entry in entries:
        chart_data.append({
            "Bus": entry.bus_id,
            "Start": entry.charging_start_min - min_time,
            "End": entry.charging_end_min - min_time,
            "Wait Start": entry.arrival_min - min_time,
            "Wait": entry.wait_min,
        })

    # Use a simple bar representation via markdown
    total_span = max_time - min_time
    if total_span <= 0:
        return

    st.caption("Timeline (arrival → wait → charge):")
    for item in chart_data:
        wait_bar = "░" * max(1, int(item["Wait"] / 5)) if item["Wait"] > 0 else ""
        charge_bar = "█" * max(1, int(charge_min / 5))
        offset = " " * int(item["Wait Start"] / 5)
        label = f"`{item['Bus']:12s}` {offset}{wait_bar}{charge_bar}"
        st.markdown(label)
