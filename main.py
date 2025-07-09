import os
import re
import requests
import logging
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify

# Configure logging at the top level
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__)

# --- UPDATED FOR ScraperAPI ---
# Environment variables for ScraperAPI
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
    # Correct regex: match currency symbol(s) and numeric part (including commas, dots, dashes)
    match = re.search(r"([^\d\s,\.\-]+)\s*([\d,\.\-]+)", text)
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
        logging.info(f"Fetching URL with ScraperAPI: {player_url}")
        response = requests.get(SCRAPER_API_URL, params=params, timeout=120)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        logging.error(f"ScraperAPI request failed: {e}")
        if e.response is not None:
            logging.error(f"Response body: {e.response.text}")
        raise

    soup = BeautifulSoup(response.text, "html.parser")

    # 2) Player name
    player = "Unknown Player"
    if soup.title and soup.title.string:
        player = soup.title.string.split(":", 1)[0].strip()

    # 3) Collect and filter tournament rows (exclude Online only)
    all_rows = soup.select("table.table--player-results tbody tr")
    valid_rows = []
    for row in all_rows:
        event_cell = row.select_one("td.event_name")
        name_text = event_cell.get_text() if event_cell else ""
        is_online = "Online" in name_text
        if not is_online:
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
        event_link = row.select_one("td.event_name a")
        if event_link:
            text = event_link.get_text(strip=True)
            currency_symbol, _ = parse_money(text)
            if currency_symbol:
                # Extract at most two numbers for buy-in and fee/rake
                numbers = re.findall(r"[\d,]+(?:\.[\d]+)?", text)
                relevant = numbers[:2]
                buyin_amount = sum(float(n.replace(",", "")) for n in relevant)
                buyin_currency = currency_symbol
                total_buyins[buyin_currency] = total_buyins.get(buyin_currency, 0.0) + buyin_amount

        # --- PRIZE parsing & ROI Calculation ---
        for cell in row.select("td.currency"):
            prize_currency, prize_value = parse_money(cell.get_text(strip=True))
            # Take prize only if currency matches buy-in and value > 0
            if prize_currency == buyin_currency and prize_value > 0:
                total_prizes[prize_currency] = total_prizes.get(prize_currency, 0.0) + prize_value
                if buyin_amount > 0:
                    roi = prize_value / buyin_amount
                    individual_roi_list.append(roi)
                    if year:
                        year_roi_values[year].append(roi)
                break

    # 6) Compute overall average ROI
    average_roi = (
        round(sum(individual_roi_list) / len(individual_roi_list), 4)
        if individual_roi_list else 0.0
    )

    # 7) Compute yearly stats sorted descending by year
    yearly_lines = []
    for yr, count in sorted(year_counts.items(), key=lambda x: int(x[0]), reverse=True):
        rois = year_roi_values.get(yr, [])
        avg_roi = round(sum(rois) / len(rois), 4) if rois else 0.0
        yearly_lines.append(f"{yr}: {count} tournaments, avg ROI {avg_roi}")
    yearly_text = "\n".join(yearly_lines)

    # 8) Build total buy-ins and prizes texts
    buyins_text = "\n".join(f"{cur}: {amt:,.2f}" for cur, amt in sorted(total_buyins.items()))
    prizes_text = "\n".join(f"{cur}: {amt:,.2f}" for cur, amt in sorted(total_prizes.items()))

    # 9) Return structured JSON
    return {
        "player": player,
        "totalTournaments": total_tournaments,
        "averageROIByCash": average_roi,
        "yearlyStatsText": yearly_text,
        "totalBuyinsText": buyins_text,
        "totalPrizesText": prizes_text
    }

@app.route("/", methods=["POST"])
def main_route():
    try:
        data = request.get_json(force=True) or {}
        url = data.get("url")
        if not url:
            logging.error("Request missing URL.")
            return jsonify({"error": "Missing 'url'"}), 400
        logging.info(f"Processing URL: {url}")
        result = extract_data(url)
        return jsonify(result), 200
    except Exception as e:
        logging.error(f"Internal error: {e}", exc_info=True)
        return jsonify({"error": "Internal server error."}), 500

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
