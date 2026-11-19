import json, re, sys
from pathlib import Path
from bs4 import BeautifulSoup
sys.path.insert(0, "scraper")
import scrape
folder = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / "Downloads"
pages = json.load(open("data/pages_darglobal.json", encoding="utf-8"))
added = 0
for f in sorted(folder.glob("*.html")):
    html = f.read_text(encoding="utf-8", errors="ignore")
    if "wasalt" not in html.lower():
        continue
    soup = BeautifulSoup(html, "lxml")
    tag = soup.find("link", rel="canonical") or soup.find("meta", property="og:url")
    url = (tag.get("href") or tag.get("content") or "") if tag else ""
    if "wasalt.sa" not in url:
        stem = re.sub(r"\s*\(\d+\)$", "", f.stem)
        url = "https://wasalt.sa/en/" + re.sub(r"[^a-z0-9-]+", "-", stem.lower()).strip("-")
    p = scrape.extract(html, url)
    if len(p["text"]) < 300 or "security verification" in p["text"]:
        print("skipped (no text):", f.name)
        continue
    pages = [x for x in pages if x["url"] != url]
    pages.append({"site": "Wasalt", "url": url, "title": p["title"], "text": p["text"]})
    added += 1
    print("added:", url, "| chars:", len(p["text"]))
json.dump(pages, open("data/pages.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("Wasalt pages added:", added, "| total pages:", len(pages))
