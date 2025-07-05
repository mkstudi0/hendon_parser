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
    rows = soup.select("table.table--player-results tbody tr")
    offline_rows = []
    for r in rows:
        ev = r.select_one("td.event_name")
        if ev and "Online" not in ev.get_text():
            offline_rows.append(r)
    total_tournaments = len(offline_rows)

    # 4) Prepare accumulators
    total_buyins = {}
    total_prizes = {}
    overall_roi_values = []
    year_counts = {}
    year_roi_values = {}

    # 5) Process each offline tournament
    for row in offline_rows:
        # Extract year
        date_td = row.select_one("td.date")
        year = None
        if date_td:
            m_year = re.search(r"(\d{4})", date_td.get_text())
            if m_year:
                year = m_year.group(1)
        if year:
            year_counts[year] = year_counts.get(year, 0) + 1
            year_roi_values.setdefault(year, [])

        # BUY-IN parsing
        buyin_amount = 0.0
        buyin_currency = None
        for a in row.select("td.event_name a"):
            if not a.find('img'):
                text = a.get_text().strip()
                match = re.match(r'^[€$0-9\+,\s]+', text)
                if match:
                    part = match.group(0)
                    nums = re.findall(r'[0-9][0-9,]*', part)
                    total_val = sum(float(n.replace(',', '')) for n in nums)
                    if part.startswith('$'):
                        curr = 'USD'
                    elif part.startswith('€'):
                        curr = 'EUR'
                    else:
                        curr = None
                    if curr:
                        buyin_amount = total_val
                        buyin_currency = curr
                        total_buyins[curr] = total_buyins.get(curr, 0.0) + total_val
                break

        # PRIZE parsing
        prize_amount = 0.0
        for cell in row.select("td.currency"):
            txt = cell.get_text(strip=True)
            if txt:
                curr, val = parse_money(txt)
                if buyin_currency and curr == buyin_currency:
                    prize_amount = val
                    total_prizes[curr] = total_prizes.get(curr, 0.0) + val
                    break

        # ROI calculation
        if buyin_amount > 0:
            roi = prize_amount / buyin_amount
            overall_roi_values.append(roi)
            if year:
                year_roi_values[year].append(roi)

    # 6) Compute overall average ROI
    if total_tournaments > 0:
        average_roi = round(sum(overall_roi_values) / total_tournaments, 4)
    else:
        average_roi = 0.0

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

    # 8) Return structured JSON
    return {
        "player": player,
        "totalTournaments": total_tournaments,
        "totalBuyins": total_buyins,
        "totalPrizes": total_prizes,
        "averageROIByCash": average_roi,
        "yearlyStats": yearly_stats
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






