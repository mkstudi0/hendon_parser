import os
import re
import requests
from flask import Flask, request, jsonify
from bs4 import BeautifulSoup
from collections import defaultdict

app = Flask(__name__)

# 1) Read API key and fail early if missing
SCRAPER_API_KEY = os.getenv("SCRAPER_API_KEY")
if not SCRAPER_API_KEY:
    raise RuntimeError("Error: missing SCRAPER_API_KEY environment variable")

SCRAPER_API_URL = "https://api.scraperapi.com"


def extract_data(player_url: str) -> dict:
    """
    Fetches the player profile via ScraperAPI, parses offline tournaments,
    computes totals and ROI, and returns a structured dict.
    """
    # 2) Fetch HTML via ScraperAPI
    resp = requests.get(
        SCRAPER_API_URL,
        params={
            "api_key": SCRAPER_API_KEY,
            "url": player_url,
            "render": "true"
        },
        timeout=60
    )
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    # 3) Extract player name
    title = soup.title.string or ""
    player = title.split(":", 1)[0].strip()

    # 4) Select offline tournament rows
    rows = soup.select("table.table--player-results tbody tr")
    offline = [r for r in rows if "Online" not in r.get_text()]
    total_tournaments = len(offline)

    # 5) Accumulators
    total_buyins = defaultdict(float)
    total_prizes = defaultdict(float)
    roi_values = []
    year_data = defaultdict(lambda: {"count": 0, "roi_sum": 0.0})

    # 6) Parse each row
    for tr in offline:
        # a) Year
        year = None
        date_td = tr.select_one("td.date")
        if date_td:
            m_year = re.search(r"(\d{4})", date_td.get_text())
            if m_year:
                year = m_year.group(1)

        # b) Buy-in: detect any currency symbol(s) + amounts
        event_link = tr.select_one("td.event_name a[href*='event.php']")
        if not event_link:
            continue
        evt_text = event_link.get_text(strip=True)
        m_buy = re.search(r"([^\d\+\s,]+)\s*([\d,]+(?:\s*\+\s*[\d,]+)*)", evt_text)
        if not m_buy:
            continue
        cur = m_buy.group(1)
        parts = re.split(r"\+", m_buy.group(2))
        amounts = [float(p.replace(",", "")) for p in parts]
        buyin_amt = sum(amounts)
        total_buyins[cur] += buyin_amt

        # c) Prize: find last td.currency and match same currency
        prize_cells = tr.select("td.currency")
        prize_amt = 0.0
        for cell in prize_cells[::-1]:
            txt = cell.get_text(strip=True)
            m_pr = re.search(rf"({re.escape(cur)})\s*([\d,]+)", txt)
            if m_pr:
                prize_amt = float(m_pr.group(2).replace(",", ""))
                total_prizes[cur] += prize_amt
                break

        # d) ROI for this event
        if buyin_amt > 0:
            roi = prize_amt / buyin_amt
            roi_values.append(roi)
            if year:
                year_data[year]["count"] += 1
                year_data[year]["roi_sum"] += roi

    # 7) Compute overall ROI
    average_roi = round(sum(roi_values) / len(roi_values), 4) if roi_values else 0.0

    # 8) Build dynamic currency text blocks
    buyins_text = "\n".join(f"{c} {amt:,.0f}" for c, amt in total_buyins.items())
    prizes_text = "\n".join(f"{c} {amt:,.0f}" for c, amt in total_prizes.items())

    # 9) Build yearlyStatsText
    yearly_lines = []
    for yr in sorted(year_data.keys(), reverse=True):
        info = year_data[yr]
        avg = round(info["roi_sum"] / info["count"], 4) if info["count"] else 0.0
        yearly_lines.append(f"{yr}: {info['count']} tournaments, avg ROI {avg}")
    yearly_stats_text = "\n".join(yearly_lines)

    # 10) Return JSON-ready dict
    return {
        "player": player,
        "totalTournaments": total_tournaments,
        "totalBuyins": total_buyins,
        "totalPrizes": total_prizes,
        "averageROIByCash": average_roi,
        "buyinsText": buyins_text,
        "prizesText": prizes_text,
        "yearlyStatsText": yearly_stats_text
    }


@app.route("/", methods=["POST"])
def main_route():
    req = request.get_json(force=True) or {}
    url = req.get("url")
    if not url:
        return jsonify({"error": "Missing 'url' parameter"}), 400
    try:
        result = extract_data(url)
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)









