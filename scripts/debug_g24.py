from bs4 import BeautifulSoup

from jobscout.collectors.base import PoliteClient, save_raw
from jobscout.collectors.graduates24 import parse_detail, parse_listing

client = PoliteClient()
cards = parse_listing(client.get("https://www.graduates24.com/graduate_programmes"))
card = next(c for c in cards if "Engen" in c["title"])
html = client.get(card["url"])
save_raw("g24_detail_engen.html", html)

soup = BeautifulSoup(html, "lxml")
for sel in ['[itemprop="description"]', ".g24-show-description", ".g24-show-body", ".g24-show-content"]:
    el = soup.select_one(sel)
    print(sel, "->", None if el is None else len(el.get_text(" ", strip=True)))
print("has <main>:", soup.find("main") is not None)
print("main p/li count:", len(soup.select("main p, main li")))
print("parse_detail description length:", len(parse_detail(html)["description"] or ""))

print("Largest text blocks:")
blocks = sorted(
    ((len(e.get_text(" ", strip=True)), e.name, e.get("class"), e.get("itemprop"))
     for e in soup.find_all(["div", "section", "article"])),
    key=lambda b: b[0], reverse=True,
)[:8]
for b in blocks:
    print(b)
