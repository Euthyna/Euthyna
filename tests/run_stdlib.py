"""Minimal pytest-style test runner (stdlib only) — used when pytest is unavailable."""
import importlib, sys, traceback, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
mods = ["tests.test_accountant", "tests.test_verifier", "tests.test_transforms", "tests.test_adapters"]
passed = failed = 0
for mn in mods:
    m = importlib.import_module(mn)
    for name in dir(m):
        if name.startswith("test_") and callable(getattr(m, name)):
            try:
                getattr(m, name)()
                passed += 1
            except Exception:
                failed += 1
                print(f"FAIL {mn}.{name}"); traceback.print_exc(limit=3)
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
