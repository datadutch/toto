"""Shared setup and UI helpers for participant pages."""
import os
import json
import unicodedata
import streamlit as st
from dotenv import load_dotenv
from src.db import (
    _connect, load_races, is_registration_open, update_account_name,
)

load_dotenv()

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TOKEN = os.getenv("MOTHERDUCK_TOKEN")
if _TOKEN:
    DB_PATH = f"md:toto?motherduck_token={_TOKEN}"
else:
    DB_PATH = os.path.join(_ROOT, "data", "cycling.duckdb")

with open(os.path.join(_ROOT, "translation", "translations.json"), "r", encoding="utf-8") as f:
    TRANSLATIONS = json.load(f)


def t(key: str) -> str:
    lang = st.session_state.get("language", "nl")
    return TRANSLATIONS.get(lang, {}).get(key, key)


def _normalize(text: str) -> str:
    return unicodedata.normalize("NFD", text.lower()).encode("ascii", "ignore").decode("ascii")


def setup_page(layout: str = "centered") -> dict:
    """Set page config, init session state, auth check. Returns account dict."""
    st.set_page_config(page_title="Stampers Toto", page_icon="🚴", layout=layout)
    st.markdown("<style>[data-testid='stSidebarNav'] {display: none;}</style>", unsafe_allow_html=True)

    if "language" not in st.session_state:
        st.session_state.language = "nl"
    if "account" not in st.session_state:
        st.session_state.account = None

    if st.session_state.account is None:
        st.rerun()

    return st.session_state.account


def render_header(account: dict) -> None:
    """Top header with admin button and logout."""
    _user = getattr(st, "user", None)
    _cloud_email = getattr(_user, "email", None) if _user else None
    _is_guest = getattr(_user, "is_logged_in", None) is False or _cloud_email is None

    col_title, col_admin, col_logout = st.columns([3, 1, 1])
    with col_title:
        st.write("")
    with col_admin:
        if account.get("is_admin") == "yes":
            if st.button("👑 Admin", key="btn_admin", help="Naar admin paneel", use_container_width=True):
                st.switch_page("pages/administrator.py")
    with col_logout:
        if not _is_guest:
            st.markdown("[🚪 Uitloggen](?logout=true)", unsafe_allow_html=True)
        else:
            if st.button("🚪 Uitloggen", key="btn_logout_header"):
                for _k in [k for k in st.session_state if k.startswith("scores_stage_select_")]:
                    del st.session_state[_k]
                st.session_state["_clear_auth_cookie"] = True
                st.session_state.account = None
                st.rerun()


_SCORES_SUBPAGES = {
    "totals": ("scores_nav_totals", "pages/participant_scores_totals.py"),
    "stage":  ("scores_nav_stage",  "pages/participant_scores_stage.py"),
    "riders": ("scores_nav_riders", "pages/participant_scores_riders.py"),
}


def render_scores_nav(active: str) -> None:
    """Horizontal tab-style buttons for navigating between scores sub-pages."""
    cols = st.columns(len(_SCORES_SUBPAGES))
    for col, (key, (label_key, path)) in zip(cols, _SCORES_SUBPAGES.items()):
        if col.button(
            t(label_key),
            use_container_width=True,
            type="primary" if key == active else "secondary",
            key=f"scores_nav_{key}",
        ):
            st.switch_page(path)


def render_sidebar(account: dict, active_page: str) -> None:
    """Sidebar: user info, page navigation, language selector."""
    st.sidebar.markdown(f"<center><b>{t('participant_logged_in')}</b></center>", unsafe_allow_html=True)

    if st.sidebar.button(
        f"👤 **{account['name']}** ({account['email']})",
        key="btn_username",
        help="Klik om je naam te wijzigen",
        use_container_width=True,
    ):
        st.session_state.show_change_name = True

    st.sidebar.markdown("---")
    st.sidebar.markdown("### 📋 Menu")

    nav = st.sidebar.radio(
        "Navigatie",
        options=["register", "scores"],
        format_func=lambda x: "📝 Inschrijven" if x == "register" else "🏆 Scores",
        index=0 if active_page == "register" else 1,
        label_visibility="collapsed",
        key="sidebar_nav",
    )
    if nav != active_page:
        target = "pages/participant_register.py" if nav == "register" else _SCORES_SUBPAGES["totals"][1]
        st.switch_page(target)

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


def render_name_change_modal(account: dict) -> None:
    """Inline name-change form, shown when show_change_name is True."""
    if not st.session_state.get("show_change_name", False):
        return

    st.markdown(f"**📝 {t('participant_change_name')}**")
    new_name = st.text_input(
        t("participant_new_name"),
        placeholder="e.g. Johan (max 50 chars)",
        key="new_name_input",
        label_visibility="collapsed",
    )

    if new_name.strip() and len(new_name.strip()) > 50:
        st.error(t("participant_error_username_length"))

    col1, col2 = st.columns(2)
    if col1.button(t("participant_cancel"), use_container_width=True, key="cancel_name_change"):
        st.session_state.show_change_name = False
        st.rerun()

    if (
        col2.button(t("participant_save"), type="primary", use_container_width=True, key="save_name_change")
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

    st.divider()


def load_race_selector() -> tuple:
    """Race selectbox + deadline info. Returns (races, selected_race, race_info, registration_open)."""
    races = load_races(DB_PATH)
    if not races:
        st.error("No races configured yet. Ask the administrator.")
        st.stop()

    race_options = {r["race_name"]: r for r in races}
    selected_race = st.selectbox(t("participant_select_race"), list(race_options.keys()), key="race_selector")
    race_info = race_options[selected_race]
    registration_open = is_registration_open(DB_PATH, selected_race)

    if race_info["deadline"]:
        if registration_open:
            st.info(f"⏰ {t('participant_registration_open')} **{race_info['deadline'].strftime('%d/%m/%Y om %H:%M')}**")
        else:
            st.error(f"⏰ {t('participant_registration_closed')} **{race_info['deadline'].strftime('%d/%m/%Y om %H:%M')}**. {t('participant_no_new_teams')}")

    return races, selected_race, race_info, registration_open


@st.cache_data(ttl=300)
def _load_all_rider_rows() -> list:
    conn = _connect(DB_PATH, read_only=True)
    try:
        return conn.execute(
            "SELECT rider_url, name, nickname, nationality, team_name FROM riders WHERE name IS NOT NULL ORDER BY name"
        ).fetchall()
    finally:
        conn.close()


def load_riders(selected_race: str) -> tuple:
    """Load rider options for the race.
    Returns (rider_options, url_to_label, url_to_norm, all_rows, startlist_urls).
    rider_options contains only startlist riders (falls back to all riders if no startlist).
    """
    conn = _connect(DB_PATH, read_only=True)
    try:
        race_rows = conn.execute(
            """SELECT s.rider_url, s.rider_name, r.nickname, r.nationality, r.team_name
               FROM startlists s
               JOIN riders r ON s.rider_url = r.rider_url
               WHERE s.race_name = ? AND s.rider_name IS NOT NULL
               ORDER BY s.rider_name""",
            [selected_race],
        ).fetchall()
    finally:
        conn.close()

    all_rows = _load_all_rider_rows()
    base_rows = race_rows if race_rows else all_rows

    rider_options = {}
    url_to_label = {}
    url_to_norm = {}
    for _url, _name, _nickname, _nat, _team in base_rows:
        _label = f"{_name} ({_nat or '?'}) — {_team or '?'}" + (f" [{_nickname}]" if _nickname else "")
        rider_options[_label] = _url
        url_to_label[_url] = _label
        url_to_norm[_url] = _normalize(_name)

    startlist_urls = set(rider_options.values())

    # Enrich url_to_label with non-startlist riders (for display in selected-rider list)
    for _url, _name, _nickname, _nat, _team in all_rows:
        if _url not in url_to_label:
            _label = f"{_name} ({_nat or '?'}) — {_team or '?'}" + (f" [{_nickname}]" if _nickname else "")
            url_to_label[_url] = _label

    return rider_options, url_to_label, url_to_norm, all_rows, startlist_urls
