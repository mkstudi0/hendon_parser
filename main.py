import os
import traceback
from flask import Flask, request, jsonify
from playwright.sync_api import sync_playwright

app = Flask(__name__)

# Health check endpoint
@app.route("/", methods=["GET"])
def home():
    return jsonify({"status": "OK"}), 200

# Main POST endpoint to process profile URL
@app.route("/", methods=["POST"])
def parse_profile():
    try:
        data = request.get_json(force=True)
        print("Request data:", data)

        if not data or "url" not in data:
            return jsonify({"error": "Missing 'url' in request"}), 400

        url = data["url"]
        result = extract_data(url)
        print("Result:", result)
        return jsonify(result), 200

    except Exception as e:
        # Log full traceback for debugging
        tb = traceback.format_exc()
        print(tb)
        return jsonify({"error": str(e), "trace": tb}), 500


def extract_data(url):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, timeout=60000)
        page.wait_for_selector("h1", timeout=15000)

        name = page.locator("h1").inner_text().strip()
        try:
            results_section = page.locator("h4:has-text('Results') + div")
            results = results_section.inner_text().strip()
        except Exception:
            results = "Результаты не найдены"

        browser.close()
        return {"name": name, "raw_results": results}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)


