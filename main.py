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
    # Replace non-breaking space with a regular space
    text = text.replace('\xa0', ' ')
    # Regex to find a currency symbol followed by a number
    match = re.search(r"([^\d\s,.-]+)\s*([\d,.-]+)", text)
    if not match:
        return None, 0.0
    
    symbol, number_str = match.groups()
    try:
        # Clean and convert the number string to a float
        amount = float(number_str.replace(",", ""))
        return symbol.strip(), amount
    except (ValueError, TypeError):
        return None, 0.0

def extract_data(player_url):
    # 1) Fetch page via ScraperAPI using ULTRA PREMIUM proxies
    params = {
        "api_key": SCRAPER_API_KEY,
        "url": player_url,
        "ultra_premium": "true",  # This requires a paid subscription for difficult sites
    }
    
    try:
        logging.info(f"Attempting to fetch URL with ScraperAPI ultra premium proxies: {player_url}")
        response = requests.get(SCRAPER_API_URL, params=params, timeout=120)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        logging.error(f"A request exception occurred with ScraperAPI: {e}")
        if e.response is not None:
            logging.error(f"Response body: {e.response.text}")
        raise

    soup = BeautifulSoup(response.text, "html.parser")

    # 2) Player name
    player = "Unknown Player"
    if soup.title and soup.title.string:
        player = soup.title.string.split(":", 1)[0].strip()

    # 3) CORRECTED: Collect and filter tournament rows
    # First, get all rows from the results table.
    all_rows = soup.select("table.table--player-results tbody tr")
    
    # As per instruction 1, we filter out "Online" tournaments.
    # The resulting list will be used for calculating total tournaments, buy-ins, and prizes.
    live_tournament_rows = []
    for row in all_rows:
        event_name_text = row.select_one("td.event_name").get_text() if row.select_one("td.event_name") else ""
        if "Online" not in event_name_text:
            live_tournament_rows.append(row)
            
    # Total tournaments are the count of all non-Online events.
    total_tournaments = len(live_tournament_rows)

    # 4) Prepare accumulators
    total_buyins = {}
    total_prizes = {}
    individual_roi_list = []
    year_counts = {}
    year_roi_values = {}

    # 5) Process each non-Online tournament row
    for row in live_tournament_rows:
        year = None
        if (date_td := row.select_one("td.date")) and (m_year := re.search(r"(\d{4})", date_td.get_text())):
            year = m_year.group(1)
            # Count every non-online tournament for the yearly stats.
            year_counts[year] = year_counts.get(year, 0) + 1
            year_roi_values.setdefault(year, [])

        # --- CORRECTED: BUY-IN parsing ---
        buyin_amount = 0.0
        buyin_currency = None
        event_name_cell = row.select_one("td.event_name a")
        if event_name_cell:
            text = event_name_cell.get_text(strip=True)
            currency_symbol, _ = parse_money(text)
            if currency_symbol:
                # As per instruction 3, find all numbers but only consider the first one or two
                # to avoid capturing extra numbers from the game description (e.g., "8 or Better").
                numbers = re.findall(r'[\d,]+(?:\.\d+)?', text)[:2]
                if numbers:
                    buyin_amount = sum(float(n.replace(',', '')) for n in numbers)
                    buyin_currency = currency_symbol
                    # Add to total buy-ins for all non-Online tournaments.
                    total_buyins[buyin_currency] = total_buyins.get(buyin_currency, 0.0) + buyin_amount

        # --- PRIZE parsing & ROI Calculation (Logic is correct as per instructions 4 & 5) ---
        prize_cells = row.select("td.currency")
        # This flag ensures we only process one prize per tournament row.
        prize_found_for_row = False
        for cell in prize_cells:
            prize_currency, prize_value = parse_money(cell.get_text(strip=True))
            
            # As per instruction 4, we only consider the prize that matches the buy-in currency.
            if prize_currency and prize_value > 0 and prize_currency == buyin_currency and not prize_found_for_row:
                # Add to total prizes.
                total_prizes[prize_currency] = total_prizes.get(prize_currency, 0.0) + prize_value
                
                # As per instruction 5, calculate ROI only if both buy-in and prize are present.
                if buyin_amount > 0:
                    roi = prize_value / buyin_amount
                    individual_roi_list.append(roi)
                    if year:
                        year_roi_values[year].append(roi)
                
                prize_found_for_row = True # Mark prize as found and stop processing other currency cells.

    # 6) Compute overall average ROI
    # The average is the sum of individual ROIs divided by the number of tournaments with prizes.
    average_roi = round(sum(individual_roi_list) / len(individual_roi_list), 4) if individual_roi_list else 0.0

    # 7) Compute yearly stats sorted descending by year
    yearly_text_lines = []
    for yr, count in sorted(year_counts.items(), key=lambda x: int(x[0]), reverse=True):
        rois_for_year = year_roi_values.get(yr, [])
        # Calculate average ROI for the year based only on tournaments that had a prize.
        avg = round(sum(rois_for_year) / len(rois_for_year), 4) if rois_for_year else 0.0
        yearly_text_lines.append(f"{yr}: {count} tournaments, avg ROI {avg}")
    yearly_text = "\n".join(yearly_text_lines)

    # 8) Build multi-line text for buy-ins and prizes
    buyins_text_lines = [f"{cur}: {amt:,.2f}" for cur, amt in sorted(total_buyins.items())]
    total_buyins_text = "\n".join(buyins_text_lines)

    prizes_text_lines = [f"{cur}: {amt:,.2f}" for cur, amt in sorted(total_prizes.items())]
    total_prizes_text = "\n".join(prizes_text_lines)

    # 9) Return structured JSON with final text fields
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
            logging.error("Request received without a URL.")
            return jsonify({"error": "Missing 'url'"}), 400
        
        logging.info(f"Processing request for URL: {url}")
        result = extract_data(url)
        return jsonify(result), 200
    
    except Exception as e:
        logging.error(f"A critical error occurred in main_route: {e}", exc_info=True)
        return jsonify({"error": "An internal server error occurred. See logs for details."}), 500

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)



