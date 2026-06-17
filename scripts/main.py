"""
main.py
-------
Usage:

  python main.py -u / --update            Scrape all sites, write CSVs
  python main.py -u --dry-run             Page 1 only per site (parser testing)
  python main.py -u --sites flexo updown  Update a subset of sites

  python main.py --name clank             Fuzzy search, pick a result, see prices
  python main.py --name clank --sort discount   Sort by discount (default)
  python main.py --name clank --sort price      Sort by cheapest effective price
  python main.py --name clank --sort offer      Sort by offer/sale price
  python main.py --name clank --sort original   Sort by original price
  python main.py --name clank --sort store      Sort alphabetically by store

  python main.py --deals                  All discounted products, best deals first
  python main.py --deals --sort price     Sort deals by cheapest effective price
  python main.py --deals --sort offer     Sort deals by offer price
  python main.py --deals --store flexo    Deals from one store only
  python main.py --list                   Paginated listing of all products
  python main.py --list --sort price      Sort listing by cheapest effective price
  python main.py --list --sort offer      Sort listing by offer price
  python main.py --list --store updown    Products from one store
"""

import os
import json
import math
import time
import argparse
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from rapidfuzz import process, fuzz
from tqdm import tqdm

from scrape import sites, build_url, fetch_html
from utils import normalize, clean_title, format_discount, sort_table, paginate, render_table, SORT_OPTIONS, LIST_DEAL_SORT_OPTIONS

# Single merged data file — replaces per-query iteration over 50+ CSVs.
JSON_PATH = '../data/products.json'

# token_sort_ratio threshold for treating two normalized titles as the same game.
# Catches minor cross-store naming differences (e.g. with/without "LCG") while
# keeping distinct products (base game vs. expansion) separate.
FUZZY_MATCH_THRESHOLD = 90


def merge_to_json(results: dict, targets: list) -> None:
    """
    Merge scrape results into a single JSON file keyed by store name.

    For full updates (targets == all sites) the file is rebuilt from scratch.
    For partial updates (--sites subset) the existing JSON is loaded first and
    only the targeted stores are replaced, leaving all others intact.

    Each store's value is a list of product dicts (records orientation).
    """
    # Load existing data so partial updates don't wipe untouched stores.
    existing = {}
    if os.path.exists(JSON_PATH):
        try:
            with open(JSON_PATH, 'r', encoding='utf-8') as f:
                existing = json.load(f)
        except (json.JSONDecodeError, OSError):
            existing = {}

    target_names = {s['name'] for s in targets}
    for name, df in results.items():
        if name not in target_names or df.empty:
            continue
        existing[name] = df.to_dict(orient='records')

    os.makedirs(os.path.dirname(JSON_PATH), exist_ok=True)
    with open(JSON_PATH, 'w', encoding='utf-8') as f:
        json.dump(existing, f, ensure_ascii=False)

def scrape_site(site, dry_run=False, position=0):
    """
    Scrape all pages of a single site entry from the sites registry.
    `position` pins the tqdm bar to a fixed terminal row when running concurrently.
    Returns a deduplicated DataFrame. Writes a CSV to site['output'] if non-empty.
    """
    all_products = []
    page = 1
    previous_titles = []

    with tqdm(desc=site['name'], unit=" pg", dynamic_ncols=True,
              position=position, leave=True) as pbar:
        while True:
            url = build_url(site['base_url'], site['pagination'], page)
            html = fetch_html(url)

            if html is None:
                pbar.set_postfix_str("network error")
                break
            

            page_data = site['parser'](html)
            if not page_data:
                pbar.set_postfix_str("done")
                break

            # Detect pagination loops: some sites return the last page repeatedly
            # instead of 404-ing when the page number exceeds the total.
            current_titles = [item['title'] for item in page_data]
            if current_titles == previous_titles:
                pbar.set_postfix_str("duplicate page, stopping")
                break

            previous_titles = current_titles
            all_products.extend(page_data)
            pbar.update(1)
            pbar.set_postfix(products=len(all_products))
            page += 1

            if dry_run:
                pbar.set_postfix_str("dry run, page 1 only")
                break

            time.sleep(1)  # be polite

    df = pd.DataFrame(all_products)

    if not df.empty:
        df.drop_duplicates(subset=['title'], inplace=True)
        df.to_csv(site['output'], index=False)
        tqdm.write(f"  [{site['name']}] Saved {len(df)} rows → {site['output']}")
    else:
        tqdm.write(f"  [{site['name']}] No data extracted")

    return df


def load_all_csvs():
    """
    Load all product data into a single DataFrame with a 'store' column.

    Reads from the merged JSON file (../data/products.json) when available —
    one file open instead of 50+ CSV reads.  Falls back to per-site CSVs if
    the JSON doesn't exist yet (e.g. first run before --update completes).
    """
    if os.path.exists(JSON_PATH):
        try:
            with open(JSON_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
            frames = []
            for name, records in data.items():
                if not records:
                    continue
                df = pd.DataFrame(records)
                df['store'] = name
                df['title'] = df['title'].apply(clean_title)
                df['norm']  = df['title'].apply(normalize)
                frames.append(df)
            if frames:
                return pd.concat(frames, ignore_index=True)
        except (json.JSONDecodeError, OSError):
            pass  # fall through to CSV fallback

    # CSV fallback — used before the first full --update produces products.json.
    frames = []
    for site in sites:
        path = site['output']
        if not os.path.exists(path):
            continue
        df = pd.read_csv(path)
        df['store'] = site['name']
        df['title'] = df['title'].apply(clean_title)
        df['norm']  = df['title'].apply(normalize)
        frames.append(df)

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def fuzzy_search(query, df, score_cutoff=80):
    """
    Fuzzy-match a normalized query against the 'norm' column of df.
    Returns a list of (original_title, score) tuples, deduplicated,
    sorted by score descending.
    Matching is done on normalized text so punctuation, accents, and
    language tags don't affect results. Display uses original titles.

    No result cap — all matches above score_cutoff are returned.
    The caller is responsible for paginating the list.
    """
    norm_query = normalize(query)

    norm_to_original = (
        df[['title', 'norm']]
        .drop_duplicates(subset='norm')
        .set_index('norm')['title']
        .to_dict()
    )

    matches = process.extract(
        norm_query,
        list(norm_to_original.keys()),
        scorer=fuzz.token_set_ratio,
        limit=None,          # return everything above score_cutoff
        score_cutoff=score_cutoff,
    )

    # Cluster near-duplicate norms so the pick list doesn't show the same
    # game twice under slightly different store-specific names
    # (e.g. "Arkham Horror: El Juego de Cartas" and the same title with "LCG").
    # Results are already score-sorted; keep the highest-scoring representative.
    seen: list[str] = []
    deduped: list[tuple[str, float]] = []
    for norm, score, _ in matches:
        if all(fuzz.token_sort_ratio(norm, s) < FUZZY_MATCH_THRESHOLD for s in seen):
            seen.append(norm)
            deduped.append((norm_to_original[norm], score))

    return deduped


def print_price_table(df, norm_key, sort_by='discount'):
    # Fuzzy-expand the norm lookup: include rows from stores that list the same
    # game under a slightly different name (e.g. with/without "LCG", minor
    # subtitle differences) so one pick shows the complete cross-store price picture.
    similar_norms = {
        n for n, _, _ in process.extract(
            norm_key,
            df['norm'].unique().tolist(),
            scorer=fuzz.token_sort_ratio,
            score_cutoff=FUZZY_MATCH_THRESHOLD,
            limit=None,
        )
    }
    rows = df[df['norm'].isin(similar_norms)].copy()
    if rows.empty:
        print("No results found.")
        return

    title = rows['title'].mode().iloc[0]
    rows  = sort_table(rows, by=sort_by)
    rows['descuento'] = rows.apply(
        lambda r: format_discount(r.get('original_price'), r.get('current_price')), axis=1)
    rows['url'] = rows['url'].apply(
        lambda x: x if pd.notnull(x) and str(x).startswith('http') else 'N/A')
    rows['stock_status'] = rows['stock_status'].fillna('Disponible')
    rows['current_price'] = rows['current_price'].fillna('-')

    render_table(
        rows,
        title=title,
        col_order=['store', 'original_price', 'current_price', 'descuento', 'stock_status', 'url'],
        col_names={
            'store':          'Tienda',
            'original_price': 'Precio',
            'current_price':  'Oferta',
            'descuento':      'Descuento',
            'stock_status':   'Disponibilidad',
            'url':            'URL',
        },
    )


def search_mode(query, sort_by='discount'):
    df = load_all_csvs()

    if df.empty:
        print("No CSV data found. Run the scraper first (python main.py --update).")
        return

    matches = fuzzy_search(query, df)

    if not matches:
        print(f"No matches found for '{query}'.")
        return

    print(f"\nResultados para '{query}' ({len(matches)} encontrados):\n")
    for i, (title, score) in enumerate(matches, 1):
        print(f"  {i:>3}. {title}  ({score:.0f}%)")

    print()
    try:
        choice = int(input("Selecciona un número (0 para salir): "))
    except (ValueError, EOFError):
        print("Entrada inválida.")
        return

    if choice == 0:
        return
    if not 1 <= choice <= len(matches):
        print("Número fuera de rango.")
        return

    selected_title = matches[choice - 1][0]
    selected_norm  = normalize(selected_title)
    print_price_table(df, selected_norm, sort_by=sort_by)

def deals_mode(
    store_filter=None,
    in_stock_only=False,
    lower_price=None,
    higher_price=None,
    price_range=None,
    sort_by='discount',
):
    from utils import calc_discount_pct

    def parse_price(value):
        if value is None:
            return None
        return float(str(value).replace('.', '').replace(',', '').strip())

    def normalize_price(series):
        return (
            series.astype(str)
            .str.replace('.', '', regex=False)
            .str.replace(',', '', regex=False)
            .str.extract(r'(\d+)')[0]
            .astype(float)
        )

    df = load_all_csvs()
    if df.empty:
        print("No CSV data found. Run the scraper first (python main.py --update).")
        return

    deals = df[df['current_price'].notna()].copy()

    if store_filter:
        deals = deals[deals['store'] == store_filter]
        if deals.empty:
            print(f"No deals found for store '{store_filter}'.")
            return

    if in_stock_only:
        deals = deals[
            deals['stock_status'].fillna('').astype(str).str.lower().ne('agotado')
        ]
        if deals.empty:
            print("No in-stock deals found.")
            return

    deals['_price'] = normalize_price(deals['current_price'])

    min_price = max_price = None
    if price_range:
        parts = price_range.split(':')
        if len(parts) == 2:
            min_price = parse_price(parts[0])
            max_price = parse_price(parts[1])
    elif lower_price or higher_price:
        min_price = parse_price(lower_price)
        max_price = parse_price(higher_price)

    if min_price is not None:
        deals = deals[deals['_price'] >= min_price]
    if max_price is not None:
        deals = deals[deals['_price'] <= max_price]

    if deals.empty:
        print("No deals found for given price constraints.")
        return

    # Always compute discount column for display.
    deals['_pct'] = deals.apply(
        lambda r: calc_discount_pct(r.get('original_price'), r.get('current_price')) or 0,
        axis=1,
    )
    deals['descuento'] = deals.apply(
        lambda r: format_discount(r.get('original_price'), r.get('current_price')),
        axis=1,
    )

    # Sort using sort_table for price/store, manual _pct for discount.
    if sort_by == 'discount':
        deals = deals.sort_values('_pct', ascending=False)
    else:
        deals = sort_table(deals, by=sort_by)

    deals['stock_status'] = deals['stock_status'].fillna('Disponible')
    label = f"en {store_filter}" if store_filter else "en todas las tiendas"

    render_table(
        deals,
        title=f"Ofertas activas {label} ({len(deals)} productos)",
        col_order=['store', 'title', 'original_price', 'current_price', 'descuento', 'stock_status', 'url'],
        col_names={
            'store':          'Tienda',
            'title':          'Producto',
            'original_price': 'Precio',
            'current_price':  'Oferta',
            'descuento':      'Descuento',
            'stock_status':   'Disponibilidad',
            'url':            'URL',
        },
    )

def list_mode(store_filter=None, sort_by='store', in_stock_only=False):
    df = load_all_csvs()

    if df.empty:
        print("No CSV data found. Run the scraper first (python main.py --update).")
        return

    if store_filter:
        df = df[df['store'] == store_filter]
        if df.empty:
            print(f"No products found for store '{store_filter}'.")
            return

    if in_stock_only:
        df = df[
            df['stock_status']
            .fillna('')
            .astype(str)
            .str.lower()
            .ne('agotado')
        ]
        if df.empty:
            print("No in-stock products found.")
            return

    df = sort_table(df, by=sort_by)
    df['descuento']    = df.apply(lambda r: format_discount(r.get('original_price'), r.get('current_price')), axis=1)
    df['stock_status'] = df['stock_status'].fillna('Disponible')

    label = store_filter or "todas las tiendas"
    render_table(
        df,
        title=f"Productos — {label} ({len(df)} total)",
        col_order=['store', 'title', 'original_price', 'current_price', 'descuento', 'stock_status', 'url'],
        col_names={
            'store':          'Tienda',
            'title':          'Producto',
            'original_price': 'Precio',
            'current_price':  'Oferta',
            'descuento':      'Descuento',
            'stock_status':   'Disponibilidad',
            'url':            'URL',
        },
    )


def main():
    parser = argparse.ArgumentParser(
        description="Board game store scraper / price search",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    
    parser.add_argument('-u', '--update', action='store_true',
        help="Scrape all sites and update local CSVs")

    parser.add_argument('-w', '--workers', type=int, default=20,
        metavar='N',
        help="Concurrent scraping threads for --update (default: 20)")

    parser.add_argument('--dry-run', action='store_true',
        help="With --update: fetch only page 1 per site")
    
    parser.add_argument('--sites', nargs='+', metavar='NAME',
        help="With --update: scrape only these sites")
    
    parser.add_argument('-n', '--name', metavar='QUERY',
        help="Fuzzy-search for a game across all local CSVs")
    
    parser.add_argument('--sort', choices=SORT_OPTIONS, default='discount',
        help=(
            "Sort order (default: discount). "
            "--name also accepts: original, store. "
            "--list/--deals accept: discount, price (highest first), offer (highest first)"
        ))
    
    parser.add_argument('--deals', action='store_true',
        help="List all discounted products, best discount first")
    
    parser.add_argument('--lower-price', type=str,
        help="Minimum price (e.g. 10000 or 10.000)")
    
    parser.add_argument('--higher-price', type=str,
        help="Maximum price (e.g. 100000 or 100.000)")
    
    parser.add_argument('--price', type=str,
        help="Range format min:max (e.g. 10000:100000 or 10.000:100.000)")

    parser.add_argument('--in-stock',action='store_true',
        help="Show only products that are not agotado")
    
    parser.add_argument('--list', action='store_true', dest='list_all',
        help="Paginated listing of all scraped products")
    
    parser.add_argument('--store', metavar='NAME',
        help="With --deals or --list: filter to a single store")

    args = parser.parse_args()

    # --- search ---
    if args.name:
        search_mode(args.name, sort_by=args.sort)
        return

    # --- deals ---
    if args.deals:
        if args.sort not in LIST_DEAL_SORT_OPTIONS:
            parser.error(f"--deals only supports --sort {{{', '.join(LIST_DEAL_SORT_OPTIONS)}}}")
        deals_mode(
            store_filter=args.store,
            in_stock_only=args.in_stock,
            lower_price=args.lower_price,
            higher_price=args.higher_price,
            price_range=args.price,
            sort_by=args.sort,
        )
        return

    # --- list ---
    if args.list_all:
        if args.sort not in LIST_DEAL_SORT_OPTIONS:
            parser.error(f"--list only supports --sort {{{', '.join(LIST_DEAL_SORT_OPTIONS)}}}")
        list_mode(
            store_filter=args.store,
            sort_by=args.sort,
            in_stock_only=args.in_stock,
        )
        return

    # --- update / scrape ---
    if args.update:
        targets = sites
        if args.sites:
            name_set = set(args.sites)
            targets  = [s for s in sites if s['name'] in name_set]
            missing  = name_set - {s['name'] for s in targets}
            if missing:
                print(f"Warning: unknown site names: {', '.join(missing)}")

        # Each site gets a fixed tqdm bar position so bars don't overlap.
        # as_completed() fires as soon as each site finishes regardless of order.
        results = {}
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            future_to_site = {
                pool.submit(scrape_site, site, args.dry_run, i): site
                for i, site in enumerate(targets)
            }
            for future in as_completed(future_to_site):
                site = future_to_site[future]
                try:
                    results[site['name']] = future.result()
                except Exception as e:
                    tqdm.write(f"  [{site['name']}] crashed: {e}")
                    results[site['name']] = pd.DataFrame()

        # Summary printed in original registry order, not completion order.
        summary = pd.DataFrame([
            {
                'site':    name,
                'total':   len(results[name]),
                'on_sale': int(results[name]['current_price'].notna().sum()) if not results[name].empty else 0,
                'agotado': int((results[name]['stock_status'] == 'Agotado').sum()) if not results[name].empty else 0,
            }
            for name in [s['name'] for s in targets] if name in results
        ])
        print("\n" + summary.to_string(index=False))

        merge_to_json(results, targets)
        tqdm.write(f"  Merged → {JSON_PATH}")
        return

    parser.print_help()


if __name__ == '__main__':
    main()