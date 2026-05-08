#!/usr/bin/env python3
"""
update_gas_prices.py
────────────────────
Fetches current U.S. and state gas prices from AAA and splices them into
gas-tax-calculator.html between two sentinel comments.

Sources:
  U.S. average  →  https://gasprices.aaa.com/             (Current Avg. display)
  State prices  →  https://gasprices.aaa.com/state-gas-price-averages/

Usage:
  python3 update_gas_prices.py

Requirements:
  pip install requests beautifulsoup4 lxml
"""

import os
import re
import sys
import logging
import datetime
from pathlib import Path

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    sys.exit("Missing dependencies — run: pip install requests beautifulsoup4 lxml")

# ── Paths ────────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent
HTML_FILE  = SCRIPT_DIR / "gas-tax-calculator.html"
IN_CI      = os.environ.get("CI") == "true"
LOG_FILE   = Path("/tmp/update_gas_prices.log") if IN_CI else SCRIPT_DIR / "update_gas_prices.log"

# ── URLs ─────────────────────────────────────────────────────────────────────
AAA_HOME_URL   = "https://gasprices.aaa.com/"
AAA_STATES_URL = "https://gasprices.aaa.com/state-gas-price-averages/"

# ── Sentinel comments that wrap the data block in the HTML ───────────────────
SENTINEL_START = "// ==PRICES_TODAY_START=="
SENTINEL_END   = "// ==PRICES_TODAY_END=="

# ── HTTP headers ─────────────────────────────────────────────────────────────
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# ── State name mapping: AAA label → HTML data key ────────────────────────────
STATE_MAP = {
    "Alabama":              "Alabama",
    "Alaska":               "Alaska",
    "Arizona":              "Arizona",
    "Arkansas":             "Arkansas",
    "California":           "California",
    "Colorado":             "Colorado",
    "Connecticut":          "Connecticut",
    "Delaware":             "Delaware",
    "District Of Columbia": "District of Columbia",
    "District of Columbia": "District of Columbia",
    "Florida":              "Florida",
    "Georgia":              "Georgia",
    "Hawaii":               "Hawaii",
    "Idaho":                "Idaho",
    "Illinois":             "Illinois",
    "Indiana":              "Indiana",
    "Iowa":                 "Iowa",
    "Kansas":               "Kansas",
    "Kentucky":             "Kentucky",
    "Louisiana":            "Louisiana",
    "Maine":                "Maine",
    "Maryland":             "Maryland",
    "Massachusetts":        "Massachusetts",
    "Michigan":             "Michigan",
    "Minnesota":            "Minnesota",
    "Mississippi":          "Mississippi",
    "Missouri":             "Missouri",
    "Montana":              "Montana",
    "Nebraska":             "Nebraska",
    "Nevada":               "Nevada",
    "New Hampshire":        "New Hampshire",
    "New Jersey":           "New Jersey",
    "New Mexico":           "New Mexico",
    "New York":             "New York",
    "North Carolina":       "North Carolina",
    "North Dakota":         "North Dakota",
    "Ohio":                 "Ohio",
    "Oklahoma":             "Oklahoma",
    "Oregon":               "Oregon",
    "Pennsylvania":         "Pennsylvania",
    "Rhode Island":         "Rhode Island",
    "South Carolina":       "South Carolina",
    "South Dakota":         "South Dakota",
    "Tennessee":            "Tennessee",
    "Texas":                "Texas",
    "Utah":                 "Utah",
    "Vermont":              "Vermont",
    "Virginia":             "Virginia",
    "Washington":           "Washington",
    "West Virginia":        "West Virginia",
    "Wisconsin":            "Wisconsin",
    "Wyoming":              "Wyoming",
}

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def fetch_soup(url: str) -> BeautifulSoup:
    """GET a URL and return a BeautifulSoup parse tree."""
    log.info(f"Fetching {url}")
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    log.info(f"  HTTP {resp.status_code}  ({len(resp.content):,} bytes)")
    return BeautifulSoup(resp.text, "lxml")


def to_float(raw: str) -> float | None:
    """Parse '$4.56' (or '4.56') to float, return None on failure."""
    try:
        return round(float(str(raw).strip().lstrip("$").replace(",", "")), 2)
    except (ValueError, TypeError):
        return None


# ── Fetchers ──────────────────────────────────────────────────────────────────

def fetch_us_average() -> dict:
    """
    Scrape the U.S. national average from https://gasprices.aaa.com/
    (the 'Current Avg.' display on the homepage).

    Returns a dict: { 'regular': X.XX, 'midgrade': X.XX, 'premium': X.XX, 'diesel': X.XX }
    Raises ValueError if parsing fails.
    """
    soup = fetch_soup(AAA_HOME_URL)

    # The homepage shows four grade prices in a prominent block.
    # Try several DOM patterns in order of confidence.

    # Strategy A: look for a container whose text includes "Current Avg"
    # and extract the four price figures inside it.
    for candidate in soup.find_all(True):
        text = candidate.get_text(" ", strip=True)
        if "current avg" not in text.lower():
            continue
        # Extract all dollar amounts from this element
        amounts = re.findall(r'\$\s*(\d+\.\d+)', text)
        if len(amounts) >= 4:
            log.info("  U.S. avg parsed via 'Current Avg' container")
            return {
                "regular":  float(amounts[0]),
                "midgrade": float(amounts[1]),
                "premium":  float(amounts[2]),
                "diesel":   float(amounts[3]),
            }

    # Strategy B: find all dollar amounts near grade-name labels
    # (e.g. spans/divs labelled "Regular", "Mid-Grade", "Premium", "Diesel")
    grade_labels = {
        "regular":  ["regular"],
        "midgrade": ["mid-grade", "midgrade", "mid grade"],
        "premium":  ["premium"],
        "diesel":   ["diesel"],
    }
    found = {}
    for tag in soup.find_all(True):
        label = tag.get_text(strip=True).lower()
        for grade, keywords in grade_labels.items():
            if any(kw == label for kw in keywords):
                # Look for a price in a sibling or nearby element
                for sibling in list(tag.next_siblings) + list(tag.parent.find_all(True)):
                    price_text = sibling.get_text(strip=True) if hasattr(sibling, 'get_text') else str(sibling)
                    price = to_float(price_text)
                    if price and 1.0 < price < 10.0:
                        found[grade] = price
                        break
        if len(found) == 4:
            break

    if len(found) == 4:
        log.info("  U.S. avg parsed via grade-label matching")
        return found

    # Strategy C: find all page prices and assume the first four are
    # Regular, Mid-Grade, Premium, Diesel (AAA's standard display order)
    all_prices = [
        float(m) for m in re.findall(r'\$\s*(\d+\.\d{2})', soup.get_text())
        if 1.0 < float(m) < 10.0
    ]
    if len(all_prices) >= 4:
        log.warning("  U.S. avg: falling back to first-four-prices heuristic — verify manually")
        return {
            "regular":  all_prices[0],
            "midgrade": all_prices[1],
            "premium":  all_prices[2],
            "diesel":   all_prices[3],
        }

    raise ValueError(
        "Could not parse U.S. average from AAA homepage. "
        "The page structure may have changed."
    )


def fetch_state_prices() -> dict:
    """
    Scrape state-by-state prices from the AAA state averages page.

    Returns a dict keyed by HTML state name:
      { 'Alabama': {'regular': X, 'midgrade': X, 'premium': X, 'diesel': X}, ... }
    Raises ValueError if fewer than 40 states are found.
    """
    soup  = fetch_soup(AAA_STATES_URL)
    prices = {}

    # Strategy A: standard HTML <table>
    for table in soup.find_all("table"):
        header_row = table.find("tr")
        if not header_row:
            continue

        ths = [th.get_text(strip=True).lower() for th in header_row.find_all(["th", "td"])]
        col = {}
        for i, h in enumerate(ths):
            if "state"   in h or "region" in h: col["state"]   = i
            elif "regular"  in h:               col["regular"]  = i
            elif "mid"      in h:               col["midgrade"] = i
            elif "premium"  in h:               col["premium"]  = i
            elif "diesel"   in h:               col["diesel"]   = i

        if "state" not in col or "regular" not in col:
            continue

        for row in table.find_all("tr")[1:]:
            cells = row.find_all(["td", "th"])
            if len(cells) < max(col.values()) + 1:
                continue

            raw_name = cells[col["state"]].get_text(strip=True)
            html_key = STATE_MAP.get(raw_name) or STATE_MAP.get(raw_name.title())
            if not html_key:
                continue

            entry = {}
            for field in ("regular", "midgrade", "premium", "diesel"):
                if field in col:
                    v = to_float(cells[col[field]].get_text(strip=True))
                    if v is not None:
                        entry[field] = v

            if len(entry) >= 2:
                prices[html_key] = entry

        if prices:
            log.info(f"  State prices parsed via <table> ({len(prices)} states)")
            break

    # Strategy B: data attributes on arbitrary elements
    if not prices:
        for el in soup.find_all(attrs={"data-state": True}):
            raw_name = el.get("data-state", "").strip()
            html_key = STATE_MAP.get(raw_name) or STATE_MAP.get(raw_name.title())
            if not html_key:
                continue
            entry = {}
            for field, attr in [("regular", "data-regular"), ("midgrade", "data-midgrade"),
                                 ("premium", "data-premium"), ("diesel", "data-diesel")]:
                v = to_float(el.get(attr, ""))
                if v is not None:
                    entry[field] = v
            if entry:
                prices[html_key] = entry
        if prices:
            log.info(f"  State prices parsed via data attributes ({len(prices)} states)")

    if len(prices) < 40:
        raise ValueError(
            f"Only {len(prices)} states parsed — expected 50+. "
            "The AAA page structure may have changed."
        )

    return prices


# ── HTML updater ──────────────────────────────────────────────────────────────

def build_js_block(us_avg: dict, state_prices: dict, as_of: str) -> str:
    """Render the JS sentinel block to splice into the HTML."""

    def row(key: str, p: dict) -> str:
        pad = f"'{key}':".ljust(28)
        r = p.get("regular",  0)
        m = p.get("midgrade", 0)
        pr = p.get("premium", 0)
        d = p.get("diesel",   0)
        return f"  {pad}{{ regular:{r:.2f}, midgrade:{m:.2f}, premium:{pr:.2f}, diesel:{d:.2f} }},"

    lines = [
        SENTINEL_START,
        f'const PRICES_AS_OF = "{as_of}";',
        "const PRICES_TODAY = {",
        row("US Average", us_avg),
    ]
    for key in sorted(state_prices):
        lines.append(row(key, state_prices[key]))
    lines += ["};", SENTINEL_END]
    return "\n".join(lines)


def update_html(new_block: str) -> bool:
    """
    Splice new_block into the HTML file between the sentinel comments.
    Returns True if the file was changed, False if prices were identical.
    """
    if not HTML_FILE.exists():
        raise FileNotFoundError(f"HTML file not found: {HTML_FILE}")

    html    = HTML_FILE.read_text(encoding="utf-8")
    pattern = re.compile(
        re.escape(SENTINEL_START) + r".*?" + re.escape(SENTINEL_END),
        re.DOTALL,
    )
    if not pattern.search(html):
        raise ValueError(
            f"Sentinel markers not found in {HTML_FILE.name}. "
            f"The file must contain:\n  {SENTINEL_START}\n  ...\n  {SENTINEL_END}"
        )

    new_html, count = pattern.subn(new_block, html)
    if count != 1:
        raise ValueError(f"Expected 1 sentinel block, found {count}")

    if new_html == html:
        log.info("  Prices unchanged — HTML not rewritten.")
        return False

    HTML_FILE.write_text(new_html, encoding="utf-8")
    log.info(f"  Wrote updated HTML → {HTML_FILE.name}")
    return True


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    log.info("=" * 60)
    log.info(f"Gas price updater  (CI={IN_CI})")

    # 1. Fetch U.S. average from homepage
    try:
        us_avg = fetch_us_average()
        log.info(
            f"  U.S. avg → regular ${us_avg['regular']:.2f}  "
            f"mid ${us_avg['midgrade']:.2f}  "
            f"premium ${us_avg['premium']:.2f}  "
            f"diesel ${us_avg['diesel']:.2f}"
        )
    except Exception as e:
        log.error(f"Failed to fetch U.S. average: {e}")
        sys.exit(1)

    # 2. Fetch state prices
    try:
        state_prices = fetch_state_prices()
        log.info(f"  {len(state_prices)} states fetched.")
    except Exception as e:
        log.error(f"Failed to fetch state prices: {e}")
        sys.exit(1)

    # 3. Build date string and JS block
    as_of    = datetime.date.today().strftime("%B %-d, %Y")
    js_block = build_js_block(us_avg, state_prices, as_of)

    # 4. Splice into HTML
    try:
        changed = update_html(js_block)
    except Exception as e:
        log.error(f"Failed to update HTML: {e}")
        sys.exit(1)

    if changed:
        log.info(f"Update complete — {as_of}")
    log.info("Done.")


if __name__ == "__main__":
    main()
