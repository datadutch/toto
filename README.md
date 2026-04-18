# Stampers Toto 🚴

A Dutch cycling fantasy-sports web app built with Streamlit and DuckDB. Participants pick a fantasy team of riders for a race; an admin enters stage results and the app calculates scores.

---

## Architecture

| File / Folder | Purpose |
|---|---|
| `participant.py` | Streamlit app for participants — register, log in, and submit a fantasy team |
| `app.py` | Streamlit admin app — manage races, enter stage results, manage riders and teams |
| `main.py` | CLI scraper — populates the `riders` table from procyclingstats.com |
| `src/scraper.py` | Scraping logic using the `procyclingstats` library |
| `src/db.py` | Database layer (DuckDB / MotherDuck) — all SQL and table initialisation |

---

## Database

The app uses **DuckDB**. Two modes are supported, selected automatically via an environment variable:

| Mode | When used | Path |
|---|---|---|
| **MotherDuck** (cloud) | `MOTHERDUCK_TOKEN` env var is set | `md:toto` |
| **Local file** | No token | `data/cycling.duckdb` |

### Main tables

- `riders` — UCI rider profiles (name, nationality, team, birthdate, height, weight)
- `fantasy_teams` / `fantasy_team_riders` — participant fantasy team selections per race
- `accounts` — participant accounts (email + display name)
- `races` — configured races with optional registration deadline
- `stages` — stages per race
- `stage_results` — top-15 finishing positions per stage

---

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure environment

Create a `.env` file in the project root:

```env
# Optional: use MotherDuck instead of a local DuckDB file
MOTHERDUCK_TOKEN=your_token_here
```

### 3. Scrape rider data

Populate the `riders` table by scraping the UCI ranking from procyclingstats.com:

```bash
python main.py
```

This paginates through the full UCI ranking and upserts every rider profile. A 1-second sleep between requests avoids rate-limiting.

---

## Running the apps

### Participant app

```bash
streamlit run participant.py
```

Participants can:
- Log in with an e-mail address (or via Google OAuth on Streamlit Cloud)
- Register an account
- Select a race and submit a fantasy team of riders before the deadline

### Admin app

```bash
streamlit run app.py
```

Admins can:
- Configure races and set registration deadlines
- Add / edit / delete riders
- Enter stage results (top 15 per stage)
- View all submitted fantasy teams and calculated scores

---

## Authentication

- **Streamlit Cloud**: Google OAuth is used automatically via `st.user`.
- **Local / self-hosted**: participants log in with an e-mail address; a new account is created on first login.

---

## Dependencies

| Package | Use |
|---|---|
| `streamlit` | Web UI |
| `duckdb` | Embedded / cloud database |
| `procyclingstats` | Scraping UCI rankings and rider profiles |
| `cloudscraper` | HTTP client that bypasses Cloudflare (used by procyclingstats) |
| `python-dotenv` | Loading `.env` variables |
