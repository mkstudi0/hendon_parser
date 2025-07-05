import os
import re
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify

app = Flask(__name__)

# Environment variables
SCRAPER_API_KEY = os.getenv("SCRAPER_API_KEY")
SCRAPER_API_URL = "https://api.scraperapi.com"


def parse_money(text):
    """
    Parse a string like '$ 1,500' or '€ 550' and return (currency, amount).
    """
    match = re.search(r"([€$])\s*([\d,]+)", text)
    if not match:
        return None, 0.0
    symbol, number = match.groups()
    amount = float(number.replace(",", ""))
    currency = "USD" if symbol == "$" else "EUR"
    return currency, amount


def extract_data(player_url):
    # 1) Fetch page via Scraper API
    params = {"api_key": SCRAPER_API_KEY, "url": player_url}
    response = requests.get(SCRAPER_API_URL, params=params, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    # 2) Player name
    title_text = soup.title.string or ""
    player = title_text.split(":", 1)[0].strip()

    # 3) Collect rows for offline tournaments only
    all_rows = soup.select("table.table--player-results tbody tr")
    offline_rows = [r for r in all_rows
                    if r.select_one("td.event_name") and "Online" not in r.select_one("td.event_name").get_text()]
    total_tournaments = len(offline_rows)

    # 4) Aggregate buy-ins, prizes, ROI list
    total_buyins = {}
    total_prizes = {}
    roi_values = []

    for row in offline_rows:
        # BUY-IN: find the event link without <img>
        buyin_amount = 0.0
        buyin_currency = None
        links = row.select("td.event_name a")
        event_link = None
        for a in links:
            if not a.find('img'):
                event_link = a
                break
        if event_link:
            parts = re.findall(r"[€$]\s*[\d,]+", event_link.get_text())
            for part in parts:
                curr, val = parse_money(part)
                if curr:
                    buyin_amount += val
                    total_buyins[curr] = total_buyins.get(curr, 0.0) + val
                    buyin_currency = curr

        # PRIZE
        prize_amount = 0.0
        for cell in row.select("td.currency"):
            text = cell.get_text(strip=True)
            if text:
                curr, val = parse_money(text)
                if buyin_currency:
                    if curr == buyin_currency:
                        prize_amount = val
                        total_prizes[curr] = total_prizes.get(curr, 0.0) + val
                        break
                else:
                    prize_amount += val
                    total_prizes[curr] = total_prizes.get(curr, 0.0) + val

        # ROI per tournament
        if buyin_amount > 0.0:
            roi_values.append(prize_amount / buyin_amount)

    # 5) Sum ROI
    roi_sum = round(sum(roi_values), 4)

    # 6) Return structured JSON
    return {
        "player": player,
        "totalTournaments": total_tournaments,
        "totalBuyins": total_buyins,
        "totalPrizes": total_prizes,
        "roiSum": roi_sum
    }


@app.route("/", methods=["POST"])
def main_route():
    data = request.get_json(force=True) or {}
    url = data.get("url")
    if not url:
        return jsonify({"error": "Missing 'url'"}), 400

    try:
        result = extract_data(url)
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)





