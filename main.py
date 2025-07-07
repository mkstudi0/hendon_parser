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
    Universal currency parser.
    Identifies currency symbols like $, C$, NT$, €, etc., and the amount.
    """
    if not text:
        return None, 0.0
    # \xa0 is a non-breaking space, replace it with a regular space
    text = text.replace('\xa0', ' ')
    # Regex to find a currency symbol (one or more non-digit/non-space chars)
    # followed by a number.
    match = re.search(r"([^\d\s,.-]+)\s*([\d,.-]+)", text)
    if not match:
        return None, 0.0
    
    symbol, number_str = match.groups()
    try:
        amount = float(number_str.replace(",", ""))
        # Return the actual symbol found, not a hardcoded value
        return symbol.strip(), amount
    except (ValueError, TypeError):
        return None, 0.0


def extract_data(player_url):
    # 1) Fetch page via Scraper API
    params = {"api_key": SCRAPER_API_KEY, "url": player_url}
    response = requests.get(SCRAPER_API_URL, params=params, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    # 2) Player name
    title_text = soup.title.string or ""
    player = title_text.split(":", 1)[0].strip()

    # 3) Collect and filter tournament rows
    all_rows = soup.select("table.table--player-results tbody tr")
    
    # Filter out "Online" tournaments AND tournaments with no prize data
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
    individual_roi_list = [] # Use this for the final average ROI
    year_counts = {}
    year_roi_values = {}

    # 5) Process each valid tournament row
    for row in valid_rows:
        # Extract year
        year = None
        if (date_td := row.select_one("td.date")) and (m_year := re.search(r"(\d{4})", date_td.get_text())):
            year = m_year.group(1)
            year_counts[year] = year_counts.get(year, 0) + 1
            year_roi_values.setdefault(year, [])

        # --- BUY-IN parsing ---
        buyin_amount = 0.0
        buyin_currency = None
        event_name_cell = row.select_one("td.event_name a")
        if event_name_cell:
            text = event_name_cell.get_text(strip=True)
            # Use the universal function to identify the currency
            currency_symbol, _ = parse_money(text)
            if currency_symbol:
                # Find all numbers in the string to sum them up (e.g., "1,100 + 100")
                numbers = re.findall(r'[\d,]+(?:\.\d+)?', text)
                if numbers:
                    buyin_amount = sum(float(n.replace(',', '')) for n in numbers)
                    buyin_currency = currency_symbol
                    total_buyins[buyin_currency] = total_buyins.get(buyin_currency, 0.0) + buyin_amount

        # --- PRIZE parsing ---
        prize_for_roi = 0.0
        prize_cells = row.select("td.currency")
        for cell in prize_cells:
            # Parse each prize cell
            curr, val = parse_money(cell.get_text(strip=True))
            if curr and val > 0:
                # Add every found prize to the total prize pool
                total_prizes[curr] = total_prizes.get(curr, 0.0) + val
                # Check if this prize's currency matches the buy-in currency for ROI calculation
                if curr == buyin_currency:
                    prize_for_roi = val
        
        # --- ROI calculation ---
        # Calculate ROI only if there is a buy-in AND a matching prize
        if buyin_amount > 0 and prize_for_roi > 0:
            roi = prize_for_roi / buyin_amount
            individual_roi_list.append(roi)
            if year:
                year_roi_values[year].append(roi)

    # 6) Compute overall average ROI
    average_roi = round(sum(individual_roi_list) / len(individual_roi_list), 4) if individual_roi_list else 0.0

    # 7) Compute yearly stats sorted descending by year
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

    # 9) Build multi-line text for buy-ins and prizes
    # Sort by currency symbol for consistent order and format with commas
    buyins_text_lines = [f"{cur}: {amt:,.2f}" for cur, amt in sorted(total_buyins.items())]
    total_buyins_text = "\n".join(buyins_text_lines)

    prizes_text_lines = [f"{cur}: {amt:,.2f}" for cur, amt in sorted(total_prizes.items())]
    total_prizes_text = "\n".join(prizes_text_lines)

    # 10) Return structured JSON with textual fields
    return {
        "player": player,
        "totalTournaments": total_tournaments,
        "totalBuyins": total_buyins,
        "totalPrizes": total_prizes,
        "averageROIByCash": average_roi,
        "yearlyStats": yearly_stats,
        "yearlyStatsText": yearly_text,
        "buyinsText": buyins_text
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


