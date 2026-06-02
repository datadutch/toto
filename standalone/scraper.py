import logging
import os
import time

from dotenv import load_dotenv
from src.scraper import get_all_rider_urls, get_rider_profile, SLEEP_BETWEEN_REQUESTS
from src.db import init_db, upsert_rider, rider_count

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

load_dotenv()
_TOKEN = os.getenv("MOTHERDUCK_TOKEN")
if _TOKEN:
    DB_PATH = f"md:toto?motherduck_token={_TOKEN}"
    logger.info("Using MotherDuck database")
else:
    DB_PATH = os.path.join(os.path.dirname(__file__), "data", "cycling.duckdb")
    os.makedirs(os.path.join(os.path.dirname(__file__), "data"), exist_ok=True)
    logger.info(f"Using local database: {DB_PATH}")


def main() -> None:
    if not DB_PATH.startswith("md:"):
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = init_db(DB_PATH)

    rider_urls = get_all_rider_urls()
    total = len(rider_urls)
    logger.info(f"Starting profile scrape for {total} riders...")

    success = 0
    failed = 0

    for i, url in enumerate(rider_urls, start=1):
        profile = get_rider_profile(url)
        if profile:
            upsert_rider(conn, profile)
            success += 1
            logger.info(f"[{i}/{total}] Saved: {profile.get('name')} ({url})")
        else:
            failed += 1
            logger.warning(f"[{i}/{total}] Skipped: {url}")

        if i < total:
            time.sleep(SLEEP_BETWEEN_REQUESTS)

    logger.info(f"Done. {success} saved, {failed} failed. Total in DB: {rider_count(conn)}")
    conn.close()


if __name__ == "__main__":
    main()

