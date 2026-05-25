import streamlit as st
import pandas as pd
from src.db import (
    init_fantasy_tables, load_stages, load_stage_results,
    load_team_by_account, calculate_stage_breakdown, _connect,
)
from src.participant_common import (
    DB_PATH, t,
    setup_page, render_header, render_sidebar, render_scores_nav,
    render_name_change_modal, load_race_selector,
)

account = setup_page(layout="wide")
init_fantasy_tables(DB_PATH)

render_header(account)
render_sidebar(account, "scores")

st.divider()
render_name_change_modal(account)

_, selected_race, _, _ = load_race_selector()

st.divider()

stages = load_stages(DB_PATH, selected_race)
if not stages:
    st.info(t("no_stages_available"))
    st.stop()

racing_stages = [s for s in stages if s["Stage"] != "Rest Day"]
completed = [s["Stage"] for s in stages if load_stage_results(DB_PATH, selected_race, s["Stage"])]

if not completed:
    st.info(t("no_results_this_race"))
    st.stop()

my_team = load_team_by_account(DB_PATH, account["id"], selected_race)

render_scores_nav("riders")
st.subheader(f"{t('scores_nav_riders')} — {selected_race}")
st.caption(f"{len(completed)} / {len(racing_stages)} {t('stages_completed')}")

if not my_team:
    st.info(t("participant_no_team_registered"))
    st.stop()

breakdown = calculate_stage_breakdown(DB_PATH, selected_race, my_team["id"])

# Build scored totals
if breakdown:
    df_bd = pd.DataFrame(breakdown)
    df_scored = df_bd.groupby("Rider", as_index=False)["Points"].sum()
    scored_names = set(df_scored["Rider"])
    total_pts = int(df_bd["Points"].sum())
else:
    df_scored = pd.DataFrame(columns=["Rider", "Points"])
    scored_names = set()
    total_pts = 0

# Fetch names for all team riders to include 0-point riders
rider_urls = my_team.get("rider_urls", [])
if rider_urls:
    conn = _connect(DB_PATH, read_only=True)
    try:
        placeholders = ", ".join("?" * len(rider_urls))
        name_rows = conn.execute(
            f"SELECT name FROM riders WHERE rider_url IN ({placeholders})",
            rider_urls,
        ).fetchall()
    finally:
        conn.close()
    all_names = [r[0] for r in name_rows if r[0]]
else:
    all_names = []

zero_rows = [{"Rider": n, "Points": 0} for n in all_names if n not in scored_names]
df_all = pd.concat([df_scored, pd.DataFrame(zero_rows)], ignore_index=True)

col_rider = t("col_rider")
col_total = t("col_total_points")

df_totals = (
    df_all.sort_values("Points", ascending=False)
    .reset_index(drop=True)
    .rename(columns={"Rider": col_rider, "Points": col_total})
)
df_totals.index = df_totals.index + 1

styled = df_totals.style.apply(
    lambda row: ["background-color: #fde8e8; color: black"] * len(row) if row[col_total] == 0 else [""] * len(row),
    axis=1,
)
st.dataframe(styled, height=len(df_totals) * 35 + 41, width="stretch")
st.metric(t("total_points_your_team"), total_pts)
