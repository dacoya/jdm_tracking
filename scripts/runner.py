"""
Scrape execution: walk a site's pages and collect its products.

Extracted from the former main.py, which mixed this with the terminal modes it
no longer owns. Returns records; persistence is ingest.py's job.
"""
import random
import time

import pandas as pd
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


def scrape_site(site, dry_run: bool = False, position: int = 0) -> pd.DataFrame:
    """
    Scrape every page of one registry entry.

    `position` pins the tqdm bar to a fixed row so concurrent scrapes do not
    overwrite each other's output. Writes a per-store CSV as a side artifact and
    returns the deduplicated DataFrame.
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

    df = pd.DataFrame(products)
    if df.empty:
        tqdm.write(f"  [{site['name']}] No data extracted")
        return df

    df = df.drop_duplicates(subset=["title"])
    out_path = resolve_output(site["output"])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)
    tqdm.write(f"  [{site['name']}] Saved {len(df)} rows → {out_path}")
    return df
