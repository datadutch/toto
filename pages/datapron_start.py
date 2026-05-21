import streamlit as st
import pandas as pd
from datetime import datetime
from src.db import _connect, load_races, init_fantasy_tables, init_races_table
from src.participant_common import (
    DB_PATH, t, setup_page, render_header, render_sidebar, render_name_change_modal
)

# Setup
account = setup_page(layout="wide")
init_fantasy_tables(DB_PATH)
init_races_table(DB_PATH)

render_header(account)
render_sidebar(account, "datapron")

st.divider()
render_name_change_modal(account)

# Title
st.title("📊 Datapron Insights")
st.markdown("*Discover patterns in team selections across the peloton*")

# Navigation between datapron pages
col1, col2 = st.columns([1, 1])
with col1:
    st.markdown("**📊 Overview**")
with col2:
    if st.button("→ Sleeper Picks & Patterns", use_container_width=True, type="secondary"):
        st.switch_page("pages/datapron_insights.py")

st.divider()

# Load races
races = load_races(DB_PATH)
if not races:
    st.error("No races configured yet.")
    st.stop()

race_options = {r["race_name"]: r for r in races}

# Default to "Giro d'Italia" if available, otherwise first race
default_race = "Giro d'Italia" if "Giro d'Italia" in race_options else list(race_options.keys())[0]
default_idx = list(race_options.keys()).index(default_race)

selected_race = st.selectbox(
    "🏁 Select a Race",
    list(race_options.keys()),
    index=default_idx,
    key="datapron_race_selector"
)

st.divider()

# Query database for teams and riders in selected race
conn = _connect(DB_PATH, read_only=True)

try:
    # Get all teams for the selected race
    teams_df = pd.read_sql(
        "SELECT id FROM fantasy_teams WHERE race_name = ?",
        conn,
        params=[selected_race]
    )
    
    if teams_df.empty:
        st.info(f"No teams registered for {selected_race} yet.")
        st.stop()
    
    # Get all riders from all those teams - simpler approach
    all_riders_df = pd.read_sql(
        """
        SELECT ftr.team_id, ftr.rider_url, r.name, r.nationality, r.birthdate
        FROM fantasy_team_riders ftr
        LEFT JOIN riders r ON ftr.rider_url = r.rider_url
        WHERE ftr.team_id IN (
            SELECT id FROM fantasy_teams WHERE race_name = ?
        )
        """,
        conn,
        params=[selected_race]
    )
    
    if all_riders_df.empty:
        st.info(f"No rider selections found for {selected_race}.")
        st.stop()
    
    # Aggregate the data
    riders_df = all_riders_df.groupby(['rider_url', 'name', 'nationality', 'birthdate']).size().reset_index(name='selection_count')
    riders_df = riders_df.sort_values('selection_count', ascending=False)
    
    # Calculate ages
    riders_df["birthdate"] = pd.to_datetime(riders_df["birthdate"], errors="coerce")
    today = datetime.now()
    riders_df["age"] = (today - riders_df["birthdate"]).dt.days // 365
    
    # Create columns for charts
    col1, col2 = st.columns(2)
    
    # Top 10 Most Selected Riders
    with col1:
        st.subheader("🏇 Top 10 Most Selected Riders")
        top_riders = riders_df.nlargest(10, "selection_count")[["name", "selection_count"]].reset_index(drop=True)
        top_riders = top_riders.sort_values("selection_count")  # Sort ascending for horizontal bar
        
        st.bar_chart(
            data=top_riders.set_index("name")["selection_count"],
            use_container_width=True,
            color="#FF6B6B"
        )
    
    # Top 10 Most Selected Countries
    with col2:
        st.subheader("🌍 Top 10 Most Selected Countries")
        countries = riders_df.groupby("nationality")["selection_count"].sum().reset_index()
        countries = countries.dropna(subset=["nationality"])
        top_countries = countries.nlargest(10, "selection_count").sort_values("selection_count")
        
        st.bar_chart(
            data=top_countries.set_index("nationality")["selection_count"],
            use_container_width=True,
            color="#4ECDC4"
        )
    
    st.divider()
    
    # Age Distribution Pie Chart
    st.subheader("🎂 Age Distribution of Selected Riders")
    
    # Create age groups
    riders_with_age = riders_df.dropna(subset=["age"])
    
    if not riders_with_age.empty:
        age_groups = pd.cut(
            riders_with_age["age"],
            bins=[0, 25, 30, 35, 40, 100],
            labels=["<25", "25-29", "30-34", "35-39", "40+"]
        )
        age_dist = riders_with_age.groupby(age_groups)["selection_count"].sum()
        
        st.bar_chart(
            data=age_dist,
            use_container_width=True,
            color="#95E1D3"
        )
        
        # Add detailed statistics
        st.write("**Age Statistics:**")
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Average Age", f"{riders_with_age['age'].mean():.1f} years")
        with col2:
            st.metric("Youngest", f"{riders_with_age['age'].min():.0f} years")
        with col3:
            st.metric("Oldest", f"{riders_with_age['age'].max():.0f} years")
        with col4:
            st.metric("Median Age", f"{riders_with_age['age'].median():.0f} years")
    else:
        st.warning("No age data available for selected riders.")
    
    st.divider()
    
    # Additional insights
    st.subheader("📈 Quick Stats")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Teams", len(teams_df))
    with col2:
        st.metric("Unique Riders Selected", len(riders_df))
    with col3:
        st.metric("Total Selections", riders_df["selection_count"].sum())
    with col4:
        st.metric("Countries Represented", riders_df["nationality"].nunique())

finally:
    conn.close()
