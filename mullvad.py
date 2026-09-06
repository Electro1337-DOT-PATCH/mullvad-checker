#!/usr/bin/env python3
"""
Check Mullvad account numbers and show remaining time.
Saves valid accounts + time left to valid.txt
"""

import requests
import time
import random
from pathlib import Path
from datetime import datetime, timezone

# Configuration
CODES_FILE = "codes.txt"
OPEN_FILE = "valid.txt"
BASE_DELAY = 0.8
TIMEOUT = 12

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36",
    "Accept": "application/json",
}


def normalize_account(code: str) -> str:
    code = code.strip().replace(" ", "").replace("-", "").replace("+", "")
    return "".join(c for c in code if c.isdigit())


def format_remaining(expiry_str: str) -> str:
    if not expiry_str:
        return "unknown"

    try:
        if expiry_str.endswith("Z"):
            expiry = datetime.fromisoformat(expiry_str.replace("Z", "+00:00"))
        else:
            expiry = datetime.fromisoformat(expiry_str)

        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)

        now = datetime.now(timezone.utc)
        delta = expiry - now

        if delta.total_seconds() <= 0:
            return "EXPIRED"

        days = delta.days
        hours, remainder = divmod(delta.seconds, 3600)
        minutes, _ = divmod(remainder, 60)

        parts = []
        if days > 0:
            parts.append(f"{days} day{'s' if days != 1 else ''}")
        if hours > 0:
            parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
        if minutes > 0 or not parts:
            parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")

        return ", ".join(parts)
    except Exception as e:
        return f"parse error → {e}"


def check_account(account_number: str) -> dict:
    result = {
        "account": account_number,
        "valid": False,
        "expiry": None,
        "remaining": None,
        "error": None,
    }

    try:
        url = f"https://api.mullvad.net/public/accounts/v1/{account_number}/"
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)

        if resp.status_code == 404:
            result["error"] = "INVALID_ACCOUNT"
            return result

        if resp.status_code != 200:
            result["error"] = f"HTTP {resp.status_code}"
            return result

        data = resp.json()
        result["valid"] = True
        result["expiry"] = data.get("expiry")
        result["remaining"] = format_remaining(result["expiry"])

    except requests.RequestException as e:
        result["error"] = f"Request error: {e}"
    except Exception as e:
        result["error"] = f"Unexpected error: {e}"

    return result


def main():
    codes_path = Path(CODES_FILE)
    if not codes_path.exists():
        print(f"[!] {CODES_FILE} not found")
        return

    codes = []
    with open(codes_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                codes.append(normalize_account(line))

    if not codes:
        print("[!] No account numbers found in codes.txt")
        return

    print(f"[*] Loaded {len(codes)} account number(s)\n")

    valid_count = 0

    for i, code in enumerate(codes, 1):
        print(f"[{i}/{len(codes)}] Checking {code} ... ", end="", flush=True)
        result = check_account(code)

        if result["valid"]:
            valid_count += 1

            # Save account + time left
            with open(OPEN_FILE, "a", encoding="utf-8") as f:
                f.write(f"{code} | {result['remaining']}\n")

            print("VALID")
            print(f"    Expiry          : {result['expiry']}")
            print(f"    Time left       : {result['remaining']}")
        else:
            print("INVALID / ERROR")
            if result["error"]:
                print(f"    → {result['error']}")

        print()
        delay = BASE_DELAY + random.uniform(0.1, 0.3)
        time.sleep(delay)

    print(f"[*] Done. {valid_count}/{len(codes)} valid account(s)")
    print(f"[*] Valid accounts saved to → {OPEN_FILE}")


if __name__ == "__main__":
    main()
