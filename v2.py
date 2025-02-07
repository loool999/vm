from flask import Flask, render_template, request, jsonify, Response, send_from_directory
import threading
from selenium.webdriver import Chrome, ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException, InvalidArgumentException, StaleElementReferenceException, ElementNotInteractableException, MoveTargetOutOfBoundsException
import json
import os
from time import sleep
from urllib.parse import urlparse, urlunparse
import io
import base64
from PIL import Image
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys
import logging

# --- Configure Logging ---
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

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
        logging.error(f"save_cookies fail: {e}")
    else:
        logging.info("save_cookies done")

def load_cookies(driver: Chrome) -> None:
    try:
        added_cookies = set()  # Keep track of added cookies
        for key in sorted([key for key in db.keys() if key.isnumeric()], key=lambda key: int(key)):
            cookie: dict = db[key]
            cookie_id = (cookie['domain'], cookie['name']) # Unique identifier for the cookie

            if cookie_id not in added_cookies:
                url = assemble_url(cookie)
                try:
                    # Only navigate if the domain is different AND we haven't already added this cookie
                   if urlparse(driver.current_url).hostname != urlparse(url).hostname:
                        driver.get(url)
                except Exception as navigate_err:
                    logging.error(f"Navigation error during load_cookies: {navigate_err}")
                    continue # Skip this cookie if navigation fails
                try:
                    driver.add_cookie(cookie)
                    added_cookies.add(cookie_id)  # Mark this cookie as added
                except Exception as add_cookie_err:
                    logging.error(f"Error adding cookie: {add_cookie_err}")
    except Exception as e:
        logging.error(f"load_cookies fail: {e}")
    else:
        logging.info("load_cookies done")

def is_localstorage() -> bool:
    return len([key for key in db.keys() if key.isalpha()]) > 0

def save_localstorage(ls: LocalStorage) -> None:
    try:
        items = ls.items()  # Get the dictionary
        for key, value in items.items():  # Iterate over the dictionary's items
            db[key] = value
    except Exception as e:
        logging.error(f"save_localstorage fail: {e}")
    else:
        logging.info("save_localstorage done")

def load_localstorage(ls: LocalStorage) -> None:
    try:
        for key in [key for key in db.keys() if key.isalpha()]:
            ls[key] = db[key]
    except Exception as e:
        logging.error(f"load_localstorage fail: {e}")
    else:
        logging.info("load_localstorage done")

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
driver_lock = threading.Lock()  # Lock for thread-safe driver access

def run_browser(initial_url: str = "https://www.google.com"):
    global SINGLE_PAGE, driver, image_data
    validated_url = validate_url(initial_url)
    if validated_url is None:
        logging.error(f"Invalid URL: {initial_url}.  Using default URL.")
        validated_url = "https://www.google.com"
    SINGLE_PAGE = validated_url  # Always use the validated URL

    logging.info(f"Starting Ultimate Chrome 2 with URL: {SINGLE_PAGE}")

    chrome_options = ChromeOptions()
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--headless')
    chrome_options.add_argument("start-maximized")

    try:
        driver = Chrome(options=chrome_options)
        logging.info("Chrome driver started successfully.")  # Log successful start
    except WebDriverException as e:
        logging.error(f"Error starting Chrome: {e}")
        return


    with driver_lock: # Protect driver during initialization and ls creation
        ls = LocalStorage(driver)

        try:
            driver.get(SINGLE_PAGE)
            logging.info(f"Successfully navigated to {SINGLE_PAGE}")  # Log successful navigation
        except InvalidArgumentException as e:
            logging.error(f"Error navigating to {SINGLE_PAGE}: {e}")
            driver.quit()  # Quit the driver if initial navigation fails
            return
        except Exception as e:
            logging.error(f"An unexpected error occurred during initial navigation: {e}")
            driver.quit()
            return

        if is_cookies():
            logging.info("Found cookies!")
            load_cookies(driver)

        if is_localstorage():
            logging.info("Found LocalStorage data!")
            load_localstorage(ls)

    logging.info("Running in headless mode. Data saved periodically.")

    try:
        while True:
            # Capture screenshot and store in global variable
            with driver_lock:  # Acquire lock for driver access
                try:
                    img_binary = driver.get_screenshot_as_png()
                    img = Image.open(io.BytesIO(img_binary))
                    buffered = io.BytesIO()
                    img.save(buffered, format="JPEG")  # Convert to JPEG
                    image_data = base64.b64encode(buffered.getvalue()).decode("utf-8")
                except StaleElementReferenceException:
                    logging.warning("Stale element during screenshot.  Continuing...")
                    continue  # Try again in the next iteration
                except Exception as e:
                    logging.error(f"Error during screenshot capture: {e}")
                    break  # Exit loop on other screenshot errors

            sleep(0.1)  # Capture every 100ms

            with driver_lock:  # Acquire lock for driver access
                save_cookies(driver)
                if is_localstorage():
                    save_localstorage(ls)

    except KeyboardInterrupt:
        logging.info("Shutting down...")
    finally:
        with driver_lock:
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
    global driver
    if driver is None:
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
        return jsonify({'image': ''})

@app.route('/interact', methods=['POST'])
def interact():
    global driver
    data = request.get_json()
    logging.debug(f"Received interaction request: {data}")  # Log the received data

    with driver_lock:
        if not driver:
            return jsonify({'status': 'error', 'message': 'Browser not started'})

        try:
            action = data.get('action')
            x = data.get('x', 0)
            y = data.get('y', 0)
            text = data.get('text', '')
            key = data.get('key', '')

            if action == 'click':
                # Find the element at the click coordinates using JavaScript
                try:
                    #This is the crucial change. We find the element at the point using JS.
                    script = f'''
                        var element = document.elementFromPoint({x}, {y});
                        if (element) {{
                            element.click();
                            return true; // Indicate success
                        }} else {{
                            return false; // Indicate element not found
                        }}
                    '''
                    result = driver.execute_script(script)
                    if not result:
                        logging.warning(f"No element found at coordinates ({x}, {y})")
                        return jsonify({'status': 'error', 'message': 'No element found at click location'})


                except Exception as e:
                    logging.error(f"Error clicking element: {e}")
                    return jsonify({'status': 'error', 'message': str(e)})

            elif action == 'input':
                try:
                    # Find element, focus, and send keys via JavaScript
                    script = f'''
                        var element = document.elementFromPoint({x}, {y});
                        if (element) {{
                            element.focus();
                            element.value = "{text}"; // Set the value directly
                            return true;
                        }} else {{
                            return false;
                        }}
                    '''
                    result = driver.execute_script(script)
                    if not result:
                        logging.warning(f"No element found at coordinates ({x}, {y}) for input")
                        return jsonify({'status': 'error', 'message': 'No element found at input location'})

                except Exception as e:
                     logging.error(f"Error in input action: {e}")
                     return jsonify({'status': 'error', 'message': str(e)})

            elif action == 'scroll':
                driver.execute_script(f"window.scrollBy({x}, {y});")

            elif action == 'keypress':
                try:
                    # Find element, focus, and send key via JavaScript
                    if key == 'Enter':
                        script = f'''
                            var element = document.elementFromPoint({x}, {y});
                            if (element) {{
                                element.focus();
                                var event = new KeyboardEvent('keydown', {{
                                    key: 'Enter',
                                    code: 'Enter',
                                    which: 13,
                                    keyCode: 13,
                                    bubbles: true,
                                    cancelable: true
                                }});
                                element.dispatchEvent(event);
                                return true;
                            }} else {{
                                return false;
                            }}
                        '''
                        result = driver.execute_script(script)
                        if not result:
                            logging.warning(f"No element found at coordinates ({x}, {y}) for keypress")
                            return jsonify({'status': 'error', 'message': 'No element found at keypress location'})
                except Exception as e:
                     logging.error(f"Error in keypress action: {e}")
                     return jsonify({'status': 'error', 'message': str(e)})

            elif action == 'navigate':
                new_url = validate_url(text)
                if new_url:
                     driver.get(new_url)
                else:
                    return jsonify({'status': 'error', 'message': 'Invalid URL'})

            else:
                return jsonify({'status': 'error', 'message': 'Invalid action'})

            return jsonify({'status': 'success'})

        except Exception as e:
            logging.exception(f"An unexpected error occurred during interaction: {e}")  # Log full traceback
            return jsonify({'status': 'error', 'message': str(e)})

@app.route('/static/<path:path>')
def send_static(path):
    return send_from_directory('static', path)


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)