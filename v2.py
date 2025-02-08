from flask import Flask, render_template, request, jsonify, Response
import threading
from selenium.webdriver import Chrome, ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException, InvalidArgumentException
import json
import os
from time import sleep
from urllib.parse import urlparse, urlunparse
import io
import base64
from PIL import Image

# --- Selenium Code ---

class LocalStorage:
    def __init__(self, driver):
        self.driver = driver

    def __len__(self):
        return self.driver.execute_script("return localStorage.length;")

    def items(self):
        return self.driver.execute_script(
            "var ls = window.localStorage, items = {}; "
            "for (var i = 0, k; i < ls.length; ++i) "
            "  items[k = ls.key(i)] = ls.getItem(k); "
            "return items; "
        )

    def keys(self):
        return self.driver.execute_script(
            "var ls = window.localStorage, keys = []; "
            "for (var i = 0; i < ls.length; ++i) "
            "  keys[i] = ls.key(i); "
            "return keys; "
        )

    def get(self, key):
        return self.driver.execute_script("return localStorage.getItem(arguments[0]);", key)

    def set(self, key, value):
        self.driver.execute_script("localStorage.setItem(arguments[0], arguments[1]);", key, value)
        return value

    def has(self, key):
        return key in self.keys()

    def delete(self, key):
        self.driver.execute_script("localStorage.removeItem(arguments[0]);", key)

    def clear(self):
        self.driver.execute_script("localStorage.clear();")

    def __getitem__(self, key):
        value = self.get(key)
        if value is None:
            raise KeyError(key)
        return value

    def __setitem__(self, key, value):
        self.set(key, value)

    def __contains__(self, key):
        return self.has(key)

    def __delitem__(self, key):
        if key not in self:
            raise KeyError(key)
        self.delete(key)



class FileDB(dict):
    """
    A simple file-based key-value storage.
    """
    def __init__(self, filename: str = "db.json"):
        self.filename = filename
        if os.path.exists(filename):
            try:
                with open(filename, "r") as f:
                    data = json.load(f)
                    super().__init__(data)
            except Exception:
                super().__init__()
        else:
            super().__init__()

    def _save(self):
        with open(self.filename, "w") as f:
            json.dump(self, f, indent=2)

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
    return len([key for key in db.keys() if key.isnumeric()]) > 0

def assemble_url(cookie: dict) -> str:
    url = "https://" if cookie.get("secure", False) else "http://"
    url += cookie["domain"].lstrip(".")
    url += cookie["path"]
    return url

def save_cookies(driver: Chrome) -> None:
    try:
        for key in [key for key in list(db.keys()) if key.isnumeric()]:
            del db[key]
        for index, value in enumerate(driver.get_cookies()):
            db[str(index)] = value
    except Exception as e:
        print("fail", e)
    else:
        print("done")

def load_cookies(driver: Chrome) -> None:
    try:
        for key in sorted([key for key in db.keys() if key.isnumeric()], key=lambda key: int(key)):
            cookie: dict = db[key]
            url = assemble_url(cookie)
            if urlparse(driver.current_url).hostname != urlparse(url).hostname:
                driver.get(url)
            driver.add_cookie(cookie)
    except Exception as e:
        print("fail", e)
    else:
        print("done")

def is_localstorage() -> bool:
    return len([key for key in db.keys() if key.isalpha()]) > 0

def save_localstorage(ls: LocalStorage) -> None:
    try:
        for key, value in ls.items():
            db[key] = value
    except Exception as e:
        print("fail", e)
    else:
        print("done")

def load_localstorage(ls: LocalStorage) -> None:
    assert SINGLE_PAGE, "SINGLE_PAGE must be set"
    try:
        for key in [key for key in db.keys() if key.isalpha()]:
            ls[key] = db[key]
    except Exception as e:
        print("fail", e)
    else:
        print("done")

def validate_url(url):
    """Validates and formats a URL."""
    try:
        result = urlparse(url)
        if all([result.scheme, result.netloc]):  # Check for scheme and netloc
            return url  # URL is already valid
        if not result.scheme:
            result = result._replace(scheme='http')  # Add http if missing
        return urlunparse(result)
    except:
        return None

SINGLE_PAGE = ""  # Global variable for the URL
driver = None  # Global driver variable
image_data = None # Global variable to store the latest image

def run_browser(initial_url: str = "https://www.google.com"):
    global SINGLE_PAGE, driver, image_data
    validated_url = validate_url(initial_url)
    if validated_url is None:
        print(f"Invalid URL: {initial_url}.  Using default URL.")
        validated_url = "https://www.google.com"
    SINGLE_PAGE = validated_url

    print(f"Starting Ultimate Chrome 2 with URL: {SINGLE_PAGE}")

    chrome_options = ChromeOptions()
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--headless')

    if SINGLE_PAGE:
        chrome_options.add_argument('--kiosk')
    else:
        chrome_options.add_argument("start-maximized")

    try:
        driver = Chrome(options=chrome_options)
    except WebDriverException as e:
        print(f"Error starting Chrome: {e}")
        return

    ls = LocalStorage(driver)

    try:
        if driver:  # Check if driver was successfully created
            driver.get(SINGLE_PAGE)
    except InvalidArgumentException as e:
        print(f"Error navigating to {SINGLE_PAGE}: {e}")
        return
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return


    if is_cookies():
        print("Found cookies!")
        load_cookies(driver)

    if SINGLE_PAGE and is_localstorage():
        print("Found LocalStorage data!")
        load_localstorage(ls)

    if not SINGLE_PAGE:
        try:
            search_box = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.NAME, "q"))
            )
            search_box.send_keys("ready")
        except TimeoutException:
            print("Search box not found.")

    print("Running in headless mode. Data saved periodically.")

    try:
        while True:
            # Capture screenshot and store in global variable
            if driver:
                img_binary = driver.get_screenshot_as_png()
                img = Image.open(io.BytesIO(img_binary))
                buffered = io.BytesIO()
                img.save(buffered, format="JPEG")  # Convert to JPEG for smaller size
                image_data = base64.b64encode(buffered.getvalue()).decode("utf-8")
            sleep(0)  # Capture every 100ms
            if driver:
                save_cookies(driver)
            if SINGLE_PAGE and driver:
                save_localstorage(ls)

    except KeyboardInterrupt:
        print("Shutting down...")
    finally:
        if driver:
            save_cookies(driver)
            driver.quit()


# --- Flask App Setup ---

app = Flask(__name__)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/start_browser', methods=['POST'])
def start_browser_route():
    global driver  # Access the global driver variable
    if driver is None: # Only start a new browser if one isn't already running
        url = request.form.get('url', 'https://www.google.com')
        thread = threading.Thread(target=run_browser, args=(url,))
        thread.daemon = True
        thread.start()
        return jsonify({'status': 'Browser started'})
    else:
        return jsonify({'status': 'Browser already running'})

@app.route('/get_image')
def get_image():
    global image_data
    if image_data:
        return jsonify({'image': image_data})
    else:
        return jsonify({'image': ''})  # Return empty string if no image yet


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)