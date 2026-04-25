import os
import json
import re
import unicodedata
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from src.db import (
    init_fantasy_tables, init_accounts_table,
    save_fantasy_team, load_team_by_account,
    _connect, load_races, is_registration_open,
    load_stages, load_stage_results, calculate_scores,
    update_account_name,
)
from src.voice import extract_riders_from_text, match_riders_to_db

load_dotenv()

# Root of project (one level up from pages/)
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_TOKEN = os.getenv("MOTHERDUCK_TOKEN")
if _TOKEN:
    DB_PATH = f"md:toto?motherduck_token={_TOKEN}"
else:
    DB_PATH = os.path.join(_ROOT, "data", "cycling.duckdb")

st.set_page_config(page_title="Stampers Toto", page_icon="🚴", layout="centered")

# Hide default multipage sidebar nav
st.markdown("<style>[data-testid='stSidebarNav'] {display: none;}</style>", unsafe_allow_html=True)

with open(os.path.join(_ROOT, "translations.json"), "r", encoding="utf-8") as f:
    TRANSLATIONS = json.load(f)

def _normalize(text: str) -> str:
    return unicodedata.normalize("NFD", text.lower()).encode("ascii", "ignore").decode("ascii")

def t(key: str) -> str:
    lang = st.session_state.get("language", "nl")
    return TRANSLATIONS.get(lang, {}).get(key, key)

if "language" not in st.session_state:
    st.session_state.language = "nl"

if "participant_view" not in st.session_state:
    st.session_state.participant_view = "register"

if "account" not in st.session_state:
    st.session_state.account = None

# ── Auth check ────────────────────────────────────────────────────────────────
if st.session_state.account is None:
    st.rerun()

account = st.session_state.account

# ── Guest detection ───────────────────────────────────────────────────────────
_user = getattr(st, "user", None)
_cloud_email = getattr(_user, "email", None) if _user else None
_is_guest = getattr(_user, "is_logged_in", None) is False or _cloud_email is None

# ── Header: Admin + Logout ────────────────────────────────────────────────────
col_title, col_admin, col_logout_header = st.columns([3, 1, 1])
with col_title:
    st.write("")

with col_admin:
    if account.get("is_admin") == "yes":
        if st.button("👑 Admin", key="btn_admin", help="Naar admin paneel", use_container_width=True):
            st.switch_page("pages/administrator.py")

with col_logout_header:
    if not _is_guest:
        st.markdown("[🚪 Uitloggen](?logout=true)", unsafe_allow_html=True)
    else:
        if st.button("🚪 Uitloggen", key="btn_logout_header", help="Uitloggen"):
            st.session_state.account = None
            st.rerun()

# ── Sidebar: User info ────────────────────────────────────────────────────────
st.sidebar.markdown(f"<center><b>{t('participant_logged_in')}</b></center>", unsafe_allow_html=True)

if st.sidebar.button(
    f"👤 **{account['name']}** ({account['email']})",
    key="btn_username",
    help="Klik om je naam te wijzigen",
    use_container_width=True,
):
    st.session_state.show_change_name = True

st.sidebar.markdown("---")

if st.session_state.get("show_change_name", False):
    st.markdown("""
    <style>
    .modal-overlay {
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        background-color: rgba(0, 0, 0, 0.5);
        z-index: 9999;
    }
=======

    """, unsafe_allow_html=True)

    st.markdown("📝 " + t("participant_change_name"), unsafe_allow_html=True)

    new_name = st.text_input(
        t("participant_new_name"),
        placeholder="e.g. Johan (max 50 chars)",
        key="new_name_input",
        label_visibility="collapsed",
    )

    if new_name.strip() and len(new_name.strip()) > 50:
        st.error(t("participant_error_username_length"))

    col1, col2 = st.columns([1, 1])
    if col1.button(t("participant_cancel"), use_container_width=True):
        st.session_state.show_change_name = False
        st.rerun()

    if (
        col2.button(t("participant_save"), type="primary", use_container_width=True)
        and new_name.strip()
        and len(new_name.strip()) <= 50
    ):
        if new_name.strip() == account.get("name"):
            st.error(t("participant_name_same"))
        else:
            success = update_account_name(DB_PATH, account["id"], new_name.strip())
            if success:
                account["name"] = new_name.strip()
                st.session_state.account = account
                st.success(t("participant_name_changed_success"))
                st.session_state.show_change_name = False
                st.rerun()
            else:
                st.error(t("participant_name_change_error") + f" (ID: {account['id']})")

    st.markdown("</div>", unsafe_allow_html=True)

st.divider()

# ── Sidebar Menu ──────────────────────────────────────────────────────────────
st.sidebar.markdown("### 📋 Menu")
view = st.sidebar.radio(
    "Selecteer:",
    options=["register", "scores"],
    format_func=lambda x: "📝 Inschrijven" if x == "register" else "🏆 Scores",
    label_visibility="collapsed",
    key="participant_view",
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
    conn = _connect(DB_PATH, read_only=True)
    try:
        rows = conn.execute(
            """SELECT s.rider_url, s.rider_name, r.nickname, r.nationality, r.team_name
               FROM startlists s
               JOIN riders r ON s.rider_url = r.rider_url
               WHERE s.race_name = ? AND s.rider_name IS NOT NULL
               ORDER BY s.rider_name""",
            [race_name],
        ).fetchall()
    finally:
        conn.close()
    return rows

if selected_race:
    race_rider_rows = _load_race_rider_rows(selected_race)
    _rider_rows = race_rider_rows if race_rider_rows else _load_rider_rows()
else:
    _rider_rows = _load_rider_rows()

rider_options = {}
url_to_label = {}
_url_to_norm = {}
_selected_set = set()
for _url, _name, _nickname, _nat, _team in _rider_rows:
    _label = f"{_name} ({_nat or '?'}) 德华 {_team or '?'}" + (f" [{_nickname}]" if _nickname else "")
    rider_options[_label] = _url
    url_to_label[_url] = _label
    _url_to_norm[_url] = _normalize(_name)

# ── Check registration + team ─────────────────────────────────────────────────
existing_team = load_team_by_account(DB_PATH, account["id"], selected_race)
prefill_urls = existing_team["rider_urls"] if existing_team else []
prefill_team_name = existing_team["team_name"] if existing_team else ""

state_key = f"selected_urls_{account['id']}_{selected_race}"
if state_key not in st.session_state:
    st.session_state[state_key] = list(prefill_urls)

selected_urls: list = st.session_state[state_key]

if not registration_open and not existing_team:
    st.info(t("participant_no_team_registered"))

    st.divider()
    st.subheader("🏆 Scores")
    stages = load_stages(DB_PATH, selected_race)
    if not stages:
        st.info("No stages available for this race.")
    else:
        stages_with_results = [s for s in stages if load_stage_results(DB_PATH, selected_race, s["Stage"])]
        if not stages_with_results:
            st.info(t("no_results_this_race"))
        else:
            try:
                scores = calculate_scores(DB_PATH, selected_race)
                if scores:
                    df_scores = pd.DataFrame(scores)
                    df_scores = df_scores.sort_values("Total", ascending=False).reset_index(drop=True)
                    df_scores.index = df_scores.index + 1
                    st.dataframe(df_scores[["Team", "Total"]], width="stretch")
                else:
                    st.info("No scores available yet.")
            except Exception as e:
                st.error(f"Error loading scores: {e}")
    st.stop()

st.divider()

# ── MAIN CONTENT ──────────────────────────────────────────────────────────────

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

        state_key = f"selected_urls_{account['id']}_{selected_race}"
        if state_key not in st.session_state:
            st.session_state[state_key] = list(prefill_urls)

        selected_urls: list = st.session_state[state_key]

        if existing_team:
            st.info(f"✏️ {t('participant_existing_team_warning')}**{prefill_team_name}**. {t('participant_overwrite_warning')}")

        team_name = st.text_input(
            t("participant_team_name"),
            value=prefill_team_name,
            placeholder="e.g. Team Velodutch (max 50 chars)",
            key="team_name_input",
        )

        if team_name.strip() and len(team_name.strip()) > 50:
            st.error(t("participant_error_team_name_length"))

        st.divider()

        st.markdown(f"### 👥 {t('participant_verify_selection')} — {len(selected_urls)} / 15 {t('participant_selected_count')}")
        st.progress(len(selected_urls) / 15.0)

        if "search_query" not in st.session_state:
            st.session_state.search_query = ""
        if "search_key" not in st.session_state:
            st.session_state.search_key = 0

        search_query = st.text_input(
            f"🔍 {t('participant_search_rider')}",
            placeholder=t("participant_search_rider"),
            key=f"rider_search_{st.session_state.search_key}",
            value=st.session_state.search_query,
        )
        st.session_state.search_query = search_query

        col1, col2 = st.columns(2, gap="large")

        with col1:
            st.markdown(f"#### 📋 {t('startlist')}")

            _norm_query = _normalize(search_query) if search_query else ""
            startlist_available = {
                label: url
                for label, url in rider_options.items()
                if url not in selected_urls
                and (not search_query or _norm_query in _url_to_norm.get(url, ""))
            }

            if len(selected_urls) >= 15:
                st.info(t("participant_max_riders"))
            elif not search_query:
                st.caption(t("participant_search_hint"))
            elif startlist_available:
                _available_items = list(startlist_available.items())
                if len(_available_items) > 20:
                    st.caption(f"{t('participant_many_results')} ({len(_available_items)}) — {t('participant_refine_search')}")
                    _available_items = _available_items[:20]
                _available_labels = [label for label, _ in _available_items]
                add_label = st.radio(
                    t("participant_add_rider"),
                    options=_available_labels,
                    index=0,
                    key="rider_add_select_startlist",
                    label_visibility="collapsed",
                )
                if st.button(f"➕ {t('participant_add_rider')}", width="stretch", key="btn_add_rider_startlist"):
                    st.session_state[state_key].append(startlist_available[add_label])
                    st.session_state.search_key += 1
                    st.session_state.search_query = ""
                    st.rerun()
            else:
                _already = [
                    url_to_label.get(url, url).split(" (")[0]
                    for url in selected_urls
                    if _norm_query in _url_to_norm.get(url, "")
                ]
                if _already:
                    st.caption(f"✅ {t('participant_already_selected')}: **{', '.join(_already)}**")
                else:
                    st.caption(t("participant_no_riders_found"))

        with col2:
            st.markdown("#### 🚴 Rennerslijst")

            @st.cache_data(ttl=300)
            def _load_all_rider_rows():
                conn = _connect(DB_PATH, read_only=True)
                try:
                    rows = conn.execute(
                        "SELECT rider_url, name, nickname, nationality, team_name FROM riders WHERE name IS NOT NULL ORDER BY name"
                    ).fetchall()
                finally:
                    conn.close()
                return rows

            all_rider_rows = _load_all_rider_rows()

            general_rider_options = {}
            general_url_to_label = {}
            general_url_to_norm = {}

            startlist_rider_urls = {url for url in rider_options.values()}

            for _url, _name, _nickname, _nat, _team in all_rider_rows:
                if _url not in startlist_rider_urls:
                    _label = f"{_name} ({_nat or '?'}) 德华 {_team or '?'}" + (f" [{_nickname}]" if _nickname else "")
                    general_rider_options[_label] = _url
                    general_url_to_label[_url] = _label
                    general_url_to_norm[_url] = _normalize(_name)

            for _url, _name, _nickname, _nat, _team in all_rider_rows:
                _label = f"{_name} ({_nat or '?'}) 德华 {_team or '?'}" + (f" [{_nickname}]" if _nickname else "")
                if _url not in url_to_label:
                    url_to_label[_url] = _label

            if not general_rider_options:
                st.info("Alle renners uit de algemene database zitten al in de startlijst.")
            else:
                _norm_query_general = _normalize(search_query) if search_query else ""
                general_available = {
                    label: url
                    for label, url in general_rider_options.items()
                    if url not in selected_urls
                    and (not search_query or _norm_query_general in general_url_to_norm.get(url, ""))
                }

            if len(selected_urls) >= 15:
                st.info(t("participant_max_riders"))
            elif not search_query:
                st.caption(t("participant_search_hint"))
            elif general_available:
                _available_items = list(general_available.items())
                if len(_available_items) > 20:
                    st.caption(f"{t('participant_many_results')} ({len(_available_items)}) — {t('participant_refine_search')}")
                    _available_items = _available_items[:20]
                _available_labels = [label for label, _ in _available_items]
                add_label = st.radio(
                    t("participant_add_rider"),
                    options=_available_labels,
                    index=0,
                    key="rider_add_select_general",
                    label_visibility="collapsed",
                )
                if st.button(f"➕ {t('participant_add_rider')}", width="stretch", key="btn_add_rider_general"):
                    st.session_state[state_key].append(general_available[add_label])
                    st.session_state.search_key += 1
                    st.session_state.search_query = ""
                    st.rerun()
            else:
                _already = [
                    general_url_to_label.get(url, url).split(" (")[0]
                    for url in selected_urls
                    if _norm_query_general in general_url_to_norm.get(url, "")
                ]
                if _already:
                    st.caption(f"✅ {t('participant_already_selected')}: **{', '.join(_already)}**")

        # ── Selected riders list ──────────────────────────────────────────────
        if selected_urls:
            st.markdown(f"**{t('participant_selected_riders')}**")
            for i, url in enumerate(selected_urls):
                label = url_to_label.get(url, url)
                col_name, col_btn = st.columns([5, 1], vertical_alignment="center")
                col_name.markdown(f"{i + 1}. {label.split(' (')[0]}")
                if col_btn.button("✖", key=f"remove_{i}", width="stretch", help=t("delete_rider")):
                    st.session_state[state_key].pop(i)
                    st.rerun()
        else:
            st.caption(t("participant_no_riders_selected"))

        st.divider()

        # ── Save ─────────────────────────────────────────────────────────────
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
                    del st.session_state[state_key]
                    st.success(f"{t('participant_team_saved')}")
                    st.balloons()
                except Exception as exc:
                    st.error(f"{t('save_error')} {exc}")

elif view == "scores":
    stages = load_stages(DB_PATH, selected_race)
    if not stages:
        st.info("No stages available for this race.")
    else:
        stages_with_results = [s for s in stages if load_stage_results(DB_PATH, selected_race, s["Stage"])]

        if not stages_with_results:
            st.info(t("no_results_this_race"))
        else:
            st.subheader(f"Completed stages: {len(stages_with_results)} / {len(stages)}")

            try:
                scores = calculate_scores(DB_PATH, selected_race)
                if scores:
                    df_scores = pd.DataFrame(scores)
                    df_scores = df_scores.sort_values("Total", ascending=False).reset_index(drop=True)
                    df_scores.index = df_scores.index + 1
                    st.dataframe(
                        df_scores[["Team", "Total"]],
                        width="stretch",
                        hide_index=False,
                    )
                    st.divider()
                    st.caption(f"Updated based on {len(stages_with_results)} completed stages")
                else:
                    st.info("No scores available yet.")
            except Exception as e:
                st.error(f"Error loading scores: {e}")

# ── Language Selector (Sidebar - At Bottom) ───────────────────────────────────
st.sidebar.markdown("---")
st.sidebar.selectbox(
    t("language"),
    options=["nl", "en"],
    index=0 if st.session_state.language == "nl" else 1,
    format_func=lambda x: "🇳🇱 Nederlands" if x == "nl" else "🇬🇧 English",
    key="lang_selector",
    on_change=lambda: st.session_state.update({"language": st.session_state.lang_selector}),
    label_visibility="visible",
)
