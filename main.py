import os
import re
from flask import Flask, request, jsonify
from playwright.sync_api import sync_playwright

app = Flask(__name__)

def extract_data(url):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, timeout=60000)
        page.wait_for_selector("h1", timeout=15000)

        # Player's name
        name = page.locator("h1").inner_text().strip()

        # Total tournaments (offline only counted below)
        total_buyins = {}
        total_prizes = {}
        roi_values = []
        stats_by_year = {}

        # Iterate through all result rows
        rows = page.locator("table.table--player-results tbody tr")
        for i in range(rows.count()):
            row = rows.nth(i)
            text = row.inner_text()
            # Exclude online events
            if "Online" in text:
                continue

            # Parse buy-in (may have "+")
            event_text = row.locator("td.event_name").inner_text()
            m = re.search(r'([€$A-Za-z]\s?[\d,]+(?:\s*\+\s*[€$A-Za-z]\s?[\d,]+)?)', event_text)
            if not m:
                continue
            raw_buyin = m.group(1)
            currency = raw_buyin.strip()[0]
            parts = [int(x.replace(currency, "").replace(" ", "").replace(",", "")) 
                     for x in raw_buyin.split("+")]
            buyin_amount = sum(parts)

            # Parse prize (last currency cell)
            prize_text = row.locator("td.currency").last.inner_text().strip()
            prize_currency = prize_text[0]
            prize_amount = int(prize_text.replace(prize_currency, "").replace(" ", "").replace(",", ""))

            # Accumulate buyins/prizes in matching currency
            total_buyins.setdefault(currency, 0)
            total_buyins[currency] += buyin_amount
            if prize_currency == currency:
                total_prizes.setdefault(currency, 0)
                total_prizes[currency] += prize_amount

            # ROI for this event
            roi = prize_amount / buyin_amount
            roi_values.append(roi)

            # Group by year
            date_text = row.locator("td.date").inner_text().strip()
            year = int(date_text.split("-")[-1])
            stats_by_year.setdefault(year, []).append(roi)

        # Calculate overall average ROI
        average_roi = round(sum(roi_values) / len(roi_values), 4) if roi_values else 0.0

        # Build yearlyStatsText (reverse chronological)
        yearly_stats_text = "\n".join(
            f"{yr}: {len(vals)} tournaments, avg ROI {round(sum(vals)/len(vals), 4)}"
            for yr, vals in sorted(stats_by_year.items(), reverse=True)
        )

        # Build buy-ins and prizes text lists
        buyins_text = "\n".join(
            f"{cur} {amt:,}" for cur, amt in sorted(total_buyins.items())
        )
        prizes_text = "\n".join(
            f"{cur} {amt:,}" for cur, amt in sorted(total_prizes.items())
        )

        browser.close()

        return {
            "player": name,
            "totalTournaments": sum(len(vals) for vals in stats_by_year.values()),
            "totalBuyins": total_buyins,
            "totalBuyinsText": buyins_text,
            "totalPrizes": total_prizes,
            "totalPrizesText": prizes_text,
            "averageROIByCash": average_roi,
            "yearlyStatsText": yearly_stats_text
        }

@app.route("/", methods=["POST"])
def main():
    data = request.get_json() or {}
    url = data.get("url")
    if not url:
        return jsonify({"error": "Missing 'url' parameter"}), 400
    try:
        result = extract_data(url)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)








