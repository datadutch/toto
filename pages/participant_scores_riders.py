import streamlit as st
import pandas as pd
from src.db import (
    init_fantasy_tables, load_stages, load_stage_results,
    load_team_by_account, calculate_stage_breakdown,
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
if not breakdown:
    st.info(t("no_points_yet"))
    st.stop()

df_bd = pd.DataFrame(breakdown)
df_totals = (
    df_bd.groupby("Rider", as_index=False)["Points"]
    .sum()
    .sort_values("Points", ascending=False)
    .reset_index(drop=True)
    .rename(columns={"Rider": t("col_rider"), "Points": t("col_total_points")})
)
df_totals.index = df_totals.index + 1
st.dataframe(df_totals, height=len(df_totals) * 35 + 41, use_container_width=True)
st.metric(t("total_points_your_team"), int(df_bd["Points"].sum()))
