import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.unified_command_router import get_router

router = get_router()

test_cases = [
    ("open whatsapp on my phone", True, "verified_foreground"),
    ("open youtube on my phone", True, "verified_foreground"),
    ("open maps on my phone", True, "verified_foreground"),
    ("open amazon on my phone", True, "verified_foreground"),
    ("open calendar on my phone", True, "verified_foreground"),
    ("open camera on my phone", True, "verified_foreground"),
    ("open gallery on my phone", True, "verified_foreground"),
    ("open settings on my phone", True, "verified_foreground"),
    ("open prime video on my phone", True, "verified_foreground"),
    ("open non_existent_application_xyz on my phone", False, "app_not_installed"),
]

print("=" * 80)
print("APP LAUNCH REGRESSION & VERIFICATION SUITE (LIVE REDMI NOTE 12 5G)")
print("=" * 80)

passed = 0
failed = 0

for cmd, expected_succ, expected_status in test_cases:
    time.sleep(0.5)
    t0 = time.time()
    res = router.execute_single_action(cmd, user_id=1)
    duration = time.time() - t0
    
    actual_succ = res.get("success", res.get("status") not in ("error", "failed", "app_not_installed"))
    actual_status = res.get("status")
    response_msg = res.get("response") or res.get("message")
    
    succ_match = (actual_succ == expected_succ)
    status_match = (actual_status == expected_status)
    
    is_pass = succ_match and status_match
    if is_pass:
        passed += 1
        mark = "[PASS]"
    else:
        failed += 1
        mark = "[FAIL]"
        
    print(f"{mark} CMD: '{cmd}'")
    print(f"       Duration: {duration:.2f}s | Status: {actual_status} | Success: {actual_succ}")
    print(f"       Response: {response_msg}")
    print("-" * 80)

print(f"\nRESULTS: Passed={passed}/{len(test_cases)}, Failed={failed}/{len(test_cases)}")
if failed == 0:
    print("[ALL TESTS PASSED WITH 100% SUCCESS]")
