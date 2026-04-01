"""
scrape.py
---------
HTML parsers for each board game store and the site configuration registry.
No I/O or scraping logic lives here — import this from main.py.
"""

import requests
from bs4 import BeautifulSoup


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def fetch_html(url):
    """GET a URL and return a BeautifulSoup tree, or None on any network error."""
    try:
        response = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            timeout=15
        )
        response.raise_for_status()
        return BeautifulSoup(response.text, 'html.parser')
    except requests.exceptions.RequestException as e:
        print(f"Network error on {url}: {e}")
        return None


# ---------------------------------------------------------------------------
# Parsers
# Each function receives a BeautifulSoup tree and returns a list of dicts:
#   { title, original_price, current_price, stock_status }
#
# Conventions:
#   original_price  — the normal / crossed-out price (always populated if any price exists)
#   current_price   — the discounted price; None when no discount is active
#   stock_status    — "Agotado", "Oferta", or None
# ---------------------------------------------------------------------------

def flexogames(html):
    if not html:
        return []
    extracted_data = []
    list_items = html.find_all('li', class_='grid__item')
    for item in list_items:
        title_div = item.find('div', class_='grid-view-item__title')
        if not title_div:
            continue
        title = title_div.get_text(strip=True)
        
        link_elem = item.find('a', class_='grid-view-item__link')
        url = "https://www.flexogames.cl" + link_elem['href'] if link_elem else None

        current_price = None
        original_price = None
        price_compare_elem = item.find('div', class_='price__compare')
        s_tag = price_compare_elem.find('s') if price_compare_elem else None
        if s_tag and s_tag.get_text(strip=True):
            original_price = s_tag.get_text(strip=True)
            sale_span = item.find('span', class_='price-item--sale')
            current_price = sale_span.get_text(strip=True) if sale_span else None
        else:
            reg_div = item.find('div', class_='price__regular')
            if reg_div:
                reg_span = reg_div.find('span', class_='price-item--regular')
                original_price = reg_span.get_text(strip=True) if reg_span else None

        if current_price == original_price:
            current_price = None

        dl_elem = item.find('dl', class_='price')
        stock_status = "Agotado" if dl_elem and 'price--sold-out' in dl_elem.get('class', []) else None

        extracted_data.append({
            'title': title, 'original_price': original_price, 'current_price': current_price,
            'stock_status': stock_status, 'url': url
        })
    return extracted_data


def lafortalezapuq(html):
    if not html:
        return []
    extracted_data = []
    list_items = html.find_all('figure', class_='product')
    for item in list_items:
        title_elem = item.find('h5')
        if not title_elem:
            continue
        title = title_elem.get_text(strip=True)
        
        link_elem = item.find('a', href=True)
        url = link_elem['href'] if link_elem else None

        current_price = None
        original_price = None
        discount_price_elem = item.find('span', class_='product-price-discount')
        if discount_price_elem:
            sale_elem = discount_price_elem.find('i')
            if sale_elem:
                current_price = sale_elem.get_text(strip=True)
                sale_elem.extract()
                original_price = discount_price_elem.get_text(strip=True)
        else:
            regular_price_elem = item.find('span', class_='product-price')
            if regular_price_elem:
                original_price = regular_price_elem.get_text(strip=True)

        if current_price == original_price:
            current_price = None

        extracted_data.append({
            'title': title, 'original_price': original_price, 'current_price': current_price,
            'stock_status': None, 'url': 'https://www.lafortalezapuq.cl'+url
        })
    return extracted_data


def planetaloz(html):
    if not html:
        return []
    extracted_data = []
    list_items = html.find_all('article', class_='product-miniature')
    for item in list_items:
        title_elem = item.find('h1', class_='product-title')
        if not title_elem:
            continue
        title = title_elem.get_text(strip=True)
        
        link_elem = title_elem.find('a', href=True)
        url = link_elem['href'] if link_elem else None

        price_elem = item.find('span', class_='price')
        regular_elem = item.find('span', class_='regular-price')
        
        # Extract and clean text (handling leading/trailing whitespace and non-breaking spaces)
        raw_price = price_elem.get_text(strip=True) if price_elem else None
        raw_regular = regular_elem.get_text(strip=True) if regular_elem else None

        if raw_regular:
            original_price = raw_regular
            current_price = raw_price
        else:
            original_price = raw_price
            current_price = None

        if current_price == original_price:
            current_price = None

        # Offer status logic
        stock_elem = item.find('li', class_='out_of_stock')
        is_agotado = True if stock_elem else False
        
        stock_status = None
        if is_agotado:
            stock_status = "Agotado"
        elif current_price:
            stock_status = "Oferta"

        extracted_data.append({
            'title': title, 
            'original_price': original_price, 
            'current_price': current_price,
            'stock_status': stock_status, 
            'url': url
        })
    return extracted_data

def updown_juegos(html):
    if not html:
        return []
    extracted_data = []
    list_items = html.find_all('div', class_='product-element-bottom')
    for item in list_items:
        title_elem = item.find('h3', class_='wd-entities-title')
        if not title_elem:
            continue
        title = title_elem.get_text(strip=True)
        
        link_elem = title_elem.find('a', href=True)
        url = link_elem['href'] if link_elem else None

        price_container = item.find('span', class_='price')
        if not price_container:
            continue
        del_elem = price_container.find('del')
        ins_elem = price_container.find('ins')
        if del_elem and ins_elem:
            original_price = del_elem.get_text(strip=True)
            current_price = ins_elem.get_text(strip=True)
        else:
            bdi_elem = price_container.find('bdi')
            original_price = bdi_elem.get_text(strip=True) if bdi_elem else price_container.get_text(strip=True)
            current_price = None

        if current_price == original_price:
            current_price = None

        parent_container = item.parent
        stock_elem = parent_container.find('span', class_='out-of-stock')
        extracted_data.append({
            'title': title, 'original_price': original_price, 'current_price': current_price,
            'stock_status': "Agotado" if stock_elem else None, 'url': url
        })
    return extracted_data


def aldeajuegos(html):
    if not html:
        return []
    extracted_data = []
    list_items = html.find_all('article', class_='product-miniature')
    for item in list_items:
        title_elem = item.find('h2', class_='product-title')
        if not title_elem:
            continue
        title = title_elem.get_text(strip=True)
        
        link_elem = title_elem.find('a', href=True)
        url = link_elem['href'] if link_elem else None

        price_elem = item.find('span', class_='price')
        regular_elem = item.find('span', class_='regular-price')
        if regular_elem:
            original_price = regular_elem.get_text(strip=True)
            current_price = price_elem.get_text(strip=True) if price_elem else None
        else:
            original_price = price_elem.get_text(strip=True) if price_elem else None
            current_price = None

        if current_price == original_price:
            current_price = None

        stock_status = None
        flags_container = item.find('ul', class_='product-flags')
        if flags_container:
            if flags_container.find('li', class_='out_of_stock'): stock_status = "Agotado"
            elif flags_container.find('li', class_='discount') or current_price: stock_status = "Oferta"

        extracted_data.append({
            'title': title, 'original_price': original_price, 'current_price': current_price,
            'stock_status': stock_status, 'url': url
        })
    return extracted_data


def elpatiogeek(html):
    if not html:
        return []
    extracted_data = []
    list_items = html.find_all('div', class_='grid-item')
    for item in list_items:
        product_link = item.find('a', class_='product-grid-item')
        if not product_link:
            continue
            
        url = "https://www.elpatiogeek.cl" + product_link['href'] if product_link.has_attr('href') else None
        
        title_elem = item.find('p')
        title = title_elem.get_text(strip=True) if title_elem else None
        if not title:
            continue

        price_val = None
        current_price = None
        original_price = None
        
        # Primary price extraction
        price_container = item.find('div', class_='product-item--price')
        if price_container:
            small_tag = price_container.find('small')
            if small_tag:
                price_val = small_tag.get_text(strip=True)
            else:
                span_h1 = price_container.find('span', class_='h1')
                if span_h1:
                    spans = span_h1.find_all('span', class_='visually-hidden')
                    price_val = spans[-1].get_text(strip=True) if spans else span_h1.get_text(strip=True)

        # Sale tag extraction (contains the crossed-out original price)
        sale_tag = item.find('div', class_='sale-tag')
        classes = item.get('class', [])
        
        if sale_tag:
            # If sale-tag exists, the primary price_val is the discounted (current) price
            original_price = sale_tag.get_text(strip=True) or None
            current_price = price_val
        else:
            # If no sale-tag, price_val is the standard (original) price
            original_price = price_val
            current_price = None

        if current_price == original_price:
            current_price = None

        # Stock status
        stock_status = None
        if 'sold-out' in classes:
            stock_status = "Agotado"
        elif 'on-sale' in classes or current_price:
            stock_status = "Oferta"

        extracted_data.append({
            'title': title, 
            'current_price': current_price, 
            'original_price': original_price,
            'stock_status': stock_status, 
            'url': url
        })
    return extracted_data


def cartonespesados(html):
    if not html:
        return []
    extracted_data = []
    list_items = html.find_all('li', class_='wc-block-product')
    for item in list_items:
        title_elem = item.find('h3', class_='wp-block-post-title')
        if not title_elem:
            continue
        title = title_elem.get_text(strip=True)
        
        link_elem = title_elem.find('a', href=True)
        url = link_elem['href'] if link_elem else None

        current_price = None
        original_price = None
        price_container = item.find('div', class_='wc-block-components-product-price')
        if price_container:
            del_elem, ins_elem = price_container.find('del'), price_container.find('ins')
            if del_elem and ins_elem:
                original_price, current_price = del_elem.get_text(strip=True), ins_elem.get_text(strip=True)
            else:
                bdi_elem = price_container.find('bdi')
                original_price = bdi_elem.get_text(strip=True) if bdi_elem else price_container.get_text(strip=True).replace('IVA INC', '').strip()

        classes = item.get('class', [])
        stock_status = "Agotado" if 'outofstock' in classes else ("Oferta" if 'onsale' in classes or current_price else None)
        extracted_data.append({
            'title': title, 'current_price': current_price, 'original_price': original_price,
            'stock_status': stock_status, 'url': url
        })
    return extracted_data


def cartonazo(html):
    if not html:
        return []
    extracted_data = []
    list_items = html.find_all('li', class_='product')
    for item in list_items:
        title_elem = item.find('h2', class_='woocommerce-loop-product__title')
        if not title_elem:
            continue
        title = title_elem.get_text(strip=True)
        
        link_elem = item.find('a', class_='woocommerce-LoopProduct-link', href=True)
        url = link_elem['href'] if link_elem else None

        current_price = None
        original_price = None
        price_container = item.find('span', class_='price')
        if price_container:
            del_elem, ins_elem = price_container.find('del'), price_container.find('ins')
            if del_elem and ins_elem:
                original_price, current_price = del_elem.get_text(strip=True), ins_elem.get_text(strip=True)
            else:
                bdi_elem = price_container.find('bdi')
                original_price = bdi_elem.get_text(strip=True) if bdi_elem else price_container.get_text(strip=True)

        classes = item.get('class', [])
        stock_status = "Agotado" if 'outofstock' in classes else ("Oferta" if 'sale' in classes or current_price else None)
        extracted_data.append({
            'title': title, 'current_price': current_price, 'original_price': original_price,
            'stock_status': stock_status, 'url': url
        })
    return extracted_data


def dementegames(html):
    if not html:
        return []
    extracted_data = []
    list_items = html.find_all('article', class_='product-miniature')
    for item in list_items:
        title_elem = item.find('h2', class_='product-title')
        if not title_elem:
            continue
        title = title_elem.get_text(strip=True)
        
        link_elem = title_elem.find('a', href=True)
        url = link_elem['href'] if link_elem else None

        price_elem, regular_elem = item.find('span', class_='price'), item.find('span', class_='regular-price')
        if regular_elem:
            original_price, current_price = regular_elem.get_text(strip=True), (price_elem.get_text(strip=True) if price_elem else None)
        else:
            original_price, current_price = (price_elem.get_text(strip=True) if price_elem else None), None

        if current_price == original_price: current_price = None
        stock_status = None
        flags_container = item.find('ul', class_='product-flags')
        if flags_container:
            if flags_container.find('li', class_='out-of-stock'): stock_status = "Agotado"
            elif flags_container.find('li', class_='discount') or current_price: stock_status = "Oferta"

        extracted_data.append({
            'title': title, 'current_price': current_price, 'original_price': original_price,
            'stock_status': stock_status, 'url': url
        })
    return extracted_data


def drjuegos(html):
    if not html:
        return []
    extracted_data = []
    list_items = html.find_all('article', class_='product-container')
    for item in list_items:
        title_elem = item.find('h5', class_='product-name')
        if not title_elem:
            continue
        title = title_elem.get_text(strip=True)
        
        link_elem = title_elem.find('a', href=True)
        url = link_elem['href'] if link_elem else None

        price_elem, regular_elem = item.find('span', class_='price product-price'), item.find('span', class_='regular-price')
        if regular_elem:
            original_price, current_price = regular_elem.get_text(strip=True), (price_elem.get_text(strip=True) if price_elem else None)
        else:
            original_price, current_price = (price_elem.get_text(strip=True) if price_elem else None), None

        if current_price == original_price: current_price = None
        stock_status = None
        avail_elem = item.find('div', class_='product-availability')
        if avail_elem and any(x in avail_elem.get_text(strip=True).lower() for x in ['agotado', 'sin stock', 'no disponible']):
            stock_status = "Agotado"
        if stock_status != "Agotado" and item.find('div', class_='product-flags'):
            stock_status = "Oferta"

        extracted_data.append({
            'title': title, 'current_price': current_price, 'original_price': original_price,
            'stock_status': stock_status, 'url': url
        })
    return extracted_data


def vudugaming(html):
    if not html:
        return []
    extracted_data = []
    list_items = html.find_all('article', class_='product-block')
    for item in list_items:
        title_elem = item.find('a', class_='product-block__name')
        if not title_elem:
            continue
        title = title_elem.get_text(strip=True)
        url = "https://www.vudugaming.cl" + title_elem['href'] if title_elem.has_attr('href') else None

        current_price, original_price = None, None
        new_price_elem, old_price_elem = item.find('div', class_='product-block__price--new'), item.find('div', class_='product-block__price--old')
        if old_price_elem:
            original_price, current_price = old_price_elem.get_text(strip=True), (new_price_elem.get_text(strip=True) if new_price_elem else None)
        else:
            price_elem = item.find('div', class_='product-block__price')
            if price_elem: original_price = price_elem.get_text(strip=True)

        is_agotado = any('agotado' in l.get_text(strip=True).lower() for l in item.find_all('div', class_='product-block__label'))
        add_btn = item.find('button', class_='product-block__button--add-to-cart')
        if add_btn and add_btn.has_attr('disabled'): is_agotado = True

        stock_status = "Agotado" if is_agotado else ("Oferta" if current_price else None)
        extracted_data.append({
            'title': title, 'current_price': current_price, 'original_price': original_price,
            'stock_status': stock_status, 'url': url
        })
    return extracted_data


def piedrabruja(html):
    if not html:
        return []
    extracted_data = []
    list_items = html.find_all('div', class_='product-card')
    for item in list_items:
        title_elem = item.find('a', class_='product-card__title')
        if not title_elem:
            continue
        title = title_elem.get_text(strip=True)
        url = "https://piedrabruja.cl" + title_elem['href'] if title_elem.has_attr('href') else None

        current_price, original_price = None, None
        price_container = item.find('div', class_='price')
        if price_container:
            reg_p, sale_p = price_container.find('span', class_='price__regular'), price_container.find('span', class_='price__sale')
            if sale_p and reg_p:
                current_price, original_price = reg_p.get_text(strip=True), sale_p.get_text(strip=True)
            elif reg_p:
                original_price = reg_p.get_text(strip=True)

        is_agotado = False
        add_to_cart_btn = item.find('button', class_='cowlendar-add-to-cart')
        if add_to_cart_btn:
            btn_txt = add_to_cart_btn.find('span', class_='hidden md:block')
            if btn_txt and 'agotado' in btn_txt.get_text(strip=True).lower(): is_agotado = True

        stock_status = "Agotado" if is_agotado else ("Oferta" if current_price or (item.find('div', class_='badges') and item.find('div', class_='badges').find('span', class_='badge--onsale')) else None)
        extracted_data.append({
            'title': title, 'current_price': current_price, 'original_price': original_price,
            'stock_status': stock_status, 'url': url
        })
    return extracted_data


def gatoarcano(html):
    if not html:
        return []
    extracted_data = []
    list_items = html.find_all('li', class_='product')
    for item in list_items:
        title_elem = item.find('h2', class_='woocommerce-loop-product__title')
        if not title_elem:
            continue
        title = title_elem.get_text(strip=True)
        
        link_elem = item.find('a', href=True)
        url = link_elem['href'] if link_elem else None

        current_price, original_price = None, None
        price_container = item.find('span', class_='price')
        if price_container:
            del_e, ins_e = price_container.find('del'), price_container.find('ins')
            if del_e and ins_e:
                original_price, current_price = del_e.get_text(strip=True), ins_e.get_text(strip=True)
            else:
                bdi = price_container.find('bdi')
                original_price = bdi.get_text(strip=True) if bdi else price_container.get_text(strip=True)

        stock_status = "Agotado" if 'outofstock' in item.get('class', []) or item.find('span', class_='now_sold') else ("Oferta" if 'sale' in item.get('class', []) or current_price else None)
        extracted_data.append({
            'title': title, 'current_price': current_price, 'original_price': original_price,
            'stock_status': stock_status, 'url': url
        })
    return extracted_data

def top8(html):
    if not html:
        return []

    extracted_data = []
    list_items = html.find_all('section', class_='grid__item')

    for item in list_items:
        title_elem = item.find('h3', class_='bs-collection__product-title')
        if not title_elem:
            continue

        title = title_elem.get_text(strip=True)
        
        # Link extraction
        link_elem = item.find('a', href=True)
        product_url = link_elem['href'] if link_elem else None
        if product_url and not product_url.startswith('http'):
            product_url = "https://www.top8.cl" + product_url

        current_price = None
        original_price = None
        stock_status = None

        price_container = item.find('div', class_='bs-collection__product-price')
        if price_container:
            del_elem = price_container.find('del', class_='bs-collection__old-price')
            final_price_elem = price_container.find('div', class_='bs-collection__product-final-price')

            if del_elem:
                original_price = del_elem.get_text(strip=True)
                current_price = final_price_elem.get_text(strip=True) if final_price_elem else None
            elif final_price_elem:
                original_price = final_price_elem.get_text(strip=True)

        if current_price == original_price:
            current_price = None

        is_agotado = False
        # Check for stock notice in comments or specific divs
        notice_elem = item.find('div', class_='bs-collection__product-notice')
        stock_badge = item.find('div', class_='bs-stock')
        
        check_text = ""
        if notice_elem: check_text += notice_elem.get_text(strip=True).lower()
        if stock_badge: check_text += stock_badge.get_text(strip=True).lower()
        
        if any(x in check_text for x in ['agotado', 'sin stock', 'fuera de stock']):
            is_agotado = True

        product_wrapper = item.find('div', class_='bs-collection__product')
        if product_wrapper and 'out-of-stock' in product_wrapper.get('class', []):
            is_agotado = True

        if is_agotado:
            stock_status = "Agotado"
        elif current_price or (product_wrapper and 'has-discount' in product_wrapper.get('class', [])):
            stock_status = "Oferta"

        extracted_data.append({
            'title': title,
            'current_price': current_price,
            'original_price': original_price,
            'stock_status': stock_status,
            'url': product_url
        })

    return extracted_data


def ludipuerto(html):
    if not html:
        return []
    extracted_data = []
    list_items = html.find_all('div', class_='product-grid-item')
    for item in list_items:
        title_elem = item.find('h3', class_='wd-entities-title')
        if not title_elem:
            continue
        title = title_elem.get_text(strip=True)
        
        link_elem = title_elem.find('a', href=True)
        url = link_elem['href'] if link_elem else None

        current_price, original_price = None, None
        price_container = item.find('span', class_='price')
        if price_container:
            del_e, ins_e = price_container.find('del'), price_container.find('ins')
            if del_e and ins_e:
                original_price, current_price = del_e.get_text(strip=True), ins_e.get_text(strip=True)
            else:
                bdi = price_container.find('bdi')
                original_price = bdi.get_text(strip=True) if bdi else price_container.get_text(strip=True)

        stock_status = "Agotado" if 'outofstock' in item.get('class', []) else ("Oferta" if 'sale' in item.get('class', []) or current_price else None)
        extracted_data.append({
            'title': title, 'current_price': current_price, 'original_price': original_price,
            'stock_status': stock_status, 'url': url
        })
    return extracted_data


def magicsur(html):
    if not html:
        return []
    extracted_data = []
    list_items = html.find_all('article', class_='product-miniature')
    
    for item in list_items:
        title_elem = item.find('h2', class_='product-title')
        if not title_elem:
            continue
        title = title_elem.get_text(strip=True)
        
        link_elem = title_elem.find('a', href=True)
        url = link_elem['href'] if link_elem else None

        current_price, original_price = None, None
        price_container = item.find('div', class_='product-price-and-shipping')
        if price_container:
            curr, reg = price_container.find('span', class_='product-price'), price_container.find('span', class_='regular-price')
            if curr: current_price = curr.get_text(strip=True)
            if reg: original_price = reg.get_text(strip=True)
        if current_price == original_price: current_price = None

        # Enhanced Stock Check
        is_agotado = False
        
        # 1. Check availability badge/text
        avail = item.find('div', class_='product-availability')
        if avail:
            avail_text = avail.get_text(strip=True).lower()
            # Added 'fuera de stock' to the matching list
            if any(x in avail_text for x in ['agotado', 'sin stock', 'out of stock', 'fuera de stock']):
                is_agotado = True
        
        # 2. Check product flags
        flags = item.find('ul', class_='product-flags')
        if flags:
            for f in flags.find_all('li'):
                flag_text = f.get_text(strip=True).lower()
                if any(x in flag_text for x in ['agotado', 'out of stock', 'fuera de stock']):
                    is_agotado = True
                    break

        stock_status = "Agotado" if is_agotado else ("Oferta" if original_price else None)
        
        extracted_data.append({
            'title': title, 
            'current_price': current_price, 
            'original_price': original_price,
            'stock_status': stock_status, 
            'url': url
        })
    return extracted_data

def gameofmagictienda(html):
    if not html:
        return []

    extracted_data = []
    list_items = html.find_all('section', class_='grid__item')

    for item in list_items:
        title_elem = item.find('h3', class_='bs-collection__product-title')
        if not title_elem:
            continue

        title = title_elem.get_text(strip=True)
        
        # Link extraction
        link_elem = item.find('a', href=True)
        product_url = link_elem['href'] if link_elem else None
        if product_url and not product_url.startswith('http'):
            product_url = "https://www.gameofmagictienda.cl" + product_url

        current_price = None
        original_price = None
        stock_status = None

        price_container = item.find('div', class_='bs-collection__product-price')
        if price_container:
            del_elem = price_container.find('del', class_='bs-collection__old-price')
            final_price_elem = price_container.find('div', class_='bs-collection__product-final-price')

            if del_elem:
                original_price = del_elem.get_text(strip=True)
                current_price = final_price_elem.get_text(strip=True) if final_price_elem else None
            elif final_price_elem:
                original_price = final_price_elem.get_text(strip=True)

        if current_price == original_price:
            current_price = None

        is_agotado = False
        # Check for specific "Agotado" text in common notice or badge areas
        notice_elem = item.find('div', class_='bs-collection__product-notice')
        stock_badge = item.find('div', class_='bs-stock')
        
        check_text = ""
        if notice_elem: check_text += notice_elem.get_text(strip=True).lower()
        if stock_badge: check_text += stock_badge.get_text(strip=True).lower()
        
        if 'agotado' in check_text or 'sin stock' in check_text:
            is_agotado = True

        product_wrapper = item.find('div', class_='bs-collection__product')
        if product_wrapper and 'out-of-stock' in product_wrapper.get('class', []):
            is_agotado = True

        if is_agotado:
            stock_status = "Agotado"
        elif current_price or (product_wrapper and 'has-discount' in product_wrapper.get('class', [])):
            stock_status = "Oferta"

        extracted_data.append({
            'title': title,
            'current_price': current_price,
            'original_price': original_price,
            'stock_status': stock_status,
            'url': product_url
        })

    return extracted_data

def mangaigames(html):
    if not html:
        return []
    extracted_data = []
    list_items = html.find_all('li', class_='product')
    for item in list_items:
        title_elem = item.find('h2', class_='woocommerce-loop-product__title')
        if not title_elem:
            continue
        title = title_elem.get_text(strip=True)
        
        link_elem = item.find('a', class_='ast-loop-product__link', href=True)
        url = link_elem['href'] if link_elem else None

        current_price, original_price = None, None
        price_container = item.find('span', class_='price')
        if price_container:
            del_elem, ins_elem = price_container.find('del'), price_container.find('ins')
            if del_elem and ins_elem:
                original_price, current_price = del_elem.get_text(strip=True), ins_elem.get_text(strip=True)
            else:
                bdi = price_container.find('bdi')
                original_price = bdi.get_text(strip=True) if bdi else price_container.get_text(strip=True)

        classes = item.get('class', [])
        is_agotado = 'outofstock' in classes
        
        stock_status = None
        if is_agotado:
            stock_status = "Agotado"
        elif 'sale' in classes or current_price:
            stock_status = "Oferta"

        extracted_data.append({
            'title': title, 
            'current_price': current_price, 
            'original_price': original_price,
            'stock_status': stock_status, 
            'url': url
        })
    return extracted_data

def revaruk(html):
    if not html:
        return []
    extracted_data = []
    list_items = html.find_all('li', class_='product')
    for item in list_items:
        title_elem = item.find('h2', class_='woocommerce-loop-product__title')
        if not title_elem:
            continue
        title = title_elem.get_text(strip=True)
        
        link_elem = item.find('a', class_='ast-loop-product__link', href=True)
        url = link_elem['href'] if link_elem else None

        current_price, original_price = None, None
        price_container = item.find('span', class_='price')
        if price_container:
            del_elem, ins_elem = price_container.find('del'), price_container.find('ins')
            if del_elem and ins_elem:
                original_price, current_price = del_elem.get_text(strip=True), ins_elem.get_text(strip=True)
            else:
                bdi = price_container.find('bdi')
                original_price = bdi.get_text(strip=True) if bdi else price_container.get_text(strip=True)

        classes = item.get('class', [])
        # Stock status check via class or specific span text
        is_agotado = 'outofstock' in classes
        out_of_stock_span = item.find('span', class_='ast-shop-product-out-of-stock')
        if out_of_stock_span and 'agotado' in out_of_stock_span.get_text(strip=True).lower():
            is_agotado = True
        
        stock_status = None
        if is_agotado:
            stock_status = "Agotado"
        elif 'sale' in classes or current_price or item.find('span', class_='ast-onsale-card'):
            stock_status = "Oferta"

        extracted_data.append({
            'title': title, 
            'current_price': current_price, 
            'original_price': original_price,
            'stock_status': stock_status, 
            'url': url
        })
    return extracted_data
def cardgame(html):
    if not html:
        return []

    extracted_data = []
    # Identify the product container based on the provided class
    list_items = html.find_all('div', class_='bs-collection__product')

    for item in list_items:
        title_elem = item.find('h3', class_='bs-collection__product-title')
        if not title_elem:
            continue

        title = title_elem.get_text(strip=True)
        
        # Link extraction
        link_elem = title_elem.find('a', href=True)
        product_url = link_elem['href'] if link_elem else None
        if product_url and not product_url.startswith('http'):
            product_url = "https://www.cardgame.cl" + product_url

        current_price = None
        original_price = None
        stock_status = None

        # Price extraction: final-price is current, old-price is original
        price_container = item.find('section', class_='bs-collection__product-price')
        if price_container:
            final_price_elem = price_container.find('div', class_='bs-collection__product-final-price')
            old_price_elem = price_container.find('del', class_='bs-collection__product-old-price')

            if old_price_elem:
                original_price = old_price_elem.get_text(strip=True)
                current_price = final_price_elem.get_text(strip=True) if final_price_elem else None
            elif final_price_elem:
                original_price = final_price_elem.get_text(strip=True)

        if current_price == original_price:
            current_price = None

        # Stock check: Look for the specific 'Agotado' div or the 'outStock' class
        is_agotado = False
        stock_div = item.find('div', class_='bs-collection__stock')
        if stock_div and 'agotado' in stock_div.get_text(strip=True).lower():
            is_agotado = True
        
        classes = item.get('class', [])
        if 'outStock' in classes:
            is_agotado = True

        if is_agotado:
            stock_status = "Agotado"
        elif current_price or 'has-discount' in classes:
            stock_status = "Oferta"

        extracted_data.append({
            'title': title,
            'current_price': current_price,
            'original_price': original_price,
            'stock_status': stock_status,
            'url': product_url
        })

    return extracted_data


# ---------------------------------------------------------------------------
# Site registry
# ---------------------------------------------------------------------------

# Each entry controls how main.py scrapes and stores a site.
# pagination styles:
#   'shopify'    → ?page=N  (Shopify, page 1 uses base URL)
#   'page_param' → ?page=N  (PrestaShop and others, same pattern)
#   'woo'        → /page/N/ (WooCommerce)
#   'gatoarcano' → custom AJAX param (handled explicitly in build_url)

sites = [
    {
        'name': 'flexo',
        'base_url': 'https://www.flexogames.cl/collections/juegos-de-mesa',
        'parser': flexogames,
        'pagination': 'shopify',
        'output': '../data/flexogames_jdm.csv',
    },
    {
        'name': 'lafortalezapuq',
        'base_url': 'https://www.lafortalezapuq.cl/jdm',
        'parser': lafortalezapuq,
        'pagination': 'shopify',
        'output': '../data/lafortalezapuq_jdm.csv',
    },
    {
        'name': 'planetaloz',
        'base_url': 'https://www.planetaloz.cl/14-juegos-de-mesa',
        'parser': planetaloz,
        'pagination': 'page_param',
        'output': '../data/planetaloz_jdm.csv',
    },
    {
        'name': 'updown',
        'base_url': 'https://www.updown.cl/categoria-producto/juegos-de-mesa',
        'parser': updown_juegos,
        'pagination': 'woo',
        'output': '../data/updown_jdm.csv',
    },
    {
        'name': 'aldeajuegos',
        'base_url': 'https://www.aldeajuegos.cl/7-juegos-de-mesa',
        'parser': aldeajuegos,
        'pagination': 'page_param',
        'output': '../data/aldeajuegos_jdm.csv',
    },
    {
        'name': 'elpatiogeek',
        'base_url': 'https://www.elpatiogeek.cl/collections/all',
        'parser': elpatiogeek,
        'pagination': 'shopify',
        'output': '../data/elpatiogeek_jdm.csv',
    },
    {
        'name': 'mangaigames',
        'base_url': 'https://mangaigames.cl/tienda',
        'parser': mangaigames,
        'pagination': 'woo',
        'output': '../data/mangaigames_jdm.csv',
    },
    {
        'name': 'cartonespesados',
        'base_url': 'https://cartonespesados.cl/product-category/juegos-de-mesa',
        'parser': cartonespesados,
        'pagination': 'woo',
        'output': '../data/cartonespesados_jdm.csv',
    },
    {
        'name': 'cartonazo',
        'base_url': 'https://cartonazo.com/categoria-producto/juego-de-mesa',
        'parser': cartonazo,
        'pagination': 'woo',
        'output': '../data/cartonazo_jdm.csv',
    },
    {
        'name': 'dementegames',
        'base_url': 'https://dementegames.cl/10-juegos-de-mesa',
        'parser': dementegames,
        'pagination': 'page_param',
        'output': '../data/dementegames_jdm.csv',
    },
    {
        'name': 'drjuegos',
        'base_url': 'https://www.drjuegos.cl/2-todos-los-productos',
        'parser': drjuegos,
        'pagination': 'page_param',
        'output': '../data/drjuegos_jdm.csv',
    },
    {
        'name': 'vudugaming',
        'base_url': 'https://www.vudugaming.cl/juegos-de-mesa',
        'parser': vudugaming,
        'pagination': 'page_param',
        'output': '../data/vudugaming_jdm.csv',
    },
    {
        'name': 'piedrabruja',
        'base_url': 'https://piedrabruja.cl/collections/juegos-de-mesa',
        'parser': piedrabruja,
        'pagination': 'shopify',
        'output': '../data/piedrabruja_jdm.csv',
    },
    {
        'name': 'gatoarcano',
        'base_url': 'https://gatoarcano.cl/product-category/juegos-de-mesa',
        'parser': gatoarcano,
        'pagination': 'gatoarcano',
        'output': '../data/gatoarcano_jdm.csv',
    },
    {
        'name': 'ludipuerto',
        'base_url': 'https://www.ludipuerto.cl/categoria-producto/juegos-de-mesa',
        'parser': ludipuerto,
        'pagination': 'woo',
        'output': '../data/ludipuerto_jdm.csv',
    },
    {
        'name': 'magicsur',
        'base_url': 'https://www.magicsur.cl/15-juegos-de-mesa-magicsur-chile',
        'parser': magicsur,
        'pagination': 'page_param',
        'output': '../data/magicsur_jdm.csv',
    },
    {
        'name': 'gameofmagictienda',
        'base_url': 'https://www.gameofmagictienda.cl/collection/juegos-de-mesa',
        'parser': gameofmagictienda,
        'pagination': 'page_param',
        'output': '../data/gameofmagictienda_jdm.csv',
    },
    {
        'name': 'top8',
        'base_url': 'https://www.top8.cl/collection/juegos-de-mesa',
        'parser': top8,
        'pagination': 'page_param',
        'output': '../data/top8_jdm.csv',
    },
    {
        'name': 'revaruk',
        'base_url': 'https://revaruk.cl/product-category/juegos-de-mesa',
        'parser': revaruk,
        'pagination': 'woo',
        'output': '../data/revaruk_jdm.csv',
    },
    {
        'name': 'cardgame',
        'base_url': 'https://www.cardgame.cl/collection/juegos-de-mesa',
        'parser': cardgame,
        'pagination': 'page_param',
        'output': '../data/cardgame_jdm.csv',
    }
]


def build_url(base_url, pagination, page):
    """Construct the paginated URL for a given page number and pagination style."""
    if pagination == 'gatoarcano':
        # Custom AJAX endpoint; page 1 still needs the param.
        return f"{base_url}/?jsf=epro-archive-products&pagenum={page}"
    if page == 1:
        return base_url  # All other styles use the bare URL for page 1.
    if pagination in ('shopify', 'page_param'):
        return f"{base_url}?page={page}"
    if pagination == 'woo':
        return f"{base_url}/page/{page}/"
    raise ValueError(f"Unknown pagination style: {pagination}")
