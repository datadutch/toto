import duckdb
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def _connect(db_path: str, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    """Open a DuckDB connection. MotherDuck connections never use read_only."""
    if db_path.startswith("md:"):
        return duckdb.connect(db_path)
    return duckdb.connect(db_path, read_only=read_only)

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS riders (
    rider_url    VARCHAR PRIMARY KEY,
    name         VARCHAR,
    nationality  VARCHAR,
    birthdate    VARCHAR,
    height       FLOAT,
    weight       FLOAT,
    team_name    VARCHAR,
    team_url     VARCHAR,
    scraped_at   TIMESTAMP DEFAULT now()
)
"""

DELETE_RIDER_SQL = "DELETE FROM riders WHERE rider_url = ?"

INSERT_RIDER_SQL = """
INSERT INTO riders (rider_url, name, nationality, birthdate, height, weight, team_name, team_url, scraped_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, now())
"""


def init_db(db_path: str) -> duckdb.DuckDBPyConnection:
    """Open (or create) a DuckDB database and ensure the riders table exists."""
    conn = _connect(db_path)
    conn.execute(CREATE_TABLE_SQL)
    logger.info(f"Database ready at {db_path}")
    return conn


def upsert_rider(conn: duckdb.DuckDBPyConnection, rider: dict) -> None:
    """Insert or update a rider record (delete+insert for MotherDuck compatibility)."""
    values = [
        rider.get("rider_url"),
        rider.get("name"),
        rider.get("nationality"),
        rider.get("birthdate"),
        rider.get("height"),
        rider.get("weight"),
        rider.get("team_name"),
        rider.get("team_url"),
    ]
    conn.execute(DELETE_RIDER_SQL, [values[0]])
    conn.execute(INSERT_RIDER_SQL, values)


def save_rider(db_path: str, rider_url: str, name: str, nationality: str, birthdate: str,
               height: Optional[float], weight: Optional[float], team_name: str, team_url: str) -> None:
    """Upsert a single rider via a standalone db_path connection."""
    conn = _connect(db_path)
    try:
        upsert_rider(conn, {
            "rider_url": rider_url,
            "name": name,
            "nationality": nationality or None,
            "birthdate": birthdate or None,
            "height": height,
            "weight": weight,
            "team_name": team_name or None,
            "team_url": team_url or None,
        })
    finally:
        conn.close()


def delete_rider(db_path: str, rider_url: str) -> None:
    """Delete a rider by URL."""
    conn = _connect(db_path)
    try:
        conn.execute(DELETE_RIDER_SQL, [rider_url])
    finally:
        conn.close()


def rider_count(conn: duckdb.DuckDBPyConnection) -> int:
    return conn.execute("SELECT count(*) FROM riders").fetchone()[0]


FANTASY_TEAMS_SQL = """
CREATE TABLE IF NOT EXISTS fantasy_teams (
    id           INTEGER,
    manager_name VARCHAR NOT NULL,
    team_name    VARCHAR NOT NULL,
    race_name    VARCHAR,
    created_at   TIMESTAMP DEFAULT now()
)
"""

FANTASY_RIDERS_SQL = """
CREATE TABLE IF NOT EXISTS fantasy_team_riders (
    team_id   INTEGER NOT NULL,
    slot      INTEGER NOT NULL,
    rider_url VARCHAR NOT NULL
)
"""


def init_fantasy_tables(db_path: str) -> None:
    conn = _connect(db_path)
    try:
        conn.execute(FANTASY_TEAMS_SQL)
        conn.execute(FANTASY_RIDERS_SQL)
        # Migrations
        try:
            conn.execute("ALTER TABLE fantasy_teams ADD COLUMN race_name VARCHAR")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE fantasy_teams ADD COLUMN account_id INTEGER")
        except Exception:
            pass
    finally:
        conn.close()


def save_fantasy_team(db_path: str, manager_name: str, team_name: str, rider_urls: list[str], race_name: str = None, account_id: int = None) -> int:
    conn = _connect(db_path)
    try:
        if account_id is not None:
            existing = conn.execute(
                "SELECT id FROM fantasy_teams WHERE account_id = ? AND race_name = ?",
                [account_id, race_name],
            ).fetchone()
        else:
            existing = conn.execute(
                "SELECT id FROM fantasy_teams WHERE lower(manager_name) = lower(?) AND race_name = ?",
                [manager_name, race_name],
            ).fetchone()

        if existing:
            team_id = existing[0]
            conn.execute(
                "UPDATE fantasy_teams SET team_name = ?, manager_name = ? WHERE id = ?",
                [team_name, manager_name, team_id],
            )
            conn.execute("DELETE FROM fantasy_team_riders WHERE team_id = ?", [team_id])
        else:
            team_id = conn.execute("SELECT coalesce(max(id), 0) + 1 FROM fantasy_teams").fetchone()[0]
            conn.execute(
                "INSERT INTO fantasy_teams (id, manager_name, team_name, race_name, account_id, created_at) VALUES (?, ?, ?, ?, ?, now())",
                [team_id, manager_name, team_name, race_name, account_id],
            )

        for slot, url in enumerate(rider_urls, start=1):
            conn.execute(
                "INSERT INTO fantasy_team_riders (team_id, slot, rider_url) VALUES (?, ?, ?)",
                [team_id, slot, url],
            )
        return team_id
    finally:
        conn.close()


def load_team_by_account(db_path: str, account_id: int, race_name: str) -> Optional[dict]:
    """Return existing team for an account+race, or None."""
    conn = _connect(db_path, read_only=True)
    try:
        row = conn.execute(
            "SELECT id, team_name FROM fantasy_teams WHERE account_id = ? AND race_name = ?",
            [account_id, race_name],
        ).fetchone()
        if not row:
            return None
        team_id, team_name = row
        urls = [r[0] for r in conn.execute(
            "SELECT rider_url FROM fantasy_team_riders WHERE team_id = ? ORDER BY slot",
            [team_id],
        ).fetchall()]
        return {"id": team_id, "team_name": team_name, "rider_urls": urls}
    finally:
        conn.close()


# ── Accounts ───────────────────────────────────────────────────────────────────────
CREATE_ACCOUNTS_SQL = """
CREATE TABLE IF NOT EXISTS accounts (
    id         INTEGER,
    email      VARCHAR,
    name       VARCHAR,
    is_admin   VARCHAR DEFAULT 'no',
    created_at TIMESTAMP DEFAULT now()
)
"""


def init_accounts_table(db_path: str) -> None:
    conn = _connect(db_path)
    try:
        conn.execute(CREATE_ACCOUNTS_SQL)
        # Migration: add is_admin column if it doesn't exist
        try:
            conn.execute("ALTER TABLE accounts ADD COLUMN is_admin VARCHAR DEFAULT 'no'")
        except Exception:
            pass
        # Migration: ensure existing accounts have is_admin set
        try:
            conn.execute("UPDATE accounts SET is_admin = 'no' WHERE is_admin IS NULL OR is_admin = ''")
        except Exception:
            pass
    finally:
        conn.close()


def init_admin_accounts(db_path: str, admin_emails: list[str]) -> None:
    """One-time migration: set is_admin='yes' for accounts in the admin_emails list."""
    if not admin_emails:
        return
    conn = _connect(db_path)
    try:
        for email in admin_emails:
            conn.execute(
                "UPDATE accounts SET is_admin = 'yes' WHERE lower(email) = lower(?)",
                [email.strip()],
            )
    finally:
        conn.close()


def get_account_by_email(db_path: str, email: str) -> Optional[dict]:
    conn = _connect(db_path, read_only=True)
    try:
        row = conn.execute(
            "SELECT id, email, name, is_admin FROM accounts WHERE lower(email) = lower(?)", [email.strip()]
        ).fetchone()
        if not row:
            return None
        return {"id": row[0], "email": row[1], "name": row[2], "is_admin": row[3] or "no"}
    finally:
        conn.close()


def create_account(db_path: str, email: str, name: str, is_admin: str = "no") -> dict:
    conn = _connect(db_path)
    try:
        next_id = conn.execute("SELECT coalesce(max(id), 0) + 1 FROM accounts").fetchone()[0]
        conn.execute(
            "INSERT INTO accounts (id, email, name, is_admin, created_at) VALUES (?, ?, ?, ?, now())",
            [next_id, email.lower().strip(), name.strip(), is_admin],
        )
        return {"id": next_id, "email": email.lower().strip(), "name": name.strip(), "is_admin": is_admin}
    finally:
        conn.close()


def set_admin_status(db_path: str, email: str, is_admin: str) -> bool:
    """Set admin status for an account. Returns True if account was found and updated."""
    conn = _connect(db_path)
    try:
        result = conn.execute(
            "UPDATE accounts SET is_admin = ? WHERE lower(email) = lower(?)",
            [is_admin, email.strip()],
        )
        return result.rowcount > 0
    finally:
        conn.close()


def load_fantasy_teams(db_path: str, race_name: str = None) -> list[dict]:
    conn = _connect(db_path, read_only=True)
    try:
        if race_name:
            rows = conn.execute(
                "SELECT id, manager_name, team_name, race_name, created_at FROM fantasy_teams WHERE race_name = ? OR race_name IS NULL ORDER BY created_at DESC",
                [race_name],
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, manager_name, team_name, race_name, created_at FROM fantasy_teams ORDER BY created_at DESC"
            ).fetchall()
        return [{"id": r[0], "manager_name": r[1], "team_name": r[2], "race_name": r[3], "created_at": r[4]} for r in rows]
    finally:
        conn.close()


def load_fantasy_team_riders(db_path: str, team_id: int) -> list[str]:
    conn = _connect(db_path, read_only=True)
    try:
        rows = conn.execute(
            """SELECT r.name, r.nationality, r.team_name
               FROM fantasy_team_riders ftr
               JOIN riders r ON r.rider_url = ftr.rider_url
               WHERE ftr.team_id = ?
               ORDER BY ftr.slot""",
            [team_id],
        ).fetchall()
        return [{"name": r[0], "nationality": r[1], "team": r[2]} for r in rows]
    finally:
        conn.close()


# ── Races (with deadlines) ───────────────────────────────────────────────────

CREATE_RACES_SQL = """
CREATE TABLE IF NOT EXISTS races (
    race_name VARCHAR PRIMARY KEY,
    deadline  TIMESTAMP
)
"""

RACE_SEEDS = [
    ("Giro d'Italia",      "2026-05-07 22:00:00"),
    ("De Brabantse Pijl",  "2026-04-16 22:00:00"),
    ("Amstel Gold Race",   "2026-04-18 22:00:00"),
]


def init_races_table(db_path: str) -> None:
    conn = _connect(db_path)
    try:
        conn.execute(CREATE_RACES_SQL)
        for race_name, deadline in RACE_SEEDS:
            exists = conn.execute(
                "SELECT count(*) FROM races WHERE race_name = ?", [race_name]
            ).fetchone()[0]
            if not exists:
                conn.execute(
                    "INSERT INTO races (race_name, deadline) VALUES (?, ?)",
                    [race_name, deadline],
                )
    finally:
        conn.close()


def load_races(db_path: str) -> list[dict]:
    conn = _connect(db_path, read_only=True)
    try:
        rows = conn.execute(
            "SELECT race_name, deadline FROM races ORDER BY deadline"
        ).fetchall()
        return [{"race_name": r[0], "deadline": r[1]} for r in rows]
    finally:
        conn.close()


def update_deadline(db_path: str, race_name: str, deadline) -> None:
    conn = _connect(db_path)
    try:
        conn.execute(
            "UPDATE races SET deadline = ? WHERE race_name = ?",
            [deadline, race_name],
        )
    finally:
        conn.close()


def is_registration_open(db_path: str, race_name: str) -> bool:
    """Returns True if the deadline has not yet passed (or no deadline set)."""
    conn = _connect(db_path, read_only=True)
    try:
        row = conn.execute(
            "SELECT deadline FROM races WHERE race_name = ?", [race_name]
        ).fetchone()
        if not row or row[0] is None:
            return True
        from datetime import datetime
        deadline = row[0] if isinstance(row[0], datetime) else datetime.fromisoformat(str(row[0]))
        # Deadlines are stored and entered as local time; compare against local now()
        return datetime.now() < deadline.replace(tzinfo=None)
    finally:
        conn.close()


# ── Stages ────────────────────────────────────────────────────────────────────

CREATE_STAGES_SQL = """
CREATE TABLE IF NOT EXISTS stages (
    race_name  VARCHAR NOT NULL,
    date       VARCHAR NOT NULL,
    day        VARCHAR,
    stage_name VARCHAR NOT NULL,
    route      VARCHAR,
    km         FLOAT
)
"""

GIRO_2025_STAGES = [
    ("Giro d'Italia", "08/05", "Friday",    "Stage 1",       "Nessebar - Burgas",                       156.0),
    ("Giro d'Italia", "09/05", "Saturday",  "Stage 2",       "Burgas - Valiko Tarnovo",                 220.0),
    ("Giro d'Italia", "10/05", "Sunday",    "Stage 3",       "Plovdiv - Sofia",                         174.0),
    ("Giro d'Italia", "11/05", None,        "Rest Day",      None,                                      None),
    ("Giro d'Italia", "12/05", "Tuesday",   "Stage 4",       "Catanzaro - Cosenza",                     144.0),
    ("Giro d'Italia", "13/05", "Wednesday", "Stage 5",       "Praia a Mare - Potenza",                  204.0),
    ("Giro d'Italia", "14/05", "Thursday",  "Stage 6",       "Paestum - Naples",                        161.0),
    ("Giro d'Italia", "15/05", "Friday",    "Stage 7",       "Formia - Blockhaus",                      246.0),
    ("Giro d'Italia", "16/05", "Saturday",  "Stage 8",       "Chieti - Fermo",                          159.0),
    ("Giro d'Italia", "17/05", "Sunday",    "Stage 9",       "Cervia - Corno alle Scale",               184.0),
    ("Giro d'Italia", "18/05", None,        "Rest Day",      None,                                      None),
    ("Giro d'Italia", "19/05", "Tuesday",   "Stage 10 (ITT)","Viareggio - Massa",                        40.2),
    ("Giro d'Italia", "20/05", "Wednesday", "Stage 11",      "Porcari (Paper District) - Chiavari",     178.0),
    ("Giro d'Italia", "21/05", "Thursday",  "Stage 12",      "Imperia - Novi Ligure",                   177.0),
    ("Giro d'Italia", "22/05", "Friday",    "Stage 13",      "Alessandria - Verbania",                  186.0),
    ("Giro d'Italia", "23/05", "Saturday",  "Stage 14",      "Aosta - Pila",                            133.0),
    ("Giro d'Italia", "24/05", "Sunday",    "Stage 15",      "Voghera - Milan",                         136.0),
    ("Giro d'Italia", "25/05", None,        "Rest Day",      None,                                      None),
    ("Giro d'Italia", "26/05", "Tuesday",   "Stage 16",      "Bellinzona - Carì",                       113.0),
    ("Giro d'Italia", "27/05", "Wednesday", "Stage 17",      "Cassano d'Adda - Andalo",                 200.0),
    ("Giro d'Italia", "28/05", "Thursday",  "Stage 18",      "Fai della Paganella - Pieve di Soligo",  167.0),
    ("Giro d'Italia", "29/05", "Friday",    "Stage 19",      "Feltre - Alleghe (Piani di Pezzè)",       151.0),
    ("Giro d'Italia", "30/05", "Saturday",  "Stage 20",      "Gemona del Friuli 1976-2026 - Piancavallo", 199.0),
    ("Giro d'Italia", "31/05", "Sunday",    "Stage 21",      "Rome - Rome",                             131.0),
]

BRABANTSE_PIJL_STAGES = [
    ("De Brabantse Pijl", "17/04", "Thursday", "Stage 1", "Beersel - Overijse", 163.0),
]

AMSTEL_GOLD_STAGES = [
    ("Amstel Gold Race", "19/04", "Sunday", "Stage 1", "Maastricht - Berg en Terblijt", 257.4),
]


def init_stages_table(db_path: str) -> None:
    conn = _connect(db_path)
    try:
        conn.execute(CREATE_STAGES_SQL)
        existing_giro = conn.execute(
            "SELECT count(*) FROM stages WHERE race_name = 'Giro d''Italia'"
        ).fetchone()[0]
        if existing_giro == 0:
            conn.executemany(
                "INSERT INTO stages (race_name, date, day, stage_name, route, km) VALUES (?, ?, ?, ?, ?, ?)",
                GIRO_2025_STAGES,
            )
        existing_bp = conn.execute(
            "SELECT count(*) FROM stages WHERE race_name = 'De Brabantse Pijl'"
        ).fetchone()[0]
        if existing_bp == 0:
            conn.executemany(
                "INSERT INTO stages (race_name, date, day, stage_name, route, km) VALUES (?, ?, ?, ?, ?, ?)",
                BRABANTSE_PIJL_STAGES,
            )
        existing_agr = conn.execute(
            "SELECT count(*) FROM stages WHERE race_name = 'Amstel Gold Race'"
        ).fetchone()[0]
        if existing_agr == 0:
            conn.executemany(
                "INSERT INTO stages (race_name, date, day, stage_name, route, km) VALUES (?, ?, ?, ?, ?, ?)",
                AMSTEL_GOLD_STAGES,
            )
    finally:
        conn.close()


def load_stages(db_path: str, race_name: str) -> list[dict]:
    conn = _connect(db_path, read_only=True)
    try:
        rows = conn.execute(
            "SELECT date, day, stage_name, route, km FROM stages WHERE race_name = ? ORDER BY date",
            [race_name],
        ).fetchall()
        return [
            {"Date": r[0], "Day": r[1] or "", "Stage": r[2], "Route": r[3] or "", "KM": r[4]}
            for r in rows
        ]
    finally:
        conn.close()


# ── Stage results ─────────────────────────────────────────────────────────────

CREATE_STAGE_RESULTS_SQL = """
CREATE TABLE IF NOT EXISTS stage_results (
    race_name  VARCHAR NOT NULL,
    stage_name VARCHAR NOT NULL,
    position   INTEGER NOT NULL,
    rider_url  VARCHAR NOT NULL,
    PRIMARY KEY (race_name, stage_name, position)
)
"""


def init_stage_results_table(db_path: str) -> None:
    conn = _connect(db_path)
    try:
        conn.execute(CREATE_STAGE_RESULTS_SQL)
    finally:
        conn.close()


def save_stage_results(db_path: str, race_name: str, stage_name: str, rider_urls: list[str]) -> None:
    conn = _connect(db_path)
    try:
        conn.execute(
            "DELETE FROM stage_results WHERE race_name = ? AND stage_name = ?",
            [race_name, stage_name],
        )
        for pos, url in enumerate(rider_urls, start=1):
            conn.execute(
                "INSERT INTO stage_results (race_name, stage_name, position, rider_url) VALUES (?, ?, ?, ?)",
                [race_name, stage_name, pos, url],
            )
    finally:
        conn.close()


def delete_stage_results(db_path: str, race_name: str, stage_name: str) -> None:
    conn = _connect(db_path)
    try:
        conn.execute(
            "DELETE FROM stage_results WHERE race_name = ? AND stage_name = ?",
            [race_name, stage_name],
        )
    finally:
        conn.close()


def load_stage_results(db_path: str, race_name: str, stage_name: str) -> list[dict]:
    conn = _connect(db_path, read_only=True)
    try:
        rows = conn.execute(
            """SELECT sr.position, r.name, r.nationality, r.team_name
               FROM stage_results sr
               JOIN riders r ON r.rider_url = sr.rider_url
               WHERE sr.race_name = ? AND sr.stage_name = ?
               ORDER BY sr.position""",
            [race_name, stage_name],
        ).fetchall()
        return [{"Pos": r[0], "Rider": r[1], "NAT": r[2], "Team": r[3]} for r in rows]
    finally:
        conn.close()


def stages_with_results(db_path: str, race_name: str) -> set[str]:
    conn = _connect(db_path, read_only=True)
    try:
        rows = conn.execute(
            "SELECT DISTINCT stage_name FROM stage_results WHERE race_name = ?",
            [race_name],
        ).fetchall()
        return {r[0] for r in rows}
    finally:
        conn.close()


# ── Scoring ───────────────────────────────────────────────────────────────────

STAGE_POINTS = {1: 15, 2: 14, 3: 13, 4: 12, 5: 11, 6: 10,
                7: 9, 8: 8, 9: 7, 10: 6, 11: 5, 12: 4, 13: 3, 14: 2, 15: 1}


def calculate_scores(db_path: str, race_name: str) -> list[dict]:
    """Return per-team, per-stage scores plus totals for all finished stages."""
    conn = _connect(db_path, read_only=True)
    try:
        # All stage results for this race
        results_rows = conn.execute(
            "SELECT stage_name, position, rider_url FROM stage_results WHERE race_name = ? ORDER BY stage_name, position",
            [race_name],
        ).fetchall()

        if not results_rows:
            return []

        # Build lookup: rider_url → {stage_name: points}
        rider_stage_points: dict[str, dict[str, int]] = {}
        finished_stages: list[str] = []
        for stage_name, position, rider_url in results_rows:
            if stage_name not in finished_stages:
                finished_stages.append(stage_name)
            pts = STAGE_POINTS.get(position, 0)
            rider_stage_points.setdefault(rider_url, {})[stage_name] = pts

        # All fantasy teams for this race and their riders
        teams = conn.execute(
            "SELECT id, manager_name, team_name FROM fantasy_teams WHERE race_name = ? OR race_name IS NULL ORDER BY id",
            [race_name],
        ).fetchall()

        team_riders = conn.execute(
            "SELECT team_id, rider_url FROM fantasy_team_riders"
        ).fetchall()

        team_rider_map: dict[int, list[str]] = {}
        for team_id, rider_url in team_riders:
            team_rider_map.setdefault(team_id, []).append(rider_url)

        rows_out = []
        for team_id, manager_name, team_name in teams:
            urls = team_rider_map.get(team_id, [])
            row: dict = {"Team": team_name, "Manager": manager_name}
            total = 0
            for stage in finished_stages:
                stage_pts = sum(
                    rider_stage_points.get(url, {}).get(stage, 0) for url in urls
                )
                row[stage] = stage_pts
                total += stage_pts
            row["Total"] = total
            rows_out.append(row)

        # Sort by total descending
        rows_out.sort(key=lambda r: r["Total"], reverse=True)
        return rows_out
    finally:
        conn.close()


def calculate_stage_breakdown(db_path: str, race_name: str, team_id: int) -> list[dict]:
    """Return which riders scored points in each finished stage for one team."""
    conn = _connect(db_path, read_only=True)
    try:
        finished = conn.execute(
            "SELECT DISTINCT stage_name FROM stage_results WHERE race_name = ? ORDER BY stage_name",
            [race_name],
        ).fetchall()

        urls = [r[0] for r in conn.execute(
            "SELECT rider_url FROM fantasy_team_riders WHERE team_id = ?", [team_id]
        ).fetchall()]

        rows_out = []
        for (stage_name,) in finished:
            results = conn.execute(
                """SELECT sr.position, r.name
                   FROM stage_results sr
                   JOIN riders r ON r.rider_url = sr.rider_url
                   WHERE sr.race_name = ? AND sr.stage_name = ? AND sr.rider_url IN ({})
                   ORDER BY sr.position""".format(",".join("?" * len(urls))),
                [race_name, stage_name] + urls,
            ).fetchall()
            for pos, name in results:
                rows_out.append({
                    "Stage": stage_name,
                    "Rider": name,
                    "Position": pos,
                    "Points": STAGE_POINTS.get(pos, 0),
                })
        return rows_out
    finally:
        conn.close()
