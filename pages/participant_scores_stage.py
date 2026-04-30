import streamlit as st
import pandas as pd
from src.db import (
    init_fantasy_tables, load_stages, load_stage_results,
    load_team_by_account, STAGE_POINTS, _connect,
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
my_rider_urls = set(my_team["rider_urls"]) if my_team else set()

render_scores_nav("stage")
st.subheader(f"🏁 {t('scores_nav_stage')} — {selected_race}")
st.caption(f"{len(completed)} / {len(racing_stages)} {t('stages_completed')}")

selected_stage = st.selectbox(t("select_stage"), completed, key="scores_stage_select")

conn = _connect(DB_PATH, read_only=True)
try:
    stage_rows = conn.execute(
        """SELECT sr.position, sr.rider_url, r.name, r.nationality, r.team_name
           FROM stage_results sr
           JOIN riders r ON r.rider_url = sr.rider_url
           WHERE sr.race_name = ? AND sr.stage_name = ?
           ORDER BY sr.position""",
        [selected_race, selected_stage],
    ).fetchall()
finally:
    conn.close()

if stage_rows:
    rows = []
    for pos, rider_url, name, nat, team in stage_rows:
        pts = STAGE_POINTS.get(pos, 0)
        in_team = rider_url in my_rider_urls
        rows.append({
            t("col_pos"): pos,
            t("col_rider"): ("✅ " if in_team else "") + (name or "?"),
            t("col_nat"): nat or "?",
            t("col_team"): team or "?",
            t("col_points"): pts,
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

    if my_team:
        col_rider_key = t("col_rider")
        col_points_key = t("col_points")
        my_pts = sum(r[col_points_key] for r in rows if r[col_rider_key].startswith("✅"))
        st.metric(t("your_points_this_stage"), my_pts)
else:
    st.info(t("no_stage_results"))
