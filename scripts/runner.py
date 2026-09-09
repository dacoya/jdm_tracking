"""
Scrape execution: walk a site's pages and collect its products.

Extracted from the former main.py, which mixed this with the terminal modes it
no longer owns. Returns records; persistence is ingest.py's job.
"""
import csv
import random
import time

from tqdm import tqdm

try:
    from .paths import resolve_output
    from .scrape import build_url, fetch_html
except ImportError:
    from paths import resolve_output
    from scrape import build_url, fetch_html

# Politeness delay between page requests. Jitter avoids a robotic cadence, which
# is part of what keeps Cloudflare from degrading the IP's reputation.
PAGE_DELAY_MIN = 1.0
PAGE_DELAY_JITTER = 1.5


def scrape_site(site, dry_run: bool = False, position: int = 0) -> list[dict]:
    """
    Scrape every page of one registry entry.

    `position` pins the tqdm bar to a fixed row so concurrent scrapes do not
    overwrite each other's output. Writes a per-store CSV as a side artifact and
    returns the deduplicated records.
    """
    products: list = []
    previous_titles: list = []
    page = 1

    with tqdm(desc=site["name"], unit=" pg", dynamic_ncols=True,
              position=position, leave=True) as pbar:
        while True:
            html = fetch_html(build_url(site["base_url"], site["pagination"], page))
            if html is None:
                pbar.set_postfix_str("network error")
                break

            page_data = site["parser"](html)
            if not page_data:
                pbar.set_postfix_str("done")
                break

            # Some sites serve the last page repeatedly instead of 404-ing once
            # the page number exceeds the total, so an unchanged page means stop.
            titles = [item["title"] for item in page_data]
            if titles == previous_titles:
                pbar.set_postfix_str("duplicate page, stopping")
                break

            previous_titles = titles
            products.extend(page_data)
            pbar.update(1)
            pbar.set_postfix(products=len(products))
            page += 1

            if dry_run:
                pbar.set_postfix_str("dry run, page 1 only")
                break

            time.sleep(PAGE_DELAY_MIN + random.uniform(0, PAGE_DELAY_JITTER))

    if not products:
        tqdm.write(f"  [{site['name']}] No data extracted")
        return []

    # Keyed on url, not title: a store may legitimately list the same title
    # twice (base game and a preorder, or two languages) at different urls.
    unique: dict = {}
    for item in products:
        unique.setdefault(item["url"], item)
    # Sorted so a store reshuffling its pages between runs does not rewrite the
    # whole CSV as a diff of moved lines.
    rows = sorted(unique.values(), key=lambda r: r["url"])

    columns = list(dict.fromkeys(key for row in rows for key in row))
    out_path = resolve_output(site["output"])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    tqdm.write(f"  [{site['name']}] Saved {len(rows)} rows → {out_path}")
    return rows
