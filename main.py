import os
import re
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify

app = Flask(__name__)

SCRAPER_KEY = os.getenv("SCRAPER_API_KEY")
SCRAPER_ENDPOINT = "https://api.scraperapi.com"


def parse_money(text):
    """Парсит строку вида '$ 1,500' или '€ 550', возвращает (currency, value)."""
    m = re.match(r"([€$])\s*([\d,]+)", text.strip())
    if not m:
        return None, 0.0
    symbol, num = m.groups()
    # Убираем запятые
    val = float(num.replace(",", ""))
    curr = "USD" if symbol == "$" else "EUR"
    return curr, val


def extract_data(profile_url):
    # 1) Обход Cloudflare через ScraperAPI
    resp = requests.get(
        SCRAPER_ENDPOINT,
        params={"api_key": SCRAPER_KEY, "url": profile_url},
        timeout=30
    )
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    # 2) Имя игрока из <title> до двоеточия
    title = soup.title.string or ""
    name = title.split(":", 1)[0].strip()

    # 3) Сбор только офлайн-турниров: фильтрация строк без 'Online'
    rows = soup.select("table.results tbody tr")
    offline_rows = [row for row in rows
                    if row.find("td", class_="event_name")
                    and "Online" not in row.find("td", class_="event_name").get_text()]

    total_tournaments = len(offline_rows)

    # 4) Подсчёт buy-ins, prizes и ROI
    buyins = {}
    prizes = {}
    roi_list = []

    for row in offline_rows:
        # 4.1) BUY-IN
        ev_td = row.find("td", class_="event_name")
        buyin_total = 0.0
        buyin_curr = None
        if ev_td:
            link = ev_td.find_all("a")[-1]
            parts = re.findall(r"[€$]\s*[\d,]+", link.get_text())
            for part in parts:
                curr, val = parse_money(part)
                buyin_total += val
                buyins[curr] = buyins.get(curr, 0.0) + val
                buyin_curr = curr

        # 4.2) PRIZE
        prize_total = 0.0
        cells = row.find_all("td", class_="currency")
        for cell in cells:
            text = cell.get_text(strip=True)
            if text:
                curr, val = parse_money(text)
                if buyin_curr:
                    if curr == buyin_curr:
                        prize_total = val
                        prizes[curr] = prizes.get(curr, 0.0) + val
                        break
                else:
                    prize_total += val
                    prizes[curr] = prizes.get(curr, 0.0) + val

        # 4.3) ROI для турнира
        if buyin_total > 0:
            roi_list.append(prize_total / buyin_total)

    # 5) Суммарный ROI
    roi_sum = sum(roi_list)

    return {
        "name": name,
        "total_tournaments": total_tournaments,
        "total_buyins": buyins,
        "total_prizes": prizes,
        "roi_sum": round(roi_sum, 4)
    }


@app.route("/", methods=["POST"])
def main_route():
    data = request.get_json() or {}
    url = data.get("url")
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




