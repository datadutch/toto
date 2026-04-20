import os
import re
import json
import duckdb
import streamlit as st
import pandas as pd
from dotenv import load_dotenv
from procyclingstats import Stage as PCSStage
from src.db import (
    init_fantasy_tables, save_fantasy_team, load_fantasy_teams, load_fantasy_team_riders,
    init_stages_table, load_stages,
    init_stage_results_table, save_stage_results, delete_stage_results, load_stage_results, stages_with_results,
    calculate_scores, calculate_stage_breakdown,
    init_races_table, load_races, update_deadline,
    init_accounts_table, init_admin_accounts, get_account_by_email, create_account, set_admin_status,
    save_rider, delete_rider,
)

load_dotenv()

# ── Load Translations from JSON ──────────────────────────────────────────────
with open("translations.json", "r", encoding="utf-8") as f:
    TRANSLATIONS = json.load(f)

_TOKEN = os.getenv("MOTHERDUCK_TOKEN") or ""
if _TOKEN:
    DB_PATH = f"md:toto?motherduck_token={_TOKEN}"
    _READ_ONLY = False  # MotherDuck does not support read_only attach
else:
    DB_PATH = os.path.join(os.path.dirname(__file__), "data", "cycling.duckdb")
    _READ_ONLY = True

st.set_page_config(page_title="Stampers Toto Administratie", page_icon="🚴", layout="wide")

# ── Custom CSS for Fixed Footer Language Selector ──────────────────────────
st.markdown("""
    <style>
    /* Fixed footer for language selector */
    .footer {
        position: fixed;
        bottom: 0;
        right: 0;
        width: auto;
        padding: 12px 20px;
        background-color: rgba(255, 255, 255, 0.95);
        border-top: 1px solid #e0e0e0;
        z-index: 999;
        display: flex;
        align-items: center;
        gap: 10px;
        box-shadow: 0 -2px 8px rgba(0,0,0,0.1);
    }
    .footer span {
        font-size: 14px;
        color: #666;
    }
    </style>
""", unsafe_allow_html=True)

# ── Initialize Language ──────────────────────────────────────────────────────
if "language" not in st.session_state:
    st.session_state.language = "nl"

def t(key):
    """Translate a key to the current language"""
    return TRANSLATIONS[st.session_state.language].get(key, key)


def get_connection():
    return duckdb.connect(DB_PATH, read_only=_READ_ONLY)


# ── Shared: rider options (cached) ───────────────────────────────────────────
@st.cache_data(ttl=300)
def _get_all_rider_rows():
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT rider_url, name, nationality, team_name FROM riders WHERE name IS NOT NULL ORDER BY name"
        ).fetchall()
    finally:
        conn.close()


# ── Shared: positional results entry UI ─────────────────────────────────────
_POSITIONS_NL = ["1e", "2e", "3e", "4e", "5e", "6e", "7e", "8e", "9e", "10e",
                 "11e", "12e", "13e", "14e", "15e"]
_NONE = "— niet geselecteerd —"


def _get_stage_number_from_name(stage_name: str):
    """Extract stage number from stage name like 'Stage 1' or 'Stage 1 (ITT)'."""
    if "rest" in stage_name.lower():
        return None
    match = re.search(r'stage\s+(\d+)', stage_name, re.IGNORECASE)
    if match:
        return match.group(1)
    match = re.search(r'(\d+)', stage_name)
    return match.group(1) if match else None


def _race_identifier_from_name(race_name: str) -> str:
    """Convert race name to ProCyclingStats identifier."""
    # Giro d'Italia -> giro-d-italia
    return race_name.lower().replace(" ", "-").replace("'", "")


def _fetch_top_15_from_pcs(race_name: str, stage_name: str) -> list[dict]:
    """Fetch top 15 riders from ProCyclingStats for a race stage."""
    race_id = _race_identifier_from_name(race_name)
    stage_num = _get_stage_number_from_name(stage_name)
    if not stage_num:
        return []
    
    # Construct PCS URL
    pcs_url = f"race/{race_id}/{stage_num}/result"
    
    try:
        stage = PCSStage(pcs_url)
        result = stage.parse()
        riders = result.get("results", [])
        
        top_15 = []
        for rider in riders:
            if rider.get("rank") and len(top_15) < 15:
                top_15.append(rider)
        return top_15
    except Exception as e:
        st.error(f"Failed to fetch from ProCyclingStats: {e}")
        return []


def _render_results_entry(race_name: str, stage_name: str, key_prefix: str):
    """Render 15 positional selectboxes for entering stage results."""
    rider_rows = _get_all_rider_rows()
    url_to_name = {url: name for url, name, _, _ in rider_rows}
    # label -> url
    all_options = {
        f"{name} ({nat or '?'}) — {team or '?'}": url
        for url, name, nat, team in rider_rows
    }

    # Load existing results to pre-fill
    existing = load_stage_results(DB_PATH, race_name, stage_name)
    prefill_urls = [None] * 15
    if existing:
        _url_by_name = {name: url for url, name, _, _ in rider_rows}
        for r in existing:
            idx = r["Pos"] - 1
            if 0 <= idx < 15:
                prefill_urls[idx] = _url_by_name.get(r["Rider"])

    if existing:
        st.info(f"Resultaten al opgeslagen voor **{stage_name}** — opslaan overschrijft.")

    # Session state key for current selections
    sk = f"results_{key_prefix}_{stage_name}"
    if sk not in st.session_state:
        st.session_state[sk] = [url for url in prefill_urls]

    current = st.session_state[sk]
    label_list = [_NONE] + list(all_options.keys())

    all_labels = [_NONE] + list(all_options.keys())

    for i in range(15):
        # Determine current selection label
        cur_url = current[i]
        cur_label = _NONE
        if cur_url:
            cur_label = next((lbl for lbl, url in all_options.items() if url == cur_url), _NONE)
        cur_idx = all_labels.index(cur_label) if cur_label in all_labels else 0

        col_pos, col_sel = st.columns([1, 8])
        col_pos.markdown(f"**{_POSITIONS_NL[i]}**")
        chosen = col_sel.selectbox(
            f"Positie {i+1}",
            options=all_labels,
            index=cur_idx,
            key=f"{key_prefix}_pos_{i}_{stage_name}",
            label_visibility="collapsed",
        )
        current[i] = all_options.get(chosen)

    st.session_state[sk] = current

    filled = [u for u in current if u]
    duplicates = len(filled) - len(set(filled))
    st.caption(f"{len(filled)} / 15 posities ingevuld" + (f" — ⚠️ {duplicates} dubbele renner(s)" if duplicates else ""))

    if st.button("💾 Opslaan", width="stretch", key=f"{key_prefix}_save_{stage_name}"):
        if len(filled) != 15:
            st.error(f"Vul alle 15 posities in (nu {len(filled)}).")
        elif len(set(filled)) != 15:
            st.error("Elke renner mag maar één keer voorkomen. Verwijder duplicaten.")
        else:
            try:
                save_stage_results(DB_PATH, race_name, stage_name, current)
                st.success(f"Resultaten opgeslagen voor **{stage_name}**!")
                st.rerun()
            except Exception as exc:
                st.error(f"Kon niet opslaan: {exc}")

    if existing:
        if st.button("🗑️ Uitslag verwijderen", width="stretch", key=f"{key_prefix}_delete_{stage_name}", type="secondary"):
            delete_stage_results(DB_PATH, race_name, stage_name)
            st.session_state.pop(sk, None)
            for _i in range(15):
                st.session_state.pop(f"{key_prefix}_pos_{_i}_{stage_name}", None)
            st.cache_data.clear()
            st.success(f"Uitslag verwijderd voor **{stage_name}**.")
            st.rerun()


def load_data(name_filter, nationality_filter, team_filter):
    query = "SELECT * FROM riders WHERE 1=1"
    params = []

    if name_filter:
        query += " AND lower(name) LIKE ?"
        params.append(f"%{name_filter.lower()}%")
    if nationality_filter and nationality_filter != "All":
        query += " AND nationality = ?"
        params.append(nationality_filter)
    if team_filter:
        query += " AND lower(team_name) LIKE ?"
        params.append(f"%{team_filter.lower()}%")

    query += " ORDER BY name"
    conn = get_connection()
    try:
        return conn.execute(query, params).df()
    finally:
        conn.close()


# ── Check DB exists ──────────────────────────────────────────────────────────
if not DB_PATH.startswith("md:") and not os.path.exists(DB_PATH):
    st.warning("Database not found. Run `python main.py` first to scrape rider data.")
    st.stop()

try:
    _conn = get_connection()
    total = _conn.execute("SELECT count(*) FROM riders").fetchone()[0]
    _conn.close()
except Exception:
    st.error("Could not read from database. Make sure the scraper has run.")
    st.stop()

init_fantasy_tables(DB_PATH)
init_stages_table(DB_PATH)
init_stage_results_table(DB_PATH)
init_races_table(DB_PATH)
init_accounts_table(DB_PATH)

# ── One-time migration: promote old ADMIN_EMAILS to is_admin='yes' ────────────
_ADMIN_EMAILS_OLD = [
    e.strip().lower()
    for e in str(os.getenv("ADMIN_EMAILS", "")).split(",")
    if e.strip()
]
if _ADMIN_EMAILS_OLD:
    init_admin_accounts(DB_PATH, _ADMIN_EMAILS_OLD)

# ── Admin login ───────────────────────────────────────────────────────────────
if "admin_account" not in st.session_state:
    st.session_state.admin_account = None

# ── Language Selector (Sidebar - Always Visible) ───────────────────────────────
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

if st.session_state.admin_account is None:
    st.title(f"🚴 {t('title')}")
    st.subheader(t("login"))
    _email = st.text_input("E-mail", placeholder=t("email_placeholder"))
    if not _email.strip():
        st.stop()
    _acct = get_account_by_email(DB_PATH, _email.strip())
    if not _acct:
        _acct = create_account(DB_PATH, _email.strip(), _email.strip().split("@")[0])
    # Check if account has admin privileges
    if _acct.get("is_admin") != "yes":
        st.error(t("no_access"))
        st.stop()
    st.session_state.admin_account = _acct
    st.rerun()

_admin = st.session_state.admin_account
_col_title, _col_middle, _col_logout = st.columns([4, 2, 1])
_col_title.title(f"🚴 {t('title')}")

# Link to participant app with auto-login
if _admin and _admin.get("email"):
    participant_url = os.getenv("PARTICIPANT_APP_URL")
    if participant_url:
        # Add email parameter for auto-login
        separator = "&" if "?" in participant_url else "?"
        full_url = f"{participant_url}{separator}email={_admin['email']}&auto_login=true"
        _col_middle.link_button(f"👥 {t('participant_app')}", full_url, type="primary", help=t("participant_help"), width="stretch")
    else:
        _col_middle.warning("⚠️ PARTICIPANT_APP_URL not set in environment variables")

if _col_logout.button(t("logout"), key="admin_logout"):
    st.session_state.admin_account = None
    st.rerun()

st.caption(f"{t('database_riders')} **{total:,}** {t('database_riders_suffix')}")


tab_explorer, tab_giro, tab_bp, tab_agr, tab_scores, tab_settings, tab_riders = st.tabs([
    f"🔍 {t('tab_explorer')}", 
    f"🏁 {t('tab_giro')}", 
    f"🚵 {t('tab_brabantse')}", 
    f"🌷 {t('tab_amstel')}", 
    f"🏆 {t('tab_scores')}", 
    f"👥 {t('tab_teams')}", 
    f"➕ {t('tab_riders')}"
])

# ── Tab: Explorer ─────────────────────────────────────────────────────────────
with tab_explorer:
    # Sidebar filters (visible on both tabs but only used here)
    st.sidebar.header(t("filters"))
    name_filter = st.sidebar.text_input(t("search_by_name"), placeholder="e.g. Pogacar")
    team_filter = st.sidebar.text_input(t("search_by_team"), placeholder="e.g. UAE")

    _conn2 = get_connection()
    nationalities = ["All"] + sorted(
        [r[0] for r in _conn2.execute(
            "SELECT DISTINCT nationality FROM riders WHERE nationality IS NOT NULL ORDER BY nationality"
        ).fetchall()]
    )
    _conn2.close()
    nationality_filter = st.sidebar.selectbox(t("nationality"), nationalities)

    df = load_data(name_filter, nationality_filter, team_filter)
    st.subheader(f"{len(df):,} {t('riders_found')}")

    if df.empty:
        st.info(t("no_match"))
    else:
        display_cols = ["name", "nationality", "birthdate", "height", "weight", "team_name"]
        display_cols = [c for c in display_cols if c in df.columns]

        st.dataframe(
            df[display_cols].rename(columns={
                "name": "Name",
                "nationality": "NAT",
                "birthdate": "Date of Birth",
                "height": "Height (m)",
                "weight": "Weight (kg)",
                "team_name": "Team",
            }),
            width="stretch",
            hide_index=True,
        )

    st.divider()
    st.subheader(t("rider_detail"))

    rider_names = df["name"].dropna().tolist() if not df.empty else []
    if rider_names:
        selected = st.selectbox(t("select_rider"), rider_names)
        if selected:
            row = df[df["name"] == selected].iloc[0]
            col1, col2, col3 = st.columns(3)
            col1.metric(t("nationality"), row.get("nationality") or "—")
            col2.metric(t("date_of_birth"), row.get("birthdate") or "—")
            col3.metric(t("team"), row.get("team_name") or "—")
            col1.metric(t("height"), f"{row['height']} m" if pd.notna(row.get("height")) else "—")
            col2.metric(t("weight"), f"{row['weight']} kg" if pd.notna(row.get("weight")) else "—")
            if row.get("rider_url"):
                st.markdown(f"[View on ProCyclingStats](https://www.procyclingstats.com/{row['rider_url']})")

# ── Tab: Giro d'Italia ────────────────────────────────────────────────────────
with tab_giro:
    st.subheader(f"{t('giro_d_italia')} — {t('stage_overview')}")

    stages = load_stages(DB_PATH, "Giro d'Italia")
    finished = stages_with_results(DB_PATH, "Giro d'Italia")

    if stages:
        stages_df = pd.DataFrame(stages)
        stages_df["Results"] = stages_df["Stage"].apply(
            lambda s: "✅" if s in finished else ("—" if s == "Rest Day" else "")
        )

        def highlight_rest(row):
            if row["Stage"] == "Rest Day":
                return ["background-color: #f0f0f0; color: #888"] * len(row)
            return [""] * len(row)

        styled = (
            stages_df.style
            .apply(highlight_rest, axis=1)
            .format({"KM": lambda v: f"{v:.1f}" if pd.notna(v) and v else "—"})
        )
        st.dataframe(styled, hide_index=True, width="stretch")

        racing_stages = [s for s in stages if s["Stage"] != "Rest Day"]
        total_km = sum(s["KM"] for s in racing_stages if s["KM"])
        col1, col2, col3 = st.columns(3)
        col1.metric("Racing stages", len(racing_stages))
        col2.metric("Total distance", f"{total_km:.1f} km")
        col3.metric("Rest days", sum(1 for s in stages if s["Stage"] == "Rest Day"))

    # ── Enter / view stage results ─────────────────────────────────────────────
    st.divider()
    st.subheader(t("stage_results"))

    racing_stage_names = [s["Stage"] for s in stages if s["Stage"] != "Rest Day"]

    sub_giro_enter, sub_giro_view = st.tabs([f"📝 {t('enter_results')}", f"📊 {t('view_results')}"])

    with sub_giro_enter:
        if racing_stage_names:
            col_sel, col_fetch = st.columns([3, 1])
            with col_sel:
                giro_selected = st.selectbox("Etappe", racing_stage_names, key="giro_result_stage")
            with col_fetch:
                if st.button(f"🌐 {t('fetch_pcs')}", key="giro_fetch_pcs"):
                    with st.spinner(t("fetching")):
                        riders = _fetch_top_15_from_pcs("Giro d'Italia", giro_selected)
                        if riders:
                            # Save directly to database
                            save_stage_results(DB_PATH, "Giro d'Italia", giro_selected, riders)
                            st.success(f"✓ {t('fetched_saved')} {len(riders)} {t('riders')} {giro_selected}")
                            st.rerun()
                        else:
                            st.warning(t("no_results_fetched"))
            
            _render_results_entry("Giro d'Italia", giro_selected, "giro")

    with sub_giro_view:
        if racing_stage_names:
            giro_view_stage = st.selectbox("Etappe", racing_stage_names, key="giro_view_stage")
            giro_results = load_stage_results(DB_PATH, "Giro d'Italia", giro_view_stage)
            if giro_results:
                st.dataframe(pd.DataFrame(giro_results), hide_index=True, width="stretch")
            else:
                st.info(t("no_stage_results"))

    # ── Registration deadline ──────────────────────────────────────────────────
    st.divider()
    st.markdown(f"#### {t('registration_deadline')}")
    _giro_races = load_races(DB_PATH)
    _giro_race = next((r for r in _giro_races if r["race_name"] == "Giro d'Italia"), None)
    if _giro_race:
        _cur = _giro_race["deadline"]
        _c1, _c2, _c3 = st.columns([2, 2, 1])
        _new_date = _c1.date_input(t("date"), value=_cur.date() if _cur else None, key="giro_dl_date")
        _new_time = _c2.time_input(t("time"), value=_cur.time() if _cur else None, key="giro_dl_time")
        if _c3.button(f"💾 {t('save')}", key="giro_dl_save", width="stretch"):
            from datetime import datetime
            combined = datetime.combine(_new_date, _new_time)
            update_deadline(DB_PATH, "Giro d'Italia", combined)
            st.success(f"{t('deadline_updated')} {combined.strftime('%d/%m/%Y %H:%M')}")
            st.rerun()

# ── Tab: De Brabantse Pijl ───────────────────────────────────────────────────
with tab_bp:
    st.subheader(t("brabantse_pijl"))

    bp_stages = load_stages(DB_PATH, "De Brabantse Pijl")
    bp_stage_names = [s["Stage"] for s in bp_stages]

    sub_bp_enter, sub_bp_view = st.tabs([f"📝 {t('enter_results')}", f"📊 {t('view_results')}"])

    with sub_bp_enter:
        if bp_stage_names:
            col_sel, col_fetch = st.columns([3, 1])
            with col_sel:
                bp_selected = st.selectbox("Etappe", bp_stage_names, key="bp_result_stage")
            with col_fetch:
                if st.button(f"🌐 {t('fetch_pcs')}", key="bp_fetch_pcs"):
                    with st.spinner(t("fetching")):
                        riders = _fetch_top_15_from_pcs("De Brabantse Pijl", bp_selected)
                        if riders:
                            save_stage_results(DB_PATH, "De Brabantse Pijl", bp_selected, riders)
                            st.success(f"✓ {t('fetched_saved')} {len(riders)} {t('riders')} {bp_selected}")
                            st.rerun()
                        else:
                            st.warning(t("no_results_fetched"))
            
            _render_results_entry("De Brabantse Pijl", bp_selected, "bp")

    with sub_bp_view:
        if bp_stage_names:
            bp_view_stage = st.selectbox("Etappe", bp_stage_names, key="bp_view_stage")
            bp_results = load_stage_results(DB_PATH, "De Brabantse Pijl", bp_view_stage)
            if bp_results:
                st.dataframe(pd.DataFrame(bp_results), hide_index=True, width="stretch")
            else:
                st.info(t("no_stage_results"))

    # ── Registration deadline ──────────────────────────────────────────────────
    st.divider()
    st.markdown(f"#### {t('registration_deadline')}")
    _bp_races = load_races(DB_PATH)
    _bp_race = next((r for r in _bp_races if r["race_name"] == "De Brabantse Pijl"), None)
    if _bp_race:
        _cur = _bp_race["deadline"]
        _c1, _c2, _c3 = st.columns([2, 2, 1])
        _new_date = _c1.date_input(t("date"), value=_cur.date() if _cur else None, key="bp_dl_date")
        _new_time = _c2.time_input(t("time"), value=_cur.time() if _cur else None, key="bp_dl_time")
        if _c3.button(f"💾 {t('save')}", key="bp_dl_save", width="stretch"):
            from datetime import datetime
            combined = datetime.combine(_new_date, _new_time)
            update_deadline(DB_PATH, "De Brabantse Pijl", combined)
            st.success(f"{t('deadline_updated')} {combined.strftime('%d/%m/%Y %H:%M')}")
            st.rerun()

# ── Tab: Amstel Gold Race ─────────────────────────────────────────────────────
with tab_agr:
    st.subheader(t("amstel_gold_race"))

    agr_stages = load_stages(DB_PATH, "Amstel Gold Race")
    agr_stage_names = [s["Stage"] for s in agr_stages]

    sub_agr_enter, sub_agr_view = st.tabs([f"📝 {t('enter_results')}", f"📊 {t('view_results')}"])

    with sub_agr_enter:
        if agr_stage_names:
            col_sel, col_fetch = st.columns([3, 1])
            with col_sel:
                agr_selected = st.selectbox("Etappe", agr_stage_names, key="agr_result_stage")
            with col_fetch:
                if st.button(f"🌐 {t('fetch_pcs')}", key="agr_fetch_pcs"):
                    with st.spinner(t("fetching")):
                        riders = _fetch_top_15_from_pcs("Amstel Gold Race", agr_selected)
                        if riders:
                            save_stage_results(DB_PATH, "Amstel Gold Race", agr_selected, riders)
                            st.success(f"✓ {t('fetched_saved')} {len(riders)} {t('riders')} {agr_selected}")
                            st.rerun()
                        else:
                            st.warning(t("no_results_fetched"))
            
            _render_results_entry("Amstel Gold Race", agr_selected, "agr")

    with sub_agr_view:
        if agr_stage_names:
            agr_view_stage = st.selectbox("Etappe", agr_stage_names, key="agr_view_stage")
            agr_results = load_stage_results(DB_PATH, "Amstel Gold Race", agr_view_stage)
            if agr_results:
                st.dataframe(pd.DataFrame(agr_results), hide_index=True, width="stretch")
            else:
                st.info(t("no_stage_results"))

    # ── Registration deadline ──────────────────────────────────────────────────
    st.divider()
    st.markdown(f"#### {t('registration_deadline')}")
    _agr_races = load_races(DB_PATH)
    _agr_race = next((r for r in _agr_races if r["race_name"] == "Amstel Gold Race"), None)
    if _agr_race:
        _cur = _agr_race["deadline"]
        _c1, _c2, _c3 = st.columns([2, 2, 1])
        _new_date = _c1.date_input(t("date"), value=_cur.date() if _cur else None, key="agr_dl_date")
        _new_time = _c2.time_input(t("time"), value=_cur.time() if _cur else None, key="agr_dl_time")
        if _c3.button(f"💾 {t('save')}", key="agr_dl_save", width="stretch"):
            from datetime import datetime
            combined = datetime.combine(_new_date, _new_time)
            update_deadline(DB_PATH, "Amstel Gold Race", combined)
            st.success(f"{t('deadline_updated')} {combined.strftime('%d/%m/%Y %H:%M')}")
            st.rerun()

# ── Tab: Scores ───────────────────────────────────────────────────────────────
with tab_scores:
    st.subheader(f"🏆 {t('scores')}")
    st.caption(t("scoring_system"))

    _all_races = load_races(DB_PATH)
    _score_race_tabs = st.tabs([r["race_name"] for r in _all_races])

    for _score_race_tab, _race in zip(_score_race_tabs, _all_races):
        _rname = _race["race_name"]
        with _score_race_tab:
            scores = calculate_scores(DB_PATH, _rname)

            if not scores:
                st.info(f"{t('no_scores')} **{_rname}**.")
            else:
                scores_df = pd.DataFrame(scores)

                st.markdown(f"#### {t('ranking')}")
                st.dataframe(
                    scores_df,
                    hide_index=True,
                    width="stretch",
                )

                st.divider()
                st.markdown(f"#### {t('team_breakdown')}")
                teams = load_fantasy_teams(DB_PATH, _rname)
                if teams:
                    team_labels = {f"{t['team_name']} ({t['manager_name']})": t["id"] for t in teams}
                    chosen_label = st.selectbox("Team", list(team_labels.keys()), key=f"scores_team_{_rname}")
                    if chosen_label:
                        chosen_id = team_labels[chosen_label]
                        breakdown = calculate_stage_breakdown(DB_PATH, _rname, chosen_id)
                        if breakdown:
                            bd_df = pd.DataFrame(breakdown)
                            st.dataframe(bd_df, hide_index=True, width="stretch")
                            st.metric(t("total_points"), int(bd_df["Points"].sum()))
                        else:
                            st.info(t("no_team_riders"))

# ── Tab: Teams ───────────────────────────────────────────────────────────────
with tab_settings:
    st.subheader(f"👥 {t('teams')}")
    
    # ── Admin User Management ─────────────────────────────────────────────
    if st.session_state.admin_account.get("is_admin") == "yes":
        st.markdown("---")
        st.subheader(f"👑 {t('admin_users')}")
        
        # List all accounts with admin status
        conn = get_connection()
        all_accounts = conn.execute("SELECT email, name, is_admin FROM accounts ORDER BY is_admin DESC, email").fetchall()
        conn.close()
        
        if all_accounts:
            df_accounts = pd.DataFrame(all_accounts, columns=[t("email"), t("name"), "Admin"])
            st.dataframe(df_accounts, hide_index=True, width="stretch")
            
            st.markdown("---")
            st.subheader(t("admin_status_change"))
            
            email_to_update = st.text_input(t("email_address"), placeholder="e.g. user@example.com", key="admin_email_update")
            if email_to_update:
                new_status = st.radio(t("admin_status"), ["yes", "no"], key="admin_status_choice")
                if st.button(t("save_rider"), key="save_admin_status"):
                    success = set_admin_status(DB_PATH, email_to_update, new_status)
                    if success:
                        st.success(f"{t('admin_status_change')} {email_to_update} naar '{new_status}'")
                        st.rerun()
                    else:
                        st.error(f"Account not found: {email_to_update}")
        else:
            st.info(t("no_accounts"))
        
        st.markdown("---")
    
    races_for_settings = load_races(DB_PATH)
    races_for_settings_names = [r["race_name"] for r in races_for_settings]
    settings_race = st.selectbox(t("select_race"), races_for_settings_names, key="settings_race_select")

    st.markdown(f"#### {t('registered_teams')}")
    teams_all = load_fantasy_teams(DB_PATH, settings_race)
    if not teams_all:
        st.info(t("no_teams"))
    else:
        # Show summary table of all teams
        summary_df = pd.DataFrame([
            {t("name"): team["team_name"], t("manager"): team["manager_name"], t("registered"): team["created_at"]}
            for team in teams_all
        ])
        st.dataframe(summary_df, hide_index=True, width="stretch")

        st.divider()
        team_labels_all = {f"{team['team_name']} (by {team['manager_name']})": team["id"] for team in teams_all}
        chosen_team = st.selectbox(t("view_team_riders"), list(team_labels_all.keys()), key="settings_team_select")
        if chosen_team:
            chosen_id = team_labels_all[chosen_team]
            team_riders = load_fantasy_team_riders(DB_PATH, chosen_id)
            if team_riders:
                st.dataframe(
                    pd.DataFrame(team_riders).rename(columns={t("rider"): "Rider", "nationality": t("nat"), "team": t("team")}),
                    hide_index=True,
                    width="stretch",
                )


# ── Tab: Renners ──────────────────────────────────────────────────────────────
with tab_riders:
    st.subheader(t("add_edit_riders"))

    sub_add, sub_edit, sub_delete = st.tabs([f"➕ {t('add_new_rider')}", f"✏️ {t('edit_rider')}", f"🗑️ {t('delete_rider')}"])

    with sub_add:
        st.markdown(t("add_description"))
        _tc = get_connection()
        _team_rows = _tc.execute(
            "SELECT DISTINCT team_name, team_url FROM riders WHERE team_name IS NOT NULL ORDER BY team_name"
        ).fetchall()
        _tc.close()
        _team_options = {r[0]: r[1] for r in _team_rows}
        _team_names = list(_team_options.keys())

        with st.form("add_rider_form"):
            r_name = st.text_input(f"{t('rider_name')} *", placeholder=t("rider_name_placeholder"))
            c1, c2 = st.columns(2)
            r_nat = c1.text_input(t("nationality"), placeholder=t("nationality_placeholder"), max_chars=3)
            r_bdate = c2.text_input(t("birthdate"), placeholder=t("birthdate_placeholder"))
            c3, c4 = st.columns(2)
            r_height = c3.number_input(t("height"), min_value=1.4, max_value=2.2, value=None, step=0.01, format="%.2f")
            r_weight = c4.number_input(t("weight"), min_value=40.0, max_value=120.0, value=None, step=0.5, format="%.1f")
            r_team = st.selectbox(t("team"), options=[t("select_team")] + _team_names, key="add_rider_team")
            r_url = st.text_input(f"{t('rider_url')} *", placeholder=t("rider_url_placeholder"))
            submitted = st.form_submit_button(f"💾 {t('save_rider')}", width="stretch")

        if submitted:
            if not r_name.strip() or not r_url.strip():
                st.error(t("name_url_required"))
            else:
                chosen_team = r_team if r_team != t("select_team") else None
                chosen_team_url = _team_options.get(chosen_team) if chosen_team else None
                try:
                    save_rider(DB_PATH, r_url.strip(), r_name.strip(), r_nat.strip() or None,
                               r_bdate.strip() or None, r_height, r_weight,
                               chosen_team, chosen_team_url)
                    st.cache_data.clear()
                    st.success(f"Renner **{r_name.strip()}** {t('rider_saved')}")
                except Exception as exc:
                    st.error(f"{t('save_error')} {exc}")

    with sub_edit:
        st.markdown(t("edit_description"))
        edit_search = st.text_input(t("search_rider"), key="edit_rider_search", placeholder=t("search_placeholder"))
        if edit_search.strip():
            _ec = get_connection()
            edit_rows = _ec.execute(
                "SELECT rider_url, name, nationality, birthdate, height, weight, team_name, team_url "
                "FROM riders WHERE name ILIKE ? ORDER BY name LIMIT 20",
                [f"%{edit_search.strip()}%"],
            ).fetchall()
            _ec.close()
            if not edit_rows:
                st.info(t("no_riders_found"))
            else:
                edit_labels = {f"{r[1]} ({r[2] or '?'}) — {r[6] or '?'}": r for r in edit_rows}
                chosen_label = st.selectbox(t("select_rider_edit"), list(edit_labels.keys()), key="edit_rider_select")
                if chosen_label:
                    er = edit_labels[chosen_label]
                    with st.form("edit_rider_form"):
                        er_name = st.text_input(f"{t('rider_name')} *", value=er[1] or "")
                        ec1, ec2 = st.columns(2)
                        er_nat = ec1.text_input(t("nationality"), value=er[2] or "", max_chars=3)
                        er_bdate = ec2.text_input(t("birthdate"), value=er[3] or "")
                        ec3, ec4 = st.columns(2)
                        er_height = ec3.number_input(t("height"), min_value=1.4, max_value=2.2, value=float(er[4]) if er[4] else None, step=0.01, format="%.2f")
                        er_weight = ec4.number_input(t("weight"), min_value=40.0, max_value=120.0, value=float(er[5]) if er[5] else None, step=0.5, format="%.1f")
                        er_team = st.text_input(t("team"), value=er[6] or "")
                        er_team_url = st.text_input(f"{t('team')} URL", value=er[7] or "")
                        st.text_input(t("rider_url"), value=er[0], disabled=True)
                        edit_submitted = st.form_submit_button(f"💾 {t('save_rider')}", width="stretch")

                    if edit_submitted:
                        if not er_name.strip():
                            st.error(t("name_required"))
                        else:
                            try:
                                save_rider(DB_PATH, er[0], er_name.strip(), er_nat.strip() or None,
                                           er_bdate.strip() or None, er_height, er_weight,
                                           er_team.strip() or None, er_team_url.strip() or None)
                                st.cache_data.clear()
                                st.success(f"Renner **{er_name.strip()}** {t('rider_updated')}")
                            except Exception as exc:
                                st.error(f"{t('save_error')} {exc}")

    with sub_delete:
        st.markdown(t("delete_description"))
        del_search = st.text_input(t("search_rider"), key="del_rider_search", placeholder=t("search_placeholder"))
        if del_search.strip():
            _dc = get_connection()
            del_rows = _dc.execute(
                "SELECT rider_url, name, nationality, team_name FROM riders WHERE name ILIKE ? ORDER BY name LIMIT 20",
                [f"%{del_search.strip()}%"],
            ).fetchall()
            _dc.close()
            if not del_rows:
                st.info(t("no_riders_found"))
            else:
                del_labels = {f"{r[1]} ({r[2] or '?'}) — {r[3] or '?'}": r[0] for r in del_rows}
                del_chosen = st.selectbox(t("select_rider_edit"), list(del_labels.keys()), key="del_rider_select")
                if del_chosen:
                    del_url = del_labels[del_chosen]
                    st.warning(f"{t('delete_confirm')} **{del_chosen}**.")
                    if st.button(f"🗑️ {t('delete_permanent')}", type="primary", key="del_rider_confirm"):
                        try:
                            delete_rider(DB_PATH, del_url)
                            st.cache_data.clear()
                            st.success(t("rider_deleted"))
                            st.rerun()
                        except Exception as exc:
                            st.error(f"{t('delete_error')} {exc}")

