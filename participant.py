import os
import json
import re
import time
import unicodedata
import urllib.parse
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
from login import get_account, t, DB_PATH, get_is_guest, _normalize

# ── Environment Detection ───────────────────────────────────────────────────
def get_login_url():
    """Detect if running locally or in production and return the appropriate URL."""
    # Check if we're running on Streamlit Cloud
    if "STREAMLIT_CLOUD" in os.environ:
        # Production environment - Streamlit Cloud
        return "https://stamperstotogalore.streamlit.app/"
    else:
        # Local development
        return "http://localhost:8500/"

# ── Load Translations from JSON ──────────────────────────────────────────────
with open("translations.json", "r", encoding="utf-8") as f:
    TRANSLATIONS = json.load(f)

# ── Initialize Language ──────────────────────────────────────────────────────
if "language" not in st.session_state:
    st.session_state.language = "nl"

# ── Initialize view state ──────────────────────────────────────────────────────
if "participant_view" not in st.session_state:
    st.session_state.participant_view = "register"

# Initialize account if not present
if "account" not in st.session_state:
    st.session_state.account = None

# ── Session Management Functions ───────────────────────────────────────────
def extend_session(account_id):
    """Extend the current session by 10 minutes."""
    conn = _connect(DB_PATH)
    try:
        # Get current session for this account
        current_session = conn.execute(
            "SELECT session_id FROM sessions WHERE account_id = ?",
            [str(account_id)]
        ).fetchone()
        
        if current_session:
            # Extend existing session
            session_id = current_session[0]
            new_expiry = int(time.time()) + 600  # Extend by 10 minutes
            conn.execute(
                "UPDATE sessions SET expiry = ? WHERE session_id = ?",
                [new_expiry, session_id]
            )
            conn.commit()
            return session_id
        else:
            # Create new session
            session_id = str(uuid.uuid4())
            expiry = int(time.time()) + 600
            conn.execute(
                "INSERT INTO sessions (session_id, account_id, expiry) VALUES (?, ?, ?)",
                [session_id, str(account_id), expiry]
            )
            conn.commit()
            return session_id
    finally:
        conn.close()
    return None

# ── Auto-login via session ID in URL ────────────────────────────────────────
query_params = st.query_params
if query_params.get("session_id") and st.session_state.account is None:
    session_id = query_params.get("session_id")
    # Validate session and get account
    conn = _connect(DB_PATH)
    try:
        # Debug: Show we're checking the session
        st.info(f"🔍 Controleer sessie: {session_id[:8]}...")
        
        # Check if session exists and is not expired
        session = conn.execute(
            "SELECT account_id, expiry FROM sessions WHERE session_id = ?",
            [session_id]
        ).fetchone()
        
        if session:
            st.info(f"📋 Sessie gevonden: account={session[0]}, verloopt={time.ctime(session[1])}")
            
            if session[1] > int(time.time()):
                # Session is valid, get account
                st.info(f"✅ Sessie is geldig, account ophalen...")
                account_id = session[0]
                account = conn.execute(
                    "SELECT * FROM accounts WHERE id = ?",
                    [account_id]
                ).fetchone()
                
                if account:
                    st.info(f"👤 Account gevonden: {dict(account).get('email')}")
                    # Convert account to dict and store in session
                    account_dict = dict(account)
                    # Ensure all keys are strings
                    account_dict = {str(k): v for k, v in account_dict.items()}
                    st.session_state.account = account_dict
                    
                    # Debug: Show successful login
                    st.success(f"✅ Succesvol ingelogd als {account_dict.get('name', 'gebruiker')}")
                    
                    # Extend the session (instead of deleting it)
                    new_expiry = int(time.time()) + 600
                    conn.execute(
                        "UPDATE sessions SET expiry = ? WHERE session_id = ?",
                        [new_expiry, session_id]
                    )
                    conn.commit()
                    
                    # Store session ID in session state for future extensions
                    st.session_state.session_id = session_id
                    
                    # Clear the query params from URL
                    st.query_params.clear()
                    # Continue without rerun - the page will render normally with the account loaded
                else:
                    st.error(f"❌ Account niet gevonden voor ID: {account_id}")
            else:
                st.error(f"❌ Sessie is verlopen op {time.ctime(session[1])}")
        else:
            st.error(f"❌ Sessie {session_id[:8]}... niet gevonden in database")
    except Exception as e:
        st.error(f"❌ Fout bij sessie herstel: {e}")
    finally:
        conn.close()

# Add logout button in header (after _is_guest is defined)
_is_guest = get_is_guest()
if st.session_state.account is not None:
    # Create columns for title, admin button, and logout button
    col_title, col_admin, col_logout_header = st.columns([3, 1, 1])
    with col_title:
        # Title was already set above, just add spacing
        st.write("")  # Add some space
    
    # Add admin button if user is admin
    with col_admin:
        account = st.session_state.account
        if account.get("is_admin") == "yes":
            # Use the fixed admin URL
            admin_url = "https://stamperstoto.streamlit.app/"
            admin_params = {
                "email": account["email"],
            } 
            
            full_admin_url = f"{admin_url}?{urllib.parse.urlencode(admin_params)}" 
            
            # Use st.link_button for better styling (Streamlit 1.25+)
            # Note: st.link_button opens in same tab by default
            if hasattr(st, 'link_button'):
                st.link_button("👑 Admin", full_admin_url, help="Naar admin paneel", use_container_width=True)
            else:
                st.markdown(
                    f'<a href="{full_admin_url}" target="_self" style="display: inline-block; width: 100%; text-align: center;">👑 Admin</a>',
                    unsafe_allow_html=True,
                    help="Naar admin paneel"
                )
    
    with col_logout_header:
        if not _is_guest:
            # On Streamlit Cloud, logout is handled by the platform
            st.markdown("[🚪 Uitloggen](?logout=true)", unsafe_allow_html=True)
        else:
            if st.button("🚪 Uitloggen", key="btn_logout_header", help="Uitloggen"):
                st.session_state.account = None
                login_url = get_login_url()
                st.success(f"✅ Succesvol uitgelogd! Je kunt dit venster sluiten of naar [login pagina]({login_url}) gaan.")
                st.stop()

# ── Logged in ─────────────────────────────────────────────────────────────────
account = st.session_state.account

# Debug: Check what's in session state
if st.session_state.account is None:
    # Check if there's a session_id but no account (should not happen)
    if 'session_id' in st.session_state:
        # Try to restore session
        conn = _connect(DB_PATH)
        try:
            session = conn.execute(
                "SELECT account_id, expiry FROM sessions WHERE session_id = ?",
                [st.session_state.session_id]
            ).fetchone()
            
            if session and session[1] > int(time.time()):
                # Session is still valid, restore account
                account_id = session[0]
                account = conn.execute(
                    "SELECT * FROM accounts WHERE id = ?",
                    [account_id]
                ).fetchone()
                
                if account:
                    account_dict = {str(k): v for k, v in dict(account).items()}
                    st.session_state.account = account_dict
                    st.rerun()
        finally:
            conn.close()

# Debug: Show session status and database info
if st.session_state.account is None:
    st.warning("🔍 Controleer sessie... ")
    if 'session_id' in st.session_state:
        st.info(f"Sessie-ID gevonden: {st.session_state.session_id[:8]}... (probeer te herstellen)")
    
    # Always show debug button when no account
    if st.button("🔧 Toon database sessies"):
        conn = _connect(DB_PATH)
        try:
            sessions = conn.execute("SELECT * FROM sessions").fetchall()
            if sessions:
                st.write("### Actieve Sessies:")
                for session in sessions:
                    expiry_time = time.ctime(session[2])
                    is_expired = session[2] < int(time.time())
                    status = "❌ Verlopen" if is_expired else "✅ Actief"
                    st.write(f"- ID: {session[0][:8]}..., Account: {session[1]}, Verloopt: {expiry_time} {status}")
            else:
                st.write("📊 Geen actieve sessies gevonden")
            
            # Also show accounts for debugging
            accounts = conn.execute("SELECT id, email, name FROM accounts LIMIT 5").fetchall()
            if accounts:
                st.write("### Account Overzicht:")
                for acc in accounts:
                    st.write(f"- ID: {acc[0]}, Email: {acc[1]}, Naam: {acc[2]}")
        finally:
            conn.close()

# Toon een foutmelding als er geen account is
if st.session_state.account is None:
    login_url = get_login_url()
    st.error(f"❌ Je bent niet ingelogd. Ga naar de [login pagina]({login_url}) om in te loggen.")
    st.stop()

# Use the account from session state
account = st.session_state.account

# ── Sidebar: User info ──────────────────────────────────────────────────────

# "Ingelogd als" label
st.sidebar.markdown(f"<center><b>{t('participant_logged_in')}</b></center>", unsafe_allow_html=True)

# Clickable username to open name change popup
if st.sidebar.button(
    f"👤 **{account['name']}** ({account['email']})", 
    key="btn_username",
    help="Klik om je naam te wijzigen",
    use_container_width=True
):
    st.session_state.show_change_name = True

st.sidebar.markdown("---")

if st.session_state.get("show_change_name", False):
    # Full overlay to block the rest of the website
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
    
    
    # Modal title
    st.markdown('📝 ' + t("participant_change_name"), unsafe_allow_html=True)
    
    # Input field
    new_name = st.text_input(
        t("participant_new_name"), 
        placeholder="e.g. Johan (max 50 chars)", 
        key="new_name_input",
        label_visibility="collapsed"
    )
    
    # Real-time validation
    if new_name.strip() and len(new_name.strip()) > 50:
        st.error(t("participant_error_username_length"))
    
    # Buttons
    col1, col2 = st.columns([1, 1])
    if col1.button(t("participant_cancel"), use_container_width=True):
        st.session_state.show_change_name = False
        st.rerun()
    
    if col2.button(t("participant_save"), type="primary", use_container_width=True) and new_name.strip() and len(new_name.strip()) <= 50:
        # Check if name is actually different
        if new_name.strip() == account.get("name"):
            st.error(t("participant_name_same"))
        else:
            print(f"Attempting to update account {account['id']} with name: {new_name.strip()}")
            success = update_account_name(DB_PATH, account["id"], new_name.strip())
            print(f"Update result: {success}")
            if success:
                account["name"] = new_name.strip()
                st.session_state.account = account
                # Extend session on action
                if 'session_id' in st.session_state:
                    extend_session(account["id"])
                st.success(t("participant_name_changed_success"))
                st.session_state.show_change_name = False
                st.rerun()
            else:
                st.error(t("participant_name_change_error") + f" (ID: {account['id']})")
    
    st.markdown('</div>', unsafe_allow_html=True)

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
    _label = f"{_name} ({_nat or '?'}) 德华 {_team or '?'}" + (f" [{_nickname}]" if _nickname else "")
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
        team_name = st.text_input(t("participant_team_name"), value=prefill_team_name, placeholder="e.g. Team Velodutch (max 50 chars)", key="team_name_input")
        
        # Real-time validation for team name length
        if team_name.strip() and len(team_name.strip()) > 50:
            st.error(t("participant_error_team_name_length"))

        st.divider()

        # ── Dual Search Boxes for Rider Selection ──────────────────────────────────
        st.markdown(f"### 👥 {t('participant_verify_selection')} — {len(selected_urls)} / 15 {t('participant_selected_count')}")

        # Show progress bar
        progress = len(selected_urls) / 15.0
        st.progress(progress)

        # Use session state to control search input so we can clear it
        if "search_query" not in st.session_state:
            st.session_state.search_query = ""
        if "search_key" not in st.session_state:
            st.session_state.search_key = 0
        
        search_query = st.text_input(
            f"🔍 {t('participant_search_rider')}", 
            placeholder=t("participant_search_rider"), 
            key=f"rider_search_{st.session_state.search_key}",
            value=st.session_state.search_query
        )
        # Update session state with current search query
        st.session_state.search_query = search_query

        # Two column layout for search boxes
        col1, col2 = st.columns(2, gap="large")

        with col1:
            st.markdown(f"#### 📋 {t('startlist')}")
            
            # Filter rider options by search query (name only, accent-insensitive), exclude already selected
            _norm_query = _normalize(search_query) if search_query else ""
            startlist_available = {
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
                    # Clear search box after adding rider
                    st.session_state.search_key += 1
                    st.session_state.search_query = ""
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

        with col2:
            st.markdown(f"#### 🚴 Rennerslijst")
            
            # For the general rider database search, we need to load all riders
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
            
            # Build general rider options - exclude riders that are already in the startlist
            general_rider_options = {}
            general_url_to_label = {}
            general_url_to_norm = {}
            
            # Get URLs from startlist for filtering - we need to compare the actual rider URLs
            startlist_rider_urls = {url for url in rider_options.values()}
            
            for _url, _name, _nickname, _nat, _team in all_rider_rows:
                # Only include riders that are NOT in the startlist
                if _url not in startlist_rider_urls:
                    _label = f"{_name} ({_nat or '?'}) 德华 {_team or '?'}" + (f" [{_nickname}]" if _nickname else "")
                    general_rider_options[_label] = _url
                    general_url_to_label[_url] = _label
                    general_url_to_norm[_url] = _normalize(_name)
            
            # Add all general riders to the unified url_to_label lookup after the loop
            # This ensures that riders from general database are properly displayed
            for _url, _name, _nickname, _nat, _team in all_rider_rows:
                _label = f"{_name} ({_nat or '?'}) 德华 {_team or '?'}" + (f" [{_nickname}]" if _nickname else "")
                if _url not in url_to_label:  # Don't overwrite startlist entries
                    url_to_label[_url] = _label

            # Show info if no riders are available in general database (all are in startlist)
            if not general_rider_options:
                st.info("Alle renners uit de algemene database zitten al in de startlijst.")
            else:
                # Filter general rider options
                _norm_query_general = _normalize(search_query) if search_query else ""
                general_available = {
                    label: url
                    for label, url in general_rider_options.items()
                    if url not in selected_urls and (
                        not search_query or _norm_query_general in general_url_to_norm.get(url, "")
                    )
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
                    # Clear search box after adding rider
                    st.session_state.search_key += 1
                    st.session_state.search_query = ""
                    st.rerun()
            else:
                # Check if the rider is missing because already selected
                _already = [
                    general_url_to_label.get(url, url).split(" (")[0]
                    for url in selected_urls
                    if _norm_query_general in general_url_to_norm.get(url, "")
                ]
                if _already:
                    st.caption(f"✅ {t('participant_already_selected')}: **{', '.join(_already)}**")
                # else: removed the participant_no_riders_found message

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
                    # Extend session on action
                    if 'session_id' in st.session_state:
                        extend_session(account["id"])
                    
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

# ── Language Selector (Sidebar - At Bottom) ──────────────────────────────────
st.sidebar.markdown("---")
st.sidebar.selectbox(
    t("language"),
    options=["nl", "en"],
    index=0 if st.session_state.language == "nl" else 1,
    format_func=lambda x: "🇳🇱 Nederlands" if x == "nl" else "🇬🇧 English",
    key="lang_selector",
    on_change=lambda: st.session_state.update({"language": st.session_state.lang_selector}),
    label_visibility="visible"
)
