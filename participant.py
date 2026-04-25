import os
import json
import re
import unicodedata
import streamlit as st
from dotenv import load_dotenv
from supabase import create_client
from src.db import get_account_by_email, create_account

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

# ── Supabase config ──────────────────────────────────────────────────────────
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "")

# ── Load Translations from JSON ──────────────────────────────────────────────
with open("translations.json", "r", encoding="utf-8") as f:
    TRANSLATIONS = json.load(f)

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

def _get_supabase():
    if "_supabase" not in st.session_state:
        st.session_state._supabase = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    return st.session_state._supabase

# ── Auto-login via environment variable ──────────────────────────────────────
if st.session_state.account is None:
    env_auto_login_email = os.getenv("PARTICIPANT_AUTO_LOGIN_EMAIL")
    if env_auto_login_email:
        acct = get_account_by_email(DB_PATH, env_auto_login_email)
        if acct:
            st.session_state.account = acct
            st.rerun()


# ── Login sub-views ───────────────────────────────────────────────────────────

def _show_name_form():
    """New user: email verified, still needs a display name."""
    email = st.session_state.pending_email
    st.success(f"✅ E-mailadres **{email}** geverifieerd!")
    st.subheader("Welkom! Kies een naam voor je account.")

    with st.form("name_form"):
        name_input = st.text_input(
            t("participant_your_name"),
            placeholder="e.g. Johan (max 50 chars)",
        )
        submitted = st.form_submit_button("✅ Account aanmaken", type="primary", use_container_width=True)

    if submitted:
        if not name_input.strip():
            st.error("Voer een naam in.")
        elif len(name_input.strip()) > 50:
            st.error(t("participant_error_username_length"))
        else:
            acct = create_account(DB_PATH, email, name_input.strip())
            st.session_state.account = acct
            st.session_state.pop("pending_email", None)
            st.rerun()

    st.stop()


def _show_otp_step():
    """Step 2: user received the code by email, enters it here."""
    email = st.session_state.otp_email
    st.info(f"📧 Code verstuurd naar **{email}**. Vul hem hieronder in.")

    with st.form("otp_form"):
        code_input = st.text_input(
            "Inlogcode",
            placeholder="123456",
            max_chars=6,
            help="6-cijferige code uit de e-mail",
        )
        col_ok, col_back = st.columns([2, 1])
        submitted = col_ok.form_submit_button("✅ Inloggen", use_container_width=True, type="primary")
        back = col_back.form_submit_button("↩ Terug", use_container_width=True)

    if back:
        st.session_state.pop("otp_email", None)
        st.rerun()

    if submitted:
        if not code_input.strip():
            st.error("Voer de 6-cijferige code in.")
            st.stop()
        try:
            sb = _get_supabase()
            resp = sb.auth.verify_otp({
                "email": email,
                "token": code_input.strip(),
                "type": "email",
            })
            verified_email = resp.user.email
            st.session_state.pop("otp_email", None)
            acct = get_account_by_email(DB_PATH, verified_email)
            if acct:
                st.session_state.account = acct
            else:
                st.session_state.pending_email = verified_email
            st.rerun()
        except Exception:
            st.error("❌ Ongeldige of verlopen code. Probeer opnieuw of vraag een nieuwe code aan.")

    st.divider()
    if st.button("📨 Nieuwe code aanvragen"):
        try:
            sb = _get_supabase()
            sb.auth.sign_in_with_otp({
                "email": email,
                "options": {"should_create_user": True},
            })
            st.success("Nieuwe code verstuurd.")
        except Exception as e:
            st.error(f"Kon geen code versturen: {e}")

    st.stop()


def _show_email_step():
    """Step 1: ask for email and send OTP code."""
    if st.session_state.pop("auth_error", False):
        st.error("❌ De code is verlopen of ongeldig. Vraag hieronder een nieuwe aan.")

    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        st.error("⚠️ Supabase is niet geconfigureerd. Stel SUPABASE_URL en SUPABASE_ANON_KEY in als secrets.")
        st.stop()

    email_input = st.text_input(t("email"), placeholder="e.g. johan@example.com")

    if not email_input.strip():
        st.stop()

    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not re.match(email_pattern, email_input.strip()):
        st.error(t("participant_invalid_email"))
        st.stop()

    if st.button("📨 Stuur inlogcode", type="primary", use_container_width=True):
        try:
            sb = _get_supabase()
            sb.auth.sign_in_with_otp({
                "email": email_input.strip(),
                "options": {"should_create_user": True},
            })
            st.session_state.otp_email = email_input.strip()
            st.rerun()
        except Exception as e:
            st.error(f"Kon geen code versturen: {e}")

    st.stop()


def show_login_form():
    st.set_page_config(page_title="Stampers Toto", page_icon="🚴", layout="centered")
    st.markdown("<style>[data-testid='stSidebarNav'] {display: none;}</style>", unsafe_allow_html=True)

    col_title, _ = st.columns([4, 1])
    with col_title:
        st.title(f"🚴 {t('participant_welcome')}")

    st.subheader(t("participant_login_register"))

    if st.session_state.get("pending_email"):
        _show_name_form()
    elif st.session_state.get("otp_email"):
        _show_otp_step()
    else:
        _show_email_step()


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
