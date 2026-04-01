"""
scrape.py
---------
HTML parsers for each board game store and the site configuration registry.
No I/O or scraping logic lives here — import this from main.py.
"""

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup


# ── HTTP ───────────────────────────────────────────────────────────────────────

def fetch_html(url):
    session = requests.Session()
    retry_strategy = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504]
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    try:
        r = session.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            timeout=45,
        )
        r.raise_for_status()
        return BeautifulSoup(r.text, 'html.parser')
    except requests.exceptions.RequestException as e:
        print(f"Network error on {url}: {e}")
        return None

# ── Utility ───────────────────────────────────────────────────────────────────

def _text(el):
    return el.get_text(strip=True) if el else None

def _url(el, base=""):
    if not el or not el.get('href'): return None
    return el['href'] if el['href'].startswith('http') else base + el['href']

def _prices(orig, curr):
    return (orig, curr) if orig != curr else (orig, None)

# ── Primitive helpers ──────────────────────────────────────────────────────────

_OOS_WORDS = ('agotado', 'sin stock', 'out of stock', 'fuera de stock', 'no disponible')


def _txt(el):
    """get_text(strip=True) → str, or None if el is None."""
    return el.get_text(strip=True) if el else None


def _url(el, base=""):
    """Extract href from an element; prepend base if relative. Returns None if missing."""
    href = el.get('href') if el else None
    if not href:
        return None
    return href if href.startswith('http') else base + href


def _norm(orig, curr):
    """Nullify current_price when it equals original_price (no real discount)."""
    return (orig, None) if orig == curr else (orig, curr)


def _oos(text):
    """Return True if text contains any out-of-stock phrase."""
    t = (text or '').lower()
    return any(w in t for w in _OOS_WORDS)


# ── Price helpers ──────────────────────────────────────────────────────────────

def _woo_prices(container):
    """
    WooCommerce standard price block.
    <del> = original, <ins> = sale. Falls back to <bdi> or raw text.
    Returns (original_price, current_price).
    """
    if not container:
        return None, None
    del_e, ins_e = container.find('del'), container.find('ins')
    if del_e and ins_e:
        return _txt(del_e), _txt(ins_e)
    bdi = container.find('bdi')
    raw = _txt(bdi) or container.get_text(strip=True).replace('IVA INC', '').strip() or None
    return raw, None


def _presta_prices(item):
    """
    PrestaShop standard price pair.
    <span class='regular-price'> = original, <span class='price'> = sale.
    Returns (original_price, current_price).
    """
    reg   = _txt(item.find('span', class_='regular-price'))
    price = _txt(item.find('span', class_='price'))
    return _norm(reg or price, price if reg else None)


# ── Stock helpers ──────────────────────────────────────────────────────────────

def _stock_flags(item, oos_cls='out_of_stock', discount_cls='discount', curr=None):
    """
    PrestaShop <ul class='product-flags'> pattern.
    Returns "Agotado", "Oferta", or None.
    """
    flags = item.find('ul', class_='product-flags')
    if flags:
        if flags.find('li', class_=oos_cls):
            return "Agotado"
        if flags.find('li', class_=discount_cls) or curr:
            return "Oferta"
    return None


def _stock_cls(cls, curr, sale_cls='sale', oos_cls='outofstock', extra_sale=False):
    """
    WooCommerce item-class pattern.
    Returns "Agotado", "Oferta", or None.
    """
    if oos_cls in cls:
        return "Agotado"
    if sale_cls in cls or curr or extra_sale:
        return "Oferta"
    return None


# ── Generic parsers ────────────────────────────────────────────────────────────

def _parse_woo_li(html, link_cls='woocommerce-LoopProduct-link',
                  extra_oos=None, extra_sale=None):
    """
    Generic WooCommerce parser for <li class='product'> grids.
    Used by: cartonazo, mangaigames, revaruk, gatoarcano.

    link_cls:    CSS class for the product anchor (None = first <a href>).
    extra_oos:   callable(item) -> bool for store-specific OOS signals.
    extra_sale:  callable(item) -> bool for store-specific sale signals.
    """
    res = []
    for item in (html.find_all('li', class_='product') if html else []):
        try:
            t_elem = item.find('h2', class_='woocommerce-loop-product__title')
            if not t_elem:
                continue
            orig, curr = _norm(*_woo_prices(item.find('span', class_='price')))
            cls  = item.get('class', [])
            oos  = 'outofstock' in cls or bool(extra_oos and extra_oos(item))
            sale = bool(extra_sale and extra_sale(item))
            link = (item.find('a', class_=link_cls, href=True) if link_cls else None) \
                   or item.find('a', href=True)
            res.append({
                'title': _txt(t_elem), 'original_price': orig, 'current_price': curr,
                'stock_status': "Agotado" if oos else _stock_cls(cls, curr, extra_sale=sale),
                'url': _url(link),
            })
        except Exception as e:
            print(f"  [_parse_woo_li] skipping item: {e}")
    return res


def _parse_presta(html, title_tag='h2', title_cls='product-title',
                  item_cls='product-miniature', oos_flag='out_of_stock'):
    """
    Generic PrestaShop parser for <article class='product-miniature'> grids.
    Used by: aldeajuegos, dementegames, planetaloz (h1 variant).

    title_tag / title_cls: heading element and class for the product name.
    oos_flag:  class on the <li> inside product-flags that signals out-of-stock.
    """
    res = []
    for item in (html.find_all('article', class_=item_cls) if html else []):
        try:
            t_elem = item.find(title_tag, class_=title_cls)
            if not t_elem:
                continue
            orig, curr = _presta_prices(item)
            stock = _stock_flags(item, oos_cls=oos_flag, curr=curr)
            res.append({
                'title': _txt(t_elem), 'original_price': orig, 'current_price': curr,
                'stock_status': stock, 'url': _url(t_elem.find('a', href=True)),
            })
        except Exception as e:
            print(f"  [_parse_presta] skipping item: {e}")
    return res


def _parse_bs(html, item_tag='section', item_cls='grid__item', base_url=''):
    """
    Generic BS-collection parser.
    Used by: top8, gameofmagictienda, cardgame.

    item_tag / item_cls: container element and class for each product card.
    base_url: prepended to relative hrefs.
    """
    res = []
    for item in (html.find_all(item_tag, class_=item_cls) if html else []):
        try:
            t_elem = item.find('h3', class_='bs-collection__product-title')
            if not t_elem:
                continue

            # Price — accept both div and section wrappers; old-price class varies slightly.
            orig, curr = None, None
            pc = item.find(['div', 'section'], class_='bs-collection__product-price')
            if pc:
                del_e = pc.find('del', class_=lambda c: bool(c and any('old-price' in x for x in c)))
                fin_e = pc.find('div', class_='bs-collection__product-final-price')
                orig, curr = (_txt(del_e), _txt(fin_e)) if del_e else (_txt(fin_e), None)
            orig, curr = _norm(orig, curr)

            # Stock — aggregate text from all known notice / badge locations.
            pw  = item.find('div', class_='bs-collection__product')
            cls = list(item.get('class', [])) + list(pw.get('class', []) if pw else [])
            check = ' '.join(filter(None, [
                _txt(item.find('div', class_='bs-collection__product-notice')),
                _txt(item.find('div', class_='bs-stock')),
                _txt(item.find('div', class_='bs-collection__stock')),
            ]))
            oos   = _oos(check) or 'out-of-stock' in cls or 'outStock' in cls
            stock = "Agotado" if oos else ("Oferta" if curr or 'has-discount' in cls else None)

            link = t_elem.find('a', href=True) or item.find('a', href=True)
            res.append({
                'title': _txt(t_elem), 'original_price': orig, 'current_price': curr,
                'stock_status': stock, 'url': _url(link, base_url),
            })
        except Exception as e:
            print(f"  [_parse_bs] skipping item: {e}")
    return res


# ── Site-specific parsers ──────────────────────────────────────────────────────
#
# Stores that need custom logic get their own function.
# Stores fully covered by a generic parser are one-liners.

def flexogames(html):
    """Shopify. Stock/sale encoded as classes on <dl class='price'>."""
    res = []
    for item in (html.find_all('li', class_='grid__item') if html else []):
        try:
            t_elem = item.find('div', class_='grid-view-item__title')
            if not t_elem:
                continue
            pc    = item.find('div', class_='price__compare')
            s_tag = pc.find('s') if pc else None
            if s_tag and _txt(s_tag):
                orig, curr = _norm(_txt(s_tag), _txt(item.find('span', class_='price-item--sale')))
            else:
                reg  = item.find('div', class_='price__regular')
                orig, curr = _norm(_txt(reg.find('span', class_='price-item--regular') if reg else None), None)
            dl    = item.find('dl', class_='price')
            stock = "Agotado" if dl and 'price--sold-out' in dl.get('class', []) else None
            res.append({
                'title': _txt(t_elem), 'original_price': orig, 'current_price': curr,
                'stock_status': stock,
                'url': _url(item.find('a', class_='grid-view-item__link'), "https://www.flexogames.cl"),
            })
        except Exception as e:
            print(f"  [flexogames] skipping item: {e}")
    return res


def lafortalezapuq(html):
    """Custom CMS. Discounted price stored inside <i> tag within the price span."""
    res = []
    for item in (html.find_all('figure', class_='product') if html else []):
        try:
            t_elem = item.find('h5')
            if not t_elem:
                continue
            dp = item.find('span', class_='product-price-discount')
            if dp:
                sale = dp.find('i')
                curr = _txt(sale)
                if sale:
                    sale.extract()  # remove <i> so remaining text is the original
                orig = _txt(dp)
            else:
                orig, curr = _txt(item.find('span', class_='product-price')), None
            orig, curr = _norm(orig, curr)
            res.append({
                'title': _txt(t_elem), 'original_price': orig, 'current_price': curr,
                'stock_status': None,
                'url': _url(item.find('a', href=True), "https://www.lafortalezapuq.cl"),
            })
        except Exception as e:
            print(f"  [lafortalezapuq] skipping item: {e}")
    return res


def planetaloz(html):
    """PrestaShop. h1 title variant."""
    return _parse_presta(html, title_tag='h1', title_cls='product-title')


def updown_juegos(html):
    """WooCommerce/Woodmart. Stock span lives on the parent container, not the product div."""
    res = []
    for item in (html.find_all('div', class_='product-element-bottom') if html else []):
        try:
            t_elem = item.find('h3', class_='wd-entities-title')
            if not t_elem:
                continue
            pc = item.find('span', class_='price')
            if not pc:
                continue
            orig, curr = _norm(*_woo_prices(pc))
            stock = "Agotado" if item.parent.find('span', class_='out-of-stock') else None
            res.append({
                'title': _txt(t_elem), 'original_price': orig, 'current_price': curr,
                'stock_status': stock, 'url': _url(t_elem.find('a', href=True)),
            })
        except Exception as e:
            print(f"  [updown_juegos] skipping item: {e}")
    return res


def aldeajuegos(html):
    """PrestaShop."""
    return _parse_presta(html)


def elpatiogeek(html):
    res = []
    for item in (html.find_all('div', class_='grid-item') if html else []):
        if not (title := _text(item.find('p'))): continue
        
        pc = item.find('div', class_='product-item--price')
        pval = None
        is_sale = False
        
        if pc:
            if sm := pc.find('small'): 
                pval = _text(sm)
            elif sh1 := pc.find('span', class_='h1'): 
                pval = _text(s[-1]) if (s := sh1.find_all('span', class_='visually-hidden')) else _text(sh1)
            
            vh = pc.find('span', class_='visually-hidden')
            if vh and 'venta' in _text(vh).lower(): 
                is_sale = True

        sale_tag = item.find('div', class_='sale-tag')
        
        orig, curr = (_text(sale_tag), pval) if is_sale and sale_tag else (pval, None)
        orig, curr = _prices(orig or None, curr)
        
        cls = item.get('class', [])
        stock = "Agotado" if 'sold-out' in cls else ("Oferta" if 'on-sale' in cls or curr else None)
        
        res.append({
            'title': title, 
            'original_price': orig, 
            'current_price': curr, 
            'stock_status': stock, 
            'url': _url(item.find('a', class_='product-grid-item'), "https://www.elpatiogeek.cl")
        })
    return res


def cartonespesados(html):
    """WooCommerce Blocks. Uses wc-block-components-product-price."""
    res = []
    for item in (html.find_all('li', class_='wc-block-product') if html else []):
        try:
            t_elem = item.find('h3', class_='wp-block-post-title')
            if not t_elem:
                continue
            orig, curr = _norm(*_woo_prices(item.find('div', class_='wc-block-components-product-price')))
            cls   = item.get('class', [])
            stock = "Agotado" if 'outofstock' in cls else ("Oferta" if 'onsale' in cls or curr else None)
            res.append({
                'title': _txt(t_elem), 'original_price': orig, 'current_price': curr,
                'stock_status': stock, 'url': _url(t_elem.find('a', href=True)),
            })
        except Exception as e:
            print(f"  [cartonespesados] skipping item: {e}")
    return res


def cartonazo(html):
    """WooCommerce."""
    return _parse_woo_li(html, link_cls='woocommerce-LoopProduct-link')


def dementegames(html):
    """PrestaShop. OOS flag uses hyphenated class 'out-of-stock'."""
    return _parse_presta(html, oos_flag='out-of-stock')


def drjuegos(html):
    """PrestaShop variant. Uses article.product-container and availability div for stock."""
    res = []
    for item in (html.find_all('article', class_='product-container') if html else []):
        try:
            t_elem = item.find('h5', class_='product-name')
            if not t_elem:
                continue
            # Uses 'price product-price' span (multi-class) instead of the standard 'price'.
            price_elem = item.find('span', class_='price product-price')
            reg_elem   = item.find('span', class_='regular-price')
            orig, curr = _norm(
                _txt(reg_elem) or _txt(price_elem),
                _txt(price_elem) if reg_elem else None,
            )
            avail = _txt(item.find('div', class_='product-availability')) or ''
            stock = "Agotado" if _oos(avail) else ("Oferta" if item.find('div', class_='product-flags') else None)
            res.append({
                'title': _txt(t_elem), 'original_price': orig, 'current_price': curr,
                'stock_status': stock, 'url': _url(t_elem.find('a', href=True)),
            })
        except Exception as e:
            print(f"  [drjuegos] skipping item: {e}")
    return res


def vudugaming(html):
    """Custom store. Stock detected via label text and disabled add-to-cart button."""
    res = []
    for item in (html.find_all('article', class_='product-block') if html else []):
        try:
            t_elem = item.find('a', class_='product-block__name')
            if not t_elem:
                continue
            old  = item.find('div', class_='product-block__price--old')
            new_ = item.find('div', class_='product-block__price--new')
            orig, curr = _norm(
                _txt(old) or _txt(item.find('div', class_='product-block__price')),
                _txt(new_) if old else None,
            )
            btn = item.find('button', class_='product-block__button--add-to-cart')
            oos = (
                any(_oos(_txt(l)) for l in item.find_all('div', class_='product-block__label'))
                or bool(btn and btn.has_attr('disabled'))
            )
            res.append({
                'title': _txt(t_elem), 'original_price': orig, 'current_price': curr,
                'stock_status': "Agotado" if oos else ("Oferta" if curr else None),
                'url': _url(t_elem, "https://www.vudugaming.cl"),
            })
        except Exception as e:
            print(f"  [vudugaming] skipping item: {e}")
    return res


def piedrabruja(html):
    """Shopify. Inverted naming: price__regular = current sale price, price__sale = original."""
    res = []
    for item in (html.find_all('div', class_='product-card') if html else []):
        try:
            t_elem = item.find('a', class_='product-card__title')
            if not t_elem:
                continue
            pc     = item.find('div', class_='price')
            reg_p  = pc.find('span', class_='price__regular') if pc else None
            sale_p = pc.find('span', class_='price__sale')    if pc else None
            # Counter-intuitive naming: __regular holds the sale price, __sale holds the crossed-out original.
            orig, curr = _norm(
                _txt(sale_p) if sale_p else _txt(reg_p),
                _txt(reg_p) if sale_p else None,
            )
            btn     = item.find('button', class_='cowlendar-add-to-cart')
            btn_txt = btn.find('span', class_='hidden md:block') if btn else None
            oos     = bool(btn_txt and _oos(_txt(btn_txt)))
            badges  = item.find('div', class_='badges')
            stock   = "Agotado" if oos else (
                "Oferta" if curr or (badges and badges.find('span', class_='badge--onsale')) else None
            )
            res.append({
                'title': _txt(t_elem), 'original_price': orig, 'current_price': curr,
                'stock_status': stock, 'url': _url(t_elem, "https://piedrabruja.cl"),
            })
        except Exception as e:
            print(f"  [piedrabruja] skipping item: {e}")
    return res


def gatoarcano(html):
    """WooCommerce with custom AJAX pagination. Extra OOS via span.now_sold."""
    return _parse_woo_li(
        html,
        link_cls=None,
        extra_oos=lambda item: bool(item.find('span', class_='now_sold')),
    )


def ludipuerto(html):
    """WooCommerce/Woodmart. Same container structure as updown but different item class."""
    res = []
    for item in (html.find_all('div', class_='product-grid-item') if html else []):
        try:
            t_elem = item.find('h3', class_='wd-entities-title')
            if not t_elem:
                continue
            orig, curr = _norm(*_woo_prices(item.find('span', class_='price')))
            stock = _stock_cls(item.get('class', []), curr)
            res.append({
                'title': _txt(t_elem), 'original_price': orig, 'current_price': curr,
                'stock_status': stock, 'url': _url(t_elem.find('a', href=True)),
            })
        except Exception as e:
            print(f"  [ludipuerto] skipping item: {e}")
    return res


def magicsur(html):
    """PrestaShop variant. Prices in product-price-and-shipping div."""
    res = []
    for item in (html.find_all('article', class_='product-miniature') if html else []):
        try:
            t_elem = item.find('h2', class_='product-title')
            if not t_elem:
                continue
            pc   = item.find('div', class_='product-price-and-shipping')
            orig, curr = _norm(
                _txt(pc.find('span', class_='regular-price') if pc else None),
                _txt(pc.find('span', class_='product-price')  if pc else None),
            )
            check = ' '.join(filter(None, [
                _txt(item.find('div', class_='product-availability')),
                _txt(item.find('ul',  class_='product-flags')),
            ]))
            stock = "Agotado" if _oos(check) else ("Oferta" if curr else None)
            res.append({
                'title': _txt(t_elem), 'original_price': orig, 'current_price': curr,
                'stock_status': stock, 'url': _url(t_elem.find('a', href=True)),
            })
        except Exception as e:
            print(f"  [magicsur] skipping item: {e}")
    return res


def mangaigames(html):
    """WooCommerce with Astra theme link class."""
    return _parse_woo_li(html, link_cls='ast-loop-product__link')


def revaruk(html):
    """WooCommerce/Astra. Extra OOS via ast-shop-product-out-of-stock; extra sale via ast-onsale-card."""
    return _parse_woo_li(
        html,
        link_cls='ast-loop-product__link',
        extra_oos=lambda item: bool(
            (s := item.find('span', class_='ast-shop-product-out-of-stock')) and _oos(_txt(s))
        ),
        extra_sale=lambda item: bool(item.find('span', class_='ast-onsale-card')),
    )


def top8(html):
    """BS-collection store."""
    return _parse_bs(html, item_tag='section', item_cls='grid__item', base_url="https://www.top8.cl")


def gameofmagictienda(html):
    """BS-collection store."""
    return _parse_bs(html, item_tag='section', item_cls='grid__item', base_url="https://www.gameofmagictienda.cl")


def cardgame(html):
    """BS-collection store. Uses div containers instead of section."""
    return _parse_bs(html, item_tag='div', item_cls='bs-collection__product', base_url="https://www.cardgame.cl")

def labovedadelmago(html):
    """WooCommerce generic implementation. Relies on standard loop classes and _parse_woo_li."""
    return _parse_woo_li(
        html, 
        link_cls='woocommerce-LoopProduct-link',
        extra_sale=lambda item: item.find('span', class_='onsale') is not None
    )
def calabozotienda(html):
    res = []
    for item in (html.find_all('div', class_='card mb-3 box-shadow') if html else []):
        try:
            p_elem = item.find('p', class_='card-text')
            t_elem = p_elem.find('span') if p_elem else None
            if not t_elem: 
                continue

            orig = _txt(item.find('span', style=lambda s: s and 'line-through' in s))
            curr = _txt(item.find('span', class_='font-color'))
            orig, curr = _norm(orig or curr, curr if orig else None)

            stock = "Agotado" if item.find('span', class_='badge-danger') else ("Oferta" if curr or item.find('span', class_='burbuja-descuento') else None)

            res.append({
                'title': _txt(t_elem), 
                'original_price': orig, 
                'current_price': curr, 
                'stock_status': stock, 
                'url': _url(item.find('a', href=True), "https://www.calabozotienda.cl")
            })
        except Exception as e: 
            print(f"  [calabozotienda] skip: {e}")
    return res

def zonaxgamers(html):
    res = []
    for item in (html.find_all('div', class_='product-block__wrapper') if html else []):
        try:
            t_elem = item.find('a', class_='product-block__name')
            if not t_elem:
                continue

            old = item.find('div', class_='product-block__price--old')
            new_ = item.find('div', class_='product-block__price--new')
            orig, curr = _norm(
                _txt(old) or _txt(item.find('div', class_='product-block__price')),
                _txt(new_) if old else None,
            )

            btn = item.find('button', class_='product-block__button--add-to-cart')
            oos = (
                any(_oos(_txt(l)) for l in item.find_all('div', class_='product-block__label'))
                or bool(btn and btn.has_attr('disabled'))
            )

            stock = "Agotado" if oos else ("Oferta" if curr else None)

            res.append({
                'title': _txt(t_elem),
                'original_price': orig,
                'current_price': curr,
                'stock_status': stock,
                'url': _url(t_elem, "https://zonaxgamers.cl"),
            })
        except Exception as e:
            print(f"  [zonaxgamers] skip: {e}")
    return res

def cafe2d6(html):
    res = []
    for item in (html.find_all('li', class_='item') if html else []):
        try:
            t_elem = item.find('h3')
            if not t_elem:
                continue

            pc = item.find('p', class_='price')
            orig, curr = None, None
            if pc:
                span = pc.find('span')
                if span:
                    orig = _txt(span)
                    span.extract()
                    curr = _txt(pc)
                else:
                    orig = _txt(pc)
            
            orig, curr = _norm(orig, curr)
            
            cls = item.get('class', [])
            oos = 'sold-out' in cls or item.find(class_='add-to-agotado')
            stock = "Agotado" if oos else ("Oferta" if 'on-sale' in cls or curr else None)

            res.append({
                'title': _txt(t_elem),
                'original_price': orig,
                'current_price': curr,
                'stock_status': stock,
                'url': _url(item.find('a', href=True), "https://www.cafe2d6.cl")
            })
        except Exception as e:
            print(f"  [cafe2d6] skip: {e}")
    return res

def griffingames(html):
    res = []
    for item in (html.find_all('div', class_='product_item--inner') if html else []):
        try:
            t_elem = item.find('h3', class_='product_item--title')
            if not t_elem:
                continue

            orig, curr = _norm(*_woo_prices(item.find('span', class_='price')))
            
            parent_cls = item.parent.get('class', []) if item.parent else []
            btn = item.find('a', class_='button')
            oos = 'outofstock' in parent_cls or (btn and _oos(_txt(btn)))
            
            stock = "Agotado" if oos else ("Oferta" if curr or item.find('span', class_='onsale') else None)

            res.append({
                'title': _txt(t_elem),
                'original_price': orig,
                'current_price': curr,
                'stock_status': stock,
                'url': _url(t_elem.find('a', href=True))
            })
        except Exception as e:
            print(f"  [griffingames] skip: {e}")
    return res

def playcenter(html):
    """WooCommerce/Astra generic implementation."""
    return _parse_woo_li(html, link_cls='ast-loop-product__link')

def enroque(html):
    res = []
    for item in (html.find_all('li', class_='js-pagination-result') if html else []):
        try:
            t_elem = item.find('a', class_='card-link')
            if not t_elem:
                continue

            orig, curr = None, None
            pc = item.find('div', class_='price__default')
            if pc:
                was = pc.find('s', class_='price__was')
                cur = pc.find('strong', class_='price__current')
                orig, curr = _norm(
                    _txt(was) or _txt(cur),
                    _txt(cur) if _txt(was) else None
                )
            
            oos = bool(item.find('span', class_='product-label--sold-out') or item.find('div', class_=lambda c: c and 'price--sold-out' in c))
            stock = "Agotado" if oos else ("Oferta" if curr or item.find('span', class_='product-label--sale') else None)

            res.append({
                'title': _txt(t_elem),
                'original_price': orig,
                'current_price': curr,
                'stock_status': stock,
                'url': _url(t_elem, "https://juegosenroque.cl")
            })
        except Exception as e:
            print(f"  [enroque] skip: {e}")
    return res

def kaiojuegos(html):
    res = []
    for item in (html.find_all('div', class_='thumbnail-container') if html else []):
        try:
            if not (t_elem := item.find('h3', class_='product-title')): continue
            
            pc = item.find('div', class_='product-price-and-shipping')
            reg = _txt(pc.find('span', class_='regular-price')) if pc else None
            price = _txt(pc.find('span', class_='price')) if pc else None
            orig, curr = _norm(reg or price, price if reg else None)
            
            flags = _txt(item.find('ul', class_='product-flags')) or ''
            oos = _oos(flags) or bool((btn := item.find('button', class_='add-to-cart')) and btn.has_attr('disabled'))
            stock = "Agotado" if oos else ("Oferta" if curr or 'oferta' in flags.lower() else None)

            res.append({
                'title': _txt(t_elem), 
                'original_price': orig, 
                'current_price': curr, 
                'stock_status': stock, 
                'url': _url(t_elem.find('a', href=True), "https://kaiojuegos.cl")
            })
        except Exception as e: 
            print(f"  [kaiojuegos] skip: {e}")
    return res

def manahouse(html):
    res = []
    for item in (html.find_all('div', class_='product-grid-item') if html else []):
        try:
            if not (t_elem := item.find('a', class_='product-grid-item__title')): continue
            
            orig, curr = None, None
            if pc := item.find(class_='product-grid-item__price'):
                was = pc.find(['s', 'del'])
                if was:
                    orig_text = _txt(was)
                    was.extract()
                    orig, curr = _norm(orig_text, _txt(pc))
                else:
                    orig, curr = _norm(_txt(pc), None)

            btn = item.find('button', attrs={'name': 'add'})
            badges = item.find_all(class_=lambda c: c and ('badge' in c.lower() or 'label' in c.lower()))
            oos = bool(btn and btn.has_attr('disabled')) or any(_oos(_txt(b)) for b in badges)
            
            stock = "Agotado" if oos else ("Oferta" if curr else None)

            res.append({
                'title': _txt(t_elem),
                'original_price': orig,
                'current_price': curr,
                'stock_status': stock,
                'url': _url(t_elem, "https://manahouse.cl")
            })
        except Exception as e:
            print(f"  [manahouse] skip: {e}")
    return res

def devir(html):
    res = []
    for item in (html.find_all('li', class_='product-item') if html else []):
        try:
            if not (t_elem := item.find('a', class_='product-item-link')): continue
            
            orig, curr = None, None
            pc = item.find('div', class_='price-box')
            if pc:
                old_p = pc.find('span', class_='old-price')
                new_p = pc.find('span', class_='special-price')
                
                if old_p and new_p:
                    orig_val = _txt(old_p.find('span', class_='price'))
                    curr_val = _txt(new_p.find('span', class_='price'))
                    orig, curr = _norm(orig_val, curr_val)
                else:
                    orig, curr = _norm(_txt(pc.find('span', class_='price')), None)

            action_area = item.find('div', class_='actions-primary')
            action_text = _txt(action_area).lower() if action_area else ""
            
            oos = 'avísame' in action_text or 'avisame' in action_text or bool(item.find('div', class_='stock unavailable'))
            stock = "Agotado" if oos else ("Oferta" if curr else None)

            res.append({
                'title': _txt(t_elem),
                'original_price': orig,
                'current_price': curr,
                'stock_status': stock,
                'url': _url(t_elem, "https://devir.cl")
            })
        except Exception as e:
            print(f"  [devir] skip: {e}")
    return res
    
def thirdimpact(html):
    res = []
    for item in (html.find_all('section', class_='grid__item') if html else []):
        try:
            if not (t_elem := item.find('h3', class_='bs-collection__product-title')): 
                continue

            orig, curr = None, None
            pc = item.find('div', class_='bs-collection__product-price')
            if pc:
                del_e = pc.find('del', class_='bs-collection__old-price')
                fin_e = pc.find('div', class_=lambda c: c and 'bs-collection__product-final-price' in c)
                orig, curr = _norm(_txt(del_e) or _txt(fin_e), _txt(fin_e) if del_e else None)

            btn = item.find('button', attrs={'data-bs': 'cart.add.collection'})
            oos = not btn or btn.has_attr('disabled')
            stock = "Agotado" if oos else ("Oferta" if curr else None)

            res.append({
                'title': _txt(t_elem),
                'original_price': orig,
                'current_price': curr,
                'stock_status': stock,
                'url': _url(item.find('a', href=True), "https://www.thirdimpact.cl")
            })
        except Exception as e:
            print(f"  [thirdimpact] skip: {e}")
    return res

def buhojuegosdemesa(html):
    res = []
    for item in (html.find_all('a', class_='product-card') if html else []):
        try:
            if not (t_elem := item.find('div', class_='product-card__name')): continue

            orig, curr = None, None
            pc = item.find('div', class_='product-card__price')
            if pc:
                for hidden in pc.find_all('span', class_='visually-hidden'):
                    hidden.extract()
                was = pc.find('s')
                if was:
                    orig_val = _txt(was)
                    was.extract()
                    orig, curr = _norm(orig_val, _txt(pc))
                else:
                    orig, curr = _norm(_txt(pc), None)

            btn = item.find('span', class_='product-card__overlay-btn')
            tags = item.find_all('div', class_='product-tag')
            check_text = f"{_txt(btn)} {' '.join(_txt(t) for t in tags)}"
            
            oos = _oos(check_text)
            stock = "Agotado" if oos else ("Oferta" if curr else None)

            res.append({
                'title': _txt(t_elem),
                'original_price': orig,
                'current_price': curr,
                'stock_status': stock,
                'url': _url(item, "https://buhojuegosdemesa.cl")
            })
        except Exception as e:
            print(f"  [buhojuegosdemesa] skip: {e}")
    return res

def mirzu(html):
    """WooCommerce/Astra theme."""
    return _parse_woo_li(html, link_cls='ast-loop-product__link')
def peakgames(html):
    """BS-collection store."""
    return _parse_bs(html, item_tag='section', item_cls='grid__item', base_url="https://www.peakgames.cl")
def laloseta(html):
    """WooCommerce generic implementation."""
    return _parse_woo_li(html, link_cls='woocommerce-LoopProduct-link')
    
# ── Site registry ──────────────────────────────────────────────────────────────
#
# pagination styles:
#   'shopify'    → ?page=N        (page 1 uses bare URL)
#   'page_param' → ?page=N        (PrestaShop and others, same pattern)
#   'woo'        → /page/N/       (WooCommerce)
#   'gatoarcano' → custom AJAX    (handled explicitly in build_url)

sites = [
    {'name': 'flexo',            'base_url': 'https://www.flexogames.cl/collections/juegos-de-mesa',            'parser': flexogames,       'pagination': 'shopify',    'output': '../data/flexogames_jdm.csv'},
    {'name': 'lafortalezapuq',   'base_url': 'https://www.lafortalezapuq.cl/jdm',                               'parser': lafortalezapuq,   'pagination': 'shopify',    'output': '../data/lafortalezapuq_jdm.csv'},
    {'name': 'planetaloz',       'base_url': 'https://www.planetaloz.cl/14-juegos-de-mesa',                      'parser': planetaloz,       'pagination': 'page_param', 'output': '../data/planetaloz_jdm.csv'},
    {'name': 'updown',           'base_url': 'https://www.updown.cl/categoria-producto/juegos-de-mesa',          'parser': updown_juegos,    'pagination': 'woo',        'output': '../data/updown_jdm.csv'},
    {'name': 'aldeajuegos',      'base_url': 'https://www.aldeajuegos.cl/7-juegos-de-mesa',                      'parser': aldeajuegos,      'pagination': 'page_param', 'output': '../data/aldeajuegos_jdm.csv'},
    {'name': 'elpatiogeek',      'base_url': 'https://www.elpatiogeek.cl/collections/all',                       'parser': elpatiogeek,      'pagination': 'shopify',    'output': '../data/elpatiogeek_jdm.csv'},
    {'name': 'mangaigames',      'base_url': 'https://mangaigames.cl/tienda',                                    'parser': mangaigames,      'pagination': 'woo',        'output': '../data/mangaigames_jdm.csv'},
    {'name': 'cartonespesados',  'base_url': 'https://cartonespesados.cl/product-category/juegos-de-mesa',       'parser': cartonespesados,  'pagination': 'woo',        'output': '../data/cartonespesados_jdm.csv'},
    {'name': 'cartonazo',        'base_url': 'https://cartonazo.com/categoria-producto/juego-de-mesa',           'parser': cartonazo,        'pagination': 'woo',        'output': '../data/cartonazo_jdm.csv'},
    {'name': 'dementegames',     'base_url': 'https://dementegames.cl/10-juegos-de-mesa',                        'parser': dementegames,     'pagination': 'page_param', 'output': '../data/dementegames_jdm.csv'},
    {'name': 'drjuegos',         'base_url': 'https://www.drjuegos.cl/2-todos-los-productos',                    'parser': drjuegos,         'pagination': 'page_param', 'output': '../data/drjuegos_jdm.csv'},
    {'name': 'vudugaming',       'base_url': 'https://www.vudugaming.cl/juegos-de-mesa',                         'parser': vudugaming,       'pagination': 'page_param', 'output': '../data/vudugaming_jdm.csv'},
    {'name': 'piedrabruja',      'base_url': 'https://piedrabruja.cl/collections/juegos-de-mesa',                'parser': piedrabruja,      'pagination': 'shopify',    'output': '../data/piedrabruja_jdm.csv'},
    {'name': 'gatoarcano',       'base_url': 'https://gatoarcano.cl/product-category/juegos-de-mesa',            'parser': gatoarcano,       'pagination': 'gatoarcano', 'output': '../data/gatoarcano_jdm.csv'},
    {'name': 'ludipuerto',       'base_url': 'https://www.ludipuerto.cl/categoria-producto/juegos-de-mesa',      'parser': ludipuerto,       'pagination': 'woo',        'output': '../data/ludipuerto_jdm.csv'},
    {'name': 'magicsur',         'base_url': 'https://www.magicsur.cl/15-juegos-de-mesa-magicsur-chile',         'parser': magicsur,         'pagination': 'page_param', 'output': '../data/magicsur_jdm.csv'},
    {'name': 'gameofmagictienda','base_url': 'https://www.gameofmagictienda.cl/collection/juegos-de-mesa',       'parser': gameofmagictienda,'pagination': 'page_param', 'output': '../data/gameofmagictienda_jdm.csv'},
    {'name': 'top8',             'base_url': 'https://www.top8.cl/collection/juegos-de-mesa',                    'parser': top8,             'pagination': 'page_param', 'output': '../data/top8_jdm.csv'},
    {'name': 'revaruk',          'base_url': 'https://revaruk.cl/product-category/juegos-de-mesa',               'parser': revaruk,          'pagination': 'woo',        'output': '../data/revaruk_jdm.csv'},
    {'name': 'cardgame',         'base_url': 'https://www.cardgame.cl/collection/juegos-de-mesa',                'parser': cardgame,         'pagination': 'page_param', 'output': '../data/cardgame_jdm.csv'},
    {'name': 'labovedadelmago',  'base_url': 'https://www.labovedadelmago.cl/categoria-producto/juegos-de-mesa', 'parser': labovedadelmago,'pagination': 'woo', 'output': '../data/labovedadelmago_jdm.csv'},
    {'name': 'calabozotienda', 'base_url': 'https://www.calabozotienda.cl/tienda/familia/JUEGOS%20DE%20MESA', 'parser': calabozotienda, 'pagination': 'calabozo', 'output': '../data/calabozotienda_jdm.csv'},
    {'name': 'zonaxgamers', 'base_url': 'https://zonaxgamers.cl/juegos-de-mesa', 'parser': zonaxgamers, 'pagination': 'page_param', 'output': '../data/zonaxgamers_jdm.csv'},
    {'name': 'cafe2d6', 'base_url': 'https://www.cafe2d6.cl/collections/all', 'parser': cafe2d6, 'pagination': 'shopify', 'output': '../data/cafe2d6_jdm.csv'},
    {'name': 'griffingames', 'base_url': 'https://www.griffingames.cl/categoria-producto/juegos-de-mesa', 'parser': griffingames, 'pagination': 'woo', 'output': '../data/griffingames_jdm.csv'},
    {'name': 'playcenter', 'base_url': 'https://playcenter.cl/categoria-producto/juegos-de-mesa', 'parser': playcenter, 'pagination': 'woo', 'output': '../data/playcenter_jdm.csv'},
    {'name': 'enroque', 'base_url': 'https://juegosenroque.cl/collections/todos-los-juegos-de-mesa', 'parser': enroque, 'pagination': 'shopify', 'output': '../data/enroque_jdm.csv'},
    {'name': 'kaiojuegos', 'base_url': 'https://kaiojuegos.cl/18-juegos-de-mesa', 'parser': kaiojuegos, 'pagination': 'page_param', 'output': '../data/kaiojuegos_jdm.csv'},
    {'name': 'manahouse', 'base_url': 'https://manahouse.cl/collections/juegos-de-mesa', 'parser': manahouse, 'pagination': 'shopify', 'output': '../data/manahouse_jdm.csv'},
    {'name': 'devir', 'base_url': 'https://devir.cl/juegos-de-mesa', 'parser': devir, 'pagination': 'devir', 'output': '../data/devir_jdm.csv'},
    {'name': 'thirdimpact_asmodee', 'base_url': 'https://www.thirdimpact.cl/brand/asmodee', 'parser': thirdimpact, 'pagination': 'page_param', 'output': '../data/thirdimpact_asmodee_jdm.csv'},
    {'name': 'thirdimpact_devir', 'base_url': 'https://www.thirdimpact.cl/brand/devir', 'parser': thirdimpact, 'pagination': 'page_param', 'output': '../data/thirdimpact_devir_jdm.csv'},
    {'name': 'buho', 'base_url': 'https://buhojuegosdemesa.cl/collections/catalogo', 'parser': buhojuegosdemesa, 'pagination': 'shopify', 'output': '../data/buho_jdm.csv'},
    {'name': 'mirzu', 'base_url': 'https://mirzu.cl/tienda', 'parser': mirzu, 'pagination': 'woo', 'output': '../data/mirzu_jdm.csv'},
    {'name': 'peakgames', 'base_url': 'https://www.peakgames.cl/collection/juegos-de-mesa', 'parser': peakgames, 'pagination': 'page_param', 'output': '../data/peakgames_jdm.csv'},
    {'name': 'laloseta', 'base_url': 'https://laloseta.cl/categoria-producto/juego-de-mesa', 'parser': laloseta, 'pagination': 'woo', 'output': '../data/laloseta_jdm.csv'}
]



def build_url(base_url, pagination, page):
    """Construct the paginated URL for a given page number and pagination style."""
    if pagination == 'gatoarcano':
        return f"{base_url}/?jsf=epro-archive-products&pagenum={page}"
    if pagination == 'calabozo':
        return f"{base_url}/{page}"
    if page == 1:
        return base_url
    if pagination in ('shopify', 'page_param'):
        return f"{base_url}?page={page}"
    if pagination == 'devir':
        return f"{base_url}?p={page}"
    if pagination == 'woo':
        return f"{base_url}/page/{page}/"
    raise ValueError(f"Unknown pagination style: {pagination}")
