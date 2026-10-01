"""
SOPHICUSE course list builder.

Reads Syracuse University's public undergraduate course catalog
(coursecatalog.syracuse.edu) and saves every course's code, title, credits,
school, description, and prerequisites to courses.json for the SOPHICUSE
"Find your course" search.

Rules it follows:
- Only visits pages that robots.txt allows (it checks every URL first).
- Never touches /course-search/api, /search/, /pdf/, or anything behind a login.
- Waits between requests so it doesn't strain the university's servers.

Run it:  python scraper/scrape_catalog.py
"""
import json, re, sys, time, urllib.robotparser
from datetime import date
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE = "https://coursecatalog.syracuse.edu"
SITEMAP = BASE + "//sitemap.xml"          # exactly as listed in robots.txt
INDEX = BASE + "/undergraduate/courses/"
DELAY_SECONDS = 3
OUT = Path(__file__).resolve().parent.parent / "courses.json"
HEADERS = {"User-Agent": "SOPHICUSE course list builder (student project; https://github.com/sophiaschwartz/SOPHICUSE---GPA-Tracker)"}

SUBJECT_URL = re.compile(r"/undergraduate/courses/([a-z0-9_-]+)/?$")
HEADER = re.compile(r"^([A-Z]{2,4})\s+(\d{3}[A-Z]?)\s+(.+?)\s+\(\s*([^()]*?)\s*Credits?\s*\)\s*$")

session = requests.Session()
session.headers.update(HEADERS)
robots = urllib.robotparser.RobotFileParser(BASE + "/robots.txt")


def allowed(url):
    return robots.can_fetch(HEADERS["User-Agent"], url)


def get(url):
    if not allowed(url):
        print(f"  skipped (blocked by robots.txt): {url}")
        return None
    time.sleep(DELAY_SECONDS)
    r = session.get(url, timeout=30)
    if r.status_code != 200:
        print(f"  HTTP {r.status_code}: {url}")
        return None
    return r.text


def subject_pages():
    """Find every subject page (ecn, ist, psc, ...) from the sitemap, or the index page as a backup."""
    urls = set()
    xml = get(SITEMAP)
    if xml:
        for loc in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml):
            if SUBJECT_URL.search(loc):
                urls.add(loc if loc.endswith("/") else loc + "/")
    if not urls:
        html = get(INDEX)
        if html:
            for a in BeautifulSoup(html, "html.parser").find_all("a", href=True):
                href = a["href"]
                full = href if href.startswith("http") else BASE + href
                if SUBJECT_URL.search(full):
                    urls.add(full if full.endswith("/") else full + "/")
    return sorted(urls)


def clean(s):
    return re.sub(r"\s+", " ", s.replace("\u00a0", " ")).strip()


def parse_lines(lines):
    """Turn the text of a catalog page into course records."""
    courses, cur = [], None
    for raw in lines:
        line = clean(raw)
        if not line:
            continue
        m = HEADER.match(line)
        if m:
            if cur:
                courses.append(cur)
            cur = {"c": f"{m.group(1)} {m.group(2)}", "t": m.group(3).strip(), "cr": m.group(4).strip(),
                   "s": "", "d": "", "p": ""}
            continue
        if not cur:
            continue
        low = line.lower()
        if "prereq:" in low:
            cur["p"] = line.split(":", 1)[1].strip()[:200]
        elif low.startswith(("cross-listed", "double-numbered", "repeatable", "shared competencies",
                             "university requirement", "offered", "credit cannot", "course catalogs")) and len(line) < 120 and not cur["d"]:
            continue
        elif not cur["s"] and not cur["d"] and len(line) < 70 and not line.endswith("."):
            cur["s"] = line
        elif not cur["d"] and len(line) > 25:
            cur["d"] = line[:400]
    if cur:
        courses.append(cur)
    return courses


def block_lines(root):
    """Text of each innermost block element (paragraph, list item, heading), one per line.
    Joining inline pieces with spaces keeps "ECN 101", the title, and "(3 Credits)" on one line."""
    leaves = [el for el in root.find_all(["p", "li", "h2", "h3", "h4", "div", "span"])
              if el.name != "span" and not el.find(["p", "div", "li", "h2", "h3", "h4"])]
    return [el.get_text(" ") for el in leaves] or root.get_text("\n").split("\n")


def parse_page(html):
    soup = BeautifulSoup(html, "html.parser")
    blocks = soup.select("div.courseblock")
    if blocks:
        out = []
        for b in blocks:
            out += parse_lines(block_lines(b))
        return out
    main = soup.select_one("#textcontainer") or soup.select_one("main") or soup.body or soup
    return parse_lines(block_lines(main))


def main():
    robots.read()
    pages = subject_pages()
    if not pages:
        sys.exit("Couldn't find any subject pages. The catalog layout may have changed.")
    print(f"Found {len(pages)} subject pages.")
    all_courses, seen = [], set()
    for i, url in enumerate(pages, 1):
        html = get(url)
        if not html:
            continue
        found = parse_page(html)
        for c in found:
            if c["c"] not in seen:
                seen.add(c["c"])
                all_courses.append({k: v for k, v in c.items() if v})
        print(f"[{i}/{len(pages)}] {url} -> {len(found)} courses")
    if len(all_courses) < 100:
        sys.exit(f"Only found {len(all_courses)} courses, so courses.json was not changed. Check the parser.")
    all_courses.sort(key=lambda c: c["c"])
    OUT.write_text(json.dumps({"source": BASE, "updated": date.today().isoformat(), "courses": all_courses},
                              ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Saved {len(all_courses)} courses to {OUT.name}")


if __name__ == "__main__":
    main()
