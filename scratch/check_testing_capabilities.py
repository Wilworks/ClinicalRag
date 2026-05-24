import sys
import subprocess

print("Python version:", sys.version)

libraries = ["selenium", "playwright", "pyppeteer", "requests_html", "webdriver_manager"]
for lib in libraries:
    try:
        __import__(lib)
        print(f"Library '{lib}' is INSTALLED")
    except ImportError:
        print(f"Library '{lib}' is NOT installed")

# Check if chrome is on path
try:
    chrome_ver = subprocess.check_output(["reg", "query", "HKEY_CURRENT_USER\\Software\\Google\\Chrome\\BLBeacon", "/v", "version"], stderr=subprocess.DEVNULL)
    print("Chrome registry version:", chrome_ver.decode().strip())
except Exception as e:
    print("Chrome registry version could not be read:", e)
