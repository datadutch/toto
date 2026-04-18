import os
import json
import unicodedata
import logging

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
- Do not invent riders not mentioned
- Ignore any non-rider text (greetings, race names, etc.)
- Return ONLY the JSON object, no other text
"""


def _normalize(text: str) -> str:
    """Lowercase + strip diacritics so 'pogacar' matches 'Pogačar'."""
    return unicodedata.normalize("NFD", text.lower()).encode("ascii", "ignore").decode("ascii")


def extract_riders_from_text(text: str) -> list[str]:
    """
    Use Mistral to extract a list of rider names from freeform text.
    Returns a list of rider name strings (max 15).
    Raises RuntimeError if MISTRAL_API_KEY is not set.
    """
    api_key = os.getenv("MISTRAL_API_KEY")
    if not api_key:
        raise RuntimeError("MISTRAL_API_KEY is not set. Add it to your .env or Streamlit secrets.")

    try:
        from mistralai import Mistral
    except ImportError:
        raise RuntimeError("The 'mistralai' package is not installed. Run: pip install mistralai")

    client = Mistral(api_key=api_key)
    response = client.chat.complete(
        model=MISTRAL_MODEL,
        messages=[
            {"role": "system", "content": _EXTRACTION_SYSTEM_PROMPT},
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

    return result.get("riders") or []


def match_riders_to_db(extracted_names: list[str], db_path: str) -> tuple[list[str], list[str]]:
    """
    Fuzzy-match extracted rider names to rider_urls in the database.
    Uses accent-insensitive normalization (same as the participant UI search).

    Returns:
        (matched_urls, not_found_names)
        - matched_urls: list of rider_url strings (max 15, preserving order)
        - not_found_names: list of input names that could not be matched
    """
    from src.db import _connect

    conn = _connect(db_path, read_only=True)
    try:
        rows = conn.execute(
            "SELECT rider_url, name FROM riders WHERE name IS NOT NULL"
        ).fetchall()
    finally:
        conn.close()

    # Build normalized lookup: norm_name -> rider_url (first match wins)
    norm_to_url: dict[str, str] = {}
    for url, name in rows:
        norm = _normalize(name)
        if norm not in norm_to_url:
            norm_to_url[norm] = url

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
            # 2. Substring match: spoken name appears in DB name or vice versa
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
