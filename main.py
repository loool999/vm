from flask import Flask, request, jsonify, render_template
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
import json
import os
from time import sleep
from threading import Thread

app = Flask(__name__)

# File-based storage for cookies and LocalStorage
COOKIE_FILE = "cookies.json"
LOCALSTORAGE_FILE = "localstorage.json"

def save_data(filename, data):
    with open(filename, "w") as f:
        json.dump(data, f, indent=2)

def load_data(filename):
    if os.path.exists(filename):
        with open(filename, "r") as f:
            return json.load(f)
    return {}

# Start Selenium WebDriver
def start_browser():
    global driver
    chrome_options = Options()
    chrome_options.add_argument('--headless')  # Run in the background
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument("start-maximized")

    driver = webdriver.Chrome(options=chrome_options)

    # Load saved cookies
    driver.get("https://google.com")  # Open a page to apply cookies
    cookies = load_data(COOKIE_FILE)
    for cookie in cookies:
        driver.add_cookie(cookie)
    
    driver.get("https://google.com")  # Reload page after setting cookies

# Background thread to keep browser running
def keep_browser_alive():
    while True:
        sleep(60)  # Save cookies every 60 seconds
        save_data(COOKIE_FILE, driver.get_cookies())

# Start browser on server start
start_browser()
thread = Thread(target=keep_browser_alive, daemon=True)
thread.start()

@app.route('/')
def index():
    return render_template("index.html")

@app.route('/search', methods=['POST'])
def search():
    query = request.json.get("query")
    driver.get("https://google.com")
    search_box = driver.find_element(By.NAME, "q")
    search_box.send_keys(query)
    search_box.submit()
    sleep(2)
    return jsonify({"message": "Search complete!"})

@app.route('/get_cookies', methods=['GET'])
def get_cookies():
    return jsonify(driver.get_cookies())

@app.route('/set_cookies', methods=['POST'])
def set_cookies():
    cookies = request.json.get("cookies", [])
    for cookie in cookies:
        driver.add_cookie(cookie)
    driver.get("https://google.com")  # Reload after setting cookies
    return jsonify({"message": "Cookies set successfully!"})

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
