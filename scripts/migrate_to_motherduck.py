"""
One-off migration: copy all tables from local cycling.duckdb to MotherDuck.
Run once:  .venv\Scripts\python.exe scripts/migrate_to_motherduck.py
"""
import os
import sys
import duckdb
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("MOTHERDUCK_TOKEN")
if not TOKEN:
    sys.exit("MOTHERDUCK_TOKEN not found in .env")

LOCAL_DB = os.path.join(os.path.dirname(__file__), "..", "data", "cycling.duckdb")
LOCAL_DB = os.path.abspath(LOCAL_DB)

if not os.path.exists(LOCAL_DB):
    sys.exit(f"Local database not found: {LOCAL_DB}")

TABLES = ["riders", "stages", "stage_results", "fantasy_teams", "fantasy_team_riders"]

print("Connecting to MotherDuck...")
md_conn = duckdb.connect(f"md:?motherduck_token={TOKEN}")

print("Creating database 'toto' on MotherDuck (if not exists)...")
md_conn.execute("CREATE DATABASE IF NOT EXISTS toto")
md_conn.execute("USE toto")

print(f"Attaching local database: {LOCAL_DB}")
md_conn.execute(f"ATTACH '{LOCAL_DB}' AS local (READ_ONLY)")

for table in TABLES:
    print(f"  Migrating {table}...", end=" ")
    try:
        count_local = md_conn.execute(f"SELECT count(*) FROM local.main.{table}").fetchone()[0]
    except Exception:
        print("not found locally, skipping.")
        continue

    # Drop and recreate in MotherDuck
    md_conn.execute(f"DROP TABLE IF EXISTS toto.main.{table}")
    md_conn.execute(f"CREATE TABLE toto.main.{table} AS SELECT * FROM local.main.{table}")
    count = md_conn.execute(f"SELECT count(*) FROM toto.main.{table}").fetchone()[0]
    print(f"done ({count:,} rows).")

md_conn.execute("DETACH local")
md_conn.close()
print("\nMigration complete. MotherDuck database: md:toto")
