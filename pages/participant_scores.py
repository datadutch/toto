import streamlit as st
import pandas as pd
from src.db import (
    init_fantasy_tables, load_stages, load_stage_results, calculate_scores,
    calculate_stage_breakdown, load_team_by_account, STAGE_POINTS, _connect,
)
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

racing_stages = [s for s in stages if s["Stage"] != "Rest Day"]
completed_stage_names = [s["Stage"] for s in stages if load_stage_results(DB_PATH, selected_race, s["Stage"])]

if not completed_stage_names:
    st.info(t("no_results_this_race"))
    st.stop()

my_team = load_team_by_account(DB_PATH, account["id"], selected_race)

st.caption(f"{len(completed_stage_names)} / {len(racing_stages)} etappes voltooid")

tab_totals, tab_stage, tab_riders = st.tabs([
    "🏆 Totale team scores",
    "🏁 Stage resultaat",
    "🚴 Renners totaal",
])

# ── Tab 1: Totale team scores ─────────────────────────────────────────────────
with tab_totals:
    try:
        scores = calculate_scores(DB_PATH, selected_race)
        if scores:
            df = pd.DataFrame(scores).sort_values("Total", ascending=False).reset_index(drop=True)
            df.index = df.index + 1
            st.dataframe(df, use_container_width=True)
        else:
            st.info("No scores available yet.")
    except Exception as e:
        st.error(f"Error loading scores: {e}")

# ── Tab 2: Stage resultaat ────────────────────────────────────────────────────
with tab_stage:
    selected_stage = st.selectbox("Kies een etappe", completed_stage_names, key="scores_stage_select")

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

    my_rider_urls = set(my_team["rider_urls"]) if my_team else set()

    if stage_rows:
        rows = []
        for pos, rider_url, name, nat, team in stage_rows:
            pts = STAGE_POINTS.get(pos, 0)
            in_team = rider_url in my_rider_urls
            rows.append({
                "Pos": pos,
                "Renner": ("✅ " if in_team else "") + (name or "?"),
                "NAT": nat or "?",
                "Ploeg": team or "?",
                "Punten": pts,
            })
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

        if my_team:
            my_pts = sum(r["Punten"] for r in rows if r["Renner"].startswith("✅"))
            st.metric("Jouw punten deze etappe", my_pts)
    else:
        st.info(t("no_stage_results"))

# ── Tab 3: Totale renners scores ──────────────────────────────────────────────
with tab_riders:
    if not my_team:
        st.info(t("participant_no_team_registered"))
    else:
        breakdown = calculate_stage_breakdown(DB_PATH, selected_race, my_team["id"])
        if not breakdown:
            st.info("Nog geen punten voor jouw renners.")
        else:
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
