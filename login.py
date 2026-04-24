import os
import json
import re
import unicodedata
import urllib.parse
import streamlit as st
from dotenv import load_dotenv
from src.db import (
    init_fantasy_tables, init_accounts_table,
    get_account_by_email, create_account,
)

def _normalize(text: str) -> str:
    """Lowercase + strip diacritics so 'pogacar' matches 'Pogačar'."""
    return unicodedata.normalize("NFD", text.lower()).encode("ascii", "ignore").decode("ascii")

load_dotenv()

# ── Database Path ────────────────────────────────────────────────────────────
_TOKEN = os.getenv("MOTHERDUCK_TOKEN")
if _TOKEN:
    DB_PATH = f"md:toto?motherduck_token={_TOKEN}"
else:
    DB_PATH = os.path.join(os.path.dirname(__file__), "data", "cycling.duckdb")

st.set_page_config(page_title="Stampers Toto", page_icon="🚴", layout="centered")

# Hide default multipage sidebar nav
st.markdown("<style>[data-testid='stSidebarNav'] {display: none;}</style>", unsafe_allow_html=True)

# ── Load Translations from JSON ──────────────────────────────────────────────
with open("translations.json", "r", encoding="utf-8") as f:
    TRANSLATIONS = json.load(f)

# ── Translation function ─────────────────────────────────────────────────────
def t(key: str) -> str:
    """Get translation for current language."""
    lang = st.session_state.get("language", "nl")
    return TRANSLATIONS.get(lang, {}).get(key, key)

# Create columns for title and login button
col_title, col_login = st.columns([4, 1])
with col_title:
    st.title(f"🚴 LOGIN {t("participant_welcome")}")

# ── Initialize session state ─────────────────────────────────────────────────
if "language" not in st.session_state:
    st.session_state.language = "nl"

if "account" not in st.session_state:
    st.session_state.account = None

# ── Check if running on Streamlit Cloud ──────────────────────────────────────
_cloud_email = None
_cloud_name = None
_user = getattr(st, "user", None)

if _user:
    _cloud_email = _user.email
    _cloud_name = getattr(_user, "name", None) or getattr(_user, "full_name", None)

_is_guest = getattr(_user, "is_logged_in", None) is False or _cloud_email is None

# ── Session state ─────────────────────────────────────────────────────────────
if "participant_view" not in st.session_state:
    st.session_state.participant_view = "register"

# ── Auto-login via environment variable ──────────────────────────────────────
if st.session_state.account is None:
    env_auto_login_email = os.getenv("PARTICIPANT_AUTO_LOGIN_EMAIL")
    if env_auto_login_email:
        account = get_account_by_email(DB_PATH, env_auto_login_email)
        if account:
            st.session_state.account = account
            st.rerun()

# Show the login form
def show_login_form():
    st.subheader(t("participant_login_register"))

    email_input = st.text_input(t("email"), placeholder="e.g. johan@example.com")

    if not email_input.strip():
        st.stop()

    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not re.match(email_pattern, email_input.strip()):
        st.error(t("participant_invalid_email"))
        st.stop()

    account = get_account_by_email(DB_PATH, email_input.strip())

    if account:
        st.session_state.account = account
        st.success(f"{t('participant_welcome_back')}, **{account['name']}**!")
        st.switch_page("pages/participant.py")
    else:
        st.info(t("participant_no_account"))
        name_input = st.text_input(t("participant_your_name"), placeholder="e.g. Johan (max 50 chars)", key="name_input")

        if name_input.strip() and len(name_input.strip()) > 50:
            st.error(t("participant_error_username_length"))

        with st.form(key="create_account_form"):
            if st.form_submit_button(t("participant_create_account"), width="stretch"):
                account = create_account(DB_PATH, email_input.strip(), name_input.strip())
                st.session_state.account = account
                st.success(f"✅ Ingelogd! Welkom, **{account['name']}**!")
                st.switch_page("pages/participant.py")

    st.stop()


# ── Manual login / registration (local dev or guest) ─────────────────────────
if st.session_state.account is not None:
    st.switch_page("pages/participant.py")

show_login_form()


# Return the account if logged in
def get_account():
    return st.session_state.account

# Return the DB_PATH
def get_db_path():
    return DB_PATH

# Return the _is_guest variable
def get_is_guest():
    return _is_guest
