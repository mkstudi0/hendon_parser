from flask import Flask, request, jsonify
from playwright.sync_api import sync_playwright

app = Flask(__name__)

def extract_data(url):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, timeout=60000)
        page.wait_for_selector("h1", timeout=15000)

        # Получаем имя игрока
        name = page.locator("h1").inner_text().strip()

        # Пытаемся найти блок с результатами
        try:
            results_section = page.locator("h4:has-text('Results') + div")
            results = results_section.inner_text().strip()
        except Exception:
            results = "Результаты не найдены"

        browser.close()
        return {
            "name": name,
            "raw_results": results
        }

@app.route("/", methods=["POST"])
def main():
    try:
        data = request.get_json()
        if not data or "url" not in data:
            return jsonify({"error": "Missing 'url' in request"}), 400

        url = data["url"]
        result = extract_data(url)
        return jsonify(result)

    except Exception as e:
        return jsonify({"error": str(e)}), 500

import os

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

