import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, urlunparse
import argparse
import json
import sys
import time

visited = set()
errors = []

session = requests.Session()
session.headers.update({
    "User-Agent": "InternalHealthCheckBot/1.0"
})

def login(login_file):
    """Login using credentials from JSON file."""
    try:
        with open(login_file, "r") as f:
            creds = json.load(f)
    except Exception as e:
        print(f"Failed to read login file: {e}")
        sys.exit(1)

    resp = session.get(creds["login_url"])
    soup = BeautifulSoup(resp.text, "html.parser")
    form = soup.find("form")

    payload = {}
    for input_tag in form.find_all("input"):
        name = input_tag.get("name")
        value = input_tag.get("value", "")
        if name == "log":
            payload[name] = creds["username"]
        elif name == "pwd":
            payload[name] = creds["password"]
        else:
            payload[name] = value

    resp = session.post(
        creds["login_url"],
        data=payload,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Referer": creds["login_url"]
        },
        timeout=10
    )
    resp.raise_for_status()
    print("Login final URL:", resp.url)
    print("Redirects:", [r.status_code for r in resp.history])
    print(session.cookies.get_dict())

def normalize_url(url):
    parsed = urlparse(url)

    path = parsed.path.rstrip("/")

    return urlunparse((
        parsed.scheme,
        parsed.netloc,
        path,
        parsed.params,
        parsed.query,
        ""
    ))

def is_internal(url, base_url):
    return urlparse(url).netloc == urlparse(base_url).netloc

BLOCKED_PATHS = (
    "/logout",
    "/wp-admin",
    "/wp-json",
    "/download",
    "/wp-content",
    "?action="
)

def is_allowed(url, base_url):
    if not is_internal(url, base_url):
        return False
    
    for blocked in BLOCKED_PATHS:
        if blocked in url:
            return False
        
    return True

def crawl(url, base_url):
    url = normalize_url(url)

    if url in visited:
        return
    
    print(f"Crawling: {url}")
    visited.add(url)

    time.sleep(0.5)

    try:
        resp = session.get(url, timeout=10)
    except requests.RequestException as e:
        errors.append((url, str(e)))
        return
    
    status = resp.status_code
    if status >= 400:
        errors.append((url, status))
        return
    
    if "text/html" not in resp.headers.get("Content-Type", ""):
        return
    
    soup = BeautifulSoup(resp.text, "html.parser")
    for link in soup.find_all("a", href=True):
        if link["href"].startswith("#"):
            continue

        next_url = urljoin(url, link["href"])
        if is_allowed(next_url, base_url):
            crawl(next_url, base_url)

def main():
    parser = argparse.ArgumentParser(description="Simple authenticated web crawler")
    parser.add_argument("url", help="Base URL of the site to crawl")
    parser.add_argument("--login-file", help="JSON file with login credentials", default=None)
    args = parser.parse_args()

    if args.login_file:
        login(args.login_file)

    crawl(args.url, args.url)

    if errors:
        print("\nErrors found:")
        for url, status in errors:
            print(status, url)
    else:
        print("No errors found.")

if __name__ == "__main__":
    main()