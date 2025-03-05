from __future__ import annotations

import json
import os
from time import sleep
from urllib.parse import urlparse, urljoin
import base64
import threading

from selenium.webdriver import Chrome, ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException, InvalidArgumentException, StaleElementReferenceException, ElementNotInteractableException
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys

from flask import Flask, render_template, request, jsonify, Response

from localstorage import LocalStorage

# Configuration
SINGLE_PAGE = ""
DB_FILENAME = "db.json"
SCREENSHOT_INTERVAL = 0.1

class FileDB(dict):
    """File-based key-value storage."""
    def __init__(self, filename: str = DB_FILENAME):
        self.filename = filename
        self.load()

    def load(self):
        if os.path.exists(self.filename):
            try:
                with open(self.filename, "r") as f:
                    data = json.load(f)
                    super().__init__(data)
            except (FileNotFoundError, json.JSONDecodeError):
                super().__init__()
        else:
            super().__init__()

    def _save(self):
        try:
            with open(self.filename, "w") as f:
                json.dump(self, f, indent=2)
        except IOError as e:
            print(f"Error saving to {self.filename}: {e}")

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self._save()

    def __delitem__(self, key):
        super().__delitem__(key)
        self._save()

    def clear(self):
        super().clear()
        self._save()

db = FileDB()

def is_cookies() -> bool:
    return any(key.isnumeric() for key in db)

def assemble_url(cookie: dict) -> str:
    url = "https://" if cookie.get("secure", False) else "http://"
    url += cookie["domain"].lstrip(".")
    url += cookie["path"]
    return url

def save_cookies(driver: Chrome) -> None:
    print("Saving cookies...", end=" ")
    try:
        for key in list(db.keys()):
            if key.isnumeric():
                del db[key]
        for index, value in enumerate(driver.get_cookies()):
            db[str(index)] = value
        print("done")
    except Exception as e:
        print("fail", e)

def load_cookies(driver: Chrome) -> None:
    print("Loading cookies...", end=" ")
    try:
        for key in sorted([key for key in db if key.isnumeric()], key=int):
            cookie: dict = db[key]
            url = assemble_url(cookie)
            if urlparse(driver.current_url).hostname != urlparse(url).hostname:
                driver.get(url)
            driver.add_cookie(cookie)
        print("done")
    except Exception as e:
        print("fail", e)

def is_localstorage() -> bool:
    return any(key.isalpha() for key in db)

def save_localstorage(ls: LocalStorage) -> None:
    print("Saving LocalStorage...", end=" ")
    try:
        for key, value in ls.items():
            db[key] = value
        print("done")
    except Exception as e:
        print("fail", e)

def load_localstorage(ls: LocalStorage) -> None:
    print("Loading LocalStorage...", end=" ")
    assert SINGLE_PAGE, "SINGLE_PAGE must be set for LocalStorage to work."
    try:
        for key in [key for key in db if key.isalpha()]:
            ls[key] = db[key]
        print("done")
    except Exception as e:
        print("fail", e)

# --- Flask App Setup ---
app = Flask(__name__)
driver = None
ls = None
latest_screenshot = None
screenshot_lock = threading.Lock()
driver_lock = threading.Lock()  # Lock for driver access

def initialize_driver():
    global driver, ls
    if driver:
        return

    chrome_options = ChromeOptions()
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--disable-gpu')

    if SINGLE_PAGE:
        chrome_options.add_argument('--kiosk')
    else:
        chrome_options.add_argument("start-maximized")

    driver = Chrome(options=chrome_options)
    ls = LocalStorage(driver)

    if not SINGLE_PAGE:
        driver.get("https://google.com")
    else:
        driver.get(SINGLE_PAGE)

    if is_cookies():
        print("Found some cookies to restore!")
        load_cookies(driver)

    if SINGLE_PAGE and is_localstorage():
        print("Found some LocalStorage data to restore!")
        load_localstorage(ls)

    print("Driver initialized.")

def capture_screenshots():
    global latest_screenshot
    initialize_driver()
    while True:
        try:
            with screenshot_lock:
                screenshot = driver.get_screenshot_as_png()
                latest_screenshot = base64.b64encode(screenshot).decode('utf-8')
            sleep(SCREENSHOT_INTERVAL)
        except Exception as e:
            print(f"Error in capture_screenshots: {e}")
            sleep(1)

screenshot_thread = threading.Thread(target=capture_screenshots, daemon=True)
screenshot_thread.start()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/navigate', methods=['POST'])
def navigate():
    initialize_driver()
    url = request.form.get('url')
    if url:
        try:
            if not url.startswith(('http://', 'https://')):
                current_url = driver.current_url
                if current_url == 'data:,':
                    current_url = 'https://www.google.com'
                url = urljoin(current_url, url)

            driver.get(url)
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.TAG_NAME, 'body'))
            )
            return jsonify({'status': 'success', 'current_url': driver.current_url})
        except TimeoutException:
            return jsonify({'status': 'error', 'message': 'Timed out'})
        except InvalidArgumentException:
            return jsonify({'status': 'error', 'message': 'Invalid URL'})
        except WebDriverException as e:
            return jsonify({'status': 'error', 'message': str(e)})
    return jsonify({'status': 'error', 'message': 'No URL provided'})

@app.route('/get_screenshot')
def get_screenshot():
    global latest_screenshot
    with screenshot_lock:
        if latest_screenshot:
            return jsonify({'image': latest_screenshot})
        else:
            return jsonify({'error': 'No screenshot available'})

@app.route('/interact', methods=['POST'])
def interact():
    """Handles user interactions (clicks and key presses)."""
    initialize_driver()
    data = request.get_json()
    if not data:
        return jsonify({'status': 'error', 'message': 'No interaction data provided'})

    action_type = data.get('type')
    x = data.get('x')
    y = data.get('y')
    key = data.get('key')

    with driver_lock:  # Ensure exclusive access to the driver
        try:
            if action_type == 'click' and x is not None and y is not None:
                # Use ActionChains for more reliable clicks
                actions = ActionChains(driver)
                actions.move_by_offset(x, y).click().perform()
                actions.move_by_offset(-x,-y).perform() # prevents errors
            elif action_type == 'keypress' and key is not None:
                 # Convert special key names to Selenium Keys
                if key == 'Enter':
                    selenium_key = Keys.ENTER
                elif key == 'Backspace':
                    selenium_key = Keys.BACKSPACE
                elif key == 'Tab':
                    selenium_key = Keys.TAB
                # ... add more special key mappings as needed ...
                else:
                    selenium_key = key
                
                actions = ActionChains(driver)
                actions.send_keys(selenium_key).perform()

            return jsonify({'status': 'success'})

        except StaleElementReferenceException:
            return jsonify({'status': 'error', 'message': 'Element is stale'})
        except ElementNotInteractableException:
            return jsonify({'status': 'error', 'message': 'Element not interactable'})
        except Exception as e:
            return jsonify({'status': 'error', 'message': str(e)})
        

@app.route('/shutdown', methods=['POST'])
def shutdown():
    global driver
    if driver:
        save_cookies(driver)
        if SINGLE_PAGE and ls:
            save_localstorage(ls)
        driver.quit()
        driver = None
        print("Driver shut down.")
        return jsonify({'status': 'success'})
    return jsonify({'status': 'error', 'message': 'Driver not initialized'})

if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=5000)