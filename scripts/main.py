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
import random
import argparse
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from rapidfuzz import process, fuzz
from tqdm import tqdm

# Imports work both when installed as the `tablero` package (relative form) and
# when main.py is run directly from inside scripts/ (flat form, CWD on sys.path).
try:
    from .scrape import sites, build_url, fetch_html
    from .utils import (
        normalize, clean_title, format_discount, sort_table,
        paginate, render_table, SORT_OPTIONS, LIST_DEAL_SORT_OPTIONS,
    )
    from .paths import JSON_PATH, resolve_output
    from . import metadata, validation, history, stats, analytics, alerts, dedup, flags
    from . import export as exporter
except ImportError:
    from scrape import sites, build_url, fetch_html
    from utils import (
        normalize, clean_title, format_discount, sort_table,
        paginate, render_table, SORT_OPTIONS, LIST_DEAL_SORT_OPTIONS,
    )
    from paths import JSON_PATH, resolve_output
    import metadata, validation, history, stats, analytics, alerts, dedup, flags
    import export as exporter

# Smart-sort keys are accepted by --deals / --list in addition to the column sorts.
ALL_SORT_OPTIONS = LIST_DEAL_SORT_OPTIONS + analytics.SMART_SORT_OPTIONS
# Every sort key argparse should accept (validated per-mode in main()).
CLI_SORT_CHOICES = tuple(dict.fromkeys(SORT_OPTIONS + analytics.SMART_SORT_OPTIONS))

# Single merged data file (resolved to an absolute path in paths.py) — replaces
# per-query iteration over 50+ CSVs.

# token_sort_ratio threshold for treating two normalized titles as the same game.
# Catches minor cross-store naming differences (e.g. with/without "LCG") while
# keeping distinct products (base game vs. expansion) separate.
FUZZY_MATCH_THRESHOLD = 90

# Minimum composite relevance (see _relevance) for a search result to be shown.
# WRatio inclusion is deliberately lenient for typo tolerance, so this floor drops
# spurious substring hits (a garbage query that happens to contain a short title)
# while keeping real typos, which score well above it.
RELEVANCE_FLOOR = 55

# Emoji markers for the new/restock flags, shown decorating result rows.
_FLAG_MARK = {flags.FLAG_NEW: '🆕', flags.FLAG_RESTOCK: '🔄'}


def _flag_mark(flag) -> str:
    """Emoji marker for a flag value ('' when unflagged / absent)."""
    return _FLAG_MARK.get(flag, '')


def _prepend_marks(df, col):
    """Values of df[col] with a new/restock marker prepended where the row is flagged."""
    if 'flag' not in df.columns:
        return list(df[col])
    return [f"{_flag_mark(f)} {v}" if _flag_mark(f) else v
            for f, v in zip(df['flag'], df[col])]


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
    flag_totals = {'new': 0, 'restock': 0}
    for name, df in results.items():
        if name not in target_names or df.empty:
            continue
        # Reject obviously-broken rows (bad prices, empty titles) before persisting.
        checked = validation.validate_prices(df)
        bad = checked[checked['is_anomaly']]
        if not bad.empty:
            reasons = bad['anomaly_reason'].str.split(';').explode().value_counts().to_dict()
            print(f"  [{name}] rejected {len(bad)} invalid row(s): {reasons}")
        clean = checked[~checked['is_anomaly']].drop(columns=['is_anomaly', 'anomaly_reason'])

        # Flag new / restock vs the store's PREVIOUS snapshot (before we overwrite it).
        flagged = flags.flag_changes(clean, existing.get(name, []))
        counts = flags.flag_counts(flagged)
        flag_totals['new'] += counts['new']
        flag_totals['restock'] += counts['restock']

        # Persist only the flags that are set, to keep products.json lean.
        records = flagged.to_dict(orient='records')
        for r in records:
            if r.get('flag') is None:
                r.pop('flag', None)
        existing[name] = records

    if flag_totals['new'] or flag_totals['restock']:
        print(f"  Novedades: {flag_totals['new']} nuevos, {flag_totals['restock']} restock")

    JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
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

            time.sleep(1 + random.uniform(0, 1.5))  # be polite; jitter avoids a robotic cadence

    df = pd.DataFrame(all_products)

    if not df.empty:
        df.drop_duplicates(subset=['title'], inplace=True)
        out_path = resolve_output(site['output'])
        out_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(out_path, index=False)
        tqdm.write(f"  [{site['name']}] Saved {len(df)} rows → {out_path}")
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
        path = resolve_output(site['output'])
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


def _relevance(norm_query, norm):
    """
    Blended relevance score (0–100) for a normalized title against the query.

    - token_sort_ratio penalizes extra/reordered tokens, so it breaks the
      "everything matches at 100%" tie for short queries ("catan" scores higher
      against "catan" than against "catan big box" or "dobble catan").
    - partial_ratio tolerates within-word typos and substrings, so a misspelled
      "terraformin" still scores against "terraforming mars".
    """
    set_s = fuzz.token_set_ratio(norm_query, norm)
    sort_s = fuzz.token_sort_ratio(norm_query, norm)
    partial_s = fuzz.partial_ratio(norm_query, norm)
    return 0.30 * set_s + 0.40 * sort_s + 0.30 * partial_s


def _rank_boost(norm_query, norm):
    """Sorting-only bonus that surfaces the base/exact product ahead of variants."""
    if norm == norm_query:
        return 100.0          # exact match always first
    if norm.startswith(norm_query + ' '):
        return 12.0           # query is the leading words ("catan ...")
    if norm_query in norm.split():
        return 6.0            # query is a whole token somewhere
    return 0.0


def fuzzy_search(query, df, score_cutoff=80):
    """
    Fuzzy-match a query against the 'norm' column and rank results by relevance.

    Returns a list of dicts (best first), each with:
      title, norm, score (0–100 relevance), n_stores, min_price, in_stock.

    Near-identical titles for the same game across stores are clustered into one
    entry; the most relevant member is the representative.  Each entry is enriched
    with the cheapest price, how many stores carry it, and whether any has stock —
    so the pick list is decision-ready, not just a list of names.
    """
    norm_query = normalize(query)

    titles_by_norm = (
        df[['title', 'norm']]
        .drop_duplicates(subset='norm')
        .set_index('norm')['title']
        .to_dict()
    )

    # WRatio casts a wider, typo-tolerant net (partial + token strategies combined);
    # the composite _relevance below re-ranks so true matches still surface first.
    matches = process.extract(
        norm_query,
        list(titles_by_norm.keys()),
        scorer=fuzz.WRatio,
        limit=None,
        score_cutoff=score_cutoff,
    )
    if not matches:
        return []

    # Greedily cluster near-duplicate norms (same game under store-specific names).
    anchors, clusters = [], []
    for norm, _score, _ in matches:
        for ci, anchor in enumerate(anchors):
            if fuzz.token_sort_ratio(norm, anchor) >= FUZZY_MATCH_THRESHOLD:
                clusters[ci].append(norm)
                break
        else:
            anchors.append(norm)
            clusters.append([norm])

    # Aggregate price / store / stock once over just the matched rows.
    member_norms = set().union(*clusters)
    cand = df[df['norm'].isin(member_norms)].copy()
    cand['_price'] = stats.effective_price(cand)
    status = cand['stock_status'] if 'stock_status' in cand else None
    cand['_in_stock'] = (
        ~status.fillna('').astype(str).str.lower().eq('agotado') if status is not None else True
    )

    results = []
    for members in clusters:
        sub = cand[cand['norm'].isin(members)]
        rep = max(members, key=lambda n: _relevance(norm_query, n) + _rank_boost(norm_query, n))
        rel = _relevance(norm_query, rep)
        prices = sub['_price'][sub['_price'].notna() & (sub['_price'] > 0)]
        # Aggregate flag: 'new' if any listing is new, else 'restock' if any restocked.
        sub_flags = set(sub['flag'].dropna()) if 'flag' in sub.columns else set()
        cluster_flag = (flags.FLAG_NEW if flags.FLAG_NEW in sub_flags
                        else flags.FLAG_RESTOCK if flags.FLAG_RESTOCK in sub_flags else None)
        results.append({
            'title':     titles_by_norm[rep],
            'norm':      rep,
            'score':     min(100.0, rel),
            '_rank':     rel + _rank_boost(norm_query, rep),
            'n_stores':  int(sub['store'].nunique()),
            'min_price': float(prices.min()) if not prices.empty else None,
            'in_stock':  bool(sub['_in_stock'].any()),
            'flag':      cluster_flag,
        })

    # Drop weak/spurious matches (lenient WRatio inclusion can let substring noise in).
    results = [r for r in results if r['score'] >= RELEVANCE_FLOOR]

    # Rank: relevance, then popularity (more stores), then shorter title (base game).
    results.sort(key=lambda r: (r['_rank'], r['n_stores'], -len(r['title'])), reverse=True)
    return results


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
    rows['store'] = _prepend_marks(rows, 'store')  # 🆕/🔄 next to a store's listing

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


def search_mode(query, limit=30):
    df = load_all_csvs()

    if df.empty:
        print("No CSV data found. Run the scraper first (tablero --update).")
        return

    matches = fuzzy_search(query, df)

    if not matches:
        print(f"Sin coincidencias para '{query}'.")
        return

    shown = matches[:limit]
    print(f"\nResultados para '{query}' ({len(matches)} encontrados):\n")
    for i, r in enumerate(shown, 1):
        price = f"${r['min_price']:,.0f}".replace(',', '.') if r['min_price'] else "s/precio"
        stores = f"{r['n_stores']} tienda" + ("s" if r['n_stores'] != 1 else "")
        avail = "" if r['in_stock'] else " · agotado"
        title = (r['title'][:42] + '…') if len(r['title']) > 43 else r['title']
        mark = _flag_mark(r.get('flag'))
        tail = f"  {mark}" if mark else ""
        print(f"  {i:>3}. {title:<44} desde {price:>9} · {stores}{avail}  ({r['score']:.0f}%){tail}")
    if len(matches) > limit:
        print(f"\n  … y {len(matches) - limit} más (afina la búsqueda para verlos)")

    # Drill-down: pick a number to see that game's per-store prices; 0 returns to the menu.
    while True:
        try:
            raw = input("\nSelecciona un número para ver precios (0 para volver al menú): ").strip()
        except (EOFError, KeyboardInterrupt):
            return
        if raw == "0":
            return
        if not raw.isdigit() or not (1 <= int(raw) <= len(shown)):
            print("Número fuera de rango.")
            continue
        print_price_table(df, shown[int(raw) - 1]['norm'])


def deals_mode(
    store_filter=None,
    in_stock_only=False,
    lower_price=None,
    higher_price=None,
    price_range=None,
    sort_by='discount',
):
    try:
        from .utils import calc_discount_pct
    except ImportError:
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

    # Sort: smart metrics (value/scarcity/volatility), discount via _pct, else column.
    if sort_by in analytics.SMART_SORT_OPTIONS:
        deals = analytics.smart_sort(deals, by=sort_by)
    elif sort_by == 'discount':
        deals = deals.sort_values('_pct', ascending=False)
    else:
        deals = sort_table(deals, by=sort_by)

    deals['stock_status'] = deals['stock_status'].fillna('Disponible')
    deals['title'] = _prepend_marks(deals, 'title')  # 🆕/🔄 next to new/restocked items
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
    return deals

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

    if sort_by in analytics.SMART_SORT_OPTIONS:
        df = analytics.smart_sort(df, by=sort_by)
    else:
        df = sort_table(df, by=sort_by)
    df['descuento']    = df.apply(lambda r: format_discount(r.get('original_price'), r.get('current_price')), axis=1)
    df['stock_status'] = df['stock_status'].fillna('Disponible')
    df['title'] = _prepend_marks(df, 'title')  # 🆕/🔄 next to new/restocked items

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
    return df


def leaderboard_mode():
    """Print the store leaderboard (cheapest overall first)."""
    df = load_all_csvs()
    if df.empty:
        print("No hay datos. Corre el scraper primero (tablero --update).")
        return
    analytics.render_store_leaderboard(df)


def history_mode(query):
    """Show the price-history sparkline per store for the game matching `query`."""
    df = load_all_csvs()
    if df.empty:
        print("No hay datos. Corre el scraper primero (tablero --update).")
        return

    qn = normalize(query)
    norms = df['norm'].dropna().unique().tolist()
    best = process.extractOne(qn, norms, scorer=fuzz.token_set_ratio)
    if not best or best[1] < 60:
        print(f"Sin coincidencias para '{query}'.")
        return
    norm_key = best[0]
    title = df[df['norm'] == norm_key]['title'].iloc[0]

    hist = history.load_history()
    prefix = f"{norm_key}|"
    keys = sorted(k for k in hist if k.startswith(prefix))
    if not keys:
        print(f"Sin historial para '{title}'. El historial se acumula en cada --update.")
        return

    print(f"\nHistorial de precios — {title}\n")
    for k in keys:
        store = k.split('|', 1)[1]
        t = history.price_trend(norm_key, store, history=hist)
        spark = history.sparkline([p['price'] for p in t['points']])
        line = f"  {store:16} {spark}  ${t['first']:,.0f}→${t['last']:,.0f} ({t['change_pct']:+.0f}%, n={t['n']})"
        print(line.replace(',', '.'))


def alerts_mode(queries, threshold, output_file=None):
    """Check a watchlist of games against a price threshold; optionally write JSON."""
    df = load_all_csvs()
    if df.empty:
        print("No hay datos. Corre el scraper primero (tablero --update).")
        return
    result = alerts.alert_on_keywords(queries, threshold, df, output_file=output_file)
    if not result:
        print(f"Ningún juego de {queries} está en o bajo ${threshold:,.0f}.".replace(',', '.'))
        return
    print(f"\n🔔  {len(result)} alerta(s) de precio:\n")
    for a in result:
        line = f"  {a['query']:16} ${a['price']:,.0f}  {a['store']:14} {str(a['matched_title'])[:34]}"
        print(line.replace(',', '.'))
    if output_file:
        print(f"\nEscrito → {output_file}")


def novedades_mode(kind=None):
    """
    List items flagged 'new' or 'restock' by the most recent update.

    `kind` filters to 'new' or 'restock'; None shows both.
    """
    df = load_all_csvs()
    if df.empty:
        print("No hay datos. Corre el scraper primero (tablero --update).")
        return
    if 'flag' not in df.columns:
        print("No hay novedades registradas. Corre 'tablero --update' para detectarlas.")
        return

    wanted = [kind] if kind else [flags.FLAG_NEW, flags.FLAG_RESTOCK]
    nov = df[df['flag'].isin(wanted)].copy()
    if nov.empty:
        print("Sin novedades en la última actualización.")
        return

    nov['tipo'] = nov['flag'].map({flags.FLAG_NEW: '🆕 Nuevo', flags.FLAG_RESTOCK: '🔄 Restock'})
    nov['descuento'] = nov.apply(
        lambda r: format_discount(r.get('original_price'), r.get('current_price')), axis=1)
    nov['stock_status'] = nov['stock_status'].fillna('Disponible')
    nov = nov.sort_values(['flag', 'store', 'title'])

    c = flags.flag_counts(nov)
    render_table(
        nov,
        title=f"Novedades — {c['new']} nuevos, {c['restock']} restock ({len(nov)} ítems)",
        col_order=['tipo', 'store', 'title', 'original_price', 'current_price', 'descuento', 'stock_status', 'url'],
        col_names={
            'tipo':           'Tipo',
            'store':          'Tienda',
            'title':          'Producto',
            'original_price': 'Precio',
            'current_price':  'Oferta',
            'descuento':      'Descuento',
            'stock_status':   'Disponibilidad',
            'url':            'URL',
        },
    )
    return nov


def update_mode(workers=5, dry_run=False, site_names=None):
    """
    Scrape sites and merge the results into the JSON database.

    Scrapes all sites by default, or only those named in `site_names`.
    Runs `workers` scrapes concurrently; `dry_run` fetches only page 1 per site.
    """
    targets = sites
    if site_names:
        name_set = set(site_names)
        targets  = [s for s in sites if s['name'] in name_set]
        missing  = name_set - {s['name'] for s in targets}
        if missing:
            print(f"Warning: unknown site names: {', '.join(missing)}")

    if not targets:
        print("No matching sites to update.")
        return

    # Each site gets a fixed tqdm bar position so bars don't overlap.
    # as_completed() fires as soon as each site finishes regardless of order.
    results = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        future_to_site = {
            pool.submit(scrape_site, site, dry_run, i): site
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

    # Record per-site scrape metadata (timestamp / count / success) for incremental updates.
    meta = metadata.load_metadata()
    for name in [s['name'] for s in targets]:
        df = results.get(name)
        ok = df is not None and not df.empty
        meta = metadata.record_scrape(meta, name, len(df) if df is not None else 0, ok)

    # Snapshot price history and refresh the cached market stats from the full catalog.
    full = load_all_csvs()
    if not full.empty:
        history.save_history(history.record_dataframe_history(full))
        meta = metadata.set_price_stats(meta, stats.market_summary(full))
    metadata.save_metadata(meta)
    tqdm.write(f"  Metadata + history actualizados → {metadata.METADATA_PATH.name}, {history.HISTORY_PATH.name}")


def incremental_update(site_names=None, max_age_hours=24, workers=5, dry_run=False):
    """
    Rescrape only stores that are stale: never scraped, last scrape failed, or
    older than `max_age_hours`.  Reduces load versus a full --update.
    """
    names = site_names or [s['name'] for s in sites]
    meta = metadata.load_metadata()
    stale = metadata.stale_sites(meta, names, max_age_hours)
    if not stale:
        print(f"Todas las tiendas se scrapearon hace < {max_age_hours}h — nada que actualizar.")
        return
    print(f"Actualización incremental: {len(stale)}/{len(names)} tiendas obsoletas → {', '.join(stale)}")
    update_mode(workers=workers, dry_run=dry_run, site_names=stale)


def main():
    parser = argparse.ArgumentParser(
        description="Board game store scraper / price search",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    
    parser.add_argument('-u', '--update', action='store_true',
        help="Scrape all sites and update local CSVs")

    parser.add_argument('-w', '--workers', type=int, default=5,
        metavar='N',
        help="Concurrent scraping threads for --update (default: 5; "
             "lower is gentler on Cloudflare, higher is faster)")

    parser.add_argument('--dry-run', action='store_true',
        help="With --update: fetch only page 1 per site")
    
    parser.add_argument('--sites', nargs='+', metavar='NAME',
        help="With --update: scrape only these sites")
    
    parser.add_argument('-n', '--name', metavar='QUERY',
        help="Fuzzy-search for a game across all local CSVs")
    
    parser.add_argument('--sort', choices=CLI_SORT_CHOICES, default='discount',
        help=(
            "Sort order (default: discount). "
            "--name accepts: discount, price, offer, original, store. "
            "--list/--deals also accept smart sorts: value, scarcity, volatility."
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

    parser.add_argument('--incremental', action='store_true',
        help="With --update: rescrape only stores older than --max-age")

    parser.add_argument('--max-age', type=float, default=24, metavar='H',
        help="With --update --incremental: max store age in hours (default: 24)")

    parser.add_argument('--export', choices=exporter.VALID_FORMATS, metavar='FMT',
        help="With --deals or --list: also export results (csv|json|html)")

    parser.add_argument('--leaderboard', action='store_true',
        help="Show the store leaderboard (cheapest overall first)")

    parser.add_argument('--new', nargs='?', const='all', choices=['all', 'new', 'restock'],
        metavar='KIND',
        help="List items flagged new/restock in the last update (optionally 'new' or 'restock')")

    parser.add_argument('--history', metavar='QUERY',
        help="Show per-store price-history sparklines for a game")

    parser.add_argument('--alert', action='store_true',
        help="Check a watchlist (--watch) against a price threshold (--threshold)")

    parser.add_argument('--watch', nargs='+', metavar='GAME',
        help="With --alert: games to monitor")

    parser.add_argument('--threshold', type=float, metavar='N',
        help="With --alert: alert when a watched game's best price <= N")

    parser.add_argument('--alert-out', metavar='FILE',
        help="With --alert: write alerts as JSON to this file")

    args = parser.parse_args()

    # --- search ---
    if args.name:
        search_mode(args.name)
        return

    # --- deals ---
    if args.deals:
        if args.sort not in ALL_SORT_OPTIONS:
            parser.error(f"--deals only supports --sort {{{', '.join(ALL_SORT_OPTIONS)}}}")
        result = deals_mode(
            store_filter=args.store,
            in_stock_only=args.in_stock,
            lower_price=args.lower_price,
            higher_price=args.higher_price,
            price_range=args.price,
            sort_by=args.sort,
        )
        _maybe_export(result, args.export)
        return

    # --- list ---
    if args.list_all:
        if args.sort not in ALL_SORT_OPTIONS:
            parser.error(f"--list only supports --sort {{{', '.join(ALL_SORT_OPTIONS)}}}")
        result = list_mode(
            store_filter=args.store,
            sort_by=args.sort,
            in_stock_only=args.in_stock,
        )
        _maybe_export(result, args.export)
        return

    # --- leaderboard ---
    if args.leaderboard:
        leaderboard_mode()
        return

    # --- novedades (new / restock) ---
    if args.new:
        novedades_mode(None if args.new == 'all' else args.new)
        return

    # --- price history ---
    if args.history:
        history_mode(args.history)
        return

    # --- keyword alerts ---
    if args.alert:
        if not args.watch or args.threshold is None:
            parser.error("--alert requires --watch GAME [GAME ...] and --threshold N")
        alerts_mode(args.watch, args.threshold, output_file=args.alert_out)
        return

    # --- update / scrape ---
    if args.update:
        if args.incremental:
            incremental_update(site_names=args.sites, max_age_hours=args.max_age,
                               workers=args.workers, dry_run=args.dry_run)
        else:
            update_mode(workers=args.workers, dry_run=args.dry_run, site_names=args.sites)
        return

    # No mode flag → launch the interactive TUI.
    try:
        from .tui import run_tui
    except ImportError:
        from tui import run_tui
    run_tui()


def _maybe_export(df, fmt):
    """Export a result DataFrame if a format was requested and there's data."""
    if not fmt or df is None or df.empty:
        return
    path = exporter.export_comparison(df, fmt=fmt)
    print(f"\nExportado ({fmt}) → {path}")


if __name__ == '__main__':
    main()