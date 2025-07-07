import os
import re
import requests
import traceback
from flask import Flask, request, jsonify
from bs4 import BeautifulSoup
from collections import defaultdict
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

app = Flask(__name__)

# Load ScraperAPI key from environment
SCRAPER_API_KEY = os.getenv("SCRAPER_API_KEY")
if not SCRAPER_API_KEY:
    raise RuntimeError("Please set the SCRAPER_API_KEY environment variable")

API_URL = "http://api.scraperapi.com/"

# Create a session with retry/backoff
session = requests.Session()
retry_strategy = Retry(
    total=3,
    backoff_factor=1,
    status_forcelist=[500, 502, 503, 504],
    allowed_methods=["GET"]
)
adapter = HTTPAdapter(max_retries=retry_strategy)
session.mount("http://", adapter)
session.mount("https://", adapter)


def fetch_html_via_scraperapi(target_url: str, use_js: bool = True) -> str:
    """
    Fetch the target URL via ScraperAPI with optional JS rendering.
    To disable JS rendering and get raw HTML, call with use_js=False.
    """
    params = {
        "api_key": SCRAPER_API_KEY,
        "url": target_url,
    }
    # Include render parameter only if JS rendering is required
    if use_js:
        params["render"] = "true"

    resp = session.get(API_URL, params=params, timeout=60)
    if resp.status_code != 200:
        print(f"ScraperAPI returned {resp.status_code}", resp.text)
        resp.raise_for_status()
    return resp.text


def parse_profile(target_url: str) -> dict:
    """
    Parses the player profile and returns structured data.
    """
    # Fetch raw HTML without JS by setting use_js=False, or keep True for JS-rendered content
    html = fetch_html_via_scraperapi(target_url, use_js=True)
    soup = BeautifulSoup(html, "html.parser")

    # 1) Player name
    name_tag = soup.select_one("h1.player-profile-name")
    player_name = name_tag.get_text(strip=True) if name_tag else ""

    # 2) Offline tournament rows
    rows = soup.select("table.table--player-results tbody tr")

    total_tournaments = 0
    buyins = defaultdict(float)
    prizes = defaultdict(float)
    total_roi = 0.0
    year_data = defaultdict(lambda: {"tournaments": 0, "roi_sum": 0.0})

    for tr in rows:
        text = tr.get_text()
        if "Online" in text:
            continue

        # Buy-in parsing
        event_link = tr.select_one("td.event_name a[href*='event.php']")
        if not event_link:
            continue
        event_text = event_link.get_text(strip=True)
        match_buy = re.search(r"([^\d\s,]+)\s*([\d,]+(?:\s*\+\s*[\d,]+)*)", event_text)
        if not match_buy:
            continue
        currency = match_buy.group(1)
        amounts = [int(x.replace(',', '')) for x in match_buy.group(2).split('+')]
        buyin_amount = sum(amounts)
        buyins[currency] += buyin_amount

        # Prize parsing (last currency cell)
        prize_cells = tr.select("td.currency")
        prize_amount = 0
        if prize_cells:
            last = prize_cells[-1].get_text(strip=True)
            match_pr = re.search(rf"({re.escape(currency)})\s*([\d,]+)", last)
            if match_pr:
                prize_amount = int(match_pr.group(2).replace(',', ''))
                prizes[currency] += prize_amount

        # ROI and yearly grouping
        if buyin_amount > 0:
            roi = prize_amount / buyin_amount
            total_roi += roi
            date_cell = tr.select_one("td.date")
            if date_cell:
                y_match = re.search(r"(\d{4})", date_cell.get_text())
                if y_match:
                    year = int(y_match.group(1))
                    year_data[year]["tournaments"] += 1
                    year_data[year]["roi_sum"] += roi
        total_tournaments += 1

    # Compute overall average ROI
    average_roi = round(total_roi / total_tournaments, 4) if total_tournaments else 0.0

    # Build currency text
    def build_currency_text(d):
        return "\n".join(f"{cur} {amt:,.0f}" for cur, amt in sorted(d.items()))

    totalBuyinsText = build_currency_text(buyins)
    totalPrizesText = build_currency_text(prizes)

    # Build yearlyStatsText
    yearly_lines = []
    for yr in sorted(year_data.keys(), reverse=True):
        info = year_data[yr]
        avg_year = round(info["roi_sum"] / info["tournaments"], 4) if info["tournaments"] else 0.0
        yearly_lines.append(f"{yr}: {info['tournaments']} tournaments, avg ROI {avg_year}")
    yearlyStatsText = "\n".join(yearly_lines)

    return {
        "player": player_name,
        "totalTournaments": total_tournaments,
        "totalBuyinsText": totalBuyinsText,
        "totalPrizesText": totalPrizesText,
        "averageROIByCash": average_roi,
        "yearlyStatsText": yearlyStatsText
    }

@app.route("/", methods=["POST"])
def main():
    payload = request.get_json(force=True) or {}
    url = payload.get("url")
    if not url:
        return jsonify({"error": "Missing 'url' parameter"}), 400
    try:
        result = parse_profile(url)
        return jsonify(result), 200
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
