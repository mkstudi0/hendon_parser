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

def parse\_money(text):  
    """  
    Parse a string like '$ 1,500' or '€ 550' and return (currency, amount).  
    """  
    match \= re.search(r"(\[€$\])\\s\*(\[\\d,\]+)", text)  
    if not match:  
        return None, 0.0  
    symbol, number \= match.groups()  
    amount \= float(number.replace(",", ""))  
    currency \= "USD" if symbol \== "$" else "EUR"  
    return currency, amount

def extract_data(player_url):
    # 1) Fetch page via ScraperAPI using ULTRA PREMIUM proxies
    # This section is configured for a paid plan.
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

    \# 3\) Collect rows for offline tournaments only  
    rows \= soup.select("table.table--player-results tbody tr")  
    offline\_rows \= \[r for r in rows if (ev := r.select\_one("td.event\_name")) and "Online" not in ev.get\_text()\]  
    total\_tournaments \= len(offline\_rows)

    \# 4\) Prepare accumulators  
    total\_buyins \= {}  
    total\_prizes \= {}  
    overall\_roi\_values \= \[\]  
    year\_counts \= {}  
    year\_roi\_values \= {}

    \# 5\) Process each offline tournament  
    for row in offline\_rows:  
        \# Extract year  
        year \= None  
        if (date\_td := row.select\_one("td.date")) and (m\_year := re.search(r"(\\d{4})", date\_td.get\_text())):  
            year \= m\_year.group(1)  
            year\_counts\[year\] \= year\_counts.get(year, 0\) \+ 1  
            year\_roi\_values.setdefault(year, \[\])

        \# BUY-IN parsing  
        buyin\_amount \= 0.0  
        buyin\_currency \= None  
        for a in row.select("td.event\_name a"):  
            if not a.find('img'):  
                text \= a.get\_text().strip()  
                if (match := re.match(r'^\[€$0-9\\+,\\s\]+', text)):  
                    part \= match.group(0)  
                    nums \= re.findall(r'\[0-9\]\[0-9,\]\*', part)  
                    total\_val \= sum(float(n.replace(',', '')) for n in nums)  
                    if part.startswith('$'):  
                        curr \= 'USD'  
                    elif part.startswith('€'):  
                        curr \= 'EUR'  
                    else:  
                        curr \= None  
                    if curr:  
                        buyin\_amount \= total\_val  
                        buyin\_currency \= curr  
                        total\_buyins\[curr\] \= total\_buyins.get(curr, 0.0) \+ total\_val  
                break

        \# PRIZE parsing  
        prize\_amount \= 0.0  
        for cell in row.select("td.currency"):  
            txt \= cell.get\_text(strip=True)  
            if txt:  
                curr, val \= parse\_money(txt)  
                if buyin\_currency and curr \== buyin\_currency:  
                    prize\_amount \= val  
                    total\_prizes\[curr\] \= total\_prizes.get(curr, 0.0) \+ val  
                    break

        \# ROI calculation  
        if buyin\_amount \> 0:  
            roi \= prize\_amount / buyin\_amount  
            overall\_roi\_values.append(roi)  
            if year:  
                year\_roi\_values\[year\].append(roi)

    \# 6\) Compute overall average ROI  
    average\_roi \= round(sum(overall\_roi\_values) / total\_tournaments, 4\) if total\_tournaments else 0.0

    \# 7\) Compute yearly stats sorted descending by year  
    yearly\_stats \= \[\]  
    for yr, count in sorted(year\_counts.items(), key=lambda x: int(x\[0\]), reverse=True):  
        rois \= year\_roi\_values.get(yr, \[\])  
        avg \= round(sum(rois) / count, 4\) if count else 0.0  
        yearly\_stats.append({  
            "year": int(yr),  
            "tournaments": count,  
            "averageROIByCash": avg  
        })

    \# 8\) Build multi-line yearly text  
    yearly\_text\_lines \= \[f"{s\['year'\]}: {s\['tournaments'\]} tournaments, avg ROI {s\['averageROIByCash'\]}" for s in yearly\_stats\]  
    yearly\_text \= "\\n".join(yearly\_text\_lines)

    \# 9\) Build dynamic buy-ins text for any currency  
    buyins\_text\_lines \= \[f"{cur}: {amt}" for cur, amt in total\_buyins.items()\]  
    buyins\_text \= "\\n".join(buyins\_text\_lines)

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
