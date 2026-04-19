#!/usr/bin/env python3
"""
Race Result Scraper
Fetches the first 15 riders from a ProCyclingStats race result URL.

Usage:
    python race_result_scraper.py
    (then enter the URL when prompted)

Or with command line argument:
    python race_result_scraper.py "race/amstel-gold-race/2025/result"
"""

import sys
import cloudscraper
from procyclingstats import Stage


def extract_path_from_url(url: str) -> str:
    """Extract the path part from a URL (handles both full URLs and paths)."""
    url = url.strip()
    
    # If it starts with http:// or https://, extract the path
    if url.startswith("http://") or url.startswith("https://"):
        # Remove protocol
        if "://" in url:
            url = url.split("://", 1)[1]
        # Remove domain
        if "/" in url:
            url = url.split("/", 1)[1]
    
    # Ensure it doesn't have trailing slash
    url = url.rstrip("/")
    
    # Add 'result' suffix if not already present
    if not url.endswith("/result") and not url.endswith("-result"):
        # Check if it looks like a race path (race/.../year format)
        parts = url.split("/")
        if len(parts) >= 3 and parts[0] == "race":
            # Add /result at the end
            url = f"{url}/result"
    
    return url


def get_top_15_riders(result_path: str) -> list[dict]:
    """Fetch race results and return the top 15 riders."""
    # Construct full URL
    if not result_path.startswith("http"):
        full_url = f"https://www.procyclingstats.com/{result_path}"
    else:
        full_url = result_path
    
    # Use cloudscraper to bypass Cloudflare protection
    scraper = cloudscraper.create_scraper()
    response = scraper.get(full_url)
    html = response.text
    
    # Pass HTML to Stage class
    stage = Stage(result_path, html=html, update_html=False)
    result = stage.parse()
    
    # Get results from the parsed data
    riders = result.get("results", [])
    
    # Take first 15 riders who have a rank (finished)
    top_15 = []
    for rider in riders:
        if rider.get("rank") and len(top_15) < 15:
            top_15.append(rider)
    
    return top_15


def print_riders(riders: list[dict]) -> None:
    """Print riders in a formatted table."""
    if not riders:
        print("No riders found.")
        return
    
    # Determine column widths
    rank_width = max(len(str(r.get("rank", ""))) for r in riders) + 2
    name_width = max(len(r.get("rider_name", "")) for r in riders) + 2
    nat_width = max(len(r.get("nationality", "")) for r in riders) + 2
    team_width = max(len(r.get("team_name", "")) for r in riders) + 2
    time_width = max(len(r.get("time", "")) for r in riders) + 2
    
    # Print header
    print("\n" + "=" * (rank_width + name_width + nat_width + team_width + time_width + 6))
    print(f"{'#':<{rank_width}} {'Rider':<{name_width}} {'Nat.':<{nat_width}} {'Team':<{team_width}} {'Time':<{time_width}}")
    print("-" * (rank_width + name_width + nat_width + team_width + time_width + 6))
    
    # Print riders
    for rider in riders:
        rank = rider.get("rank", "")
        name = rider.get("rider_name", "Unknown")
        nat = rider.get("nationality", "")
        team = rider.get("team_name", "")
        time = rider.get("time", "")
        
        print(f"{str(rank):<{rank_width}} {name:<{name_width}} {nat:<{nat_width}} {team:<{team_width}} {time:<{time_width}}")
    
    print("=" * (rank_width + name_width + nat_width + team_width + time_width + 6))
    print(f"\nTotal: {len(riders)} riders\n")


def main():
    print("=" * 60)
    print("ProCyclingStats Race Result Scraper")
    print("=" * 60)
    print("\nEnter a race result URL from ProCyclingStats")
    print("Example: race/amstel-gold-race/2025/result")
    print("         or: https://www.procyclingstats.com/race/tour-de-france/2025/stage-1/result")
    print()
    
    # Get URL from command line or input
    if len(sys.argv) > 1:
        url = sys.argv[1]
    else:
        url = input("URL: ")
    
    if not url.strip():
        print("No URL provided. Exiting.")
        sys.exit(1)
    
    # Extract the path for procyclingstats library
    result_path = extract_path_from_url(url)
    print(f"\nFetching results from: {result_path}")
    print("-" * 60)
    
    try:
        riders = get_top_15_riders(result_path)
        print_riders(riders)
    except Exception as e:
        print(f"\nError: {type(e).__name__}: {e}")
        print("\nPossible issues:")
        print("  - URL format is incorrect")
        print("  - Race results not available on ProCyclingStats")
        print("  - Network connection issue")
        sys.exit(1)


if __name__ == "__main__":
    main()
