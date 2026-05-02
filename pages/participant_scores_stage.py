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
st.subheader(f"{t('scores_nav_stage')} — {selected_race}")

stage_key = f"scores_stage_select_{selected_race}"
if stage_key not in st.session_state:
    st.session_state[stage_key] = completed[-1]

col_select, col_caption, col_metric = st.columns([3, 2, 2])
selected_stage = col_select.selectbox(t("select_stage"), completed, key=stage_key, label_visibility="collapsed")
col_caption.caption(f"{len(completed)} / {len(racing_stages)} {t('stages_completed')}")
metric_slot = col_metric.empty()

conn = _connect(DB_PATH, read_only=True)
try:
    stage_rows = conn.execute(
        """SELECT sr.position, sr.rider_url, r.name, r.nationality, r.team_name
           FROM stage_results sr
           LEFT JOIN riders r ON r.rider_url = sr.rider_url
           WHERE sr.race_name = ? AND sr.stage_name = ?
           ORDER BY sr.position""",
        [selected_race, selected_stage],
    ).fetchall()
finally:
    conn.close()

if stage_rows:
    col_pos = t("col_pos")
    col_sel = t("col_selected")
    col_rider = t("col_rider")
    col_team = t("col_team")
    col_points = t("col_points")

    rows = []
    for pos, rider_url, name, nat, team in stage_rows:
        pts = STAGE_POINTS.get(pos, 0)
        in_team = rider_url in my_rider_urls
        rows.append({
            col_pos: str(pos),
            col_sel: "✔" if in_team else "",
            col_rider: name or "?",
            col_team: team or "?",
            col_points: pts,
        })

    df = pd.DataFrame(rows)

    styled = df.style.apply(
        lambda row: ["background-color: #d4edd4; color: black"] * len(row) if row[col_sel] == "✔" else [""] * len(row),
        axis=1,
    )

    st.dataframe(
        styled,
        hide_index=True,
        height=len(df) * 35 + 41,
        use_container_width=True,
        column_config={
            col_pos: st.column_config.TextColumn(label=col_pos, width="small"),
            col_sel: st.column_config.TextColumn(label=col_sel, width="small"),
        },
    )

    if my_team:
        my_pts = sum(r[col_points] for r in rows if r[col_sel] == "✔")
        metric_slot.metric(t("your_points_this_stage"), my_pts)
else:
    st.info(t("no_stage_results"))
