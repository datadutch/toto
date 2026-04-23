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


# Create columns for title and login button
col_title, col_login = st.columns([4, 1])
with col_title:
    st.title(f"🚴 {t('participant_welcome')}")

# Remove login button from header as it's not needed
with col_login:
    st.write("")  # Empty space to maintain layout


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

# Show the login form
def show_login_form():
    st.subheader(t("participant_login_register"))

    email_input = st.text_input(t("email"), placeholder="e.g. johan@example.com")

    if not email_input.strip():
        st.stop()

    # Validate email format
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not re.match(email_pattern, email_input.strip()):
        st.error(t("participant_invalid_email"))
        st.stop()

    account = get_account_by_email(DB_PATH, email_input.strip())

    if account:
        st.success(f"{t('participant_welcome_back')}, **{account['name']}**!")
        st.session_state.account = account
        st.rerun()
    else:
        st.info(t("participant_no_account"))
        name_input = st.text_input(t("participant_your_name"), placeholder="e.g. Johan (max 50 chars)", key="name_input") 
        
        # Real-time validation for username length
        if name_input.strip() and len(name_input.strip()) > 50:
            st.error(t("participant_error_username_length"))
        
        if name_input.strip() and len(name_input.strip()) <= 50:
            if st.button(t("participant_create_account"), width="stretch"):
                account = create_account(DB_PATH, email_input.strip(), name_input.strip())
                st.session_state.account = account
                st.rerun()

    st.stop()

# Call the login form if no account is present
if st.session_state.account is None:
    show_login_form()
else:
    # If account is present, show a message
    st.success(f"Welcome back, {st.session_state.account['name']}!")