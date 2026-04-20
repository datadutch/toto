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
            "SELECT rider_url, name, nationality, team_name FROM riders WHERE name IS NOT NULL ORDER BY name"
        ).fetchall()
    finally:
        conn.close()
    return rows

_rider_rows = _load_rider_rows()  # list of (url, name, nationality, team_name)

# Build lookups fresh every run — never cache derived/normalized data
rider_options = {}   # label -> url
url_to_label = {}    # url -> label
_url_to_norm = {}    # url -> normalized name
_selected_set = set()  # for fast O(1) lookup later
for _url, _name, _nat, _team in _rider_rows:
    _label = f"{_name} ({_nat or '?'}) \u2014 {_team or '?'}"
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
        if free_text.strip():
            if st.button(f"🔍 {t('participant_recognize')}", key="btn_extract_riders"):
                with st.spinner(t("participant_recognizing")):
                    try:
                        extracted = extract_riders_from_text(free_text.strip())
                    except RuntimeError as e:
                        st.error(str(e))
                        extracted = []
                if extracted:
                    matched_urls, not_found = match_riders_to_db(extracted, DB_PATH)
                    existing = st.session_state[state_key]
                    already_in = set(existing)
                    new_urls = [u for u in matched_urls if u not in already_in]
                    slots_left = 15 - len(existing)
                    st.session_state[state_key] = existing + new_urls[:slots_left]
                    if not_found:
                        st.warning(
                            f"{len(not_found)} {t('participant_not_found')}: "
                            + ", ".join(f"**{n}**" for n in not_found)
                            + ". {t('participant_add_manually')}"
                        )
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

