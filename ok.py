import tempfile
import subprocess
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

def kill_existing_chrome():
    try:
        subprocess.run(["pkill", "chrome"], check=True)
    except Exception as e:
        print("No existing chrome processes or error killing them:", e)

def start_browser():
    # First, kill any existing Chrome processes.
    kill_existing_chrome()

    chrome_options = Options()
    # Remove headless if you need to see the window.
    # chrome_options.add_argument('--headless')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument("start-maximized")

    # Create a new, unique temporary directory for the user data.
    temp_dir = tempfile.mkdtemp()
    chrome_options.add_argument(f"--user-data-dir={temp_dir}")
    print("Using temporary user data dir:", temp_dir)

    driver = webdriver.Chrome(options=chrome_options)
    driver.get("https://google.com")
    return driver

if __name__ == "__main__":
    driver = start_browser()
    # Do your Selenium operations...
