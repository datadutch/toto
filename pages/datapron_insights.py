import streamlit as st
import pandas as pd
import numpy as np
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
st.title("🔍 Selection Patterns & Sleeper Picks")
st.markdown("*Find underrated riders and composition trends*")

# Navigation between datapron pages
col1, col2 = st.columns([1, 1])
with col1:
    if st.button("← Back to Overview", use_container_width=True, type="secondary"):
        st.switch_page("pages/datapron_start.py")
with col2:
    st.markdown("**🔍 Analysis**", help="Advanced selection analysis")

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
    key="sleepers_race_selector"
)

st.divider()

# Query database
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
    
    total_teams = len(teams_df)
    
    # Get all riders from all those teams - simpler approach
    all_riders_df = pd.read_sql(
        """
        SELECT ftr.team_id, ftr.rider_url, r.name, r.nationality, r.birthdate, r.team_name
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
    riders_df = all_riders_df.groupby(['rider_url', 'name', 'nationality', 'birthdate', 'team_name']).agg({
        'team_id': 'nunique'
    }).reset_index()
    riders_df.columns = ['rider_url', 'name', 'nationality', 'birthdate', 'team_name', 'team_count']
    riders_df['total_selections'] = all_riders_df.groupby('rider_url').size().values if len(all_riders_df) > 0 else 0
    riders_df = riders_df.sort_values('team_count', ascending=False)
    
    # Calculate selection percentage
    riders_df["selection_pct"] = (riders_df["team_count"] / total_teams) * 100
    
    # Calculate ages
    riders_df["birthdate"] = pd.to_datetime(riders_df["birthdate"], errors="coerce")
    today = datetime.now()
    riders_df["age"] = (today - riders_df["birthdate"]).dt.days // 365
    
    # Create tabs for different insights
    tab1, tab2, tab3, tab4 = st.tabs(["🌟 Sleeper Picks", "👑 Popular Picks", "📊 Selection %%", "⚖️ Balance"])
    
    with tab1:
        st.subheader("🌟 Sleeper Picks (Underrated Riders)")
        st.markdown("*Riders selected by fewer than 30% of teams - potential upside!*")
        
        sleepers = riders_df[riders_df["selection_pct"] < 30].nlargest(15, "total_selections")[
            ["name", "nationality", "team_name", "age", "selection_pct", "team_count"]
        ].reset_index(drop=True)
        
        if not sleepers.empty:
            sleepers.columns = ["Rider", "Country", "Team", "Age", "Selected %", "Teams"]
            sleepers["Selected %"] = sleepers["Selected %"].round(1).astype(str) + "%"
            st.dataframe(sleepers, use_container_width=True, hide_index=True)
        else:
            st.info("No sleeper picks available (all riders highly selected)")
    
    with tab2:
        st.subheader("👑 Popular Picks (Safe Bets)")
        st.markdown("*Riders selected by more than 60% of teams - consensus favorites*")
        
        popular = riders_df[riders_df["selection_pct"] > 60].nlargest(15, "team_count")[
            ["name", "nationality", "team_name", "age", "selection_pct", "team_count"]
        ].reset_index(drop=True)
        
        if not popular.empty:
            popular.columns = ["Rider", "Country", "Team", "Age", "Selected %", "Teams"]
            popular["Selected %"] = popular["Selected %"].round(1).astype(str) + "%"
            st.dataframe(popular, use_container_width=True, hide_index=True)
        else:
            st.info("No consensus favorites yet")
    
    with tab3:
        st.subheader("📊 Selection Distribution")
        st.markdown("*How are riders distributed across selection percentages?*")
        
        # Create selection percentage buckets
        bins = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
        labels = ["0-10%", "10-20%", "20-30%", "30-40%", "40-50%", "50-60%", "60-70%", "70-80%", "80-90%", "90-100%"]
        
        selection_dist = pd.cut(riders_df["selection_pct"], bins=bins, labels=labels, right=False)
        dist_counts = selection_dist.value_counts().sort_index()
        
        col1, col2 = st.columns(2)
        with col1:
            st.bar_chart(dist_counts, use_container_width=True, color="#6C63FF")
        with col2:
            st.metric("Most Picked Rider", 
                     f"{riders_df.loc[riders_df['selection_pct'].idxmax(), 'name']}",
                     f"{riders_df['selection_pct'].max():.0f}% in {riders_df.loc[riders_df['selection_pct'].idxmax(), 'team_count']} teams")
            st.metric("Rarest Rider",
                     f"{riders_df.loc[riders_df['selection_pct'].idxmin(), 'name']}",
                     f"{riders_df['selection_pct'].min():.0f}% in {riders_df.loc[riders_df['selection_pct'].idxmin(), 'team_count']} team")
    
    with tab4:
        st.subheader("⚖️ Selection Balance Analysis")
        st.markdown("*Statistical overview of selection diversity across teams*")
        
        col1, col2 = st.columns(2)
        with col1:
            st.metric("📍 Median Selection Rate", f"{riders_df['selection_pct'].median():.1f}%")
        with col2:
            st.metric("📊 Avg Selection Rate", f"{riders_df['selection_pct'].mean():.1f}%")
        
        col1, col2 = st.columns(2)
        with col1:
            st.metric("🎯 Standard Deviation", f"{riders_df['selection_pct'].std():.1f}%")
        with col2:
            st.metric("📈 Selection Range", f"{riders_df['selection_pct'].max() - riders_df['selection_pct'].min():.0f}%")
        
        st.divider()
        st.write("**Selection Concentration:**")
        
        # Calculate concentration
        high_consensus = (riders_df["selection_pct"] > 70).sum()
        moderate = ((riders_df["selection_pct"] >= 40) & (riders_df["selection_pct"] <= 70)).sum()
        diverse = (riders_df["selection_pct"] < 40).sum()
        
        concentrate_data = pd.DataFrame({
            "Category": ["High Consensus (>70%)", "Moderate (40-70%)", "Diverse (<40%)"],
            "Count": [high_consensus, moderate, diverse]
        })
        
        st.bar_chart(concentrate_data.set_index("Category"), use_container_width=True, color="#FF8866")
    
    st.divider()
    
    # Quick comparison table
    st.subheader("📋 Top 20 Riders by Selection")
    top_20 = riders_df.nlargest(20, "team_count")[
        ["name", "nationality", "team_name", "age", "selection_pct", "team_count", "total_selections"]
    ].reset_index(drop=True)
    
    top_20.columns = ["Rider", "Country", "Team", "Age", "% Selected", "# Teams", "Total Picks"]
    top_20["% Selected"] = top_20["% Selected"].round(1).astype(str) + "%"
    
    st.dataframe(top_20, use_container_width=True, hide_index=True)

finally:
    conn.close()
