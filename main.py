import os
import re
import requests
import logging
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify

# Configure logging at the top level
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__)

# Environment variables
SCRAPER_API_KEY = os.getenv("SCRAPER_API_KEY")
SCRAPER_API_URL = "https://api.scraperapi.com"


def extract_data(player_url):
    """
    Fetches a player's page, parses their offline tournament results,
    and returns aggregated statistics with improved logic and error handling.
    """
    # 1) Fetch page via Scraper API with 'premium' parameter to handle protected sites
    params = {
        "api_key": SCRAPER_API_KEY,
        "url": player_url,
        "premium": "true"  # Attempt to use a better proxy pool as suggested by the error log
    }
    try:
        logging.info(f"Attempting to fetch URL with premium flag: {player_url}")
        # Increased timeout to give the API more time to process
        response = requests.get(SCRAPER_API_URL, params=params, timeout=120)

        if response.status_code != 200:
            logging.error(f"Scraper API returned a non-200 status code: {response.status_code}")
            logging.error(f"Response body: {response.text}")
            raise Exception(f"Scraper API failed with status {response.status_code}. Body: {response.text}")

        response.raise_for_status()

    except requests.exceptions.RequestException as e:
        logging.error(f"A request exception occurred: {e}")
        raise

    soup = BeautifulSoup(response.text, "html.parser")

    # 2) Player name
    player = "Unknown Player"
    if soup.title and soup.title.string:
        player = soup.title.string.split(":", 1)[0].strip()

    # 3) Collect rows for offline tournaments only
    rows = soup.select("table.table--player-results tbody tr")
    if not rows:
        logging.warning("No tournament rows found. The page structure might have changed or the page was not loaded correctly.")

    offline_rows = [r for r in rows if (ev := r.select_one("td.event_name")) and "Online" not in ev.get_text()]
    total_tournaments = len(offline_rows)

    # 4) Prepare accumulators
    total_buyins = {}
    total_prizes = {}
    year_counts = {}
    year_roi_values = {}

    def parse_any_currency(text):
        if not text: return None, 0.0
        # Improved regex to better capture currency symbols like '$'
        match = re.search(r"([$€£₽¥]|[A-Z]{3})\s*([\d,.-]+)", text)
        if not match: return None, 0.0
        
        symbol, number_str = match.groups()
        try:
            amount = float(number_str.replace(",", "").replace("-", "0"))
            return symbol, amount
        except (ValueError, TypeError):
            return None, 0.0

    # 5) Process each offline tournament
    for row in offline_rows:
        try:
            year = None
            date_td = row.select_one("td.date")
            if date_td and (m_year := re.search(r"(\d{4})", date_td.get_text())):
                year = m_year.group(1)
                year_counts[year] = year_counts.get(year, 0) + 1
                year_roi_values.setdefault(year, [])

            # Parse Buy-in
            buyin_amount, buyin_currency = 0.0, None
            event_name_links = row.select("td.event_name a")
            for a in event_name_links:
                if not a.find('img'):
                    symbol, val = parse_any_currency(a.get_text(strip=True))
                    if symbol and val > 0:
                        buyin_currency, buyin_amount = symbol, val
                        total_buyins[symbol] = total_buyins.get(symbol, 0.0) + val
                        break
            
            # Parse Prize
            prize_amount, prize_currency = 0.0, None
            prize_cell = row.select_one("td.currency")
            if prize_cell:
                txt = prize_cell.get_text(strip=True)
                if txt:
                    symbol, val = parse_any_currency(txt)
                    if symbol and val >= 0:
                        prize_currency, prize_amount = symbol, val
                        total_prizes[symbol] = total_prizes.get(symbol, 0.0) + val

            # --- CORRECTED ROI LOGIC ---
            # Calculate ROI only if a buy-in was found
            if buyin_amount > 0:
                # If currencies match or there was no prize (prize_currency is None), we can calculate a meaningful ROI.
                if buyin_currency == prize_currency or prize_currency is None:
                    roi = prize_amount / buyin_amount
                    if year:
                        year_roi_values[year].append(roi)

        except Exception as e:
            logging.error(f"Failed to process a row. Error: {e}. Skipping row.")
            continue

    # 6) Compute overall average ROI based on totals for the most frequent currency
    overall_avg_roi = 0.0
    if total_buyins:
        # Find the most frequent currency for buy-ins
        main_currency = max(total_buyins, key=total_buyins.get)
        if total_buyins.get(main_currency, 0) > 0:
            overall_avg_roi = (total_prizes.get(main_currency, 0)) / total_buyins[main_currency]

    # 7) Compute yearly stats text
    yearly_text_lines = []
    if year_counts:
        for yr, count in sorted(year_counts.items(), key=lambda x: int(x[0]), reverse=True):
            rois = year_roi_values.get(yr, [])
            # Calculate average from the list of ROIs for that year
            avg_roi_for_year = round(sum(rois) / len(rois), 4) if rois else 0.0
            yearly_text_lines.append(f"{yr}: {count} tournaments, avg ROI {avg_roi_for_year}")
    yearly_stats_text = "\n".join(yearly_text_lines)

    # 8) Build multi-line text for buy-ins and prizes
    total_buyins_text = "\n".join([f"{cur}: {amt:,.2f}" for cur, amt in sorted(total_buyins.items())])
    total_prizes_text = "\n".join([f"{cur}: {amt:,.2f}" for cur, amt in sorted(total_prizes.items())])

    # 9) Return structured JSON
    return {
        "player": player,
        "totalTournaments": total_tournaments,
        "averageROIByCash": round(overall_avg_roi, 4),
        "yearlyStatsText": yearly_stats_text,
        "totalBuyinsText": total_buyins_text,
        "totalPrizesText": total_prizes_text
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
        logging.error(f"An unexpected error occurred for URL: {url}. Error: {e}", exc_info=True)
        return jsonify({"error": f"An internal server error occurred: {e}"}), 500


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
