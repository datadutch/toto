import os
import duckdb
import streamlit as st
from dotenv import load_dotenv
from src.db import init_fantasy_tables, save_fantasy_team, load_team_by_manager, _connect, load_races, is_registration_open

load_dotenv()

_TOKEN = os.getenv("MOTHERDUCK_TOKEN") or st.secrets.get("MOTHERDUCK_TOKEN", "")
if _TOKEN:
    DB_PATH = f"md:toto?motherduck_token={_TOKEN}"
else:
    DB_PATH = os.path.join(os.path.dirname(__file__), "data", "cycling.duckdb")

st.set_page_config(page_title="Stampers Toto", page_icon="🚴", layout="centered")
st.title("🚴 Stampers Toto")
st.markdown("Register your team of 15 riders below.")

if not DB_PATH.startswith("md:") and not os.path.exists(DB_PATH):
    st.error("Database not found. Ask the administrator to run the scraper first.")
    st.stop()

init_fantasy_tables(DB_PATH)

# ── Race selection ────────────────────────────────────────────────────────────
races = load_races(DB_PATH)
if not races:
    st.error("No races configured yet. Ask the administrator.")
    st.stop()

race_options = {r["race_name"]: r for r in races}
selected_race = st.selectbox("Select a race", list(race_options.keys()))

race_info = race_options[selected_race]
registration_open = is_registration_open(DB_PATH, selected_race)

if race_info["deadline"]:
    if registration_open:
        st.info(f"⏰ Registration closes on **{race_info['deadline'].strftime('%d/%m/%Y at %H:%M')}**")
    else:
        st.error(f"⏰ Registration closed on **{race_info['deadline'].strftime('%d/%m/%Y at %H:%M')}**. No new teams can be submitted.")

# ── Load all riders ───────────────────────────────────────────────────────────
@st.cache_data(ttl=300)
def get_rider_options():
    conn = _connect(DB_PATH, read_only=True)
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
if registration_open:
    mgr_lookup = st.text_input("Your name", placeholder="e.g. Johan", key="mgr_name_lookup")
    existing_team = load_team_by_manager(DB_PATH, mgr_lookup.strip(), selected_race) if mgr_lookup.strip() else None

    url_to_label = {v: k for k, v in rider_options.items()}
    prefill_labels = [url_to_label[u] for u in (existing_team["rider_urls"] if existing_team else []) if u in url_to_label]
    prefill_team_name = existing_team["team_name"] if existing_team else ""

    if existing_team:
        st.info(f"✏️ Je hebt al een team geregistreerd: **{prefill_team_name}**. Opslaan overschrijft je bestaande selectie.")

    with st.form("participant_form"):
        team_name = st.text_input("Team name", value=prefill_team_name, placeholder="e.g. Team Velodutch")

        selected_labels = st.multiselect(
            "Select up to 15 riders",
            options=list(rider_options.keys()),
            default=prefill_labels,
            max_selections=15,
            placeholder="Type a name to search...",
        )

        st.caption(f"{len(selected_labels)} / 15 riders selected")
        submitted = st.form_submit_button("✅ Save team", use_container_width=True)

    if submitted:
        errors = []
        if not mgr_lookup.strip():
            errors.append("Please enter your name.")
        if not team_name.strip():
            errors.append("Please enter a team name.")
        if len(selected_labels) == 0:
            errors.append("Select at least 1 rider.")
        if not is_registration_open(DB_PATH, selected_race):
            errors.append("Registration has closed for this race.")

        if errors:
            for e in errors:
                st.error(e)
        else:
            urls = [rider_options[lbl] for lbl in selected_labels]
            try:
                save_fantasy_team(DB_PATH, mgr_lookup.strip(), team_name.strip(), urls, selected_race)
                if existing_team:
                    st.success(f"Team **{team_name.strip()}** bijgewerkt! 🎉")
                else:
                    st.success(f"Team **{team_name.strip()}** geregistreerd! 🎉")
                st.balloons()
            except Exception as exc:
                st.error(f"Could not save your team: {exc}")
