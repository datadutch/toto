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

account = setup_page()
init_fantasy_tables(DB_PATH)

render_header(account)
render_sidebar(account, "scores")

st.divider()
render_name_change_modal(account)

_, selected_race, _, _ = load_race_selector()

st.divider()

stages = load_stages(DB_PATH, selected_race)
if not stages:
    st.info("No stages available for this race.")
    st.stop()

racing_stages = [s for s in stages if s["Stage"] != "Rest Day"]
completed = [s["Stage"] for s in stages if load_stage_results(DB_PATH, selected_race, s["Stage"])]

if not completed:
    st.info(t("no_results_this_race"))
    st.stop()

my_team = load_team_by_account(DB_PATH, account["id"], selected_race)

render_scores_nav("riders")
st.subheader(f"🚴 Renners totaal — {selected_race}")
st.caption(f"{len(completed)} / {len(racing_stages)} etappes voltooid")

if not my_team:
    st.info(t("participant_no_team_registered"))
    st.stop()

breakdown = calculate_stage_breakdown(DB_PATH, selected_race, my_team["id"])
if not breakdown:
    st.info("Nog geen punten voor jouw renners.")
    st.stop()

df_bd = pd.DataFrame(breakdown)
df_totals = (
    df_bd.groupby("Rider", as_index=False)["Points"]
    .sum()
    .sort_values("Points", ascending=False)
    .reset_index(drop=True)
    .rename(columns={"Rider": "Renner", "Points": "Totaal punten"})
)
df_totals.index = df_totals.index + 1
st.dataframe(df_totals, use_container_width=True)
st.metric("Totale punten jouw team", int(df_bd["Points"].sum()))
