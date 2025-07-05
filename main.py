import os
import re
import requests
from flask import Flask, request, jsonify
from bs4 import BeautifulSoup
from collections import defaultdict

app = Flask(__name__)

# Load ScraperAPI key from environment
SCRAPER_API_KEY = os.getenv("SCRAPER_API_KEY")
if not SCRAPER_API_KEY:
    raise RuntimeError("Please set the SCRAPER_API_KEY environment variable")

def fetch_html_via_scraperapi(target_url: str) -> str:
    """
    Fetches the target URL via ScraperAPI with JS rendering enabled.
    """
    api_url = "http://api.scraperapi.com/"
    params = {
        "api_key": SCRAPER_API_KEY,
        "url": target_url,
        "render": "true"
    }
    resp = requests.get(api_url, params=params, timeout=60)
    resp.raise_for_status()
    return resp.text

def parse_profile(target_url: str) -> dict:
    """
    Parses the player profile at the given URL and returns structured data.
    """
    html = fetch_html_via_scraperapi(target_url)
    soup = BeautifulSoup(html, "html.parser")

    # 1) Player name
    name_tag = soup.select_one("h1.player-profile-name")
    player_name = name_tag.get_text(strip=True) if name_tag else ""

    # 2) Result rows (only offline)
    rows = soup.select("table.table--player-results tbody tr")

    total_tournaments = 0
    buyins = defaultdict(float)
    prizes = defaultdict(float)
    total_roi = 0.0
    year_data = defaultdict(lambda: {"tournaments": 0, "roi_sum": 0.0})

    for tr in rows:
        text = tr.get_text()
        if "Online" in text:
            continue  # skip online events

        # Parse buy-in from event_name link text
        event_link = tr.select_one("td.event_name a[href*='event.php']")
        if not event_link:
            continue
        event_text = event_link.get_text(strip=True)
        m = re.search(r"([€$A-Za-z]{1,3})\s*([\d,]+(?:\s*\+\s*[\d,]+)*)", event_text)
        if not m:
            continue
        currency = m.group(1)
        amounts = [int(x.replace(',', '')) for x in m.group(2).split('+')]
        buyin_amount = sum(amounts)
        buyins[currency] += buyin_amount

        # Parse prize from last currency cell
        prize_cells = tr.select("td.currency")
        prize_text_raw = prize_cells[-1].get_text(strip=True) if prize_cells else ""
        m2 = re.search(rf"{re.escape(currency)}\s*([\d,]+)", prize_text_raw)
        prize_amount = int(m2.group(1).replace(',', '')) if m2 else 0
        prizes[currency] += prize_amount

        # ROI and count
        if buyin_amount > 0:
            roi = prize_amount / buyin_amount
            total_roi += roi

            # extract year
            date_text = tr.select_one("td.date").get_text(strip=True)
            year = int(date_text.split('-')[-1]) if '-' in date_text else None
            if year:
                year_data[year]["tournaments"] += 1
                year_data[year]["roi_sum"] += roi

        total_tournaments += 1

    # Compute overall average ROI
    average_roi = round(total_roi / total_tournaments, 4) if total_tournaments else 0.0

    # Build text for buy-ins and prizes
    def build_currency_text(data_dict):
        lines = [f"{cur} {amt:,.0f}" for cur, amt in sorted(data_dict.items())]
        return "\n".join(lines)

    buyins_text = build_currency_text(buyins)
    prizes_text = build_currency_text(prizes)

    # Build yearly stats text
    yearly_lines = []
    for yr in sorted(year_data.keys(), reverse=True):
        info = year_data[yr]
        avg = round(info["roi_sum"] / info["tournaments"], 4) if info["tournaments"] else 0.0
        yearly_lines.append(f"{yr}: {info['tournaments']} tournaments, avg ROI {avg}")
    yearly_stats_text = "\n".join(yearly_lines)

    return {
        "player": player_name,
        "totalTournaments": total_tournaments,
        "totalBuyinsText": buyins_text,
        "totalPrizesText": prizes_text,
        "averageROIByCash": average_roi,
        "yearlyStatsText": yearly_stats_text
    }

@app.route("/", methods=["POST"])
def main():
    payload = request.get_json(force=True)
    url = payload.get("url")
    if not url:
        return jsonify({"error": "Missing 'url' parameter"}), 400
    try:
        data = parse_profile(url)
        return jsonify(data), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)








