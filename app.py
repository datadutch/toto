import os
import duckdb
import streamlit as st
import pandas as pd
from dotenv import load_dotenv
from src.db import (
    init_fantasy_tables, save_fantasy_team, load_fantasy_teams, load_fantasy_team_riders,
    init_stages_table, load_stages,
    init_stage_results_table, save_stage_results, load_stage_results, stages_with_results,
    calculate_scores, calculate_stage_breakdown,
)

load_dotenv()

_TOKEN = os.getenv("MOTHERDUCK_TOKEN")
if _TOKEN:
    DB_PATH = f"md:toto?motherduck_token={_TOKEN}"
    _READ_ONLY = False  # MotherDuck does not support read_only attach
else:
    DB_PATH = os.path.join(os.path.dirname(__file__), "data", "cycling.duckdb")
    _READ_ONLY = True

st.set_page_config(page_title="Cyclist Explorer", page_icon="🚴", layout="wide")
st.title("🚴 Professional Cyclist Explorer")


def get_connection():
    return duckdb.connect(DB_PATH, read_only=_READ_ONLY)


def load_data(name_filter, nationality_filter, team_filter):
    query = "SELECT * FROM riders WHERE 1=1"
    params = []

    if name_filter:
        query += " AND lower(name) LIKE ?"
        params.append(f"%{name_filter.lower()}%")
    if nationality_filter and nationality_filter != "All":
        query += " AND nationality = ?"
        params.append(nationality_filter)
    if team_filter:
        query += " AND lower(team_name) LIKE ?"
        params.append(f"%{team_filter.lower()}%")

    query += " ORDER BY name"
    conn = get_connection()
    try:
        return conn.execute(query, params).df()
    finally:
        conn.close()


# ── Check DB exists ──────────────────────────────────────────────────────────
if not os.path.exists(DB_PATH):
    st.warning("Database not found. Run `python main.py` first to scrape rider data.")
    st.stop()

try:
    _conn = get_connection()
    total = _conn.execute("SELECT count(*) FROM riders").fetchone()[0]
    _conn.close()
except Exception:
    st.error("Could not read from database. Make sure the scraper has run.")
    st.stop()

init_fantasy_tables(DB_PATH)
init_stages_table(DB_PATH)
init_stage_results_table(DB_PATH)

st.caption(f"Database contains **{total:,}** riders")

tab_explorer, tab_team, tab_giro, tab_scores = st.tabs(["🔍 Explorer", "⭐ My Team", "🏁 Giro d'Italia", "🏆 Scores"])

# ── Tab: Explorer ─────────────────────────────────────────────────────────────
with tab_explorer:
    # Sidebar filters (visible on both tabs but only used here)
    st.sidebar.header("Filters")
    name_filter = st.sidebar.text_input("Search by name", placeholder="e.g. Pogacar")
    team_filter = st.sidebar.text_input("Search by team", placeholder="e.g. UAE")

    _conn2 = get_connection()
    nationalities = ["All"] + sorted(
        [r[0] for r in _conn2.execute(
            "SELECT DISTINCT nationality FROM riders WHERE nationality IS NOT NULL ORDER BY nationality"
        ).fetchall()]
    )
    _conn2.close()
    nationality_filter = st.sidebar.selectbox("Nationality", nationalities)

    df = load_data(name_filter, nationality_filter, team_filter)
    st.subheader(f"{len(df):,} riders found")

    if df.empty:
        st.info("No riders match your filters.")
    else:
        display_cols = ["name", "nationality", "birthdate", "height", "weight", "team_name"]
        display_cols = [c for c in display_cols if c in df.columns]

        st.dataframe(
            df[display_cols].rename(columns={
                "name": "Name",
                "nationality": "NAT",
                "birthdate": "Date of Birth",
                "height": "Height (m)",
                "weight": "Weight (kg)",
                "team_name": "Team",
            }),
            width="stretch",
            hide_index=True,
        )

    st.divider()
    st.subheader("Rider Detail")

    if not df.empty:
        rider_names = df["name"].dropna().tolist()
        selected = st.selectbox("Select a rider", rider_names)
        if selected:
            row = df[df["name"] == selected].iloc[0]
            col1, col2, col3 = st.columns(3)
            col1.metric("Nationality", row.get("nationality") or "—")
            col2.metric("Date of Birth", row.get("birthdate") or "—")
            col3.metric("Team", row.get("team_name") or "—")
            col1.metric("Height", f"{row['height']} m" if pd.notna(row.get("height")) else "—")
            col2.metric("Weight", f"{row['weight']} kg" if pd.notna(row.get("weight")) else "—")
            if row.get("rider_url"):
                st.markdown(f"[View on ProCyclingStats](https://www.procyclingstats.com/{row['rider_url']})")

# ── Tab: My Team ──────────────────────────────────────────────────────────────
with tab_team:
    st.subheader("Build Your Fantasy Team")

    # Load all riders for the picker
    _conn3 = get_connection()
    all_riders_df = _conn3.execute(
        "SELECT rider_url, name, nationality, team_name FROM riders WHERE name IS NOT NULL ORDER BY name"
    ).df()
    _conn3.close()

    # Map display label → rider_url
    rider_options = {
        f"{row['name']} ({row['nationality'] or '?'}) — {row['team_name'] or '?'}": row["rider_url"]
        for _, row in all_riders_df.iterrows()
    }

    with st.form("team_form"):
        col_a, col_b = st.columns(2)
        manager_name = col_a.text_input("Your name", placeholder="e.g. Johan")
        team_name_input = col_b.text_input("Team name", placeholder="e.g. Team Velodutch")

        selected_labels = st.multiselect(
            "Select exactly 15 riders",
            options=list(rider_options.keys()),
            max_selections=15,
            placeholder="Search and select riders...",
        )
        submitted = st.form_submit_button("💾 Save Team", use_container_width=True)

    if submitted:
        errors = []
        if not manager_name.strip():
            errors.append("Enter your name.")
        if not team_name_input.strip():
            errors.append("Enter a team name.")
        if len(selected_labels) != 15:
            errors.append(f"Select exactly 15 riders (currently {len(selected_labels)}).")

        if errors:
            for e in errors:
                st.error(e)
        else:
            selected_urls = [rider_options[label] for label in selected_labels]
            try:
                team_id = save_fantasy_team(DB_PATH, manager_name.strip(), team_name_input.strip(), selected_urls)
                st.success(f"Team **{team_name_input.strip()}** saved! (ID {team_id})")
            except Exception as exc:
                st.error(f"Could not save team: {exc}")

    # ── View saved teams ───────────────────────────────────────────────────────
    st.divider()
    st.subheader("Saved Teams")

    teams = load_fantasy_teams(DB_PATH)
    if not teams:
        st.info("No teams saved yet.")
    else:
        team_labels = {f"{t['team_name']} (by {t['manager_name']})": t["id"] for t in teams}
        chosen_label = st.selectbox("View a team", list(team_labels.keys()))
        if chosen_label:
            chosen_id = team_labels[chosen_label]
            team_riders = load_fantasy_team_riders(DB_PATH, chosen_id)
            if team_riders:
                st.dataframe(
                    pd.DataFrame(team_riders).rename(columns={
                        "name": "Rider",
                        "nationality": "NAT",
                        "team": "Team",
                    }),
                    hide_index=True,
                    width="stretch",
                )

# ── Tab: Giro d'Italia ────────────────────────────────────────────────────────
with tab_giro:
    st.subheader("Giro d'Italia — Stage Overview")

    stages = load_stages(DB_PATH, "Giro d'Italia")
    finished = stages_with_results(DB_PATH, "Giro d'Italia")

    if stages:
        stages_df = pd.DataFrame(stages)
        stages_df["Results"] = stages_df["Stage"].apply(
            lambda s: "✅" if s in finished else ("—" if s == "Rest Day" else "")
        )

        def highlight_rest(row):
            if row["Stage"] == "Rest Day":
                return ["background-color: #f0f0f0; color: #888"] * len(row)
            return [""] * len(row)

        styled = (
            stages_df.style
            .apply(highlight_rest, axis=1)
            .format({"KM": lambda v: f"{v:.1f}" if pd.notna(v) and v else "—"})
        )
        st.dataframe(styled, hide_index=True, width="stretch")

        racing_stages = [s for s in stages if s["Stage"] != "Rest Day"]
        total_km = sum(s["KM"] for s in racing_stages if s["KM"])
        col1, col2, col3 = st.columns(3)
        col1.metric("Racing stages", len(racing_stages))
        col2.metric("Total distance", f"{total_km:.1f} km")
        col3.metric("Rest days", sum(1 for s in stages if s["Stage"] == "Rest Day"))

    # ── Enter / view stage results ─────────────────────────────────────────────
    st.divider()
    st.subheader("Stage Results")

    racing_stage_names = [s["Stage"] for s in stages if s["Stage"] != "Rest Day"]

    result_col, view_col = st.columns([1, 1], gap="large")

    with result_col:
        st.markdown("**Enter results for a stage**")

        selected_stage = st.selectbox(
            "Select stage",
            racing_stage_names,
            key="result_stage_select",
        )

        # Pre-fill existing results if any
        existing = load_stage_results(DB_PATH, "Giro d'Italia", selected_stage)
        prefill_urls = []
        if existing:
            _conn_pre = get_connection()
            url_map = {
                row[0]: row[1]
                for row in _conn_pre.execute("SELECT name, rider_url FROM riders").fetchall()
            }
            _conn_pre.close()
            prefill_urls = [
                next((url for name, url in url_map.items() if name == r["Rider"]), None)
                for r in existing
            ]

        # Build rider options for the multiselect
        _conn_res = get_connection()
        res_riders_df = _conn_res.execute(
            "SELECT rider_url, name, nationality, team_name FROM riders WHERE name IS NOT NULL ORDER BY name"
        ).df()
        _conn_res.close()

        res_rider_options = {
            f"{row['name']} ({row['nationality'] or '?'}) — {row['team_name'] or '?'}": row["rider_url"]
            for _, row in res_riders_df.iterrows()
        }
        url_to_label = {v: k for k, v in res_rider_options.items()}
        prefill_labels = [url_to_label[u] for u in prefill_urls if u and u in url_to_label]

        with st.form("stage_results_form"):
            top15_labels = st.multiselect(
                "Top 15 finishers (in order, 1st → 15th)",
                options=list(res_rider_options.keys()),
                default=prefill_labels,
                max_selections=15,
                placeholder="Search and add riders in finishing order...",
                key="top15_multiselect",
            )
            save_results = st.form_submit_button("💾 Save Results", use_container_width=True)

        if save_results:
            if len(top15_labels) != 15:
                st.error(f"Select exactly 15 finishers (currently {len(top15_labels)}).")
            else:
                urls = [res_rider_options[lbl] for lbl in top15_labels]
                try:
                    save_stage_results(DB_PATH, "Giro d'Italia", selected_stage, urls)
                    st.success(f"Results saved for **{selected_stage}**!")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Could not save results: {exc}")

    with view_col:
        st.markdown("**View results for a stage**")
        view_stage = st.selectbox(
            "Select stage",
            racing_stage_names,
            key="view_stage_select",
        )
        results = load_stage_results(DB_PATH, "Giro d'Italia", view_stage)
        if results:
            st.dataframe(pd.DataFrame(results), hide_index=True, width="stretch")
        else:
            st.info("No results entered yet for this stage.")

# ── Tab: Scores ───────────────────────────────────────────────────────────────
with tab_scores:
    st.subheader("🏆 Fantasy Scores — Giro d'Italia")

    scores = calculate_scores(DB_PATH, "Giro d'Italia")

    if not scores:
        st.info("No stage results entered yet. Enter results in the 🏁 Giro d'Italia tab first.")
    else:
        scores_df = pd.DataFrame(scores)

        # Highlight the leader row
        def highlight_leader(row):
            if row.name == 0:
                return ["background-color: #fff3cd; font-weight: bold"] * len(row)
            return [""] * len(row)

        st.markdown("#### Standings")
        styled_scores = scores_df.style.apply(highlight_leader, axis=1)
        st.dataframe(styled_scores, hide_index=True, width="stretch")

        # Per-team breakdown
        st.divider()
        st.markdown("#### Team breakdown")

        teams = load_fantasy_teams(DB_PATH)
        if teams:
            team_labels = {f"{t['team_name']} (by {t['manager_name']})": t["id"] for t in teams}
            chosen_label = st.selectbox("Select a team", list(team_labels.keys()), key="scores_team_select")
            if chosen_label:
                chosen_id = team_labels[chosen_label]
                breakdown = calculate_stage_breakdown(DB_PATH, "Giro d'Italia", chosen_id)
                if breakdown:
                    bd_df = pd.DataFrame(breakdown)
                    st.dataframe(bd_df, hide_index=True, width="stretch")
                    st.metric("Total points from shown stages", bd_df["Points"].sum())
                else:
                    st.info("None of this team's riders finished in the top 15 of any stage yet.")
