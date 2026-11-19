#!/usr/bin/env python3
"""Collect public pages from DarGlobal and Wasalt into data/pages.json.

Examples
  python scraper/scrape.py                         # plain HTTP crawl of both sites
  python scraper/scrape.py --js --only Wasalt      # render JavaScript with Playwright
  python scraper/scrape.py --json "Wasalt=https://.../api/listings"   # add a JSON feed

Respects robots.txt, crawls only the site's own domain, and waits between requests.
"""
import argparse
import json
import re
import time
import urllib.robotparser as robotparser
from collections import deque
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

# Verify these start URLs in a browser before running.
SITES = {
    "DarGlobal": ["https://www.darglobal.co.uk/"],
    "Wasalt": ["https://wasalt.sa/en/"],
}
UA = "Mozilla/5.0 (compatible; AssignmentBot/1.0; educational use)"
SKIP_EXT = re.compile(r"\.(jpe?g|png|gif|svg|webp|pdf|zip|mp4|mp3|css|js|ico|woff2?|xml)$", re.I)
SKIP_KEYS = {"image", "images", "img", "thumbnail", "logo", "icon", "slug", "__typename", "id", "uuid"}
OUT = Path(__file__).resolve().parent.parent / "data" / "pages.json"


def host(url):
    return urlparse(url).netloc.lower().removeprefix("www.")


class Fetcher:
    def __init__(self, js, delay):
        self.js, self.delay = js, delay
        self.session = requests.Session()
        self.session.headers["User-Agent"] = UA
        self.pw = self.page = None
        if js:
            from playwright.sync_api import sync_playwright

            self.pw = sync_playwright().start()
            self.page = self.pw.chromium.launch(channel="msedge", headless=False).new_page()

    def html(self, url):
        time.sleep(self.delay)
        if self.js:
            self.page.goto(url, wait_until="domcontentloaded", timeout=45000); self.page.wait_for_timeout(4000)
            for _ in range(30):
                t = self.page.title()
                if "Just a moment" not in t and "security verification" not in t:
                    break
                self.page.wait_for_timeout(1500)
            else:
                return None
            return self.page.content()
        r = self.session.get(url, timeout=20)
        if r.status_code != 200 or "html" not in r.headers.get("content-type", ""):
            return None
        return r.text

    def close(self):
        if self.pw:
            self.pw.stop()


def load_robots(base):
    rp = robotparser.RobotFileParser()
    try:
        r = requests.get(urljoin(base, "/robots.txt"), headers={"User-Agent": UA}, timeout=10)
        rp.parse(r.text.splitlines() if r.status_code == 200 else [])
    except requests.RequestException:
        rp.parse([])
    return rp


def sitemap_urls(base, limit=300):
    urls, todo = [], [urljoin(base, "/sitemap.xml")]
    while todo and len(urls) < limit and len(todo) < 8:
        try:
            r = requests.get(todo.pop(0), headers={"User-Agent": UA}, timeout=15)
        except requests.RequestException:
            continue
        for loc in re.findall(r"<loc>\s*(.*?)\s*</loc>", r.text if r.status_code == 200 else ""):
            (todo if loc.endswith(".xml") else urls).append(loc)
    return [u for u in urls if host(u) == host(base)]


def flatten(obj, lines):
    """Turn JSON (e.g. listing feeds, __NEXT_DATA__) into 'key: value; key: value' lines."""
    if isinstance(obj, dict):
        scalars = [
            (k, v) for k, v in obj.items()
            if isinstance(v, (str, int, float)) and not isinstance(v, bool)
            and k not in SKIP_KEYS and str(v).strip() and not str(v).startswith(("http", "data:"))
        ]
        if len(scalars) >= 2:
            lines.append("; ".join(f"{k}: {str(v).strip()}" for k, v in scalars)[:400])
        for v in obj.values():
            if isinstance(v, (dict, list)):
                flatten(v, lines)
    elif isinstance(obj, list):
        for v in obj:
            flatten(v, lines)


def json_text(raw_blobs, cap=20000):
    lines = []
    for raw in raw_blobs:
        try:
            flatten(json.loads(raw), lines)
        except (ValueError, TypeError):
            continue
    seen, out = set(), []
    for line in lines:
        if line not in seen:
            seen.add(line)
            out.append(line)
    return "\n".join(out)[:cap]


def extract(html, url):
    soup = BeautifulSoup(html, "lxml")
    blobs = [s.string for s in soup.find_all("script", type="application/ld+json") if s.string]
    nd = soup.find("script", id="__NEXT_DATA__")
    if nd and nd.string:
        blobs.append(nd.string)

    links = []
    for a in soup.find_all("a", href=True):
        link = urldefrag(urljoin(url, a["href"]))[0]
        if link.startswith("http") and "?" not in link and not SKIP_EXT.search(link):
            links.append(link)

    for tag in soup(["script", "style", "noscript", "svg", "nav", "footer", "form", "iframe"]):
        tag.decompose()
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in soup.get_text("\n").splitlines()]
    text, prev = [], None
    for ln in lines:
        if len(ln) > 2 and ln != prev:
            text.append(ln)
        prev = ln
    body = "\n".join(text)
    structured = json_text(blobs)
    if structured:
        body += "\n" + structured

    h1 = soup.find("h1")
    title = (soup.title.string.strip() if soup.title and soup.title.string else "") or (h1.get_text(strip=True) if h1 else url)
    return {"title": title, "text": body, "links": links}


def crawl(site, seeds, max_pages, fetcher):
    rp = load_robots(seeds[0])
    queue = deque(seeds)
    queue.extend(sitemap_urls(seeds[0]))
    seen, pages = set(), []
    while queue and len(pages) < max_pages:
        url = queue.popleft()
        if url in seen or host(url) != host(seeds[0]) or not rp.can_fetch(UA, url):
            continue
        if re.search(r"%D[89]|[^\x00-\x7f]", url):
            continue
        seen.add(url)
        try:
            html = fetcher.html(url)
        except Exception as exc:  # keep crawling on any single failure
            print(f"  skip {url}: {exc}")
            continue
        if not html:
            continue
        page = extract(html, url)
        queue.extend(l for l in page["links"] if l not in seen)
        if len(page["text"]) >= 80:
            pages.append({"site": site, "url": url, "title": page["title"], "text": page["text"]})
            print(f"  [{len(pages)}/{max_pages}] {url}")
    return pages


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--max-pages", type=int, default=60, help="per site")
    ap.add_argument("--delay", type=float, default=1.0, help="seconds between requests")
    ap.add_argument("--js", action="store_true", help="render pages with Playwright")
    ap.add_argument("--only", choices=list(SITES), help="scrape one site only")
    ap.add_argument("--json", action="append", default=[], metavar="SITE=URL", help="extra JSON feed to include")
    args = ap.parse_args()

    fetcher = Fetcher(args.js, args.delay)
    pages = []
    try:
        for site, seeds in SITES.items():
            if args.only and site != args.only:
                continue
            print(f"Crawling {site}")
            pages += crawl(site, seeds, args.max_pages, fetcher)
    finally:
        fetcher.close()

    for item in args.json:
        site, url = item.split("=", 1)
        r = requests.get(url, headers={"User-Agent": UA}, timeout=30)
        r.raise_for_status()
        text = json_text([r.text])
        if text:
            pages.append({"site": site, "url": url, "title": f"{site} data feed", "text": text})
            print(f"  JSON feed added: {url}")

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(pages, ensure_ascii=False, indent=1), encoding="utf-8")
    by_site = {s: sum(p["site"] == s for p in pages) for s in {p["site"] for p in pages}}
    print(f"Saved {len(pages)} pages to {OUT}: {by_site}")


if __name__ == "__main__":
    main()
