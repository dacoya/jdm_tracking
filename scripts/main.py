"""
main.py
-------
Usage:

  python main.py -u / --update            Scrape all sites, write CSVs
  python main.py -u --dry-run             Page 1 only per site (parser testing)
  python main.py -u --sites flexo updown  Update a subset of sites

  python main.py --name clank             Fuzzy search, pick a result, see prices
  python main.py --name clank --sort discount   Sort price table by discount (default)
  python main.py --name clank --sort price      Sort by cheapest effective price
  python main.py --name clank --sort store      Sort alphabetically by store

  python main.py --deals                  All discounted products, best deals first
  python main.py --deals --store flexo    Deals from one store only
  python main.py --list                   Paginated listing of all products
  python main.py --list --store updown    Products from one store
"""

import os
import math
import time
import argparse
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from rapidfuzz import process, fuzz
from tqdm import tqdm

from scrape import sites, build_url, fetch_html
from utils import normalize, format_discount, sort_table, paginate, SORT_OPTIONS
import textwrap

MAX_WIDTHS = {
    'Producto': 30,
    'URL': 80,
    'Disponibilidad': 15,
}

def wrap_cell(text, width):
    return textwrap.wrap(str(text), width=width) or ['']

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
    Load every site's CSV into a single DataFrame with a 'store' column.
    Skips files that don't exist yet (site not scraped).
    Returns an empty DataFrame if no CSVs are found.
    """
    frames = []
    for site in sites:
        path = site['output']
        if not os.path.exists(path):
            continue
        df = pd.read_csv(path)
        df['store'] = site['name']
        # Precompute normalized title for fuzzy matching; original kept for display.
        df['norm'] = df['title'].apply(normalize)
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

    return [(norm_to_original[norm], score) for norm, score, _ in matches]


def print_price_table(df, norm_key, sort_by='discount'):
    """
    Print a formatted price comparison table for all rows whose normalized
    title matches norm_key, across every store that carries the game.

    Columns: Tienda | Precio | Oferta | Descuento | Disponibilidad | URL
    Sorted by `sort_by` (discount / price / store).
    """
    rows = df[df['norm'] == norm_key].copy()

    if rows.empty:
        print("No results found.")
        return

    display_title = rows['title'].mode().iloc[0]

    # Sort before building display columns so sort_table can access raw price fields.
    rows = sort_table(rows, by=sort_by)

    # Compute discount display column from raw price strings.
    rows['descuento'] = rows.apply(
        lambda r: format_discount(r.get('original_price'), r.get('current_price')),
        axis=1,
    )

    rows = rows[['store', 'original_price', 'current_price', 'descuento', 'stock_status', 'url']].copy()
    rows.columns = ['Tienda', 'Precio', 'Oferta', 'Descuento', 'Disponibilidad', 'URL']

    rows['Oferta']         = rows['Oferta'].fillna('-')
    rows['Disponibilidad'] = rows['Disponibilidad'].fillna('Disponible')
    rows['URL']            = rows['URL'].apply(
        lambda x: x if pd.notnull(x) and str(x).startswith('http') else 'N/A'
    )

    col_widths = {col: max(len(col), rows[col].astype(str).str.len().max())
                  for col in rows.columns}

    header = '  '.join(col.ljust(int(col_widths[col])) for col in rows.columns)
    separator = '  '.join('-' * int(col_widths[col]) for col in rows.columns)
    
    lines = [f"\n{display_title}", header, separator]
    for _, row in rows.iterrows():
        lines.append('  '.join(str(row[col]).ljust(int(col_widths[col])) for col in rows.columns))

    paginate(lines)


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

def parse_price(value):
    if value is None:
        return None
    return float(str(value).replace('.', '').replace(',', '').strip())

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

    display = deals[
        ['store', 'title', 'original_price', 'current_price', 'descuento', 'stock_status', 'url']
    ].copy()
    display.columns = ['Tienda', 'Producto', 'Precio', 'Oferta', 'Descuento', 'Disponibilidad', 'URL']

    col_widths = {}
    for col in display.columns:
        max_len = int(display[col].fillna('').astype(str).str.len().max())
        max_len = max(max_len, len(col))
        if col in MAX_WIDTHS:
            max_len = min(max_len, MAX_WIDTHS[col])
        col_widths[col] = max_len

    header    = '  '.join(col.ljust(col_widths[col]) for col in display.columns)
    separator = '  '.join('-' * col_widths[col] for col in display.columns)

    label = f"en {store_filter}" if store_filter else "en todas las tiendas"
    lines = [f"\nOfertas activas {label} ({len(display)} productos)\n", header, separator]

    for _, row in display.iterrows():
        wrapped_cells = {col: wrap_cell(row[col], col_widths[col]) for col in display.columns}
        max_lines = max(len(v) for v in wrapped_cells.values())
        for i in range(max_lines):
            line = []
            for col in display.columns:
                cell_lines = wrapped_cells[col]
                text = cell_lines[i] if i < len(cell_lines) else ''
                line.append(text.ljust(col_widths[col]))
            lines.append('  '.join(line))

    paginate(lines)

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

    df['descuento'] = df.apply(
        lambda r: format_discount(r.get('original_price'), r.get('current_price')),
        axis=1,
    )

    display = df[['store', 'title', 'original_price', 'current_price', 'descuento', 'stock_status', 'url']].copy()
    display.columns = ['Tienda', 'Producto', 'Precio', 'Oferta', 'Descuento', 'Disponibilidad', 'URL']
    display['Disponibilidad'] = display['Disponibilidad'].fillna('Disponible')

    col_widths = {}
    for col in display.columns:
        max_len = display[col].astype(str).str.len().max()
        
        if pd.isna(max_len):
            max_len = 0
        
        max_len = int(max_len)
        col_widths[col] = max(len(col), max_len)

    for col in col_widths:
        col_widths[col] = int(max(col_widths[col], len(col)))

    header = '  '.join(col.ljust(col_widths[col]) for col in display.columns)
    separator = '  '.join('-' * col_widths[col] for col in display.columns)

    label = store_filter or "todas las tiendas"
    lines = [f"\nProductos — {label} ({len(display)} total)\n", header, separator]

    for _, row in display.iterrows():
        lines.append('  '.join(str(row[col]).ljust(col_widths[col]) for col in display.columns))

    paginate(lines)


def main():
    help_text = """
main.py
-------
Usage:

    python main.py -u / --update            Scrape all sites, write CSVs
    python main.py -u --dry-run              Page 1 only per site (parser testing)
    python main.py -u --sites flexo updown  Update a subset of sites

    python main.py --name clank              Fuzzy search, pick a result, see prices
    python main.py --name clank --sort discount    Sort price table by discount (default)
    python main.py --name clank --sort price       Sort by cheapest effective price
    python main.py --name clank --sort store       Sort alphabetically by store

    python main.py --deals                  All discounted products, best deals first
    python main.py --deals --store flexo     Deals from one store only
    python main.py --list                    Paginated listing of all products
    python main.py --list --store updown     Products from one store
"""
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
        help="Sort order for --name results (default: discount)")
    
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
    
    parser.add_argument('--help_info', action='help', help=help_text)

    
    args = parser.parse_args()

    # --- search ---
    if args.name:
        search_mode(args.name, sort_by=args.sort)
        return

    # --- deals ---
    if args.deals:
        deals_mode(
            store_filter=args.store,
            in_stock_only=args.in_stock,
            lower_price=args.lower_price,
            higher_price=args.higher_price,
            price_range=args.price
        )
        return

    # --- list ---
    if args.list_all:
        list_mode(
            store_filter=args.store,
            sort_by=args.sort,
            in_stock_only=args.in_stock
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
        return

    parser.print_help()


if __name__ == '__main__':
    main()
