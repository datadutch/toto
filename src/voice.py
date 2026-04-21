import os
import json
import unicodedata
import logging
import difflib
from typing import Optional

from mistralai import Mistral

logger = logging.getLogger(__name__)

MISTRAL_MODEL = os.getenv("MISTRAL_MODEL", "mistral-large-latest")

_EXTRACTION_SYSTEM_PROMPT = """
You are a cycling fantasy-sports assistant. The user will type a freeform text in Dutch or English
listing up to 15 professional cycling riders for their fantasy team.

Extract the rider names and return ONLY a JSON object with this exact structure:
{"riders": ["<full rider name>", ...]}

Rules:
- Return at most 15 rider names
- Use the rider's full name where recognisable (e.g. "Pogacar" -> "Tadej Pogacar")
- Match each name to the closest entry in this list: {rider_list}
- Do not invent riders not mentioned
- Ignore any non-rider text (greetings, race names, etc.)
- Return ONLY the JSON object, no other text
"""


def _normalize(text: str) -> str:
    """Lowercase + strip diacritics so 'pogacar' matches 'Pogačar'."""
    return unicodedata.normalize("NFD", text.lower()).encode("ascii", "ignore").decode("ascii")


def extract_riders_from_text(
    text: str, 
    rider_names: Optional[list[str]] = None,
    db_rows: Optional[list[tuple[str, str]]] = None
) -> list[str]:
    """
    Use Mistral to extract a list of rider names from freeform text.
    
    Args:
        text: Freeform text containing rider names
        rider_names: Optional list of known rider names to ground the LLM's responses
        db_rows: Optional list of (rider_url, name) tuples for validation/re-matching
    
    Returns a list of rider name strings (max 15).
    Raises RuntimeError if MISTRAL_API_KEY is not set.
    """
    api_key = os.getenv("MISTRAL_API_KEY")
    if not api_key:
        raise RuntimeError("MISTRAL_API_KEY is not set. Add it to your .env or Streamlit secrets.")

    # Build the prompt with rider names if provided
    system_prompt = _EXTRACTION_SYSTEM_PROMPT
    if rider_names:
        # Filter out None values and limit to first 200
        valid_names = [n for n in rider_names[:200] if n]
        if valid_names:
            rider_list = ", ".join(valid_names)
            system_prompt = system_prompt.replace("{rider_list}", rider_list)
        else:
            # Remove the placeholder if no valid rider names
            system_prompt = system_prompt.replace("Match each name to the closest entry in this list: {rider_list}\n", "")
    else:
        # Remove the placeholder if no rider names provided
        system_prompt = system_prompt.replace("Match each name to the closest entry in this list: {rider_list}\n", "")

    client = Mistral(api_key=api_key)
    response = client.chat.complete(
        model=MISTRAL_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text},
        ],
        response_format={"type": "json_object"},
    )

    content = response.choices[0].message.content
    try:
        result = json.loads(content)
    except json.JSONDecodeError as exc:
        logger.warning(f"Mistral returned invalid JSON: {content!r} — {exc}")
        result = {}

    extracted = result.get("riders") or []
    
    # If we have DB rows, validate extracted names and try to match unmatched ones
    if db_rows and extracted:
        # Build lookup
        name_to_url = {name: url for url, name in db_rows if name}
        all_db_names = [name for _, name in db_rows if name]
        norm_to_url = {_normalize(name): url for url, name in db_rows if name}
        
        validated = []
        for name in extracted[:15]:
            # Check if the extracted name is in the DB (exact or normalized match)
            norm_name = _normalize(name)
            if name in name_to_url or norm_name in norm_to_url:
                validated.append(name)
            else:
                # The LLM returned a name not in DB - try fuzzy match against DB names
                norm_db_names = [_normalize(n) for n in all_db_names]
                close_matches = difflib.get_close_matches(norm_name, norm_db_names, n=1, cutoff=0.6)
                if close_matches:
                    # Use the matched DB name instead
                    matched_norm = close_matches[0]
                    # Find the original name with this normalized form
                    for db_url, db_name in db_rows:
                        if _normalize(db_name) == matched_norm and db_name:
                            validated.append(db_name)
                            break
                else:
                    # Keep the extracted name (will be caught as not_found in match_riders_to_db)
                    validated.append(name)
        
        return validated
    
    return extracted


def match_riders_to_db(
    extracted_names: list[str], 
    db_path: str,
    rows: Optional[list[tuple[str, str, Optional[str]]]] = None,
    race_name: Optional[str] = None
) -> tuple[list[str], list[str]]:
    """
    Fuzzy-match extracted rider names to rider_urls in the database.
    Uses accent-insensitive normalization + difflib fuzzy matching.

    Args:
        extracted_names: List of rider names extracted from text
        db_path: Path to the database
        rows: Optional pre-loaded database rows (rider_url, name) to avoid redundant queries
        race_name: Optional race name to filter riders from startlist only

    Returns:
        (matched_urls, not_found_names)
        - matched_urls: list of rider_url strings (max 15, preserving order)
        - not_found_names: list of input names that could not be matched
    """
    from src.db import _connect

    # Load DB rows if not provided
    if rows is None:
        conn = _connect(db_path, read_only=True)
        try:
            if race_name:
                # Only match riders from the startlist for this race
                rows = conn.execute(
                    "SELECT rider_url, rider_name, nickname FROM startlists s JOIN riders r ON s.rider_url = r.rider_url WHERE race_name = ? AND rider_name IS NOT NULL"
                    , [race_name]
                ).fetchall()
            else:
                # Fallback to all riders if no race specified
                rows = conn.execute(
                    "SELECT rider_url, name, nickname FROM riders WHERE name IS NOT NULL"
                ).fetchall()
        finally:
            conn.close()

    # Build normalized lookup: norm_name -> rider_url (first match wins)
    # Also keep original names and nicknames for fuzzy matching
    norm_to_url: dict[str, str] = {}
    name_to_url: dict[str, str] = {}
    all_db_names: list[str] = []
    
    for row in rows:
        url = row[0]
        name = row[1]
        nickname = row[2] if len(row) > 2 else None
        
        # Add name to lookup
        norm_name = _normalize(name)
        if norm_name not in norm_to_url:
            norm_to_url[norm_name] = url
            name_to_url[name] = url
            all_db_names.append(name)
        
        # Add nickname to lookup if it exists
        if nickname:
            norm_nickname = _normalize(nickname)
            if norm_nickname not in norm_to_url:
                norm_to_url[norm_nickname] = url
                name_to_url[nickname] = url
                all_db_names.append(nickname)

    matched_urls: list[str] = []
    not_found: list[str] = []
    seen_urls: set[str] = set()

    for name in extracted_names[:15]:
        norm_spoken = _normalize(name)
        url = None

        # 1. Exact normalized match
        if norm_spoken in norm_to_url:
            url = norm_to_url[norm_spoken]
        else:
            # 2. Try fuzzy matching with difflib
            # First try with normalized names
            norm_db_names = [_normalize(n) for n in all_db_names]
            close_matches = difflib.get_close_matches(
                norm_spoken, norm_db_names, n=1, cutoff=0.65
            )
            if close_matches:
                matched_norm = close_matches[0]
                url = norm_to_url.get(matched_norm)
            
            # 3. If no match, try token-sort for name order variants
            # (e.g., "Van der Poel Mathieu" vs "Mathieu van der Poel")
            if url is None:
                sorted_spoken = sorted(norm_spoken.split())
                for db_name in all_db_names:
                    sorted_db = sorted(_normalize(db_name).split())
                    if sorted_spoken and sorted_db:
                        # Use SequenceMatcher for token-sorted comparison
                        ratio = difflib.SequenceMatcher(
                            None, sorted_spoken, sorted_db
                        ).ratio()
                        if ratio >= 0.65:
                            url = name_to_url.get(db_name)
                            break
            
            # 4. If still no match, try substring matching as fallback
            # (for very short names like "Poel" matching "Mathieu van der Poel")
            if url is None:
                for norm_db, db_url in norm_to_url.items():
                    if norm_spoken in norm_db or norm_db in norm_spoken:
                        url = db_url
                        break

        if url and url not in seen_urls:
            matched_urls.append(url)
            seen_urls.add(url)
        else:
            not_found.append(name)
            logger.info(f"Voice: could not match rider name: {name!r}")

    return matched_urls, not_found
