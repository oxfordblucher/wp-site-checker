import requests
import argparse
import json
import sys
import time
import csv
import re
import collections
import concurrent.futures
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, urlunparse, urlencode, parse_qs
from importlib.metadata import version


class SiteHealthChecker:
    def __init__(self, args):
        self.base_url = args.url
        self.delay = args.delay
        self.timeout = args.timeout
        self.output = args.output
        self.max_workers = args.workers
        self.spider = args.spider
        
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        })

        self.visited = set()
        self.errors = []

        self.exclude_patterns = self._compile_exclude_patterns(args.exclude)

        if args.cookie:
            self._load_cookie(args.cookie)
        elif args.login_file:
            self._login(args.login_file)


    def _compile_exclude_patterns(self, patterns):
        blocked_paths = [
            "/logout",
            "/wp-admin",
            "/wp-json",
            "/download",
            "/wp-content",
            "?action="
        ]
        if patterns:
            blocked_paths.extend([p.strip() for p in patterns.split(",") if p.strip()])
        return [re.compile(re.escape(p)) for p in blocked_paths]


    def _load_cookie(self, cookie_str):
        """Allows direct injection of an authentication cookie payload string into header"""
        print("[*] Loading cookie from string...")
        if "=" in cookie_str:
            name, value = cookie_str.split("=", 1)
            self.session.cookies.set(name.strip(), value.strip(), domain=urlparse(self.base_url).netloc)
        else:
            print("Error: --cookie must be in NAME=VALUE format")
            sys.exit(1)


    def _login(self, login_file):
        """Login using credentials from JSON file."""
        try:
            with open(login_file, "r") as f:
                creds = json.load(f)
        except Exception as e:
            print(f"Failed to read login file: {e}")
            sys.exit(1)

        resp = self.session.get(creds["login_url"])
        soup = BeautifulSoup(resp.text, "html.parser")
        form = soup.find("form")
        if not form:
            print("Login form not found on the page.")
            sys.exit(1)

        payload = {}
        for input_tag in form.find_all("input"):
            name = input_tag.get("name")
            if name in creds:
                payload[name] = creds[name]
            else:
                payload[name] = input_tag.get("value", "")

        resp = self.session.post(
            creds["login_url"],
            data=payload,
            headers={
                "Referer": creds["login_url"]
            },
            timeout=self.timeout
        )
        resp.raise_for_status()
        if resp.url == creds["login_url"] or "login" in resp.url:
            print("Login failed, redirected back to login page")
            sys.exit(1)
        print("Login final URL:", resp.url)
        print("Redirects:", [r.status_code for r in resp.history])

    def is_allowed(self, url):
        if not self.is_internal(url, self.base_url):
            return False
        
        for blocked in self.exclude_patterns:
            if blocked.search(url):
                return False
            
        return True
    

    def normalize_url(self, url):
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
    

    def is_internal(self, url, base_url):
        return urlparse(url).netloc == urlparse(base_url).netloc


    def discover_links(self, url: str | None):
        """Discover links from the given sitemap URL or will scan for them."""
        sitemap_paths = [url] if url else["/sitemap.xml", "/sitemap_index.xml", "/wp-sitemap.xml"]
        discovered = set()

        for path in sitemap_paths:
            target = urljoin(self.base_url, path)
            links = self._extract_links(target)
            if links:
                discovered.update(links)
                break

        if not discovered:
            print("No sitemap found, crawling from homepage...")
            discovered.add(self.normalize_url(self.base_url))

        return [u for u in discovered if self.is_allowed(u)]


    def _extract_links(self, sitemap_url, _visited=None):
        """Recursively extract links from a sitemap XML."""
        if _visited is None:
            _visited = set()
        urls = set()
        if sitemap_url in _visited:
            return urls
        
        try:
            resp = self.session.get(sitemap_url, timeout=self.timeout)
            if resp.status_code != 200:
                return urls
            root = ET.fromstring(resp.content)
            ns = {"ns": root.tag.split("}")[0].strip("{")} if "}" in root.tag else {}

            submaps = root.findall(".//ns:sitemap/ns:loc", ns) if ns else root.findall(".//sitemap/loc")
            if submaps:
                for sub in submaps:
                    urls.update(self._extract_links(sub.text.strip(), _visited))
            else:
                locs = root.findall(".//ns:url/ns:loc", ns) if ns else root.findall(".//url/loc")
                for loc in locs:
                    urls.add(loc.text.strip())
        except Exception:
            pass
        return urls


    def crawl(self, url):

        found_links = []

        try:
            time.sleep(self.delay)
            resp = self.session.get(url, timeout=self.timeout)
            if resp.status_code >= 400:
                self.errors.append((url, resp.status_code, resp.reason))
                return []
            
            if self.spider and "text/html" in resp.headers.get("Content-Type", ""):
                soup = BeautifulSoup(resp.text, "html.parser")
                for link in soup.find_all("a", href=True):
                    if link["href"].startswith("#") or link["href"].startswith("javascript:"):
                        continue

                    next_url = self.normalize_url(urljoin(url, link["href"]))
                    if self.is_allowed(next_url):
                        found_links.append(next_url)

        except requests.RequestException as e:
            self.errors.append((url, None, str(e)))
        
        return found_links

    
    def run(self, sitemap_url: str | None, output_file: str | None):
        initial_urls = self.discover_links(sitemap_url)
        queue = collections.deque(initial_urls)
        
        enqueued = set(initial_urls)
        self.visited.update(initial_urls)

        print(f"Starting crawl with up to {self.max_workers} workers...")

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            to_dos = {}

            while queue or to_dos:
                while queue and len(to_dos) < self.max_workers * 2:
                    target = queue.popleft()
                    future = executor.submit(self.crawl, target)
                    to_dos[future] = target

                done, _ = concurrent.futures.wait(to_dos.keys(), return_when=concurrent.futures.FIRST_COMPLETED)
                for completed in done:
                    url = to_dos.pop(completed)
                    try:
                        new_links = completed.result()
                        for link in new_links:
                            if link not in self.visited and link not in enqueued:
                                queue.append(link)
                                enqueued.add(link)
                                self.visited.add(link)
                    except Exception as e:
                        self.errors.append((url, None, str(e)))

        self.generate_report(output_file)
        return len(self.errors) == 0
    

    def generate_report(self, output_file):
        if self.errors:
            print("\nErrors encountered during crawl:")
            for url, status, message in self.errors:
                print(f"{url} - {status} - {message}")
        if output_file:
            try:
                with open(output_file, mode="w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow(["URL", "Status"])
                    for url, status, message in self.errors:
                        writer.writerow([url, status, message])
            except Exception as e:
                print(f"Failed to write report: {e}")


def main():
    parser = argparse.ArgumentParser(description="Simple authenticated web crawler")
    parser.add_argument("url", help="Base URL of the site to crawl")
    parser.add_argument("-w", "--workers", help="Simultaneous workers", type=int, default=5)
    parser.add_argument("-d", "--delay", help="Delay between requests to be polite", type=float, default=0.1)
    parser.add_argument("-t", "--timeout", help="Request timeout", type=int, default=10)
    parser.add_argument("-o", "--output", help="Optional output filepath destination")
    parser.add_argument("-e", "--exclude", help="Comma-separated list of paths to exclude")
    parser.add_argument("-lf", "--login-file", help="JSON file with login credentials")
    parser.add_argument("-c", "--cookie", help="Pass authentication cookie payload into request header")
    parser.add_argument("-sm", "--sitemap", help="Optional path to sitemap. Format: /sitemap.xml")
    parser.add_argument("-sp", "--spider", help="Force spidering mode without sitemap discovery", action="store_true")
    parser.add_argument("-v", "--version", action="version", version=f"%(prog)s {version('site-health-checker')}")
    args = parser.parse_args()
    checker = SiteHealthChecker(args)

    success = checker.run(sitemap_url = args.sitemap, output_file = args.output)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()