import time
import logging
from typing import Optional

from procyclingstats import Ranking, Rider, RaceStartlist

logger = logging.getLogger(__name__)

SLEEP_BETWEEN_REQUESTS = 1.0  # seconds


# For Cloudflare-protected sites, we need cloudscraper
try:
    import cloudscraper
    _scraper = cloudscraper.create_scraper()
    _USE_CLOUDSCRAPER = True
except ImportError:
    import requests
    _scraper = requests
    _USE_CLOUDSCRAPER = False

RANKING_BASE = (
    "rankings.php?s=&nation=&age=&zage=&page=smallerorequal"
    "&team=&offset={offset}&teamlevel=&filter=Filter"
)


def get_all_rider_urls() -> list[str]:
    """
    Paginate through the UCI individual ranking using the correct query-string
    URL format and collect all rider URLs.
    """
    rider_urls: list[str] = []
    offset = 0

    while True:
        url = RANKING_BASE.format(offset=offset)
        logger.info(f"Scraping ranking at offset {offset}: {url}")
        try:
            page_ranking = Ranking(url)
            riders = page_ranking.individual_ranking("rider_url")
        except Exception as exc:
            logger.warning(f"Failed at offset {offset}: {exc}")
            break

        if not riders:
            logger.info(f"No riders returned at offset {offset} — done.")
            break

        new = [r["rider_url"] for r in riders if r.get("rider_url") and r["rider_url"] not in rider_urls]
        if not new:
            logger.info(f"No new riders at offset {offset} — done.")
            break

        rider_urls.extend(new)
        logger.info(f"  +{len(new)} riders (total: {len(rider_urls)})")
        offset += 100
        time.sleep(SLEEP_BETWEEN_REQUESTS)

    logger.info(f"Collected {len(rider_urls)} unique rider URLs.")
    return rider_urls


def get_rider_profile(rider_url: str) -> Optional[dict]:
    """
    Fetch full profile for a single rider.
    Returns a flat dict with profile fields, or None if scraping fails.
    """
    try:
        rider = Rider(rider_url)
        data = rider.parse()

        # Extract current (most recent) team from teams_history
        team_name = None
        team_url = None
        history = data.get("teams_history") or []
        if history:
            current = history[0]  # most recent entry is first
            team_name = current.get("team_name")
            team_url = current.get("team_url")

        return {
            "rider_url": rider_url,
            "name": data.get("name"),
            "nationality": data.get("nationality"),
            "birthdate": data.get("birthdate"),
            "height": data.get("height"),
            "weight": data.get("weight"),
            "team_name": team_name,
            "team_url": team_url,
        }
    except Exception as exc:
        logger.warning(f"Failed to scrape rider {rider_url}: {exc}")
        return None


def get_race_startlist(startlist_url: str) -> list[dict]:
    """
    Fetch and parse the startlist from a ProCyclingStats startlist URL.
    
    Args:
        startlist_url: Full URL to the PCS startlist page
                    (e.g., "https://www.procyclingstats.com/race/giro-ditalia/2026/startlist")
    
    Returns:
        List of rider dicts with keys: rider_url, rider_name, team_name
        Returns empty list on failure.
    """
    try:
        logger.info(f"Fetching startlist from {startlist_url}")
        
        # Use cloudscraper to bypass Cloudflare
        response = _scraper.get(startlist_url, timeout=30)
        response.raise_for_status()
        
        # Parse the startlist
        startlist = RaceStartlist(startlist_url, html=response.text, update_html=False)
        riders = startlist.startlist("rider_url", "rider_name", "team_name")
        
        # Format the results
        result = []
        for rider in riders:
            result.append({
                "rider_url": rider.get("rider_url"),
                "rider_name": rider.get("rider_name"),
                "team_name": rider.get("team_name") or "",
            })
        
        logger.info(f"Found {len(result)} riders in startlist")
        return result
        
    except Exception as exc:
        logger.error(f"Failed to fetch startlist from {startlist_url}: {exc}")
        return []
