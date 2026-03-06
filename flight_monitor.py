#!/usr/bin/env python3
"""
Flight Price Monitor: DTW -> HKG (One-way, May 1)
Uses the Amadeus API (free tier) to track price changes over time.

Setup:
  pip install requests
  Set environment variables:
    AMADEUS_API_KEY    - from https://developers.amadeus.com (free)
    AMADEUS_API_SECRET - from https://developers.amadeus.com (free)

Usage:
  python flight_monitor.py                   # check once
  python flight_monitor.py --watch 60        # check every 60 minutes
  python flight_monitor.py --history         # show price history
"""

import os
import json
import time
import argparse
import datetime
import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
ORIGIN      = "DTW"
DESTINATION = "HKG"
DEPART_DATE = "2026-05-01"
ADULTS      = 1
CURRENCY    = "USD"
MAX_RESULTS = 5
HISTORY_FILE = "price_history.json"

AMADEUS_AUTH_URL  = "https://test.api.amadeus.com/v1/security/oauth2/token"
AMADEUS_OFFERS_URL = "https://test.api.amadeus.com/v2/shopping/flight-offers"


# ---------------------------------------------------------------------------
# Amadeus auth
# ---------------------------------------------------------------------------

def get_access_token(api_key: str, api_secret: str) -> str:
    resp = requests.post(
        AMADEUS_AUTH_URL,
        data={
            "grant_type": "client_credentials",
            "client_id": api_key,
            "client_secret": api_secret,
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


# ---------------------------------------------------------------------------
# Flight search
# ---------------------------------------------------------------------------

def fetch_offers(token: str) -> list[dict]:
    """Return a list of simplified offer dicts sorted by price."""
    headers = {"Authorization": f"Bearer {token}"}
    params = {
        "originLocationCode":      ORIGIN,
        "destinationLocationCode": DESTINATION,
        "departureDate":           DEPART_DATE,
        "adults":                  ADULTS,
        "currencyCode":            CURRENCY,
        "nonStop":                 "false",
        "max":                     MAX_RESULTS,
    }
    resp = requests.get(AMADEUS_OFFERS_URL, headers=headers, params=params, timeout=20)
    resp.raise_for_status()
    raw_offers = resp.json().get("data", [])

    offers = []
    for o in raw_offers:
        price = float(o["price"]["grandTotal"])
        itinerary = o["itineraries"][0]
        segments  = itinerary["segments"]
        departure = segments[0]["departure"]["at"]
        arrival   = segments[-1]["arrival"]["at"]
        stops     = len(segments) - 1
        airline   = segments[0]["carrierCode"]
        duration  = itinerary["duration"]  # ISO 8601 e.g. PT14H30M

        offers.append({
            "price":     price,
            "airline":   airline,
            "departure": departure,
            "arrival":   arrival,
            "stops":     stops,
            "duration":  duration,
        })

    offers.sort(key=lambda x: x["price"])
    return offers


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

def load_history() -> list[dict]:
    if not os.path.exists(HISTORY_FILE):
        return []
    with open(HISTORY_FILE) as f:
        return json.load(f)


def save_history(history: list[dict]) -> None:
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)


def record_snapshot(offers: list[dict]) -> dict:
    snapshot = {
        "timestamp":   datetime.datetime.now().isoformat(),
        "lowest_price": offers[0]["price"] if offers else None,
        "offers":      offers,
    }
    history = load_history()
    history.append(snapshot)
    save_history(history)
    return snapshot


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

def print_offers(offers: list[dict], previous_low: float | None = None) -> None:
    print(f"\n{'='*60}")
    print(f"  DTW -> HKG  |  {DEPART_DATE}  |  {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")
    if not offers:
        print("  No offers found.")
        return

    for i, o in enumerate(offers, 1):
        tag = ""
        if i == 1 and previous_low is not None:
            diff = o["price"] - previous_low
            if diff < 0:
                tag = f"  *** PRICE DROP ${abs(diff):.2f} ***"
            elif diff > 0:
                tag = f"  (up ${diff:.2f})"
        stops_label = "nonstop" if o["stops"] == 0 else f"{o['stops']} stop(s)"
        duration    = o["duration"].replace("PT", "").replace("H", "h ").replace("M", "m").strip()
        print(
            f"  {i}. {o['airline']}  ${o['price']:.2f}  |  "
            f"{stops_label}  {duration}  |  "
            f"Dep {o['departure'][11:16]}  Arr {o['arrival'][11:16]}"
            f"{tag}"
        )
    print(f"{'='*60}\n")


def print_history() -> None:
    history = load_history()
    if not history:
        print("No price history recorded yet.")
        return
    print(f"\n{'='*60}")
    print(f"  Price History: DTW -> HKG  ({DEPART_DATE})")
    print(f"{'='*60}")
    for snap in history:
        ts    = snap["timestamp"][:19].replace("T", " ")
        low   = snap["lowest_price"]
        price = f"${low:.2f}" if low is not None else "N/A"
        print(f"  {ts}  ->  {price}")
    print(f"{'='*60}\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def check_once(api_key: str, api_secret: str) -> None:
    print(f"Fetching prices for {ORIGIN} -> {DESTINATION} on {DEPART_DATE} ...")
    token  = get_access_token(api_key, api_secret)
    offers = fetch_offers(token)

    history = load_history()
    previous_low = history[-1]["lowest_price"] if history else None

    print_offers(offers, previous_low)
    snapshot = record_snapshot(offers)

    if previous_low is not None and snapshot["lowest_price"] is not None:
        diff = snapshot["lowest_price"] - previous_low
        if diff < 0:
            print(f"ALERT: Price dropped by ${abs(diff):.2f} (now ${snapshot['lowest_price']:.2f})")
        elif diff > 0:
            print(f"Note:  Price rose by ${diff:.2f} (now ${snapshot['lowest_price']:.2f})")
        else:
            print("Price unchanged.")


def watch(api_key: str, api_secret: str, interval_minutes: int) -> None:
    print(f"Watching prices every {interval_minutes} minute(s). Press Ctrl+C to stop.\n")
    while True:
        try:
            check_once(api_key, api_secret)
        except requests.HTTPError as e:
            print(f"HTTP error: {e}")
        except Exception as e:
            print(f"Error: {e}")
        print(f"Next check in {interval_minutes} minute(s)...")
        time.sleep(interval_minutes * 60)


def main() -> None:
    parser = argparse.ArgumentParser(description="Monitor DTW->HKG flight prices (May 1).")
    parser.add_argument(
        "--watch", metavar="MINUTES", type=int,
        help="Continuously check prices every N minutes.",
    )
    parser.add_argument(
        "--history", action="store_true",
        help="Print recorded price history and exit.",
    )
    args = parser.parse_args()

    if args.history:
        print_history()
        return

    api_key    = os.environ.get("AMADEUS_API_KEY")
    api_secret = os.environ.get("AMADEUS_API_SECRET")

    if not api_key or not api_secret:
        print(
            "ERROR: Set AMADEUS_API_KEY and AMADEUS_API_SECRET environment variables.\n"
            "Get free credentials at https://developers.amadeus.com\n"
        )
        raise SystemExit(1)

    if args.watch:
        watch(api_key, api_secret, args.watch)
    else:
        check_once(api_key, api_secret)


if __name__ == "__main__":
    main()
