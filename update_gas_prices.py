#!/usr/bin/env python3
"""
update_gas_prices.py
────────────────────
Fetches current state gas prices from AAA and updates the data block
inside gas-tax-calculator.html.

Run manually:     python3 update_gas_prices.py
GitHub Actions:   runs automatically via .github/workflows/update-gas-prices.yml

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
    print("Missing dependencies. Install with:")
    print("    pip install requests beautifulsoup4 lxml")
    sys.exit(1)

# ── Config ────────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent
HTML_FILE  = SCRIPT_DIR / "gas-tax-calculator.html"

# Write logs to /tmp when running in CI (keeps repo clean), otherwise alongside script
IN_CI    = os.environ.get("CI") == "true"
LOG_FILE = Path("/tmp/update_gas_prices.log") if IN_CI else SCRIPT_DIR / "update_gas_prices.log"

AAA_URL        = "https://gasprices.aaa.com/state-gas-price-averages/"
SENTINEL_START = "// ==BPC_PRICES_TODAY_START=="
SENTINEL_END   = "// ==BPC_PRICES_TODAY_END=="

# ── State name mapping (AAA label → HTML data key) ───────────────────────────
STATE_MAP = {
    "National":               "US Average",
    "U.S. Average":           "US Average",
    "Alabama":                "Alabama",
    "Alaska":                 "Alaska",
    "Arizona":                "Arizona",
    "Arkansas":               "Arkansas",
    "California":             "California",
    "Colorado":               "Colorado",
    "Connecticut":            "Connecticut",
    "Delaware":               "Delaware",
    "District Of Columbia":   "District of Columbia",
    "District of Columbia":   "District of Columbia",
    "Florida":                "Florida",
    "Georgia":                "Georgia",
    "Hawaii":                 "Hawaii",
    "Idaho":                  "Idaho",
    "Illinois":               "Illinois",
    "Indiana":                "Indiana",
    "Iowa":                   "Iowa",
    "Kansas":                 "Kansas",
    "Kentucky":               "Kentucky",
    "Louisiana":              "Louisiana",
    "Maine":                  "Maine",
    "Maryland":               "Maryland",
    "Massachusetts":          "Massachusetts",
    "Michigan":               "Michigan",
    "Minnesota":              "Minnesota",
    "Mississippi":            "Mississippi",
    "Missouri":               "Missouri",
    "Montana":                "Montana",
    "Nebraska":               "Nebraska",
    "Nevada":                 "Nevada",
    "New Hampshire":          "New Hampshire",
    "New Jersey":             "New Jersey",
    "New Mexico":             "New Mexico",
    "New York":               "New York",
    "North Carolina":         "North Carolina",
    "North Dakota":           "North Dakota",
    "Ohio":                   "Ohio",
    "Oklahoma":               "Oklahoma",
    "Oregon":                 "Oregon",
    "Pennsylvania":           "Pennsylvania",
    "Rhode Island":           "Rhode Island",
    "South Carolina":         "South Carolina",
    "South Dakota":           "South Dakota",
    "Tennessee":              "Tennessee",
    "Texas":                  "Texas",
    "Utah":                   "Utah",
    "Vermont":                "Vermont",
    "Virginia":               "Virginia",
    "Washington":             "Washington",
    "West Virginia":          "West Virginia",
    "Wisconsin":              "Wisconsin",
    "Wyoming":                "Wyoming",
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


def fetch_aaa_prices() -> dict:
    """Download AAA page and parse all state prices into a dict."""
    log.info(f"Fetching {AAA_URL}")
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    resp = requests.get(AAA_URL, headers=headers, timeout=20)
    resp.raise_for_status()
    log.info(f"  HTTP {resp.status_code}  ({len(resp.content):,} bytes)")

    soup   = BeautifulSoup(resp.text, "lxml")
    prices = {}

    def parse_price(raw: str):
        try:
            return round(float(raw.strip().lstrip("$").replace(",", "")), 2)
        except (ValueError, AttributeError):
            return None

    # Strategy 1 — standard HTML <table>
    for table in soup.find_all("table"):
        header_row = table.find("tr")
        if not header_row:
            continue
        ths = [th.get_text(strip=True).lower() for th in header_row.find_all(["th", "td"])]

        col = {}
        for i, h in enumerate(ths):
            if "state" in h or "region" in h: col["state"]   = i
            elif "regular"  in h:             col["regular"]  = i
            elif "mid"      in h:             col["midgrade"] = i
            elif "premium"  in h:             col["premium"]  = i
            elif "diesel"   in h:             col["diesel"]   = i

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
                    v = parse_price(cells[col[field]].get_text(strip=True))
                    if v is not None:
                        entry[field] = v
            if len(entry) >= 2:
                prices[html_key] = entry

        if prices:
            log.info(f"  Parsed {len(prices)} states via <table>")
            return prices

    # Strategy 2 — data attributes on arbitrary elements
    for el in soup.find_all(attrs={"data-state": True}):
        raw_name = el.get("data-state", "").strip()
        html_key = STATE_MAP.get(raw_name) or STATE_MAP.get(raw_name.title())
        if not html_key:
            continue
        entry = {}
        for field, attr in [("regular","data-regular"),("midgrade","data-midgrade"),
                             ("premium","data-premium"),("diesel","data-diesel")]:
            v = parse_price(el.get(attr, ""))
            if v is not None:
                entry[field] = v
        if entry:
            prices[html_key] = entry

    if prices:
        log.info(f"  Parsed {len(prices)} states via data attributes")
        return prices

    # Strategy 3 — inline JSON/script blocks
    for script in soup.find_all("script"):
        text = script.string or ""
        if "regular" not in text.lower():
            continue
        matches = re.findall(
            r'"state"\s*:\s*"([^"]+)".*?"regular"\s*:\s*"?([\d.]+)"?'
            r'.*?"mid[_-]?grade"\s*:\s*"?([\d.]+)"?'
            r'.*?"premium"\s*:\s*"?([\d.]+)"?'
            r'.*?"diesel"\s*:\s*"?([\d.]+)"?',
            text, re.IGNORECASE | re.DOTALL
        )
        for m in matches:
            html_key = STATE_MAP.get(m[0].strip()) or STATE_MAP.get(m[0].strip().title())
            if html_key:
                prices[html_key] = {
                    "regular": float(m[1]), "midgrade": float(m[2]),
                    "premium": float(m[3]), "diesel":   float(m[4]),
                }

    if prices:
        log.info(f"  Parsed {len(prices)} states via inline script")
        return prices

    raise ValueError(
        "Could not parse prices from AAA page — structure may have changed. "
        "Check the page HTML manually."
    )


def build_js_block(prices: dict, as_of: str) -> str:
    """Render the JS sentinel block that gets spliced into the HTML."""
    lines = [
        SENTINEL_START,
        f'const PRICES_AS_OF = "{as_of}";',
        "const PRICES_TODAY = {",
    ]
    ordered = ["US Average"] + sorted(k for k in prices if k != "US Average")
    for key in ordered:
        if key not in prices:
            continue
        p = prices[key]
        pad = f"'{key}':".ljust(28)
        lines.append(
            f"  {pad}{{ regular:{p.get('regular',0):.2f}, midgrade:{p.get('midgrade',0):.2f}, "
            f"premium:{p.get('premium',0):.2f}, diesel:{p.get('diesel',0):.2f} }},"
        )
    lines += ["};", SENTINEL_END]
    return "\n".join(lines)


def update_html(new_block: str) -> bool:
    """Splice the new data block into the HTML. Returns True if file changed."""
    if not HTML_FILE.exists():
        raise FileNotFoundError(f"HTML file not found: {HTML_FILE}")

    html    = HTML_FILE.read_text(encoding="utf-8")
    pattern = re.compile(
        re.escape(SENTINEL_START) + r".*?" + re.escape(SENTINEL_END), re.DOTALL
    )
    if not pattern.search(html):
        raise ValueError(f"Sentinel markers not found in {HTML_FILE}")

    new_html, n = pattern.subn(new_block, html)
    if n != 1:
        raise ValueError(f"Expected exactly 1 sentinel block, found {n}")
    if new_html == html:
        log.info("  Prices unchanged — HTML not rewritten.")
        return False

    HTML_FILE.write_text(new_html, encoding="utf-8")
    log.info(f"  Wrote updated HTML → {HTML_FILE.name}")
    return True


def main():
    log.info("=" * 60)
    log.info(f"Gas price updater  (CI={IN_CI})")

    try:
        prices = fetch_aaa_prices()
    except Exception as e:
        log.error(f"Fetch failed: {e}")
        sys.exit(1)

    if len(prices) < 40:
        log.warning(f"Only {len(prices)} states parsed — expected 51. HTML not updated.")
        sys.exit(1)

    # Format date: "May 8, 2026"
    as_of    = datetime.date.today().strftime("%B %-d, %Y")
    js_block = build_js_block(prices, as_of)

    try:
        changed = update_html(js_block)
    except Exception as e:
        log.error(f"HTML update failed: {e}")
        sys.exit(1)

    if changed:
        us = prices.get("US Average", {})
        log.info(f"Update complete ({as_of}) — U.S. avg regular: ${us.get('regular','?'):.2f}")
    log.info("Done.")


if __name__ == "__main__":
    main()
