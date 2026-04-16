import os
import duckdb
import streamlit as st
from dotenv import load_dotenv
from src.db import init_fantasy_tables, save_fantasy_team

load_dotenv()

_TOKEN = os.getenv("MOTHERDUCK_TOKEN") or st.secrets.get("MOTHERDUCK_TOKEN", "")
if _TOKEN:
    DB_PATH = f"md:toto?motherduck_token={_TOKEN}"
else:
    DB_PATH = os.path.join(os.path.dirname(__file__), "data", "cycling.duckdb")

st.set_page_config(page_title="Giro d'Italia Fantasy", page_icon="🚴", layout="centered")
st.title("🚴 Giro d'Italia Fantasy")
st.markdown("Register your team of 15 riders below.")

if not DB_PATH.startswith("md:") and not os.path.exists(DB_PATH):
    st.error("Database not found. Ask the administrator to run the scraper first.")
    st.stop()

init_fantasy_tables(DB_PATH)

# ── Load all riders ───────────────────────────────────────────────────────────
@st.cache_data(ttl=300)
def get_rider_options():
    conn = duckdb.connect(DB_PATH, read_only=True)
    try:
        df = conn.execute(
            "SELECT rider_url, name, nationality, team_name FROM riders WHERE name IS NOT NULL ORDER BY name"
        ).df()
    finally:
        conn.close()
    options = {
        f"{row['name']} ({row['nationality'] or '?'}) — {row['team_name'] or '?'}": row["rider_url"]
        for _, row in df.iterrows()
    }
    return options

rider_options = get_rider_options()

# ── Registration form ─────────────────────────────────────────────────────────
with st.form("participant_form"):
    col_a, col_b = st.columns(2)
    manager_name = col_a.text_input("Your name", placeholder="e.g. Johan")
    team_name = col_b.text_input("Team name", placeholder="e.g. Team Velodutch")

    selected_labels = st.multiselect(
        "Select exactly 15 riders",
        options=list(rider_options.keys()),
        max_selections=15,
        placeholder="Type a name to search...",
    )

    st.caption(f"{len(selected_labels)} / 15 riders selected")
    submitted = st.form_submit_button("✅ Register my team", use_container_width=True)

if submitted:
    errors = []
    if not manager_name.strip():
        errors.append("Please enter your name.")
    if not team_name.strip():
        errors.append("Please enter a team name.")
    if len(selected_labels) != 15:
        errors.append(f"Select exactly 15 riders (you selected {len(selected_labels)}).")

    if errors:
        for e in errors:
            st.error(e)
    else:
        urls = [rider_options[lbl] for lbl in selected_labels]
        try:
            team_id = save_fantasy_team(DB_PATH, manager_name.strip(), team_name.strip(), urls)
            st.success(f"Team **{team_name.strip()}** registered successfully! 🎉")
            st.balloons()
        except Exception as exc:
            st.error(f"Could not save your team: {exc}")
