import streamlit as st
import pandas as pd
from src.db import init_fantasy_tables, load_stages, load_stage_results, calculate_scores
from src.participant_common import (
    DB_PATH, t,
    setup_page, render_header, render_sidebar, render_name_change_modal,
    load_race_selector,
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

stages_with_results = [s for s in stages if load_stage_results(DB_PATH, selected_race, s["Stage"])]

if not stages_with_results:
    st.info(t("no_results_this_race"))
    st.stop()

st.subheader(f"🏆 {t('scores')} — {selected_race}")
st.caption(f"{len(stages_with_results)} / {len([s for s in stages if s['Stage'] != 'Rest Day'])} etappes voltooid")

try:
    scores = calculate_scores(DB_PATH, selected_race)
    if scores:
        df = pd.DataFrame(scores).sort_values("Total", ascending=False).reset_index(drop=True)
        df.index = df.index + 1
        st.dataframe(df[["Team", "Total"]], width="stretch", hide_index=False)
    else:
        st.info("No scores available yet.")
except Exception as e:
    st.error(f"Error loading scores: {e}")
