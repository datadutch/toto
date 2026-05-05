import os
import json
import re
import unicodedata
import streamlit as st
from dotenv import load_dotenv
from supabase import create_client
from streamlit_cookies_controller import CookieController
from src.db import get_account_by_email, create_account

SESSION_DURATION = 5 * 3600  # 5 hours in seconds

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
with open(os.path.join(os.path.dirname(__file__), "translation", "translations.json"), "r", encoding="utf-8") as f:
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


def _set_session_cookie(refresh_token: str) -> None:
    CookieController(key="supa_cookie_ctrl").set("supa_refresh", refresh_token, max_age=SESSION_DURATION)


def _clear_session_cookie() -> None:
    CookieController(key="supa_cookie_ctrl").remove("supa_refresh")

# ── Detect post-verification redirect ────────────────────────────────────────
_qp = st.query_params
if _qp.get("verified") == "1" and not st.session_state.get("email_confirmed"):
    st.session_state["email_confirmed"] = True
    st.session_state["newly_verified"] = True
    st.query_params.clear()
    st.rerun()

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
    st.success(t("participant_email_verified").format(email=email))
    st.subheader(t("participant_welcome_choose_name"))

    with st.form("name_form"):
        name_input = st.text_input(
            t("participant_your_name"),
            placeholder="e.g. Johan (max 50 chars)",
        )
        submitted = st.form_submit_button(t("participant_create_account"), type="primary", use_container_width=True)

    if submitted:
        if not name_input.strip():
            st.error(t("participant_error_name_required"))
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
    st.info(t("participant_otp_sent").format(email=email))

    with st.form("otp_form"):
        code_input = st.text_input(
            t("participant_otp_code_label"),
            placeholder="12345678",
            max_chars=8,
            help=t("participant_otp_help"),
        )
        col_ok, col_back = st.columns([2, 1])
        submitted = col_ok.form_submit_button(t("participant_login_btn"), use_container_width=True, type="primary")
        back = col_back.form_submit_button(t("participant_back"), use_container_width=True)

    if back:
        st.session_state.pop("otp_email", None)
        st.rerun()

    if submitted:
        if not code_input.strip():
            st.error(t("participant_otp_required"))
            st.stop()
        try:
            sb = _get_supabase()
            resp = sb.auth.verify_otp({
                "email": email,
                "token": code_input.strip(),
                "type": "email",
            })
            verified_email = resp.user.email
            if resp.session and resp.session.refresh_token:
                _set_session_cookie(resp.session.refresh_token)
            st.session_state.pop("otp_email", None)
            acct = get_account_by_email(DB_PATH, verified_email)
            if acct:
                st.session_state.account = acct
            else:
                st.session_state.pending_email = verified_email
            st.rerun()
        except Exception:
            st.error(t("participant_otp_invalid"))

    st.divider()
    if st.button(t("participant_otp_resend")):
        try:
            sb = _get_supabase()
            sb.auth.sign_in_with_otp({
                "email": email,
                "options": {"should_create_user": True},
            })
            st.success(t("participant_otp_resent"))
        except Exception as e:
            st.error(f"{t('participant_otp_send_error')} {e}")

    st.stop()


def _show_email_step():
    """Step 1: ask for email and send OTP code."""
    if st.session_state.pop("auth_error", False):
        st.error(t("participant_auth_error"))

    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        st.error("⚠️ Supabase is niet geconfigureerd. Stel SUPABASE_URL en SUPABASE_ANON_KEY in als secrets.")
        st.stop()

    email_input = st.text_input(t("email"), placeholder=t("email_placeholder"))

    if not email_input.strip():
        st.stop()

    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not re.match(email_pattern, email_input.strip()):
        st.error(t("participant_invalid_email"))
        st.stop()

    if st.button(t("participant_send_otp"), type="primary", use_container_width=True):
        try:
            sb = _get_supabase()
            is_known_user = get_account_by_email(DB_PATH, email_input.strip()) is not None
            newly_verified = st.session_state.pop("newly_verified", False)
            sb.auth.sign_in_with_otp({
                "email": email_input.strip(),
                "options": {
                    "should_create_user": True,
                    "email_redirect_to": "https://stamperstotogalore.streamlit.app?verified=1",
                },
            })
            if is_known_user or newly_verified:
                st.session_state.otp_email = email_input.strip()
            else:
                st.session_state.confirm_email = email_input.strip()
            st.rerun()
        except Exception as e:
            st.error(f"Kon geen code versturen: {e}")

    st.stop()


def _show_confirm_email_step():
    """New user: confirmation email sent, waiting for them to click the link."""
    email = st.session_state.confirm_email
    st.info(t("participant_confirm_sent").format(email=email))
    st.markdown(t("participant_confirm_instructions"))
    st.divider()
    col_retry, col_back = st.columns(2)
    if col_retry.button(t("participant_confirm_resend"), use_container_width=True):
        try:
            sb = _get_supabase()
            sb.auth.sign_in_with_otp({
                "email": email,
                "options": {
                    "should_create_user": True,
                    "email_redirect_to": "https://stamperstotogalore.streamlit.app?verified=1",
                },
            })
            st.success(t("participant_confirm_resent"))
        except Exception as e:
            st.error(f"{t('participant_otp_send_error')} {e}")
    if col_back.button(t("participant_back"), use_container_width=True):
        st.session_state.pop("confirm_email", None)
        st.rerun()
    st.stop()


def show_login_form():
    st.set_page_config(page_title="Stampers Toto", page_icon="🚴", layout="centered")
    st.markdown("<style>[data-testid='stSidebarNav'] {display: none;}</style>", unsafe_allow_html=True)

    # ── Cookie-gebaseerde sessie (mag pas na set_page_config) ─────────────────
    _cookie = CookieController(key="supa_cookie_ctrl")

    if st.session_state.pop("_clear_auth_cookie", False):
        _cookie.remove("supa_refresh")
        st.session_state.pop("_refresh_attempted", None)

    if not st.session_state.get("_refresh_attempted"):
        _rt = _cookie.get("supa_refresh")
        if _rt:
            st.session_state["_refresh_attempted"] = True
            try:
                _sb = _get_supabase()
                _resp = _sb.auth.refresh_session(_rt)
                if _resp.session and _resp.user:
                    _acct = get_account_by_email(DB_PATH, _resp.user.email)
                    if _acct:
                        st.session_state.account = _acct
                        st.session_state.pop("_refresh_attempted", None)
                        _set_session_cookie(_resp.session.refresh_token)
                        st.rerun()
            except Exception:
                _cookie.remove("supa_refresh")
    # ─────────────────────────────────────────────────────────────────────────

    col_title, _ = st.columns([4, 1])
    with col_title:
        st.title(f"🚴 {t('participant_welcome')}")

    st.subheader(t("participant_login_register"))

    if st.session_state.pop("email_confirmed", False):
        st.success(t("participant_email_confirmed"))

    st.sidebar.selectbox(
        t("language"),
        options=["nl", "en"],
        index=0 if st.session_state.language == "nl" else 1,
        format_func=lambda x: "🇳🇱 Nederlands" if x == "nl" else "🇬🇧 English",
        key="lang_selector_login",
        on_change=lambda: st.session_state.update({"language": st.session_state.lang_selector_login}),
        label_visibility="visible",
    )

    if st.session_state.get("pending_email"):
        _show_name_form()
    elif st.session_state.get("otp_email"):
        _show_otp_step()
    elif st.session_state.get("confirm_email"):
        _show_confirm_email_step()
    else:
        _show_email_step()


# ── Entry point ───────────────────────────────────────────────────────────────
if st.session_state.account is None:
    show_login_form()
else:
    pg = st.navigation(
        [
            st.Page("pages/participant_register.py",       title="Inschrijven",     icon="📝"),
            st.Page("pages/participant_scores_totals.py",  title="Team scores",     icon="🏆"),
            st.Page("pages/participant_scores_stage.py",   title="Stage resultaat", icon="🏁"),
            st.Page("pages/participant_scores_riders.py",  title="Renners totaal",  icon="🚴"),
            st.Page("pages/administrator.py",              title="Administrator",   icon="👑"),
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
