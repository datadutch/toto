import os
import json
import unicodedata
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from src.db import (
    init_fantasy_tables, init_accounts_table,
    save_fantasy_team, load_team_by_account,
    get_account_by_email, create_account,
    _connect, load_races, is_registration_open,
    load_stages, load_stage_results, calculate_scores,
)
from src.voice import extract_riders_from_text, match_riders_to_db


def _normalize(text: str) -> str:
    """Lowercase + strip diacritics so 'pogacar' matches 'Pogačar'."""
    return unicodedata.normalize("NFD", text.lower()).encode("ascii", "ignore").decode("ascii")

load_dotenv()

# ── Load Translations from JSON ──────────────────────────────────────────────
with open("translations.json", "r", encoding="utf-8") as f:
    TRANSLATIONS = json.load(f)

try:
    _TOKEN = os.getenv("MOTHERDUCK_TOKEN") or st.secrets.get("MOTHERDUCK_TOKEN", "")
except Exception:
    _TOKEN = os.getenv("MOTHERDUCK_TOKEN", "")
if _TOKEN:
    DB_PATH = f"md:toto?motherduck_token={_TOKEN}"
else:
    DB_PATH = os.path.join(os.path.dirname(__file__), "data", "cycling.duckdb")

st.set_page_config(page_title="Stampers Toto", page_icon="🚴", layout="centered")

# ── Custom CSS for Fixed Footer Language Selector ──────────────────────────
st.markdown("""
    <style>
    .footer {
        position: fixed;
        bottom: 0;
        right: 0;
        width: auto;
        padding: 12px 20px;
        background-color: rgba(255, 255, 255, 0.95);
        border-top: 1px solid #e0e0e0;
        z-index: 999;
    }
    </style>
""", unsafe_allow_html=True)

# ── Initialize Language ──────────────────────────────────────────────────────
if "language" not in st.session_state:
    st.session_state.language = "nl"

def t(key):
    """Translate a key to the current language"""
    return TRANSLATIONS[st.session_state.language].get(key, key)

st.title(f"🚴 {t('participant_welcome')}")

if not DB_PATH.startswith("md:") and not os.path.exists(DB_PATH):
    st.error("Database not found. Ask the administrator to run the scraper first.")
    st.stop()

init_fantasy_tables(DB_PATH)
init_accounts_table(DB_PATH)

# ── Auth: use st.user when available (Streamlit Cloud OAuth), else manual email ──
_user = st.user if hasattr(st, "user") else None
_cloud_email = getattr(_user, "email", None)
_cloud_name = getattr(_user, "name", None)
_is_guest = getattr(_user, "is_logged_in", None) is False or _cloud_email is None

# ── Session state ─────────────────────────────────────────────────────────────
if "account" not in st.session_state:
    st.session_state.account = None

# ── Initialize view state ──────────────────────────────────────────────────────
if "participant_view" not in st.session_state:
    st.session_state.participant_view = "register"

# ── Language Selector (Sidebar - At Top) ──────────────────────────────────────
st.sidebar.selectbox(
    t("language"),
    options=["nl", "en"],
    index=0 if st.session_state.language == "nl" else 1,
    format_func=lambda x: "🇳🇱 Nederlands" if x == "nl" else "🇬🇧 English",
    key="lang_selector",
    on_change=lambda: st.session_state.update({"language": st.session_state.lang_selector}),
    label_visibility="visible"
)

# ── Auto-login via URL parameter (from admin app) ──────────────────────────────
query_params = st.query_params
auto_login_email = query_params.get("email")
auto_login_flag = query_params.get("auto_login")

if auto_login_email and auto_login_flag == "true" and st.session_state.account is None:
    account = get_account_by_email(DB_PATH, auto_login_email)
    if account:
        st.session_state.account = account
        # Clear the query params from the URL for clean display
        st.query_params.clear()
        st.rerun()

# ── Auto-login via environment variable ──────────────────────────────────────
if st.session_state.account is None:
    env_auto_login_email = os.getenv("PARTICIPANT_AUTO_LOGIN_EMAIL")
    if env_auto_login_email:
        account = get_account_by_email(DB_PATH, env_auto_login_email)
        if account:
            st.session_state.account = account
            st.rerun()

# ── Auto-login via Google (Streamlit Cloud OAuth), else manual email ──────────
if not _is_guest and _cloud_email and st.session_state.account is None:
    account = get_account_by_email(DB_PATH, _cloud_email)
    if not account:
        display_name = _cloud_name or _cloud_email.split("@")[0]
        account = create_account(DB_PATH, _cloud_email, display_name)
    st.session_state.account = account

# ── Manual login / registration (local dev or guest) ─────────────────────────
if st.session_state.account is None:
    st.subheader(t("participant_login_register"))

    email_input = st.text_input(t("email"), placeholder="e.g. johan@example.com")

    if not email_input.strip():
        st.stop()

    account = get_account_by_email(DB_PATH, email_input.strip())

    if account:
        st.success(f"{t('participant_welcome_back')}, **{account['name']}**!")
        st.session_state.account = account
        st.rerun()
    else:
        st.info(t("participant_no_account"))
        name_input = st.text_input(t("participant_your_name"), placeholder="e.g. Johan")
        if name_input.strip():
            if st.button(t("participant_create_account"), width="stretch"):
                account = create_account(DB_PATH, email_input.strip(), name_input.strip())
                st.session_state.account = account
                st.rerun()

    st.stop()

# ── Logged in ─────────────────────────────────────────────────────────────────
account = st.session_state.account

# ── Sidebar separator (only visible when logged in) ───────────────────────────
st.sidebar.markdown("---")

col_welcome, col_logout = st.columns([4, 1])
col_welcome.markdown(f"Ingelogd als **{account['name']}** ({account['email']})")
if not _is_guest:
    # On Streamlit Cloud, logout is handled by the platform
    col_logout.markdown("[Uitloggen](?logout=true)", unsafe_allow_html=False)
else:
    if col_logout.button("Uitloggen"):
        st.session_state.account = None
        st.rerun()

st.divider()

# ── Sidebar Menu (Register / Scores) - Only visible when logged in ──────────────
st.sidebar.markdown("### 📋 Menu")
view = st.sidebar.radio(
    "Selecteer:",
    options=["register", "scores"],
    format_func=lambda x: "📝 Inschrijven" if x == "register" else "🏆 Scores",
    label_visibility="collapsed",
    key="participant_view"
)

# ── Race selection ────────────────────────────────────────────────────────────
races = load_races(DB_PATH)
if not races:
    st.error("No races configured yet. Ask the administrator.")
    st.stop()

race_options = {r["race_name"]: r for r in races}
selected_race = st.selectbox(t("participant_select_race"), list(race_options.keys()))

race_info = race_options[selected_race]
registration_open = is_registration_open(DB_PATH, selected_race)

if race_info["deadline"]:
    if registration_open:
        st.info(f"⏰ {t('participant_registration_open')} **{race_info['deadline'].strftime('%d/%m/%Y om %H:%M')}**")
    else:
        st.error(f"⏰ {t('participant_registration_closed')} **{race_info['deadline'].strftime('%d/%m/%Y om %H:%M')}**. {t('participant_no_new_teams')}")

# ── Load all riders ───────────────────────────────────────────────────────────
@st.cache_data(ttl=300)
def _load_rider_rows():
    conn = _connect(DB_PATH, read_only=True)
    try:
        rows = conn.execute(
            "SELECT rider_url, name, nickname, nationality, team_name FROM riders WHERE name IS NOT NULL ORDER BY name"
        ).fetchall()
    finally:
        conn.close()
    return rows

def _load_race_rider_rows(race_name: str):
    """Load riders from startlist for a specific race"""
    conn = _connect(DB_PATH, read_only=True)
    try:
        rows = conn.execute(
            """SELECT s.rider_url, s.rider_name, r.nickname, r.nationality, r.team_name 
               FROM startlists s 
               JOIN riders r ON s.rider_url = r.rider_url
               WHERE s.race_name = ? AND s.rider_name IS NOT NULL 
               ORDER BY s.rider_name""", [race_name]
        ).fetchall()
    finally:
        conn.close()
    return rows

# Use race-specific riders if a race is selected and has a startlist, otherwise use all riders
if selected_race:
    race_rider_rows = _load_race_rider_rows(selected_race)
    if race_rider_rows:  # Use startlist if available
        _rider_rows = race_rider_rows
    else:  # Fallback to all riders if no startlist
        _rider_rows = _load_rider_rows()
else:
    _rider_rows = _load_rider_rows()

# Build lookups fresh every run — never cache derived/normalized data
rider_options = {}   # label -> url
url_to_label = {}    # url -> label
_url_to_norm = {}    # url -> normalized name
_selected_set = set()  # for fast O(1) lookup later
for _url, _name, _nickname, _nat, _team in _rider_rows:
    _label = f"{_name} ({_nat or '?'}) \u2014 {_team or '?'}" + (f" [{_nickname}]" if _nickname else "")
    rider_options[_label] = _url
    url_to_label[_url] = _label
    _url_to_norm[_url] = _normalize(_name)

# ── Check if registration is open to decide UI flow ───────────────────────────
existing_team = load_team_by_account(DB_PATH, account["id"], selected_race)
prefill_urls = existing_team["rider_urls"] if existing_team else []
prefill_team_name = existing_team["team_name"] if existing_team else ""

# Initialise session state for rider selection (reset when race changes)
state_key = f"selected_urls_{account['id']}_{selected_race}"
if state_key not in st.session_state:
    st.session_state[state_key] = list(prefill_urls)

selected_urls: list = st.session_state[state_key]

# If registration is closed and no team exists, show message in both tabs
if not registration_open and not existing_team:
    st.info(t("participant_no_team_registered"))
    
    # Still show scores tab if available
    st.divider()
    st.subheader("🏆 Scores")
    stages = load_stages(DB_PATH, selected_race)
    if not stages:
        st.info("No stages available for this race.")
    else:
        stages_with_results = [s for s in stages if load_stage_results(DB_PATH, selected_race, s["Stage"])]
        if not stages_with_results:
            st.info("No results entered yet for this race.")
        else:
            # Show scores
            try:
                scores = calculate_scores(DB_PATH, selected_race)
                if scores:
                    df_scores = pd.DataFrame(scores)
                    df_scores = df_scores.sort_values("Total", ascending=False).reset_index(drop=True)
                    df_scores.index = df_scores.index + 1
                    st.dataframe(df_scores[["Team", "Total"]], width='stretch')
                else:
                    st.info("No scores available yet.")
            except Exception as e:
                st.error(f"Error loading scores: {e}")
    st.stop()

st.divider()

# ─────────────────────────────────────────────────────────────────────────────
# MAIN CONTENT: Register or Scores based on sidebar menu
# ─────────────────────────────────────────────────────────────────────────────

if view == "register":
    if not registration_open:
        if existing_team:
            st.success(t("participant_team_registered"))
            st.subheader(f"{t('participant_your_team')}: {existing_team['team_name']}")
            for i, url in enumerate(existing_team["rider_urls"]):
                label = url_to_label.get(url, url)
                st.markdown(f"{i + 1}. {label.split(' (')[0]}")
        else:
            st.info(t("participant_no_team_registered"))
    else:
        prefill_urls = existing_team["rider_urls"] if existing_team else []
        prefill_team_name = existing_team["team_name"] if existing_team else ""

        # Initialise session state for rider selection (reset when race changes)
        state_key = f"selected_urls_{account['id']}_{selected_race}"
        if state_key not in st.session_state:
            st.session_state[state_key] = list(prefill_urls)

        selected_urls: list = st.session_state[state_key]

        if existing_team:
            st.info(f"✏️ {t('participant_existing_team_warning')}**{prefill_team_name}**. {t('participant_overwrite_warning')}")

        # ── Team name ─────────────────────────────────────────────────────────────────────────────
        team_name = st.text_input(t("participant_team_name"), value=prefill_team_name, placeholder="e.g. Team Velodutch", key="team_name_input")

        st.divider()

        # ── Free-text rider input ───────────────────────────────────────────────────
        st.markdown(f"**📝 {t('participant_free_text_header')}**")
        st.caption(t("participant_free_text_desc"))
        free_text = st.text_area(
            t("participant_riders_label"),
            placeholder=t("participant_riders_placeholder"),
            height=100,
            key="free_text_riders",
            label_visibility="collapsed",
        )
        
        # Always show the recognize button
        if st.button(f"🔍 {t('participant_recognize')}", key="btn_extract_riders"):
            if not free_text.strip():
                st.warning(t("participant_search_hint"))
            else:
                with st.spinner(t("participant_recognizing")):
                    try:
                        # Pass rider names and rows to ground the LLM's responses and validate
                        # Filter out None values
                        rider_names = [name for _, name, _, _, _ in _rider_rows if name]
                        rider_rows_for_extraction = [(url, name) for url, name, _, _, _ in _rider_rows if name]
                        extracted = extract_riders_from_text(
                            free_text.strip(), rider_names, rider_rows_for_extraction
                        )
                    except RuntimeError as e:
                        st.error(str(e))
                        extracted = []
                if extracted:
                    # Pass pre-loaded rider rows to avoid redundant DB query
                    # Include nicknames in the format (url, name, nickname)
                    rider_rows_for_matching = [(url, name, nickname) for url, name, nickname, _, _ in _rider_rows]
                    matched_urls, not_found = match_riders_to_db(extracted, DB_PATH, rider_rows_for_matching, selected_race if selected_race else None)
                    existing = st.session_state[state_key]
                    already_in = set(existing)
                    new_urls = [u for u in matched_urls if u not in already_in]
                    slots_left = 15 - len(existing)
                    added_any = len(new_urls) > 0
                    st.session_state[state_key] = existing + new_urls[:slots_left]
                    if not_found:
                        # Use startlist-specific message if we're using race-specific riders (startlist)
                        # Check if race_rider_rows was used and is not empty
                        using_startlist = selected_race and race_rider_rows and any(r for r in race_rider_rows if r[1])
                        not_found_key = 'participant_not_found_startlist' if using_startlist else 'participant_not_found'
                        st.warning(
                            f"{len(not_found)} {t(not_found_key)}: "
                            + ", ".join(f"**{n}**" for n in not_found)
                            + f". {t('participant_add_manually')}"
                        )
                    # Only rerun if we actually added new riders
                    if added_any:
                        st.rerun()
                else:
                    st.warning(t("participant_no_riders_recognized"))

        st.divider()

        # ── Rider search + add (corrections) ────────────────────────────────────────
        st.markdown(f"**{t('participant_verify_selection')}** — {len(selected_urls)} / 15 {t('participant_selected_count')}")

        search_query = st.text_input(f"🔍 {t('participant_search_rider')}", placeholder=t("participant_search_rider"), key="rider_search")

        # Filter rider options by search query (name only, accent-insensitive), exclude already selected
        _norm_query = _normalize(search_query) if search_query else ""
        available = {
            label: url
            for label, url in rider_options.items()
            if url not in selected_urls and (
                not search_query or _norm_query in _url_to_norm.get(url, "")
            )
        }

        if len(selected_urls) >= 15:
            st.info(t("participant_max_riders"))
        elif not search_query:
            st.caption(t("participant_search_hint"))
        elif available:
            _available_items = list(available.items())
            if len(_available_items) > 20:
                st.caption(f"{t('participant_many_results')} ({len(_available_items)}) — {t('participant_refine_search')}")
                _available_items = _available_items[:20]
            _available_labels = [label for label, _ in _available_items]
            add_label = st.radio(
                t("participant_add_rider"),
                options=_available_labels,
                index=0,
                key="rider_add_select",
                label_visibility="collapsed",
            )
            if st.button(f"➕ {t('participant_add_rider')}", width="stretch", key="btn_add_rider"):
                st.session_state[state_key].append(available[add_label])
                st.rerun()
        else:
            # Check if the rider is missing because already selected
            _already = [
                url_to_label.get(url, url).split(" (")[0]
                for url in selected_urls
                if _norm_query in _url_to_norm.get(url, "")
            ]
            if _already:
                st.caption(f"✅ {t('participant_already_selected')}: **{', '.join(_already)}**")
            else:
                # If using startlist and no results found, check if rider exists in general database
                using_startlist = selected_race and race_rider_rows and any(r for r in race_rider_rows if r[1])
                
                if using_startlist:
                    # We're using a startlist, check general database
                    try:
                        conn = _connect(DB_PATH, read_only=True)
                        # Search in general database
                        db_rows = conn.execute(
                            "SELECT rider_url, name, nickname, nationality, team_name FROM riders WHERE name IS NOT NULL"
                        ).fetchall()
                        conn.close()
                        
                        # Build searchable list from general database
                        general_rider_options = {}
                        general_url_to_label = {}
                        general_url_to_norm = {}
                        
                        for _url, _name, _nickname, _nat, _team in db_rows:
                            _label = f"{_name} ({_nat or '?'}) \u2014 {_team or '?'}" + (f" [{_nickname}]" if _nickname else "")
                            general_rider_options[_label] = _url
                            general_url_to_label[_url] = _label
                            general_url_to_norm[_url] = _normalize(_name)
                        
                        # Check if rider exists in general database
                        general_available = {
                            label: url
                            for label, url in general_rider_options.items()
                            if url not in selected_urls and _norm_query in general_url_to_norm.get(url, "")
                        }
                        
                        if general_available:
                            # Rider exists in database but not in current startlist
                            rider_names = [general_url_to_label[url].split(" (")[0] for url in general_available.keys()]
                            st.caption(f"🔍 {t('participant_not_found_startlist')}: **{', '.join(rider_names)}**. {t('participant_add_manually')}")
                        else:
                            st.caption(t("participant_no_riders_found"))
                    except Exception as e:
                        st.error(f"Error searching database: {e}")
                        st.caption(t("participant_no_riders_found"))
                else:
                    # Not using startlist, so search should have found riders in general database
                    # If we get here, the rider is truly not in the database
                    st.caption(t("participant_no_riders_found"))

        # ── Selected riders list ──────────────────────────────────────────────────────
        if selected_urls:
            st.markdown(f"**{t('participant_selected_riders')}**")
            for i, url in enumerate(selected_urls):
                label = url_to_label.get(url, url)
                col_name, col_btn = st.columns([5, 1], vertical_alignment="center")
                col_name.markdown(f"{i + 1}. {label.split(' (')[0]}")
                if col_btn.button("✖", key=f"remove_{i}", width="stretch", help=t('delete_rider')):
                    st.session_state[state_key].pop(i)
                    st.rerun()
        else:
            st.caption(t("participant_no_riders_selected"))

        st.divider()

        # ── Save ──────────────────────────────────────────────────────────────────────
        if st.button(f"✅ {t('participant_save_team')}", width="stretch", type="primary"):
            errors = []
            if not team_name.strip():
                errors.append(t("participant_error_team_name"))
            if len(selected_urls) == 0:
                errors.append(t("participant_error_min_riders"))
            if not is_registration_open(DB_PATH, selected_race):
                errors.append(t("participant_error_registration_closed"))

            if errors:
                for e in errors:
                    st.error(e)
            else:
                try:
                    save_fantasy_team(
                        DB_PATH,
                        manager_name=account["name"],
                        team_name=team_name.strip(),
                        rider_urls=selected_urls,
                        race_name=selected_race,
                        account_id=account["id"],
                    )
                    # Clear session state so next load pre-fills from DB
                    del st.session_state[state_key]
                    if existing_team:
                        st.success(f"{t('participant_team_saved')}")
                    else:
                        st.success(f"{t('participant_team_saved')}")
                    st.balloons()
                except Exception as exc:
                    st.error(f"{t('save_error')} {exc}")

elif view == "scores":
    stages = load_stages(DB_PATH, selected_race)
    if not stages:
        st.info("No stages available for this race.")
    else:
        # Only show stages that have results
        stages_with_results = [s for s in stages if load_stage_results(DB_PATH, selected_race, s["Stage"])]
        
        if not stages_with_results:
            st.info("No results entered yet for this race.")
        else:
            st.subheader(f"Completed stages: {len(stages_with_results)} / {len(stages)}")
            
            # Show scores
            try:
                scores = calculate_scores(DB_PATH, selected_race)
                if scores:
                    df_scores = pd.DataFrame(scores)
                    df_scores = df_scores.sort_values("Total", ascending=False).reset_index(drop=True)
                    df_scores.index = df_scores.index + 1
                    
                    # Display with proper formatting
                    st.dataframe(
                        df_scores[["Team", "Total"]],
                        width='stretch',
                        hide_index=False,
                    )
                    
                    st.divider()
                    st.caption(f"Updated based on {len(stages_with_results)} completed stages")
                else:
                    st.info("No scores available yet.")
            except Exception as e:
                st.error(f"Error loading scores: {e}")

