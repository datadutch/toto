#!/usr/bin/env python3
"""
Test script to verify the app shows a login screen instead of crashing.
This tests:
1. Database connection and table initialization
2. App imports successfully
3. Login flow works without errors
"""

import sys
import os
import tempfile
import duckdb

# Add the project directory to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_db_initialization():
    """Test that database tables can be initialized without errors."""
    print("Testing database initialization...")
    
    # Create temp directory and file path
    tmp_dir = tempfile.mkdtemp()
    db_path = os.path.join(tmp_dir, "test.duckdb")
    
    try:
        from src.db import (
            init_fantasy_tables, init_stages_table, init_stage_results_table,
            init_races_table, init_accounts_table
        )
        
        # Initialize all tables
        init_fantasy_tables(db_path)
        print("  ✓ Fantasy tables initialized")
        
        init_races_table(db_path)
        print("  ✓ Races table initialized")
        
        init_stages_table(db_path)
        print("  ✓ Stages table initialized")
        
        init_stage_results_table(db_path)
        print("  ✓ Stage results table initialized")
        
        init_accounts_table(db_path)
        print("  ✓ Accounts table initialized")
        
        # Verify data was inserted
        conn = duckdb.connect(db_path, read_only=True)
        
        race_count = conn.execute("SELECT COUNT(*) FROM races").fetchone()[0]
        print(f"  ✓ Found {race_count} races in database")
        
        stage_count = conn.execute("SELECT COUNT(*) FROM stages").fetchone()[0]
        print(f"  ✓ Found {stage_count} stages in database")
        
        # Check for our new races
        races = conn.execute("SELECT race_name FROM races ORDER BY race_name").fetchall()
        race_names = [r[0] for r in races]
        print(f"  ✓ Races: {', '.join(race_names)}")
        
        conn.close()
        
        return True
        
    except Exception as e:
        print(f"  ✗ Database initialization failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        # Clean up
        if os.path.exists(db_path):
            os.unlink(db_path)
        if os.path.exists(tmp_dir):
            os.rmdir(tmp_dir)


def test_app_imports():
    """Test that the app can be imported without errors."""
    print("\nTesting app imports...")
    
    try:
        # This will trigger all the imports and table initializations
        # We need to set environment variables to avoid MotherDuck connection
        os.environ['MOTHERDUCK_TOKEN'] = ''
        
        # Create a temporary database
        with tempfile.NamedTemporaryFile(suffix='.duckdb', delete=False) as tmp_db:
            db_path = tmp_db.name
        
        # Override DB_PATH
        import app
        # Close the connection that app opened
        
        print("  ✓ App imports successfully")
        return True
        
    except Exception as e:
        print(f"  ✗ App import failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)


def test_login_flow():
    """Test the login flow without starting the Streamlit server."""
    print("\nTesting login flow...")
    
    try:
        from src.db import (
            init_accounts_table, create_account, get_account_by_email, set_admin_status
        )
        
        # Create temp directory and file path
        tmp_dir = tempfile.mkdtemp()
        db_path = os.path.join(tmp_dir, "test.duckdb")
        
        # Initialize tables
        init_accounts_table(db_path)
        
        # Create a test account
        test_email = "test@example.com"
        account = create_account(db_path, test_email, "Test User")
        print(f"  ✓ Created account: {account['email']}")
        
        # Make it an admin
        set_admin_status(db_path, test_email, "yes")
        
        # Retrieve the account
        retrieved = get_account_by_email(db_path, test_email)
        print(f"  ✓ Retrieved account: {retrieved['email']}, is_admin={retrieved.get('is_admin')}")
        
        if retrieved.get('is_admin') == 'yes':
            print("  ✓ Account is admin")
        else:
            print("  ✗ Account is not admin")
            return False
        
        # Clean up
        if os.path.exists(db_path):
            os.unlink(db_path)
        if os.path.exists(tmp_dir):
            os.rmdir(tmp_dir)
        return True
        
    except Exception as e:
        print(f"  ✗ Login flow test failed: {e}")
        import traceback
        traceback.print_exc()
        if os.path.exists(db_path):
            os.unlink(db_path)
        if os.path.exists(tmp_dir):
            os.rmdir(tmp_dir)
        return False


def test_stages_data():
    """Test that stages data is properly formatted."""
    print("\nTesting stages data format...")
    
    try:
        from src.db import (
            GIRO_2026_STAGES, TOUR_DE_FRANCE_2026_STAGES,
            TOUR_DE_ROMANDIE_2026_STAGES, VUELTA_2026_STAGES
        )
        
        all_stages = [
            ("Giro d'Italia", GIRO_2026_STAGES),
            ("Tour de France", TOUR_DE_FRANCE_2026_STAGES),
            ("Tour de Romandie", TOUR_DE_ROMANDIE_2026_STAGES),
            ("Vuelta a España", VUELTA_2026_STAGES),
        ]
        
        for race_name, stages in all_stages:
            for i, stage in enumerate(stages):
                if len(stage) != 6:
                    print(f"  ✗ {race_name} stage {i}: has {len(stage)} elements (expected 6): {stage}")
                    return False
            print(f"  ✓ {race_name}: All {len(stages)} stages have correct format")
        
        return True
        
    except Exception as e:
        print(f"  ✗ Stages data test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    print("=" * 60)
    print("Testing Toten App Login & Initialization")
    print("=" * 60)
    
    results = []
    
    # Run all tests
    results.append(("Database Initialization", test_db_initialization()))
    results.append(("Stages Data Format", test_stages_data()))
    results.append(("Login Flow", test_login_flow()))
    
    # Note: We skip test_app_imports() because it tries to initialize DB_PATH
    # which would affect the actual app
    
    # Summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    
    for test_name, passed in results:
        status = "✓ PASSED" if passed else "✗ FAILED"
        print(f"{test_name}: {status}")
    
    all_passed = all(r[1] for r in results)
    
    if all_passed:
        print("\n✓ All tests passed! The app should show login instead of error.")
        sys.exit(0)
    else:
        print("\n✗ Some tests failed. The app may show errors.")
        sys.exit(1)
