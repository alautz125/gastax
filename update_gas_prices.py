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

    The AAA homepage renders a comparison table where:
      rows    = fuel grades  (Regular, Mid-Grade, Premium, Diesel)
      columns = time periods (Current Avg., Yesterday, Week Ago, Month Ago)

    We must take the FIRST price in each grade row (= Current Avg.),
    NOT the first four prices overall (which would be all time periods for Regular).

    Returns a dict: { 'regular': X.XX, 'midgrade': X.XX, 'premium': X.XX, 'diesel': X.XX }
    Raises ValueError if parsing fails.
    """
    soup = fetch_soup(AAA_HOME_URL)

    grade_keywords = {
        "regular":  ["regular"],
        "midgrade": ["mid-grade", "midgrade", "mid grade"],
        "premium":  ["premium"],
        "diesel":   ["diesel"],
    }

    # ── Strategy A: parse every <table> on the page ───────────────────────────
    # AAA homepage table layout:
    #   Row 0 (header): ['', 'Regular', 'Mid-Grade', 'Premium', 'Diesel', 'E85']
    #   Row 1:          ['Current Avg.', '$4.52', '$5.00', '$5.37', '$5.64', ...]
    #   Row 2:          ['Yesterday Avg.', ...]  ← we do NOT want this
    #
    # Algorithm: find the header row to learn which COLUMN = which grade,
    # then find the "Current Avg." row and read each grade's column.
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue

        # Build column-index map from the header row
        col = {}
        header_cells = [c.get_text(strip=True).lower() for c in rows[0].find_all(["td", "th"])]
        for idx, h in enumerate(header_cells):
            if h == "regular":
                col["regular"] = idx
            elif "mid" in h:
                col["midgrade"] = idx
            elif h == "premium":
                col["premium"] = idx
            elif h == "diesel":
                col["diesel"] = idx

        if len(col) < 4:
            continue  # this table doesn't have the grades we need

        # Find the "Current Avg." row (first cell contains "current")
        found = {}
        for row in rows[1:]:
            cells = row.find_all(["td", "th"])
            if not cells:
                continue
            row_label = cells[0].get_text(strip=True).lower()
            if "current" in row_label:
                for grade, idx in col.items():
                    if idx < len(cells):
                        price = to_float(cells[idx].get_text(strip=True))
                        if price and 1.0 < price < 10.0:
                            found[grade] = price
                break  # only look at the Current row

        if len(found) == 4:
            log.info("  U.S. avg parsed via table header→column mapping (Current Avg. row)")
            return found

    # ── Strategy B: grade-labelled sibling elements ───────────────────────────
    # Some AAA page variants render prices as adjacent span/div pairs:
    #   <span>Regular</span><span>$4.52</span>
    found = {}
    for tag in soup.find_all(True):
        label = tag.get_text(strip=True).lower()
        for grade, keywords in grade_keywords.items():
            if grade in found:
                continue
            if any(kw == label for kw in keywords):
                # Check immediate next siblings for a price
                for sibling in tag.next_siblings:
                    price_text = (
                        sibling.get_text(strip=True)
                        if hasattr(sibling, "get_text")
                        else str(sibling)
                    )
                    price = to_float(price_text)
                    if price and 1.0 < price < 10.0:
                        found[grade] = price
                        break
    if len(found) == 4:
        log.info("  U.S. avg parsed via grade-label sibling matching")
        return found

    # ── Strategy C: look for grade labels in any element, grab the nearest price
    # from the parent container — stops at the first valid price found per grade.
    if len(found) < 4:
        for tag in soup.find_all(True):
            label = tag.get_text(strip=True).lower()
            for grade, keywords in grade_keywords.items():
                if grade in found:
                    continue
                if any(kw == label for kw in keywords):
                    parent = tag.parent
                    if parent:
                        for el in parent.find_all(True):
                            price = to_float(el.get_text(strip=True))
                            if price and 1.0 < price < 10.0:
                                found[grade] = price
                                break
        if len(found) == 4:
            log.info("  U.S. avg parsed via grade-label parent-container search")
            return found

    # ── Strategy D: last resort — scrape the state-averages page national row ──
    # The state page often has a "National" or "U.S. Average" row we can use.
    log.warning("  Homepage strategies failed — falling back to state-page national row")
    try:
        state_soup = fetch_soup(AAA_STATES_URL)
        national_keywords = ["national", "u.s.", "us average", "united states"]
        for table in state_soup.find_all("table"):
            for row in table.find_all("tr"):
                cells = row.find_all(["td", "th"])
                if not cells:
                    continue
                first = cells[0].get_text(strip=True).lower()
                if any(kw in first for kw in national_keywords):
                    prices = []
                    for cell in cells[1:]:
                        p = to_float(cell.get_text(strip=True))
                        if p and 1.0 < p < 10.0:
                            prices.append(p)
                    if len(prices) >= 4:
                        log.info("  U.S. avg from state-page national row")
                        return {
                            "regular":  prices[0],
                            "midgrade": prices[1],
                            "premium":  prices[2],
                            "diesel":   prices[3],
                        }
    except Exception as e:
        log.warning(f"  State-page fallback also failed: {e}")

    raise ValueError(
        "Could not parse U.S. average from AAA homepage or state page. "
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
