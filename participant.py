import os
import unicodedata
import streamlit as st
from dotenv import load_dotenv
from src.db import (
    init_fantasy_tables, init_accounts_table,
    save_fantasy_team, load_team_by_account,
    get_account_by_email, create_account,
    _connect, load_races, is_registration_open,
)
from src.voice import extract_riders_from_text, match_riders_to_db


def _normalize(text: str) -> str:
    """Lowercase + strip diacritics so 'pogacar' matches 'Pogačar'."""
    return unicodedata.normalize("NFD", text.lower()).encode("ascii", "ignore").decode("ascii")

load_dotenv()

_TOKEN = os.getenv("MOTHERDUCK_TOKEN") or st.secrets.get("MOTHERDUCK_TOKEN", "")
if _TOKEN:
    DB_PATH = f"md:toto?motherduck_token={_TOKEN}"
else:
    DB_PATH = os.path.join(os.path.dirname(__file__), "data", "cycling.duckdb")

st.set_page_config(page_title="Stampers Toto", page_icon="🚴", layout="centered")
st.title("🚴 Stampers Toto")

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

# ── Auto-login via Google (Streamlit Cloud) ───────────────────────────────────
if not _is_guest and _cloud_email and st.session_state.account is None:
    account = get_account_by_email(DB_PATH, _cloud_email)
    if not account:
        display_name = _cloud_name or _cloud_email.split("@")[0]
        account = create_account(DB_PATH, _cloud_email, display_name)
    st.session_state.account = account

# ── Manual login / registration (local dev or guest) ─────────────────────────
if st.session_state.account is None:
    st.subheader("Inloggen / registreren")

    email_input = st.text_input("E-mailadres", placeholder="e.g. johan@example.com")

    if not email_input.strip():
        st.stop()

    account = get_account_by_email(DB_PATH, email_input.strip())

    if account:
        st.success(f"Welkom terug, **{account['name']}**!")
        st.session_state.account = account
        st.rerun()
    else:
        st.info("Nog geen account. Voer je naam in om je te registreren.")
        name_input = st.text_input("Jouw naam", placeholder="e.g. Johan")
        if name_input.strip():
            if st.button("Account aanmaken", use_container_width=True):
                account = create_account(DB_PATH, email_input.strip(), name_input.strip())
                st.session_state.account = account
                st.rerun()

    st.stop()

# ── Logged in ─────────────────────────────────────────────────────────────────
account = st.session_state.account

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

# ── Race selection ────────────────────────────────────────────────────────────
races = load_races(DB_PATH)
if not races:
    st.error("No races configured yet. Ask the administrator.")
    st.stop()

race_options = {r["race_name"]: r for r in races}
selected_race = st.selectbox("Selecteer een race", list(race_options.keys()))

race_info = race_options[selected_race]
registration_open = is_registration_open(DB_PATH, selected_race)

if race_info["deadline"]:
    if registration_open:
        st.info(f"⏰ Inschrijving sluit op **{race_info['deadline'].strftime('%d/%m/%Y om %H:%M')}**")
    else:
        st.error(f"⏰ Inschrijving gesloten op **{race_info['deadline'].strftime('%d/%m/%Y om %H:%M')}**. Geen nieuwe teams mogelijk.")

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

# ── Team form ─────────────────────────────────────────────────────────────────
if not registration_open:
    existing_team = load_team_by_account(DB_PATH, account["id"], selected_race)
    if existing_team:
        st.subheader(f"Jouw team: {existing_team['team_name']}")
        for i, url in enumerate(existing_team["rider_urls"]):
            label = url_to_label.get(url, url)
            st.markdown(f"{i + 1}. {label.split(' (')[0]}")
    else:
        st.info("Je had geen team geregistreerd voor deze race.")
    st.stop()

existing_team = load_team_by_account(DB_PATH, account["id"], selected_race)
prefill_urls = existing_team["rider_urls"] if existing_team else []
prefill_team_name = existing_team["team_name"] if existing_team else ""

# Initialise session state for rider selection (reset when race changes)
state_key = f"selected_urls_{account['id']}_{selected_race}"
if state_key not in st.session_state:
    st.session_state[state_key] = list(prefill_urls)

selected_urls: list = st.session_state[state_key]

if existing_team:
    st.info(f"✏️ Je hebt al een team voor deze race: **{prefill_team_name}**. Opslaan overschrijft je bestaande selectie.")

# ── Team name ─────────────────────────────────────────────────────────────────
team_name = st.text_input("Teamnaam", value=prefill_team_name, placeholder="e.g. Team Velodutch", key="team_name_input")

st.divider()

# ── Free-text rider input ───────────────────────────────────────────────────
st.markdown("**📝 Typ je renners (vrije tekst)**")
st.caption("Noem gewoon de namen, in willekeurige volgorde. De app herkent ze automatisch.")
free_text = st.text_area(
    "Renners",
    placeholder="bijv. Pogacar, Vingegaard, Evenepoel, Van der Poel, Van Aert...",
    height=100,
    key="free_text_riders",
    label_visibility="collapsed",
)
if free_text.strip():
    if st.button("🔍 Herken renners", key="btn_extract_riders"):
        with st.spinner("Even kijken..."):
            try:
                extracted = extract_riders_from_text(free_text.strip())
            except RuntimeError as e:
                st.error(str(e))
                extracted = []
        if extracted:
            matched_urls, not_found = match_riders_to_db(extracted, DB_PATH)
            st.session_state[state_key] = matched_urls
            if not_found:
                st.warning(
                    f"{len(not_found)} renner(s) niet gevonden in de database: "
                    + ", ".join(f"**{n}**" for n in not_found)
                    + ". Voeg ze hieronder handmatig toe of controleer de spelling."
                )
            st.rerun()
        else:
            st.warning("Geen renners herkend in de tekst. Controleer de invoer.")

st.divider()

# ── Rider search + add (corrections) ────────────────────────────────────────
st.markdown(f"**Controleer of pas je selectie aan** — {len(selected_urls)} / 15 geselecteerd")

search_query = st.text_input("🔍 Zoek renner", placeholder="Typ naam...", key="rider_search")

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
    st.info("Maximum van 15 renners bereikt.")
elif not search_query:
    st.caption("Zoek een renner via de zoekbalk hierboven.")
elif available:
    _available_items = list(available.items())
    if len(_available_items) > 20:
        st.caption(f"Meer dan 20 resultaten ({len(_available_items)}) — verfijn je zoekopdracht.")
        _available_items = _available_items[:20]
    _available_labels = [label for label, _ in _available_items]
    add_label = st.radio(
        "Renner toevoegen",
        options=_available_labels,
        index=0,
        key="rider_add_select",
        label_visibility="collapsed",
    )
    if st.button("➕ Toevoegen", use_container_width=True, key="btn_add_rider"):
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
        st.caption(f"✅ Al in je team: **{', '.join(_already)}**")
    else:
        st.caption("Geen renners gevonden voor deze zoekopdracht.")

# ── Selected riders list ──────────────────────────────────────────────────────
if selected_urls:
    st.markdown("**Geselecteerde renners:**")
    for i, url in enumerate(selected_urls):
        label = url_to_label.get(url, url)
        col_name, col_btn = st.columns([5, 1], vertical_alignment="center")
        col_name.markdown(f"{i + 1}. {label.split(' (')[0]}")
        if col_btn.button("✖", key=f"remove_{i}", use_container_width=True, help="Verwijderen"):
            st.session_state[state_key].pop(i)
            st.rerun()
else:
    st.caption("Nog geen renners geselecteerd.")

st.divider()

# ── Save ──────────────────────────────────────────────────────────────────────
if st.button("✅ Team opslaan", use_container_width=True, type="primary"):
    errors = []
    if not team_name.strip():
        errors.append("Voer een teamnaam in.")
    if len(selected_urls) == 0:
        errors.append("Selecteer minimaal 1 renner.")
    if not is_registration_open(DB_PATH, selected_race):
        errors.append("Inschrijving is gesloten voor deze race.")

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
                st.success(f"Team **{team_name.strip()}** bijgewerkt! 🎉")
            else:
                st.success(f"Team **{team_name.strip()}** geregistreerd! 🎉")
            st.balloons()
        except Exception as exc:
            st.error(f"Kon team niet opslaan: {exc}")
