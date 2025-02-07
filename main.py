from flask import Flask, request, jsonify, render_template, current_app
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException, InvalidArgumentException
import json
import os
from time import sleep
from threading import Thread, Event, local
import base64
from io import BytesIO
import uuid
import shutil
import psutil  # Import psutil


app = Flask(__name__)

COOKIE_FILE = "cookies.json"
# Use thread-local storage (optional, for extra safety)
thread_local = local()
browser_running = False
browser_ready = Event()
current_uuid = 1

def save_data(filename, data):
    try:
        with open(filename, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"Error saving data to {filename}: {e}")

def load_data(filename):
    try:
        if os.path.exists(filename):
            with open(filename, "r") as f:
                return json.load(f)
        return []
    except Exception as e:
        print(f"Error loading data from {filename}: {e}")
        return []

def kill_chrome_processes():
    """Kills all Chrome and chromedriver processes."""
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            if proc.info['name'] in ('chrome', 'chromedriver', 'chrome.exe', 'chromedriver.exe'):
                print(f"Killing process: {proc.info['name']} (PID: {proc.info['pid']})")
                proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass

def start_browser():
    global browser_running, current_uuid
    with app.app_context():  # Explicitly push the application context
        kill_chrome_processes() # Kill any existing processes
        if browser_running:
            print("Browser already running.")
            return

        chrome_options = Options()
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument("start-maximized")
        current_uuid = str(uuid.uuid4())
        user_data_dir = f"tmp/chrome_profile_1"
        chrome_options.add_argument(f"--user-data-dir={user_data_dir}")

        try:
            thread_local.driver = webdriver.Chrome(options=chrome_options)
            browser_running = True
            thread_local.driver.get("https://google.com")
            cookies = load_data(COOKIE_FILE)
            for cookie in cookies:
                try:
                    thread_local.driver.add_cookie(cookie)
                except InvalidArgumentException as e:
                    print(f"Invalid cookie format: {e}")
                except Exception as e:
                    print("Error adding cookie:", e)
            thread_local.driver.get("https://google.com")
            browser_ready.set()

        except Exception as e:
            print(f"Error starting browser: {e}")
            browser_running = False


def keep_browser_alive():
    global browser_running
    while browser_running:
        sleep(60)
        if not browser_running:
            break
        try:
            if hasattr(thread_local, 'driver') and thread_local.driver:
                cookies = thread_local.driver.get_cookies()
                save_data(COOKIE_FILE, cookies)
        except WebDriverException as e:
            print(f"WebDriverException in keep_browser_alive: {e}")
            browser_running = False
            break
        except Exception as e:
            print(f"Error in keep_browser_alive: {e}")

def get_driver():
    """Gets the driver from thread-local storage."""
    if not browser_ready.wait(timeout=30):
        raise TimeoutError("Browser initialization timed out")
    if not browser_running or not hasattr(thread_local, 'driver') or thread_local.driver is None:
        raise RuntimeError("Browser not running")
    return thread_local.driver


@app.route('/')
def index():
    if not browser_running:
        thread = Thread(target=start_browser)
        thread.start()
    return render_template("index.html")

@app.route('/search', methods=['POST'])
def search():
    try:
        driver = get_driver()
        query = request.json.get("query")
        if not query:
            return jsonify({"error": "Query parameter is required"}), 400

        driver.get("https://google.com")
        search_box = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.NAME, "q"))
        )
        search_box.clear()
        search_box.send_keys(query)
        search_box.submit()
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "search"))
        )
        return jsonify({"message": "Search complete!"})

    except TimeoutError as e:
        return jsonify({"error": str(e)}), 503
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 503
    except TimeoutException:
        return jsonify({"error": "Search timed out"}), 504
    except WebDriverException as e:
        print(f"WebDriverException during search: {e}")
        return jsonify({"error": "WebDriver error during search"}), 500
    except Exception as e:
        print(f"Error during search: {e}")
        return jsonify({"error": "An unexpected error occurred"}), 500


@app.route('/get_cookies', methods=['GET'])
def get_cookies():
    try:
        driver = get_driver()
        return jsonify(driver.get_cookies())
    except (TimeoutError, RuntimeError) as e:
        return jsonify({"error": str(e)}), 503
    except Exception as e:
        return jsonify({"error": "Error getting cookies"}), 500

@app.route('/set_cookies', methods=['POST'])
def set_cookies():
    try:
        driver = get_driver()
        cookies = request.json.get("cookies", [])
        if not isinstance(cookies, list):
            return jsonify({"error": "Cookies must be a list"}), 400

        driver.get("https://google.com")
        for cookie in cookies:
            driver.add_cookie(cookie)
        driver.get("https://google.com")
        return jsonify({"message": "Cookies set successfully!"})
    except (TimeoutError, RuntimeError) as e:
        return jsonify({"error": str(e)}), 503
    except Exception as e:
        return jsonify({"error": f"Error setting cookies: {e}"}), 500

@app.route('/screenshot')
def screenshot():
    try:
        driver = get_driver()
        screenshot_base64 = driver.get_screenshot_as_base64()
        return jsonify({"screenshot": screenshot_base64})
    except (TimeoutError, RuntimeError) as e:
        return jsonify({"error": str(e)}), 503
    except Exception as e:
        return jsonify({"error": "Error taking screenshot"}), 500

@app.route('/stop_browser', methods=['POST'])
def stop_browser():
    global browser_running, current_uuid
    try:
        if hasattr(thread_local, 'driver') and thread_local.driver:
            thread_local.driver.quit()
            del thread_local.driver  # Remove from thread-local storage
        if current_uuid:
            user_data_dir = f"/tmp/chrome_profile_{current_uuid}"
            if os.path.exists(user_data_dir):
                shutil.rmtree(user_data_dir)
                print(f"Deleted user data directory: {user_data_dir}")
    except Exception as e:
        print(f"Error quitting driver or deleting directory: {e}")

    browser_running = False
    current_uuid = None
    browser_ready.clear()
    return jsonify({"message": "Browser stopped"})

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)