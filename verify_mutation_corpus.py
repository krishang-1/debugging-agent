import sys
sys.path.insert(0, ".")
from benchmark.mutation_loader import load_mutation_bugs
from benchmark.mutation_harness import apply_bug, revert_bug, run_test

bugs = load_mutation_bugs()
for bug in bugs:
    apply_bug(bug)
    buggy_passed = run_test(bug)
    revert_bug(bug)
    fixed_passed = run_test(bug)
    status = "OK" if (not buggy_passed and fixed_passed) else "MISMATCH"
    print(f"{bug.bug_id}: buggy_passed={buggy_passed} fixed_passed={fixed_passed} -> {status}")
