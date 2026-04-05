"""
run_all_accounts.py
Runs the Reels pipeline for every account in config/accounts/*.json sequentially.
Usage: python tools/run_all_accounts.py
       python tools/run_all_accounts.py --count 5   (override reels per account)
"""

import os
import sys
import json
import argparse
import subprocess

sys.path.insert(0, os.path.dirname(__file__))

CONFIG_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "config", "accounts"))
SCRIPT     = os.path.join(os.path.dirname(__file__), "run_pipeline.py")


def get_accounts() -> list[str]:
    if not os.path.exists(CONFIG_DIR):
        print(f"[FATAL] No config/accounts/ directory found at {CONFIG_DIR}", flush=True)
        sys.exit(1)
    accounts = [
        os.path.splitext(f)[0]
        for f in sorted(os.listdir(CONFIG_DIR))
        if f.endswith(".json")
    ]
    if not accounts:
        print("[FATAL] No account configs found in config/accounts/", flush=True)
        sys.exit(1)
    return accounts


def run_account(account_name: str, count: int | None) -> bool:
    cmd = [sys.executable, SCRIPT, "--account", account_name]
    if count:
        cmd += ["--count", str(count)]

    print(f"\n{'#'*55}", flush=True)
    print(f"  Running account: {account_name}", flush=True)
    print(f"{'#'*55}\n", flush=True)

    result = subprocess.run(cmd, cwd=os.path.dirname(SCRIPT))
    return result.returncode == 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run pipeline for all Instagram accounts")
    parser.add_argument("--count", default=None, type=int, help="Override reels per account")
    args = parser.parse_args()

    accounts = get_accounts()
    print(f"\nFound {len(accounts)} account(s): {', '.join(accounts)}", flush=True)

    results = {}
    for account in accounts:
        ok = run_account(account, args.count)
        results[account] = "OK" if ok else "FAILED"

    print(f"\n{'='*55}", flush=True)
    print(f"  All accounts done:", flush=True)
    for account, status in results.items():
        print(f"    {account:20} {status}", flush=True)
    print(f"{'='*55}\n", flush=True)
