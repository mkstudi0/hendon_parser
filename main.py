import os
import re
import requests
import logging
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify

# Configure logging at the top level, so it's set once when the app starts.
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__)

# Environment variables
SCRAPER_API_KEY = os.getenv("SCRAPER_API_KEY")
SCRAPER_API_URL = "https://api.scraperapi.com"


def extract_data(player_url):
    """
    Fetches a player's page, parses their offline tournament results,
    and returns aggregated statistics.
    """
    # 1) Fetch page via Scraper API with error handling
    params = {"api_key": SCRAPER_API_KEY, "url": player_url}
    try:
        logging.info(f"Attempting to fetch URL: {player_url}")
        response = requests.get(SCRAPER_API_URL, params=params, timeout=60)

        if response.status_code != 200:
            logging.error(f"Scraper API returned a non-200 status code: {response.status_code}")
            logging.error(f"Response body: {response.text}")
            raise Exception(f"Scraper API failed with status {response.status_code}")

        response.raise_for_status()

    except requests.exceptions.RequestException as e:
        logging.error(f"A request exception occurred: {e}")
        raise

    soup = BeautifulSoup(response.text, "html.parser")

    # 2) Player name
    player = "Unknown Player"
    if soup.title and soup.title.string:
        title_text = soup.title.string
        player = title_text.split(":", 1)[0].strip()

    # 3) Collect rows for offline tournaments only
    rows = soup.select("table.table--player-results tbody tr")
    if not rows:
        logging.warning("No tournament rows found. The page structure might have changed.")

    offline_rows = [r for r in rows if (ev := r.select_one("td.event_name")) and "Online" not in ev.get_text()]
    total_tournaments = len(offline_rows)

    # 4) Prepare accumulators
    total_buyins = {}
    total_prizes = {}
    overall_roi_values = []
    year_counts = {}
    year_roi_values = {}

    def parse_any_currency(text):
        """Generic function to parse any currency symbol and amount."""
        if not text:
            return None, 0.0
        match = re.search(r"([^\s\d,.-]+)\s*([\d,.-]+)", text)
        if not match:
            return None, 0.0
        
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

            buyin_amount = 0.0
            buyin_currency_symbol = None
            event_name_links = row.select("td.event_name a")
            for a in event_name_links:
                if not a.find('img'):
                    text = a.get_text().strip()
                    symbol, val = parse_any_currency(text)
                    if symbol and val > 0:
                        buyin_currency_symbol = symbol
                        buyin_amount = val
                        total_buyins[symbol] = total_buyins.get(symbol, 0.0) + val
                        break

            prize_amount = 0.0
            prize_currency_symbol = None
            prize_cell = row.select_one("td.currency")
            if prize_cell:
                txt = prize_cell.get_text(strip=True)
                if txt:
                    symbol, val = parse_any_currency(txt)
                    if symbol and val > 0:
                        prize_currency_symbol = symbol
                        prize_amount = val
                        total_prizes[symbol] = total_prizes.get(symbol, 0.0) + val

            if buyin_amount > 0 and buyin_currency_symbol and (buyin_currency_symbol == prize_currency_symbol):
                roi = prize_amount / buyin_amount
                overall_roi_values.append(roi)
                if year:
                    year_roi_values[year].append(roi)

        except Exception as e:
            logging.error(f"Failed to process a row. Error: {e}. Skipping row.")
            continue

    # 6) Compute overall average ROI
    average_roi = round(sum(overall_roi_values) / len(overall_roi_values), 4) if overall_roi_values else 0.0

    # 7) Compute yearly stats text (sorted descending by year)
    yearly_text_lines = []
    if year_counts:
        for yr, count in sorted(year_counts.items(), key=lambda x: int(x[0]), reverse=True):
            rois = year_roi_values.get(yr, [])
            avg = round(sum(rois) / count, 4) if count else 0.0
            yearly_text_lines.append(f"{yr}: {count} tournaments, avg ROI {avg}")
    yearly_stats_text = "\n".join(yearly_text_lines)

    # 8) Build multi-line text for buy-ins and prizes
    total_buyins_text = "\n".join([f"{cur}: {amt:,.2f}" for cur, amt in total_buyins.items()])
    total_prizes_text = "\n".join([f"{cur}: {amt:,.2f}" for cur, amt in total_prizes.items()])

    # 9) Return structured JSON with the requested textual fields
    return {
        "player": player,
        "totalTournaments": total_tournaments,
        "averageROIByCash": average_roi,
        "yearlyStatsText": yearly_stats_text,
        "totalBuyinsText": total_buyins_text,
        "totalPrizesText": total_prizes_text
    }


@app.route("/", methods=["POST"])
def main_route():
    data = request.get_json(force=True) or {}
    url = data.get("url")
    if not url:
        logging.error("Request received without a URL.")
        return jsonify({"error": "Missing 'url'"}), 400
    try:
        result = extract_data(url)
        return jsonify(result), 200
    except Exception as e:
        logging.error(f"An unexpected error occurred for URL: {url}. Error: {e}", exc_info=True)
        return jsonify({"error": "An internal server error occurred."}), 500


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)





