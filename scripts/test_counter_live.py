"""
PSG CAS CONNECT — Live Supabase Counter Concurrency Verification Script

INSTRUCTIONS:
1. Ensure .env contains valid SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY.
2. Run via terminal: python scripts/test_counter_live.py
3. This script creates zero production side-effects (operates exclusively on department code 'ZZTEST').
"""

import os
import sys
import concurrent.futures
from dotenv import load_dotenv
from supabase import create_client

# Load environment variables from .env
load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    print("[ERROR] SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY missing from environment/.env")
    sys.exit(1)

sb_admin = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

def generate_counter_call(idx):
    """Invoke generate_application_number RPC with ZZTEST department code."""
    try:
        res = sb_admin.rpc("generate_application_number", {"p_department": "ZZTEST"}).execute()
        return res.data
    except Exception as e:
        return f"ERROR: {e}"

def main():
    print("=" * 75)
    print("  PSG CAS CONNECT — LIVE COUNTER CONCURRENCY TEST (20 Parallel Threads)")
    print("=" * 75)

    num_threads = 20
    results = []

    print(f"[*] Launching {num_threads} parallel RPC calls for department 'ZZTEST'...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(generate_counter_call, i) for i in range(1, num_threads + 1)]
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())

    print("[*] Received response tokens:")
    for r in sorted(results):
        print(f"    - {r}")

    # Verification: check format ZZTEST/001 to ZZTEST/020
    expected_set = {f"ZZTEST/{i:03d}" for i in range(1, 21)}
    actual_set = set(results)

    has_errors = any("ERROR" in str(r) for r in results)
    if has_errors:
        print("\n[FAIL] RPC returned errors during concurrent execution!")
    elif actual_set == expected_set and len(results) == 20:
        print("\n[SUCCESS] All 20 threads generated unique sequential reference IDs without gaps or duplicates!")
    else:
        print(f"\n[FAIL] Result mismatch!\nExpected: {sorted(list(expected_set))}\nActual: {sorted(results)}")

    # Cleanup: remove ZZTEST counter row from department_counters
    print("\n[*] Cleaning up ZZTEST test row from department_counters table...")
    try:
        sb_admin.table("department_counters").delete().eq("department_code", "ZZTEST").execute()
        print("[SUCCESS] Cleanup complete. Database restored to original state.")
    except Exception as e:
        print(f"[WARN] Failed to delete ZZTEST cleanup row: {e}")

if __name__ == "__main__":
    main()
