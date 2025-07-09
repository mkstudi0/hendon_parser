import os
import re
import requests
import logging
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify

# Configure logging at the top level
# Set up basic configuration for logging to track script execution.
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__)

# --- UPDATED for ScraperAPI ---
# Get the API key from environment variables for security.
SCRAPER_API_KEY = os.getenv("SCRAPER_API_KEY")
SCRAPER_API_URL = "https://api.scraperapi.com"

def parse_money(text):
    """
    Extracts currency and amount from a string like '$ 1,500' or '€ 550'.
    
    Args:
        text (str): The input string with the amount.

    Returns:
        tuple: A tuple (currency, amount) or (None, 0.0) if parsing fails.
    """
    # Corrected regular expression:
    # ([€$]) - finds the € or $ symbol.
    # \s* - finds zero or more whitespace characters.
    # ([\d,.]+) - finds one or more digits, commas, or periods.
    match = re.search(r"([€$])\s*([\d,.]+)", text)
    if not match:
        return None, 0.0
    
    symbol, number_str = match.groups()
    # Remove commas and convert the string to a floating-point number.
    amount = float(number_str.replace(",", ""))
    currency = "USD" if symbol == "$" else "EUR"
    return currency, amount

def extract_data(player_url):
    """
    Extracts player tournament data from a web page.
    """
    # 1) Fetch page via ScraperAPI using ULTRA PREMIUM proxies
    params = {
        "api_key": SCRAPER_API_KEY,
        "url": player_url,
        "ultra_premium": "true",  # Requires a paid subscription
    }
    
    try:
        logging.info(f"Attempting to fetch URL with ScraperAPI: {player_url}")
        # Set a timeout to prevent the request from hanging.
        response = requests.get(SCRAPER_API_URL, params=params, timeout=120)
        # Check if the request was successful (status code 2xx).
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        logging.error(f"Request exception with ScraperAPI: {e}")
        if e.response is not None:
            logging.error(f"Response body: {e.response.text}")
        raise

    soup = BeautifulSoup(response.text, "html.parser")

    # 2) Player name
    player = "Unknown Player"
    if soup.title and soup.title.string:
        # Extract the player's name from the page title.
        player = soup.title.string.split(":", 1)[0].strip()

    # 3) Collect rows for offline tournaments only
    rows = soup.select("table.table--player-results tbody tr")
    # Use a list comprehension to filter rows, excluding "Online" tournaments.
    offline_rows = [r for r in rows if (ev := r.select_one("td.event_name")) and "Online" not in ev.get_text()]
    total_tournaments = len(offline_rows)

    # 4) Prepare accumulators for data collection
    total_buyins = {}
    total_prizes = {}
    overall_roi_values = []
    year_counts = {}
    year_roi_values = {}

    # 5) Process each offline tournament
    for row in offline_rows:
        # Extract year
        year = None
        date_td = row.select_one("td.date")
        if date_td:
            # Corrected regular expression to find the year.
            m_year = re.search(r"(\d{4})", date_td.get_text())
            if m_year:
                year = m_year.group(1)
                year_counts[year] = year_counts.get(year, 0) + 1
                year_roi_values.setdefault(year, [])

        # Parse BUY-IN
        buyin_amount = 0.0
        buyin_currency = None
        # Look for the buy-in in the links within the event name cell.
        buyin_cell = row.select_one("td.event_name")
        if buyin_cell:
            # Use `parse_money` for clean data extraction.
            currency, amount = parse_money(buyin_cell.get_text())
            if currency:
                buyin_currency = currency
                buyin_amount = amount
                total_buyins[currency] = total_buyins.get(currency, 0.0) + amount

        # Parse PRIZE
        prize_amount = 0.0
        prize_cell = row.select_one("td.currency")
        if prize_cell:
            # Use `parse_money` to extract prize data.
            currency, amount = parse_money(prize_cell.get_text(strip=True))
            # Ensure the prize currency matches the buy-in currency.
            if buyin_currency and currency == buyin_currency:
                prize_amount = amount
                total_prizes[currency] = total_prizes.get(currency, 0.0) + amount

        # Calculate ROI
        if buyin_amount > 0:
            roi = prize_amount / buyin_amount
            overall_roi_values.append(roi)
            if year:
                year_roi_values[year].append(roi)

    # 6) Compute overall average ROI
    average_roi = round(sum(overall_roi_values) / len(overall_roi_values), 4) if overall_roi_values else 0.0

    # 7) Compute yearly stats, sorted descending by year
    yearly_stats = []
    for yr, count in sorted(year_counts.items(), key=lambda x: int(x[0]), reverse=True):
        rois = year_roi_values.get(yr, [])
        avg = round(sum(rois) / count, 4) if count else 0.0
        yearly_stats.append({
            "year": int(yr),
            "tournaments": count,
            "averageROIByCash": avg
        })

    # 8) Build multi-line yearly text
    yearly_text_lines = [f"{s['year']}: {s['tournaments']} tournaments, avg ROI {s['averageROIByCash']}" for s in yearly_stats]
    yearly_text = "\n".join(yearly_text_lines)

    # 9) Build buy-ins text
    buyins_text_lines = [f"{cur}: {amt:,.2f}" for cur, amt in total_buyins.items()]
    total_buyins_text = "\n".join(buyins_text_lines)

    # 10) Build prizes text (ERROR FIXED: this variable was missing)
    prizes_text_lines = [f"{cur}: {amt:,.2f}" for cur, amt in total_prizes.items()]
    total_prizes_text = "\n".join(prizes_text_lines)

    # 11) Return structured JSON with final data
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
        # Check if the request is JSON
        if not request.is_json:
            return jsonify({"error": "Request must be JSON"}), 415
            
        data = request.get_json()
        url = data.get("url")
        if not url:
            logging.error("Request received without a URL.")
            return jsonify({"error": "Missing 'url'"}), 400
        
        logging.info(f"Processing request for URL: {url}")
        result = extract_data(url)
        return jsonify(result), 200
    
    except Exception as e:
        # Log the full traceback for easier debugging.
        logging.error(f"A critical error occurred in main_route: {e}", exc_info=True)
        return jsonify({"error": "An internal server error occurred. See logs for details."}), 500

if __name__ == "__main__":
    # Use the PORT environment variable if available (for deployment).
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
