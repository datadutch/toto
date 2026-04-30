import streamlit as st
from src.db import init_fantasy_tables, load_team_by_account, save_fantasy_team, is_registration_open
from src.participant_common import (
    DB_PATH, t, _normalize,
    setup_page, render_header, render_sidebar, render_name_change_modal,
    load_race_selector, load_riders,
)

account = setup_page()
init_fantasy_tables(DB_PATH)

render_header(account)
render_sidebar(account, "register")

st.divider()
render_name_change_modal(account)

_, selected_race, _, registration_open = load_race_selector()

rider_options, url_to_label, url_to_norm, all_rows, startlist_urls = load_riders(selected_race)

existing_team = load_team_by_account(DB_PATH, account["id"], selected_race)
prefill_urls = existing_team["rider_urls"] if existing_team else []
prefill_team_name = existing_team["team_name"] if existing_team else ""

state_key = f"selected_urls_{account['id']}_{selected_race}"
if state_key not in st.session_state:
    st.session_state[state_key] = list(prefill_urls)

selected_urls: list = st.session_state[state_key]

# ── Registration closed ───────────────────────────────────────────────────────
if not registration_open:
    if existing_team:
        st.success(t("participant_team_registered"))
        st.subheader(f"{t('participant_your_team')}: {existing_team['team_name']}")
        for i, url in enumerate(existing_team["rider_urls"]):
            st.markdown(f"{i + 1}. {url_to_label.get(url, url).split(' (')[0]}")
    else:
        st.info(t("participant_no_team_registered"))
    st.stop()

# ── Registration open ─────────────────────────────────────────────────────────
if existing_team:
    st.info(f"✏️ {t('participant_existing_team_warning')}**{prefill_team_name}**. {t('participant_overwrite_warning')}")

team_name = st.text_input(
    t("participant_team_name"),
    value=prefill_team_name,
    placeholder="e.g. Team Velodutch (max 50 chars)",
    key="team_name_input",
)
if team_name.strip() and len(team_name.strip()) > 50:
    st.error(t("participant_error_team_name_length"))

st.divider()
st.markdown(f"### 👥 {t('participant_verify_selection')} — {len(selected_urls)} / 15 {t('participant_selected_count')}")
st.progress(len(selected_urls) / 15.0)

if "search_query" not in st.session_state:
    st.session_state.search_query = ""
if "search_key" not in st.session_state:
    st.session_state.search_key = 0

search_query = st.text_input(
    f"🔍 {t('participant_search_rider')}",
    placeholder=t("participant_search_rider"),
    key=f"rider_search_{st.session_state.search_key}",
    value=st.session_state.search_query,
)
st.session_state.search_query = search_query

col1, col2 = st.columns(2, gap="large")

# ── Startlist column ──────────────────────────────────────────────────────────
with col1:
    st.markdown(f"#### 📋 {t('startlist')}")
    _norm_query = _normalize(search_query) if search_query else ""
    startlist_available = {
        label: url
        for label, url in rider_options.items()
        if url not in selected_urls
        and (not search_query or _norm_query in url_to_norm.get(url, ""))
    }

    if len(selected_urls) >= 15:
        st.info(t("participant_max_riders"))
    elif not search_query:
        st.caption(t("participant_search_hint"))
    elif startlist_available:
        _items = list(startlist_available.items())
        if len(_items) > 20:
            st.caption(f"{t('participant_many_results')} ({len(_items)}) — {t('participant_refine_search')}")
            _items = _items[:20]
        add_label = st.radio(
            t("participant_add_rider"),
            options=[lbl for lbl, _ in _items],
            index=0,
            key="rider_add_select_startlist",
            label_visibility="collapsed",
        )
        if st.button(f"➕ {t('participant_add_rider')}", width="stretch", key="btn_add_rider_startlist"):
            st.session_state[state_key].append(startlist_available[add_label])
            st.session_state.search_key += 1
            st.session_state.search_query = ""
            st.rerun()
    else:
        _already = [
            url_to_label.get(url, url).split(" (")[0]
            for url in selected_urls
            if _norm_query in url_to_norm.get(url, "")
        ]
        if _already:
            st.caption(f"✅ {t('participant_already_selected')}: **{', '.join(_already)}**")
        else:
            st.caption(t("participant_no_riders_found"))

# ── General riders column ─────────────────────────────────────────────────────
with col2:
    st.markdown("#### 🚴 Rennerslijst")

    general_options = {}
    general_url_to_norm = {}
    for _url, _name, _nickname, _nat, _team in all_rows:
        if _url not in startlist_urls:
            _label = f"{_name} ({_nat or '?'}) — {_team or '?'}" + (f" [{_nickname}]" if _nickname else "")
            general_options[_label] = _url
            general_url_to_norm[_url] = _normalize(_name)

    if not general_options:
        st.info("Alle renners zitten al in de startlijst.")
    else:
        _norm_q2 = _normalize(search_query) if search_query else ""
        general_available = {
            label: url
            for label, url in general_options.items()
            if url not in selected_urls
            and (not search_query or _norm_q2 in general_url_to_norm.get(url, ""))
        }

        if len(selected_urls) >= 15:
            st.info(t("participant_max_riders"))
        elif not search_query:
            st.caption(t("participant_search_hint"))
        elif general_available:
            _items2 = list(general_available.items())
            if len(_items2) > 20:
                st.caption(f"{t('participant_many_results')} ({len(_items2)}) — {t('participant_refine_search')}")
                _items2 = _items2[:20]
            add_label2 = st.radio(
                t("participant_add_rider"),
                options=[lbl for lbl, _ in _items2],
                index=0,
                key="rider_add_select_general",
                label_visibility="collapsed",
            )
            if st.button(f"➕ {t('participant_add_rider')}", width="stretch", key="btn_add_rider_general"):
                st.session_state[state_key].append(general_available[add_label2])
                st.session_state.search_key += 1
                st.session_state.search_query = ""
                st.rerun()
        else:
            _already2 = [
                url_to_label.get(url, url).split(" (")[0]
                for url in selected_urls
                if _norm_q2 in general_url_to_norm.get(url, "")
            ]
            if _already2:
                st.caption(f"✅ {t('participant_already_selected')}: **{', '.join(_already2)}**")
            else:
                st.caption(t("participant_no_riders_found"))

# ── Selected riders list ──────────────────────────────────────────────────────
if selected_urls:
    st.markdown(f"**{t('participant_selected_riders')}**")
    for i, url in enumerate(selected_urls):
        col_name, col_btn = st.columns([5, 1], vertical_alignment="center")
        col_name.markdown(f"{i + 1}. {url_to_label.get(url, url).split(' (')[0]}")
        if col_btn.button("✖", key=f"remove_{i}", width="stretch", help=t("delete_rider")):
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
            del st.session_state[state_key]
            st.success(t("participant_team_saved"))
            st.balloons()
        except Exception as exc:
            st.error(f"{t('save_error')} {exc}")
