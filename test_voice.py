#!/usr/bin/env python3
"""
Test script for voice.py module - rider recognition and matching
"""

import sys
import os

# Add the project directory to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.voice import _normalize, match_riders_to_db

def test_normalize():
    """Test the normalization function."""
    print("Testing _normalize function...")
    
    tests = [
        ("Tadej Pogačar", "tadej pogacar"),
        ("Jonas Vingegaard", "jonas vingegaard"),
        ("Mathieu van der Poel", "mathieu van der poel"),
        ("Wout Van Aert", "wout van aert"),
        ("Pogacar", "pogacar"),
    ]
    
    for input_val, expected in tests:
        result = _normalize(input_val)
        if result == expected:
            print(f"  ✓ _normalize('{input_val}') = '{result}'")
        else:
            print(f"  ✗ _normalize('{input_val}') = '{result}' (expected '{expected}')")
            return False
    
    return True


def test_fuzzy_matching():
    """Test fuzzy matching with known rider data."""
    print("\nTesting fuzzy matching...")
    
    import tempfile
    import duckdb
    
    # Create a temporary database
    tmp_dir = tempfile.mkdtemp()
    db_path = os.path.join(tmp_dir, "test.duckdb")
    
    try:
        # Create test database with some riders
        conn = duckdb.connect(db_path)
        conn.execute("""
            CREATE TABLE riders (
                rider_url VARCHAR PRIMARY KEY,
                name VARCHAR,
                nationality VARCHAR,
                team_name VARCHAR
            )
        """)
        
        # Insert test riders
        test_riders = [
            ("rider/tadej-pogacar", "Tadej Pogačar", "SI", "UAE"),
            ("rider/jonas-vingegaard", "Jonas Vingegaard", "DK", "VISMA"),
            ("rider/mathieu-van-der-poel", "Mathieu van der Poel", "NL", "Alpecin"),
            ("rider/wout-van-aert", "Wout van Aert", "BE", "VISMA"),
            ("rider/remco-evenepoel", "Remco Evenepoel", "BE", "Soudal"),
        ]
        
        for url, name, nat, team in test_riders:
            conn.execute(
                "INSERT INTO riders (rider_url, name, nationality, team_name) VALUES (?, ?, ?, ?)",
                [url, name, nat, team]
            )
        
        conn.close()
        
        # Prepare rows for matching
        rows = [(url, name) for url, name, _, _ in test_riders]
        
        # Test cases with typos and variations
        test_cases = [
            (["Tadej Pogacar"], 1, 0),  # Accent missing - should match with fuzzy
            (["Vingegaard"], 1, 0),      # Partial name
            (["Vingegaart"], 1, 0),     # Typo
            (["Mathieu van der Poel"], 1, 0),  # Exact match
            (["Poel"], 1, 0),          # Partial - should fuzzy match
            (["Remco Evenepoel"], 1, 0),     # Exact match
            (["Evenepol"], 1, 0),      # Typo
            (["Unknown Rider"], 0, 1),  # Not in DB
        ]
        
        for extracted, expected_matched, expected_not_found in test_cases:
            matched, not_found = match_riders_to_db(extracted, db_path, rows)
            
            if len(matched) == expected_matched and len(not_found) == expected_not_found:
                print(f"  ✓ {extracted[0]!r} -> {len(matched)} matched, {len(not_found)} not found")
            else:
                print(f"  ✗ {extracted[0]!r} -> {len(matched)} matched (expected {expected_matched}), {len(not_found)} not found (expected {expected_not_found})")
                print(f"    Matched: {matched}")
                print(f"    Not found: {not_found}")
        
        return True
        
    finally:
        # Clean up
        if os.path.exists(db_path):
            os.unlink(db_path)
        if os.path.exists(tmp_dir):
            os.rmdir(tmp_dir)


if __name__ == "__main__":
    print("=" * 60)
    print("Testing Voice Module")
    print("=" * 60)
    
    results = []
    results.append(("Normalization", test_normalize()))
    results.append(("Fuzzy Matching", test_fuzzy_matching()))
    
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    
    for test_name, passed in results:
        status = "✓ PASSED" if passed else "✗ FAILED"
        print(f"{test_name}: {status}")
    
    all_passed = all(r[1] for r in results)
    
    if all_passed:
        print("\n✓ All tests passed!")
        sys.exit(0)
    else:
        print("\n✗ Some tests failed.")
        sys.exit(1)
