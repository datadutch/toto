import os
import json
import re
import unicodedata
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

# ── Load Translations from JSON ──────────────────────────────────────────────
with open("translations.json", "r", encoding="utf-8") as f:
    TRANSLATIONS = json.load(f)

# ── Translation function ─────────────────────────────────────────────────────
def t(key: str) -> str:
    lang = st.session_state.get("language", "nl")
    return TRANSLATIONS.get(lang, {}).get(key, key)

# ── Initialize session state ─────────────────────────────────────────────────
if "language" not in st.session_state:
    st.session_state.language = "nl"

if "account" not in st.session_state:
    st.session_state.account = None

if "participant_view" not in st.session_state:
    st.session_state.participant_view = "register"

# ── Check if running on Streamlit Cloud ──────────────────────────────────────
_user = getattr(st, "user", None)
_cloud_email = getattr(_user, "email", None) if _user else None
_cloud_name = (getattr(_user, "name", None) or getattr(_user, "full_name", None)) if _user else None
_is_guest = getattr(_user, "is_logged_in", None) is False or _cloud_email is None

# ── Auto-login via environment variable ──────────────────────────────────────
if st.session_state.account is None:
    env_auto_login_email = os.getenv("PARTICIPANT_AUTO_LOGIN_EMAIL")
    if env_auto_login_email:
        account = get_account_by_email(DB_PATH, env_auto_login_email)
        if account:
            st.session_state.account = account
            st.rerun()


def show_login_form():
    st.set_page_config(page_title="Stampers Toto", page_icon="🚴", layout="centered")
    st.markdown("<style>[data-testid='stSidebarNav'] {display: none;}</style>", unsafe_allow_html=True)

    col_title, _ = st.columns([4, 1])
    with col_title:
        st.title(f"🚴 {t('participant_welcome')}")

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
        st.rerun()
    else:
        st.info(t("participant_no_account"))
        name_input = st.text_input(t("participant_your_name"), placeholder="e.g. Johan (max 50 chars)", key="name_input")

        if name_input.strip() and len(name_input.strip()) > 50:
            st.error(t("participant_error_username_length"))

        with st.form(key="create_account_form"):
            if st.form_submit_button(t("participant_create_account"), width="stretch"):
                account = create_account(DB_PATH, email_input.strip(), name_input.strip())
                st.session_state.account = account
                st.rerun()

    st.stop()


# ── Entry point ───────────────────────────────────────────────────────────────
if st.session_state.account is None:
    show_login_form()
else:
    pg = st.navigation(
        [
            st.Page("pages/participant_main.py", title="Deelnemer", icon="🚴"),
            st.Page("pages/administrator.py", title="Administrator", icon="👑"),
        ],
        position="hidden",
    )
    pg.run()


def get_account():
    return st.session_state.account

def get_db_path():
    return DB_PATH

def get_is_guest():
    return _is_guest
