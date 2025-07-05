import os
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify

app = Flask(__name__)

SCRAPER_KEY = os.getenv("SCRAPER_API_KEY")

def parse_money(s: str):
    # Убираем символы валюты и разделители
    try:
        return float(s.replace("$","").replace(",","").strip())
    except:
        return 0.0

def extract_data(url):
    # 1) Получаем HTML через ScraperAPI
    resp = requests.get(
        "https://api.scraperapi.com",
        params={"api_key": SCRAPER_KEY, "url": url},
        timeout=30
    )
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    # 2) Имя игрока
    name = soup.find("h1").get_text(strip=True)

    # 3) Собираем все строки результатов из таблицы
    rows = soup.select("table.results tbody tr")
    data = []
    for tr in rows:
        cols = [td.get_text(strip=True) for td in tr.find_all("td")]
        # Предположим: [Date, Event, Buy-in, Prize, ROI, ...]
        if len(cols) >= 4:
            date, event, buyin, prize = cols[0], cols[1], cols[2], cols[3]
            data.append({
                "date": date,
                "event": event,
                "buyin": parse_money(buyin),
                "prize": parse_money(prize),
            })

    # 4) Считаем метрики
    total_tournaments = len(data)
    total_buyin = sum(d["buyin"] for d in data)
    total_prize = sum(d["prize"] for d in data)
    avg_roi = (total_prize - total_buyin) / total_buyin if total_buyin else 0.0

    return {
        "name": name,
        "total_tournaments": total_tournaments,
        "total_buyin": total_buyin,
        "total_prize": total_prize,
        "average_roi": round(avg_roi, 4)
    }

@app.route("/", methods=["POST"])
def main_route():
    body = request.get_json() or {}
    url = body.get("url")
    if not url:
        return jsonify({"error": "Missing 'url'"}), 400
    try:
        result = extract_data(url)
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)



