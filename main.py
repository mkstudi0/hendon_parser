import os
import re
import requests
import logging
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify

# Configure logging at the top level
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__)

# Environment variable for ScrapingBee
SCRAPINGBEE_API_KEY = os.getenv("SCRAPINGBEE_API_KEY")

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
    # 1) Fetch page via ScrapingBee API
    scrapingbee_endpoint = "https://app.scrapingbee.com/api/v1/"
    params = {
        "api_key": SCRAPINGBEE_API_KEY,
        "url": player_url,
    }
    
    try:
        logging.info(f"Attempting to fetch URL via ScrapingBee: {player_url}")
        response = requests.get(scrapingbee_endpoint, params=params, timeout=120)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        logging.error(f"A request exception occurred with ScrapingBee: {e}")
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
        is_online = "Online" in (row.select_one("td.event_name").get_text() if row.select_one("td.event_name") else "")
        
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
        year = None
        if (date_td := row.select_one("td.date")) and (m_year := re.search(r"(\d{4})", date_td.get_text())):
            year = m_year.group(1)
            year_counts[year] = year_counts.get(year, 0) + 1
            year_roi_values.setdefault(year, [])

        buyin_amount = 0.0
        buyin_currency = None
        event_name_cell = row.select_one("td.event_name a")
        if event_name_cell:
            text = event_name_cell.get_text(strip=True)
            currency_symbol, _ = parse_money(text)
            if currency_symbol:
                numbers = re.findall(r'[\d,]+(?:\.\d+)?', text)
                if numbers:
                    buyin_amount = sum(float(n.replace(',', '')) for n in numbers)
                    buyin_currency = currency_symbol
                    total_buyins[buyin_currency] = total_buyins.get(buyin_currency, 0.0) + buyin_amount

        prize_for_roi = 0.0
        prize_cells = row.select("td.currency")
        for cell in prize_cells:
            curr, val = parse_money(cell.get_text(strip=True))
            if curr and val > 0:
                total_prizes[curr] = total_prizes.get(curr, 0.0) + val
                if curr == buyin_currency:
                    prize_for_roi = val
        
        if buyin_amount > 0 and prize_for_roi > 0:
            roi = prize_for_roi / buyin_amount
            individual_roi_list.append(roi)
            if year:
                year_roi_values[year].append(roi)

    # 6) Compute overall average ROI
    average_roi = round(sum(individual_roi_list) / len(individual_roi_list), 4) if individual_roi_list else 0.0

    # 7) Compute yearly stats sorted descending by year
    yearly_text_lines = []
    for yr, count in sorted(year_counts.items(), key=lambda x: int(x[0]), reverse=True):
        rois = year_roi_values.get(yr, [])
        avg = round(sum(rois) / count, 4) if count else 0.0
        yearly_text_lines.append(f"{yr}: {count} tournaments, avg ROI {avg}")
    yearly_text = "\n".join(yearly_text_lines)

    # 9) Build multi-line text for buy-ins and prizes
    buyins_text_lines = [f"{cur}: {amt:,.2f}" for cur, amt in sorted(total_buyins.items())]
    total_buyins_text = "\n".join(buyins_text_lines)

    prizes_text_lines = [f"{cur}: {amt:,.2f}" for cur, amt in sorted(total_prizes.items())]
    total_prizes_text = "\n".join(prizes_text_lines)

    # 10) Return structured JSON with final text fields
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
    """
    This is the main entry point for requests.
    It now has enhanced error logging to catch any potential issue.
    """
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
        # This is a global catch-all to make sure we log EVERY error with its full traceback.
        logging.error(f"A critical error occurred in main_route: {e}", exc_info=True)
        return jsonify({"error": "An internal server error occurred. See logs for details."}), 500

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)



