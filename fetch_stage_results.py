#!/usr/bin/env python3
"""
Fetch Stage Results and Save to Database

For each stage in a race, fetch the top 15 riders from ProCyclingStats
and save them to the stage_results table.

Usage:
    python fetch_stage_results.py "giro-d-italia/2026" [--stages 1-21]
    python fetch_stage_results.py "tour-de-france/2025/stage-1/result"
"""

import sys
import re
import os
from typing import List, Dict, Optional
from dotenv import load_dotenv
import duckdb
import cloudscraper
from procyclingstats import Stage

# Import DB functions
sys.path.insert(0, os.path.dirname(__file__))
from src.db import _connect, init_stage_results_table

load_dotenv()

# Use the same DB path logic as the main apps
_TOKEN = os.getenv("MOTHERDUCK_TOKEN")
if _TOKEN:
    DB_PATH = f"md:toto?motherduck_token={_TOKEN}"
else:
    DB_PATH = os.path.join(os.path.dirname(__file__), "data", "cycling.duckdb")


def extract_path_from_url(url: str) -> str:
    """Extract the path part from a URL."""
    url = url.strip()
    if url.startswith("http://") or url.startswith("https://"):
        if "://" in url:
            url = url.split("://", 1)[1]
        if "/" in url:
            url = url.split("/", 1)[1]
    return url.rstrip("/")


def get_race_and_stages_from_url(url: str) -> tuple:
    """
    Extract race identifier and stage number from URL.
    Returns (race_identifier, stage_number_or_None)
    
    Examples:
        'race/giro-d-italia/2026/stage-1/result' -> ('giro-d-italia/2026', '1')
        'giro-d-italia/2026' -> ('giro-d-italia/2026', None)
    """
    path = extract_path_from_url(url)
    
    # Remove leading 'race/' if present
    if path.startswith("race/"):
        path = path[5:]
    
    # Remove '/result' suffix if present
    if path.endswith("/result"):
        path = path[:-7]
    
    # Check for stage pattern
    stage_match = re.search(r'/stage-(\d+)$', path)
    if stage_match:
        stage_num = stage_match.group(1)
        race_identifier = path[:path.rfind(f'/stage-{stage_num}')]
        return race_identifier, stage_num
    
    return path, None


def get_stages_from_db(db_path: str, race_name: str) -> List[Dict]:
    """Get all stages for a race from the database."""
    conn = _connect(db_path, read_only=True)
    try:
        rows = conn.execute(
            "SELECT stage_name, date FROM stages WHERE race_name = ? ORDER BY date",
            [race_name]
        ).fetchall()
        
        # Determine if this is a one-day race (only 1 non-rest stage)
        non_rest_stages = [r for r in rows if "rest" not in (r[0] or "").lower()]
        is_one_day_race = len(non_rest_stages) == 1
        
        return [{"stage_name": r[0], "date": r[1], "is_one_day_race": is_one_day_race} for r in rows]
    finally:
        conn.close()


def get_stage_number_from_name(stage_name: str) -> Optional[str]:
    """Extract stage number from stage name like 'Stage 1' or 'Stage 1 (ITT)'. Returns None for rest days."""
    # Skip rest days
    if "rest" in stage_name.lower() or "day" in stage_name.lower() and "stage" not in stage_name.lower():
        return None
    match = re.search(r'stage\s+(\d+)', stage_name, re.IGNORECASE)
    if match:
        return match.group(1)
    match = re.search(r'(\d+)', stage_name)
    return match.group(1) if match else None


def construct_result_url(race_identifier: str, stage_num: str, is_one_day_race: bool = False) -> str:
    """Construct ProCyclingStats result URL for a race stage."""
    if is_one_day_race:
        # One-day races don't have stage subdirectory
        return f"race/{race_identifier}/result"
    return f"race/{race_identifier}/stage-{stage_num}/result"


def fetch_top_15_riders(url: str) -> List[Dict]:
    """Fetch top 15 riders from a ProCyclingStats result URL."""
    # Use cloudscraper to bypass Cloudflare protection
    if not url.startswith("http"):
        url = f"https://www.procyclingstats.com/{url}"
    
    scraper = cloudscraper.create_scraper()
    response = scraper.get(url)
    html = response.text
    
    # Pass HTML to Stage class
    stage = Stage(url, html=html, update_html=False)
    result = stage.parse()
    riders = result.get("results", [])
    
    top_15 = []
    for rider in riders:
        if rider.get("rank") and len(top_15) < 15:
            top_15.append(rider)
    
    return top_15


def save_stage_results(db_path: str, race_name: str, stage_name: str, riders: List[Dict]) -> None:
    """Save stage results to the database."""
    conn = _connect(db_path)
    try:
        # Clear existing results for this race/stage
        conn.execute(
            "DELETE FROM stage_results WHERE race_name = ? AND stage_name = ?",
            [race_name, stage_name]
        )
        
        # Insert new results
        for idx, rider in enumerate(riders, start=1):
            rider_url = rider.get("rider_url", "")
            if not rider_url:
                # Try to find rider by name if URL is missing
                continue
            conn.execute(
                "INSERT INTO stage_results (race_name, stage_name, position, rider_url) VALUES (?, ?, ?, ?)",
                [race_name, stage_name, idx, rider_url]
            )
        
        print(f"  ✓ Saved {len(riders)} results for {race_name} - {stage_name}")
    finally:
        conn.close()


def get_existing_race_name(db_path: str, race_identifier: str) -> str:
    """
    Try to find the race_name in the database that matches the identifier.
    The race_name in DB is the full name like 'Giro d'Italia'.
    The identifier might be like 'giro-d-italia/2026' or 'giro-d-italia'.
    """
    conn = _connect(db_path, read_only=True)
    try:
        # Extract year and race name from identifier
        # Handle formats: "giro-d-italia/2026", "giro-d-italia", "race/giro-d-italia/2026"
        parts = race_identifier.replace("race/", "").split("/")
        race_part = parts[0].replace("-", " ").title()
        year = None
        
        # Extract year from identifier
        year_match = re.search(r'(\d{4})', race_identifier)
        if year_match:
            year = year_match.group(1)
        
        # Try to match by race name (without year)
        query_race = race_part.replace("D", "d'")  # Fix Giro d'Italia
        query_race = query_race.replace(" '", " d'")
        
        rows = conn.execute(
            "SELECT race_name FROM races WHERE LOWER(race_name) LIKE LOWER(?)",
            [f"%{race_part}%"],
        ).fetchall()
        
        if rows:
            return rows[0][0]
        
        # Try simpler match
        simple_name = race_part.split()[0] if race_part else race_part
        rows = conn.execute(
            "SELECT race_name FROM races WHERE LOWER(race_name) LIKE LOWER(?)",
            [f"%{simple_name}%"],
        ).fetchall()
        
        if rows:
            return rows[0][0]
        
        # Return the cleaned identifier
        return race_part
    finally:
        conn.close()


def main():
    if len(sys.argv) < 2:
        print("Usage: python fetch_stage_results.py <race_url_or_identifier>")
        print("Example: python fetch_stage_results.py giro-d-italia/2026")
        print("Example: python fetch_stage_results.py 'https://www.procyclingstats.com/race/giro-d-italia/2026/stage-1/result'")
        sys.exit(1)
    
    input_url = sys.argv[1]
    race_identifier, stage_num = get_race_and_stages_from_url(input_url)
    
    print(f"Race identifier: {race_identifier}")
    
    # Get the proper race name from the database
    race_name = get_existing_race_name(DB_PATH, race_identifier)
    print(f"Database race name: {race_name}")
    
    # Ensure stage_results table exists
    init_stage_results_table(DB_PATH)
    
    # Get all stages for this race from the database
    stages = get_stages_from_db(DB_PATH, race_name)
    
    if not stages:
        print(f"No stages found in database for race: {race_name}")
        print("Please ensure the race and its stages are in the database first.")
        sys.exit(1)
    
    print(f"\nFound {len(stages)} stages for {race_name}")
    
    # If a specific stage was provided, only process that one
    if stage_num:
        stages = [s for s in stages if get_stage_number_from_name(s["stage_name"]) == stage_num]
    
    # Process each stage
    for stage in stages:
        stage_name = stage["stage_name"]
        stage_date = stage["date"]
        stage_number = get_stage_number_from_name(stage_name)
        is_one_day_race = stage.get("is_one_day_race", False)
        
        # Skip rest days (no stage number)
        if stage_number is None and not is_one_day_race:
            print(f"  Skipping {stage_name} (rest day)")
            continue
            
        print(f"\nProcessing {race_name} - {stage_name} ({stage_date})")
        
        # For one-day races, use the race URL directly
        if is_one_day_race:
            result_url = construct_result_url(race_identifier, "1", is_one_day_race=True)
        else:
            result_url = construct_result_url(race_identifier, stage_number)
        print(f"  Fetching from: {result_url}")
        
        try:
            riders = fetch_top_15_riders(result_url)
            if riders:
                save_stage_results(DB_PATH, race_name, stage_name, riders)
            else:
                print(f"  ⚠ No riders found for {stage_name}")
        except Exception as e:
            print(f"  ✗ Error fetching {stage_name}: {type(e).__name__}: {e}")
    
    print("\n✓ All stages processed!")


if __name__ == "__main__":
    main()
