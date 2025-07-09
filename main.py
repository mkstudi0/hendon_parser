import os
import re
import requests
import logging
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__)

# --- ScraperAPI configuration ---
SCRAPER_API_KEY = os.getenv("SCRAPER_API_KEY")
SCRAPER_API_URL = "https://api.scraperapi.com"

def parse_money(text):
    """
    Universal currency parser.
    Identifies currency symbols like $, C$, NT$, €, etc., and the amount.
    """
    if not text:
        return None, 0.0
    text = text.replace('\xa0', ' ')
    match = re.search(r"([^\d\s,.-]+)\s*([\d,.-]+)", text)
    if not match:
        return None, 0.0
    symbol, number_str = match.groups()
    try:
        amount = float(number_str.replace(",", ""))
        return symbol.strip(), amount
    except (ValueError, TypeError):
        return None, 0.0

def extract_data(player_url):
    # 1) Fetch page via ScraperAPI using ULTRA PREMIUM proxies
    params = {
        "api_key": SCRAPER_API_KEY,
        "url": player_url,
        "ultra_premium": "true",
    }
    try:
        logging.info(f"Fetching URL: {player_url}")
        response = requests.get(SCRAPER_API_URL, params=params, timeout=120)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        logging.error(f"Request error: {e}")
        if e.response is not None:
            logging.error(f"Response body: {e.response.text}")
        raise

    soup = BeautifulSoup(response.text, "html.parser")

    # 2) Player name
    player = "Unknown Player"
    if soup.title and soup.title.string:
        player = soup.title.string.split(":", 1)[0].strip()

    # 3) Collect and filter tournament rows
    all_rows = soup.select("table.table--player-results tbody tr")
    valid_rows = []
    for row in all_rows:
        has_prize = any(cell.get_text(strip=True) for cell in row.select("td.currency"))
        event_text = (
            row.select_one("td.event_name").get_text()
            if row.select_one("td.event_name") else ""
        )
        is_online = "online" in event_text.lower()
        if has_prize and not is_online:
            valid_rows.append(row)
    total_tournaments = len(valid_rows)

    # 4) Prepare accumulators
    total_buyins = {}
    total_prizes = {}
    individual_roi_list = []
    year_counts = {}
    year_roi_values = {}

    # 5) Process each valid tournament row
    for row in valid_rows:
        # Year extraction
        year = None
        date_td = row.select_one("td.date")
        if date_td:
            m_year = re.search(r"(\d{4})", date_td.get_text())
            if m_year:
                year = m_year.group(1)
                year_counts[year] = year_counts.get(year, 0) + 1
                year_roi_values.setdefault(year, [])

        # --- BUY-IN parsing ---
        buyin_amount = 0.0
        buyin_currency = None
        event_link = row.select_one("td.event_name a[href*='event.php']")
        if event_link:
            text = event_link.get_text(strip=True)
            currency_symbol, _ = parse_money(text)
            if currency_symbol:
                raw_numbers = re.findall(r'[\d,]+(?:\.\d+)?', text)
                numbers = raw_numbers[:2]
                if numbers:
                    buyin_amount = sum(float(n.replace(',', '')) for n in numbers)
                    buyin_currency = currency_symbol
                    total_buyins[buyin_currency] = total_buyins.get(buyin_currency, 0.0) + buyin_amount

        # --- PRIZE parsing & ROI calculation ---
        prize_for_roi = 0.0
        prize_cells = row.select("td.currency")
        for cell in prize_cells:
            prize_currency, prize_value = parse_money(cell.get_text(strip=True))
            if prize_currency == buyin_currency and prize_value > 0:
                prize_for_roi = prize_value
                total_prizes[prize_currency] = total_prizes.get(prize_currency, 0.0) + prize_for_roi
                if buyin_amount > 0:
                    roi = prize_for_roi / buyin_amount
                    individual_roi_list.append(roi)
                    if year:
                        year_roi_values.setdefault(year, []).append(roi)
                break  # stop after first matching currency

    # 6) Compute overall average ROI by cash
    average_roi = (
        round(sum(individual_roi_list) / len(individual_roi_list), 4)
        if individual_roi_list
        else 0.0
    )

    # 7) Compute yearly stats sorted descending by year
    yearly_text_lines = []
    for yr in sorted(year_roi_values.keys(), key=lambda x: int(x), reverse=True):
        rois_for_year = year_roi_values.get(yr, [])
        count = len(rois_for_year)
        avg = round(sum(rois_for_year) / count, 4) if count else 0.0
        yearly_text_lines.append(f"{yr}: {count} tournaments, avg ROI {avg}")
    yearly_text = "\n".join(yearly_text_lines)

    # 8) Build multi-line text for buy-ins and prizes
    buyins_text_lines = [f"{cur}: {amt:,.2f}" for cur, amt in sorted(total_buyins.items())]
    total_buyins_text = "\n".join(buyins_text_lines)

    prizes_text_lines = [f"{cur}: {amt:,.2f}" for cur, amt in sorted(total_prizes.items())]
    total_prizes_text = "\n".join(prizes_text_lines)

    # 9) Return structured JSON
    return {
        "player": player,
        "totalTournaments": total_tournaments,
        "averageROIByCash": average_roi,
        "yearlyStatsText": yearly_text,
        "totalBuyinsText": total_buyins_text,
        "totalPrizesText": total_prizes_text
    }

@app.route("/", methods=["POST"])
def main_route():
    try:
        data = request.get_json(force=True) or {}
        url = data.get("url")
        if not url:
            logging.error("Missing 'url' in request.")
            return jsonify({"error": "Missing 'url'"}), 400

        logging.info(f"Processing request for URL: {url}")
        result = extract_data(url)
        return jsonify(result), 200

    except Exception as e:
        logging.error(f"Internal error: {e}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

