#!/usr/bin/env python3
"""
Test DuckDB connection and query the toto.fantasy_teams table.
Uses environment variables for configuration (MOTHERDUCK_TOKEN).
"""

import os
import duckdb
from dotenv import load_dotenv

load_dotenv()

# Determine DB path - same logic as main.py
_TOKEN = os.getenv("MOTHERDUCK_TOKEN")
if _TOKEN:
    DB_PATH = f"md:toto?motherduck_token={_TOKEN}"
    print(f"Connecting to MotherDuck: {DB_PATH}")
else:
    DB_PATH = os.path.join(os.path.dirname(__file__), "data", "cycling.duckdb")
    print(f"Connecting to local DuckDB: {DB_PATH}")

try:
    conn = duckdb.connect(DB_PATH)
    print("✓ Connection successful\n")
    
    print("Querying: SELECT * FROM toto.fantasy_teams")
    print("-" * 60)
    
    result = conn.execute("SELECT * FROM toto.fantasy_teams").fetchall()
    
    if not result:
        print("No rows returned - table may be empty or not exist")
    else:
        # Get column names
        columns = [desc[0] for desc in conn.description]
        
        # Print column headers
        print(" | ".join(columns))
        print("-" * 60)
        
        # Print rows
        for row in result:
            print(" | ".join(str(val) for val in row))
    
    print(f"\nTotal rows: {len(result)}")
    
    conn.close()
    print("\n✓ Connection closed")
    
except Exception as e:
    print(f"✗ Error: {e}")
    print("\nPossible issues:")
    print("  - Database file not found")
    print("  - Table 'toto.fantasy_teams' doesn't exist")
    print("  - Missing MOTHERDUCK_TOKEN in .env")
