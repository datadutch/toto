import os
import json
import duckdb
import streamlit as st
import urllib.parse
import pandas as pd
import cloudscraper
from dotenv import load_dotenv
from procyclingstats import Stage as PCSStage
from src.db import (
    init_fantasy_tables, load_fantasy_teams, load_fantasy_team_riders,
    init_stages_table, load_stages,
    init_stage_results_table, save_stage_results, delete_stage_results, load_stage_results, stages_with_results,
    calculate_scores, calculate_stage_breakdown,
    init_races_table, load_races, update_deadline, init_accounts_table, init_admin_accounts, get_account_by_email, 
    set_admin_status,
    save_rider, delete_rider, init_startlist_table, save_startlist, load_startlist, get_startlist_rider_names,
    update_stage_pcs_url,
)
from src.scraper import get_race_startlist

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
    _READ_ONLY = False  # MotherDuck does not support read_only attach
else:
    DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "cycling.duckdb")
    _READ_ONLY = True

st.set_page_config(page_title="Stampers Toto Administratie", page_icon="🚴", layout="wide")

# Hide default multipage sidebar nav
st.markdown("<style>[data-testid='stSidebarNav'] {display: none;}</style>", unsafe_allow_html=True)

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
import datetime

_POSITIONS_NL = ["1e", "2e", "3e", "4e", "5e", "6e", "7e", "8e", "9e", "10e",
                 "11e", "12e", "13e", "14e", "15e"]
_NONE = "— niet geselecteerd —"


def _parse_pcs_results(html: str) -> list[str]:
    """Parse top 15 rider_urls (ordered 1→15) from a PCS results page."""
    from selectolax.parser import HTMLParser
    tree = HTMLParser(html)
    table = tree.css_first("table.results")
    if not table:
        return []
    results: list[tuple[int, str]] = []
    for row in table.css("tr"):
        rank_td = row.css_first("td")
        if not rank_td:
            continue
        try:
            rank = int(rank_td.text(strip=True))
        except ValueError:
            continue
        if rank > 15:
            break
        ridername_td = row.css_first("td.ridername")
        if not ridername_td:
            continue
        link = ridername_td.css_first("a")
        if not link:
            continue
        rider_url = link.attributes.get("href", "").strip()
        if rider_url:
            results.append((rank, rider_url))
    results.sort(key=lambda x: x[0])
    return [url for _, url in results]


def _fetch_top_15_from_pcs(race_name: str, stage_name: str) -> list[str]:
    """Fetch top 15 riders from ProCyclingStats for the given race/stage."""
    stages = load_stages(DB_PATH, race_name)
    stage = next((s for s in stages if s["Stage"] == stage_name), None)
    pcs_url = stage.get("pcs_url") if stage else None
    if not pcs_url:
        st.error(f"Geen ProCyclingStats URL gevonden voor {stage_name}. Stel de URL in via het etappe-overzicht.")
        return []
    try:
        scraper = cloudscraper.create_scraper()
        response = scraper.get(pcs_url, timeout=15)
        response.raise_for_status()
        return _parse_pcs_results(response.text)
    except Exception as e:
        st.error(f"Ophalen van ProCyclingStats mislukt: {e}")
        return []


def _render_pcs_fetch_button(race_name: str, stage_name: str, stages: list, fetch_key: str):
    """Show fetch button if PCS URL exists, otherwise show URL input."""
    prefix = fetch_key.replace("_fetch_pcs", "")
    stage = next((s for s in stages if s["Stage"] == stage_name), None)
    pcs_url = stage.get("pcs_url") if stage else None

    if pcs_url:
        if st.button(f"🌐 {t('fetch_pcs')}", key=fetch_key):
            with st.spinner(t("fetching")):
                riders = _fetch_top_15_from_pcs(race_name, stage_name)
                if riders:
                    save_stage_results(DB_PATH, race_name, stage_name, riders)
                    st.session_state.pop(f"results_{prefix}_{stage_name}", None)
                    for _i in range(15):
                        st.session_state.pop(f"{prefix}_pos_{_i}_{stage_name}", None)
                    st.session_state[f"{prefix}_subtab"] = "view"
                    st.success(f"✓ {t('fetched_saved')} {len(riders)} {t('riders')} {stage_name}")
                    st.rerun()
                else:
                    st.warning(t("no_results_fetched"))
    else:
        with st.popover(f"🔗 {t('add_pcs_url')}", use_container_width=True):
            new_url = st.text_input("ProCyclingStats URL", placeholder="https://www.procyclingstats.com/race/...", key=f"{fetch_key}_url_input")
            if st.button(t("save"), key=f"{fetch_key}_url_save", type="primary"):
                if new_url.strip():
                    update_stage_pcs_url(DB_PATH, race_name, stage_name, new_url.strip())
                    st.success("URL opgeslagen.")
                    st.rerun()


def _render_results_section(race_name: str, stages: list, prefix: str):
    """Render the enter/view results section with a switchable subtab."""
    racing_stage_names = [s["Stage"] for s in stages if s["Stage"] != "Rest Day"]
    if not racing_stage_names:
        return

    subtab_key = f"{prefix}_subtab"
    if subtab_key not in st.session_state:
        st.session_state[subtab_key] = "enter"

    col_tab1, col_tab2 = st.columns(2)
    if col_tab1.button(
        f"📝 {t('enter_results')}",
        use_container_width=True,
        key=f"{prefix}_tab_enter",
        type="primary" if st.session_state[subtab_key] == "enter" else "secondary",
    ):
        st.session_state[subtab_key] = "enter"
        st.rerun()
    if col_tab2.button(
        f"📊 {t('view_results')}",
        use_container_width=True,
        key=f"{prefix}_tab_view",
        type="primary" if st.session_state[subtab_key] == "view" else "secondary",
    ):
        st.session_state[subtab_key] = "view"
        st.rerun()

    if st.session_state[subtab_key] == "enter":
        col_sel, col_fetch = st.columns([3, 1])
        with col_sel:
            selected = st.selectbox("Etappe", racing_stage_names, key=f"{prefix}_result_stage")
        with col_fetch:
            _render_pcs_fetch_button(race_name, selected, stages, f"{prefix}_fetch_pcs")
        _render_results_entry(race_name, selected, prefix)
    else:
        view_stage = st.selectbox("Etappe", racing_stage_names, key=f"{prefix}_view_stage")
        results = load_stage_results(DB_PATH, race_name, view_stage)
        if results:
            st.dataframe(pd.DataFrame(results), hide_index=True, use_container_width=True)
        else:
            st.info(t("no_stage_results"))


def _render_stages_table(race_name: str, stages: list, finished: set, key_prefix: str):
    """Render stages table with editable pcs_url column."""
    stages_df = pd.DataFrame(stages)
    stages_df["✅"] = stages_df["Stage"].apply(
        lambda s: "✅" if s in finished else ("—" if s == "Rest Day" else "")
    )
    display_df = stages_df[["Date", "Day", "Stage", "Route", "KM", "✅", "pcs_url"]].copy()

    edited_df = st.data_editor(
        display_df,
        column_config={
            "Date":    st.column_config.TextColumn(t("date"), disabled=True, width="small"),
            "Day":     st.column_config.TextColumn("Dag", disabled=True, width="small"),
            "Stage":   st.column_config.TextColumn("Etappe", disabled=True),
            "Route":   st.column_config.TextColumn("Route", disabled=True),
            "KM":      st.column_config.NumberColumn("KM", disabled=True, format="%.1f", width="small"),
            "✅":      st.column_config.TextColumn("", disabled=True, width="small"),
            "pcs_url": st.column_config.TextColumn("PCS URL", help="Klik om de ProCyclingStats URL te bewerken"),
        },
        disabled=["Date", "Day", "Stage", "Route", "KM", "✅"],
        hide_index=True,
        use_container_width=True,
        key=f"{key_prefix}_stages_editor",
    )

    changed = False
    for i in range(len(display_df)):
        orig = display_df.iloc[i]["pcs_url"]
        new  = edited_df.iloc[i]["pcs_url"]
        orig_s = "" if (orig is None or (isinstance(orig, float) and pd.isna(orig))) else str(orig).strip()
        new_s  = "" if (new  is None or (isinstance(new,  float) and pd.isna(new)))  else str(new).strip()
        if orig_s != new_s:
            update_stage_pcs_url(DB_PATH, race_name, display_df.iloc[i]["Stage"], new_s)
            changed = True
    if changed:
        st.rerun()

    racing_stages = [s for s in stages if s["Stage"] != "Rest Day"]
    total_km = sum(s["KM"] for s in racing_stages if s["KM"])
    col1, col2, col3 = st.columns(3)
    col1.metric(t("racing_stages"), len(racing_stages))
    col2.metric(t("total_distance"), f"{total_km:.1f} km")
    col3.metric(t("rest_days"), sum(1 for s in stages if s["Stage"] == "Rest Day"))


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
init_startlist_table(DB_PATH)

# ── One-time migration: promote old ADMIN_EMAILS to is_admin='yes' ────────────
_ADMIN_EMAILS_OLD = []
try:
    # Try to get from secrets (Streamlit Cloud)
    admin_emails_str = st.secrets.get("ADMIN_EMAILS", "")
except Exception:
    admin_emails_str = ""
# Fall back to environment variable
if not admin_emails_str:
    admin_emails_str = os.getenv("ADMIN_EMAILS", "")

_ADMIN_EMAILS_OLD = [
    e.strip().lower()
    for e in str(admin_emails_str).split(",")
    if e.strip()
]
if _ADMIN_EMAILS_OLD:
    init_admin_accounts(DB_PATH, _ADMIN_EMAILS_OLD)

# ── Auth check via participant session ────────────────────────────────────────
if st.session_state.get("account") is None:
    st.rerun()

_admin = st.session_state.account
if _admin.get("is_admin") != "yes":
    st.error(t("no_access"))
    st.switch_page("pages/participant_main.py")

# ── Language Selector (Sidebar - Always Visible) ──────────────────────────────
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
_col_title, _col_middle, _col_logout = st.columns([4, 2, 1])
_col_title.title(f"🚴 {t('title')}")

with _col_middle:
    if st.button(f"👥 {t('participant_app')}", help="Naar deelnemer app", use_container_width=True):
        st.switch_page("pages/participant_main.py")

if _col_logout.button(t("logout"), key="admin_logout"):
    st.session_state.account = None
    st.rerun()

st.caption(f"{t('database_riders')} **{total:,}** {t('database_riders_suffix')}")


tab_explorer, tab_giro, tab_tdf, tab_romandie, tab_vuelta, tab_scores, tab_settings, tab_riders = st.tabs([
    f"🔍 {t('tab_explorer')}", 
    f"🏁 {t('tab_giro')}", 
    f"🚴‍♂️ {t('tab_tdf')}", 
    f"🏔️ {t('tab_romandie')}", 
    f"🇪🇸 {t('tab_vuelta')}", 
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
        _render_stages_table("Giro d'Italia", stages, finished, "giro")

    # ── Enter / view stage results ─────────────────────────────────────────────
    st.divider()
    st.subheader(t("stage_results"))
    _render_results_section("Giro d'Italia", stages, "giro")

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





    # ── Startlist ─────────────────────────────────────────────────────────────
    st.divider()
    st.markdown(f"#### {t('startlist')}")
    
    _giro_pcs_url = "https://www.procyclingstats.com/race/giro-ditalia/2026"
    col_startlist_btn, col_startlist_info = st.columns([1, 3])
    
    with col_startlist_btn:
        if st.button(f"🔄 {t('fetch_startlist')}", key="btn_fetch_startlist_giro"):
            with st.spinner(t("fetching_startlist")):
                startlist_url = f"{_giro_pcs_url}/startlist"
                startlist_riders = get_race_startlist(startlist_url)
                if startlist_riders:
                    saved_count = save_startlist(DB_PATH, "Giro d'Italia", startlist_riders)
                    st.success(f"✓ {t('startlist_saved')} — {saved_count} {t('riders')}")
                    st.rerun()
                else:
                    st.warning(t("no_startlist"))
    
    current_startlist = load_startlist(DB_PATH, "Giro d'Italia")
    if current_startlist:
        with col_startlist_info:
            st.info(t("startlist_riders").format(count=len(current_startlist)))
    
    with st.expander(f"{t('view_startlist')} ({len(current_startlist) if current_startlist else 0} {t('riders')})", expanded=len(current_startlist) < 5 if current_startlist else False):
        if current_startlist:
            startlist_df = pd.DataFrame(current_startlist)
            display_cols = ['rider_name', 'team_name']
            col_names = [t('rider_name'), t('team')]
            st.dataframe(
                startlist_df[display_cols].rename(columns=dict(zip(display_cols, col_names))),
                hide_index=True,
                width="stretch"
            )
            if st.button(f"🗑️ {t('clear_startlist')}", key="btn_clear_startlist_giro", type="secondary"):
                save_startlist(DB_PATH, "Giro d'Italia", [])
                st.success(t("startlist_cleared"))
                st.rerun()
        else:
            st.info(t("no_startlist"))


# ── Tab: Tour de France ──────────────────────────────────────────────────────
with tab_tdf:
    st.subheader(f"{t('tour_de_france')} — {t('stage_overview')}")

    stages = load_stages(DB_PATH, "Tour de France")
    finished = stages_with_results(DB_PATH, "Tour de France")

    if stages:
        _render_stages_table("Tour de France", stages, finished, "tdf")

    # ── Enter / view stage results ─────────────────────────────────────────────
    st.divider()
    st.subheader(t("stage_results"))
    _render_results_section("Tour de France", stages, "tdf")

    # ── Registration deadline ──────────────────────────────────────────────────
    st.divider()
    st.markdown(f"#### {t('registration_deadline')}")
    _tdf_races = load_races(DB_PATH)
    _tdf_race = next((r for r in _tdf_races if r["race_name"] == "Tour de France"), None)
    if _tdf_race:
        _cur = _tdf_race["deadline"]
        _c1, _c2, _c3 = st.columns([2, 2, 1])
        _new_date = _c1.date_input(t("date"), value=_cur.date() if _cur else None, key="tdf_dl_date")
        _new_time = _c2.time_input(t("time"), value=_cur.time() if _cur else None, key="tdf_dl_time")
        if _c3.button(f"💾 {t('save')}", key="tdf_dl_save", width="stretch"):
            from datetime import datetime
            combined = datetime.combine(_new_date, _new_time)
            update_deadline(DB_PATH, "Tour de France", combined)
            st.success(f"{t('deadline_updated')} {combined.strftime('%d/%m/%Y %H:%M')}")
            st.rerun()


    # ── Startlist ─────────────────────────────────────────────────────────────
    st.divider()
    st.markdown(f"#### {t('startlist')}")
    
    _tdf_pcs_url = "https://www.procyclingstats.com/race/tour-de-france/2026"
    col_startlist_btn, col_startlist_info = st.columns([1, 3])
    
    with col_startlist_btn:
        if st.button(f"🔄 {t('fetch_startlist')}", key="btn_fetch_startlist_tdf"):
            with st.spinner(t("fetching_startlist")):
                startlist_url = f"{_tdf_pcs_url}/startlist"
                startlist_riders = get_race_startlist(startlist_url)
                if startlist_riders:
                    saved_count = save_startlist(DB_PATH, "Tour de France", startlist_riders)
                    st.success(f"✓ {t('startlist_saved')} — {saved_count} {t('riders')}")
                    st.rerun()
                else:
                    st.warning(t("no_startlist"))
    
    current_startlist = load_startlist(DB_PATH, "Tour de France")
    if current_startlist:
        with col_startlist_info:
            st.info(t("startlist_riders").format(count=len(current_startlist)))
    
    with st.expander(f"{t('view_startlist')} ({len(current_startlist) if current_startlist else 0} {t('riders')})", expanded=len(current_startlist) < 5 if current_startlist else False):
        if current_startlist:
            startlist_df = pd.DataFrame(current_startlist)
            display_cols = ['rider_name', 'team_name']
            col_names = [t('rider_name'), t('team')]
            st.dataframe(
                startlist_df[display_cols].rename(columns=dict(zip(display_cols, col_names))),
                hide_index=True,
                width="stretch"
            )
            if st.button(f"🗑️ {t('clear_startlist')}", key="btn_clear_startlist_tdf", type="secondary"):
                save_startlist(DB_PATH, "Tour de France", [])
                st.success(t("startlist_cleared"))
                st.rerun()
        else:
            st.info(t("no_startlist"))


# ── Tab: Tour de Romandie ────────────────────────────────────────────────────
with tab_romandie:
    st.subheader(f"{t('tour_de_romandie')} — {t('stage_overview')}")

    stages = load_stages(DB_PATH, "Tour de Romandie")
    finished = stages_with_results(DB_PATH, "Tour de Romandie")

    if stages:
        _render_stages_table("Tour de Romandie", stages, finished, "romandie")

    # ── Enter / view stage results ─────────────────────────────────────────────
    st.divider()
    st.subheader(t("stage_results"))
    _render_results_section("Tour de Romandie", stages, "romandie")

    # ── Registration deadline ──────────────────────────────────────────────────
    st.divider()
    st.markdown(f"#### {t('registration_deadline')}")
    _romandie_races = load_races(DB_PATH)
    _romandie_race = next((r for r in _romandie_races if r["race_name"] == "Tour de Romandie"), None)
    if _romandie_race:
        _cur = _romandie_race["deadline"]
        _c1, _c2, _c3 = st.columns([2, 2, 1])
        _new_date = _c1.date_input(t("date"), value=_cur.date() if _cur else None, key="romandie_dl_date")
        _new_time = _c2.time_input(t("time"), value=_cur.time() if _cur else None, key="romandie_dl_time")
        if _c3.button(f"💾 {t('save')}", key="romandie_dl_save", width="stretch"):
            from datetime import datetime
            combined = datetime.combine(_new_date, _new_time)
            update_deadline(DB_PATH, "Tour de Romandie", combined)
            st.success(f"{t('deadline_updated')} {combined.strftime('%d/%m/%Y %H:%M')}")
            st.rerun()


    # ── Startlist ─────────────────────────────────────────────────────────────
    st.divider()
    st.markdown(f"#### {t('startlist')}")
    
    _romandie_pcs_url = "https://www.procyclingstats.com/race/tour-de-romandie/2026"
    col_startlist_btn, col_startlist_info = st.columns([1, 3])
    
    with col_startlist_btn:
        if st.button(f"🔄 {t('fetch_startlist')}", key="btn_fetch_startlist_romandie"):
            with st.spinner(t("fetching_startlist")):
                startlist_url = f"{_romandie_pcs_url}/startlist"
                startlist_riders = get_race_startlist(startlist_url)
                if startlist_riders:
                    saved_count = save_startlist(DB_PATH, "Tour de Romandie", startlist_riders)
                    st.success(f"✓ {t('startlist_saved')} — {saved_count} {t('riders')}")
                    st.rerun()
                else:
                    st.warning(t("no_startlist"))
    
    current_startlist = load_startlist(DB_PATH, "Tour de Romandie")
    if current_startlist:
        with col_startlist_info:
            st.info(t("startlist_riders").format(count=len(current_startlist)))
    
    with st.expander(f"{t('view_startlist')} ({len(current_startlist) if current_startlist else 0} {t('riders')})", expanded=len(current_startlist) < 5 if current_startlist else False):
        if current_startlist:
            startlist_df = pd.DataFrame(current_startlist)
            display_cols = ['rider_name', 'team_name']
            col_names = [t('rider_name'), t('team')]
            st.dataframe(
                startlist_df[display_cols].rename(columns=dict(zip(display_cols, col_names))),
                hide_index=True,
                width="stretch"
            )
            if st.button(f"🗑️ {t('clear_startlist')}", key="btn_clear_startlist_romandie", type="secondary"):
                save_startlist(DB_PATH, "Tour de Romandie", [])
                st.success(t("startlist_cleared"))
                st.rerun()
        else:
            st.info(t("no_startlist"))


# ── Tab: Vuelta a España ─────────────────────────────────────────────────────
with tab_vuelta:
    st.subheader(f"{t('vuelta_a_espana')} — {t('stage_overview')}")

    stages = load_stages(DB_PATH, "Vuelta a España")
    finished = stages_with_results(DB_PATH, "Vuelta a España")

    if stages:
        _render_stages_table("Vuelta a España", stages, finished, "vuelta")

    # ── Enter / view stage results ─────────────────────────────────────────────
    st.divider()
    st.subheader(t("stage_results"))
    _render_results_section("Vuelta a España", stages, "vuelta")

    # ── Registration deadline ──────────────────────────────────────────────────
    st.divider()
    st.markdown(f"#### {t('registration_deadline')}")
    _vuelta_races = load_races(DB_PATH)
    _vuelta_race = next((r for r in _vuelta_races if r["race_name"] == "Vuelta a España"), None)
    if _vuelta_race:
        _cur = _vuelta_race["deadline"]
        _c1, _c2, _c3 = st.columns([2, 2, 1])
        _new_date = _c1.date_input(t("date"), value=_cur.date() if _cur else None, key="vuelta_dl_date")
        _new_time = _c2.time_input(t("time"), value=_cur.time() if _cur else None, key="vuelta_dl_time")
        if _c3.button(f"💾 {t('save')}", key="vuelta_dl_save", width="stretch"):
            from datetime import datetime
            combined = datetime.combine(_new_date, _new_time)
            update_deadline(DB_PATH, "Vuelta a España", combined)
            st.success(f"{t('deadline_updated')} {combined.strftime('%d/%m/%Y %H:%M')}")
            st.rerun()


    # ── Startlist ─────────────────────────────────────────────────────────────
    st.divider()
    st.markdown(f"#### {t('startlist')}")
    
    _vuelta_pcs_url = "https://www.procyclingstats.com/race/vuelta-a-espana/2026"
    col_startlist_btn, col_startlist_info = st.columns([1, 3])
    
    with col_startlist_btn:
        if st.button(f"🔄 {t('fetch_startlist')}", key="btn_fetch_startlist_vuelta"):
            with st.spinner(t("fetching_startlist")):
                startlist_url = f"{_vuelta_pcs_url}/startlist"
                startlist_riders = get_race_startlist(startlist_url)
                if startlist_riders:
                    saved_count = save_startlist(DB_PATH, "Vuelta a España", startlist_riders)
                    st.success(f"✓ {t('startlist_saved')} — {saved_count} {t('riders')}")
                    st.rerun()
                else:
                    st.warning(t("no_startlist"))
    
    current_startlist = load_startlist(DB_PATH, "Vuelta a España")
    if current_startlist:
        with col_startlist_info:
            st.info(t("startlist_riders").format(count=len(current_startlist)))
    
    with st.expander(f"{t('view_startlist')} ({len(current_startlist) if current_startlist else 0} {t('riders')})", expanded=len(current_startlist) < 5 if current_startlist else False):
        if current_startlist:
            startlist_df = pd.DataFrame(current_startlist)
            display_cols = ['rider_name', 'team_name']
            col_names = [t('rider_name'), t('team')]
            st.dataframe(
                startlist_df[display_cols].rename(columns=dict(zip(display_cols, col_names))),
                hide_index=True,
                width="stretch"
            )
            if st.button(f"🗑️ {t('clear_startlist')}", key="btn_clear_startlist_vuelta", type="secondary"):
                save_startlist(DB_PATH, "Vuelta a España", [])
                st.success(t("startlist_cleared"))
                st.rerun()
        else:
            st.info(t("no_startlist"))


# ── Tab: Scores ─────────────────────────────────────────────────────────────
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
    if st.session_state.account.get("is_admin") == "yes":
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
    # Sort by closest deadline (nearest date first)
    from datetime import datetime
    races_for_settings.sort(key=lambda r: abs((r["deadline"] - datetime.now()).total_seconds()) if r["deadline"] else float('inf'))
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
            r_nickname = st.text_input(t("nickname"), placeholder=t("nickname_placeholder"))
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
                    save_rider(DB_PATH, r_url.strip(), r_name.strip(), r_nickname.strip() or None, r_nat.strip() or None,
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
                "SELECT rider_url, name, nickname, nationality, birthdate, height, weight, team_name, team_url "
                "FROM riders WHERE name ILIKE ? ORDER BY name LIMIT 20",
                [f"%{edit_search.strip()}%"],
            ).fetchall()
            _ec.close()
            if not edit_rows:
                st.info(t("no_riders_found"))
            else:
                edit_labels = {f"{r[1]} ({r[3] or '?'}) — {r[7] or '?'}" + (f" [{r[2]}]" if r[2] else ""): r for r in edit_rows}
                chosen_label = st.selectbox(t("select_rider_edit"), list(edit_labels.keys()), key="edit_rider_select")
                if chosen_label:
                    er = edit_labels[chosen_label]
                    with st.form("edit_rider_form"):
                        er_name = st.text_input(f"{t('rider_name')} *", value=er[1] or "")
                        er_nickname = st.text_input(t("nickname"), value=er[2] or "")
                        ec1, ec2 = st.columns(2)
                        er_nat = ec1.text_input(t("nationality"), value=er[3] or "", max_chars=3)
                        er_bdate = ec2.text_input(t("birthdate"), value=er[4] or "")
                        ec3, ec4 = st.columns(2)
                        er_height = ec3.number_input(t("height"), min_value=1.4, max_value=2.2, value=float(er[5]) if er[5] else None, step=0.01, format="%.2f")
                        er_weight = ec4.number_input(t("weight"), min_value=40.0, max_value=120.0, value=float(er[6]) if er[6] else None, step=0.5, format="%.1f")
                        er_team = st.text_input(t("team"), value=er[7] or "")
                        er_team_url = st.text_input(f"{t('team')} URL", value=er[8] or "")
                        st.text_input(t("rider_url"), value=er[0], disabled=True)
                        edit_submitted = st.form_submit_button(f"💾 {t('save_rider')}", width="stretch")

                    if edit_submitted:
                        if not er_name.strip():
                            st.error(t("name_required"))
                        else:
                            try:
                                save_rider(DB_PATH, er[0], er_name.strip(), er_nickname.strip() or None,
                                           er_nat.strip() or None, er_bdate.strip() or None, er_height, er_weight,
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

