from flask import Flask, request, jsonify
from playwright.sync_api import sync_playwright
import re

app = Flask(__name__)

def extract_data(url):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(url)
        page.wait_for_selector('div.content')
        html = page.content()
        
        name = page.locator("h1").inner_text().strip()
        results = page.locator(".col-md-12 h4:has-text('Results') + div").inner_text()
        browser.close()

        return {
            "name": name,
            "raw_results": results
        }

@app.route("/", methods=["POST"])
def main():
    data = request.get_json()
    url = data.get("url")
    if not url:
        return jsonify({"error": "Missing URL"}), 400
    try:
        result = extract_data(url)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
