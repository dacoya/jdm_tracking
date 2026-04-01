# 🎲 tablero-cl

> Precio comparador de juegos de mesa en Chile. Scraping + búsqueda fuzzy desde la terminal.

---

## ¿Qué hace?

Recorre los catálogos de **+30 tiendas chilenas** de juegos de mesa, guarda los precios en CSVs locales, y te deja buscar, comparar, y filtrar ofertas directamente desde la terminal — sin abrir el navegador.

```
python main.py --name "clank"
```
```
Resultados para 'clank' (6 encontrados):

    1. Clank!                              (100%)
    2. Clank!: En las Catacumbas           (100%)
    3. Clank! In! Space!                   ( 97%)
    4. Clank! Sunken Treasures             ( 95%)
    ...

Selecciona un número (0 para salir): 2

Clank!: En las Catacumbas
Tienda           Precio       Oferta       Descuento  Disponibilidad  URL
---------------  -----------  -----------  ---------  --------------  ----
drjuegos         $49.990      $35.990      -28%       Disponible      https://...
cartonazo        $49.990      $39.990      -20%       Disponible      https://...
aldeajuegos      $49.990      -            -          Disponible      https://...
```

---

## Tiendas cubiertas

37 tiendas activas.

| Tienda | URL | Ubicación |
|---|---|---|
| Aldea Juegos | aldeajuegos.cl | Santiago |
| Café 2d6 | cafe2d6.cl | Santiago |
| Cartones Pesados | cartonespesados.cl | Santiago |
| Cartonazo | cartonazo.com | Santiago |
| Demente Games | dementegames.cl | Santiago |
| Devir | devir.cl | Santiago |
| DR Juegos | drjuegos.cl | Santiago |
| El Patio Geek | elpatiogeek.cl | Santiago |
| Griffin Games | griffingames.cl | Santiago |
| Juegos Enroque | juegosenroque.cl | Santiago |
| Kaio Juegos | kaiojuegos.cl | Santiago |
| La Madriguera | tiendalamadriguera.cl | Santiago |
| Ludi | ludi.cl | Santiago |
| Magic Sur | magicsur.cl | Santiago |
| Mana House | manahouse.cl | Santiago |
| Mangai Games | mangaigames.cl | Santiago |
| Piedra Bruja | piedrabruja.cl | Santiago |
| Play Center | playcenter.cl | Santiago |
| Revaruk | revaruk.cl | Santiago |
| Third Impact | thirdimpact.cl | Santiago |
| Updown Juegos | updown.cl | Santiago |
| Vudu Gaming | vudugaming.cl | Santiago |
| Zona X Gamers | zonaxgamers.cl | Santiago |
| Calabozo Tienda | calabozotienda.cl | Concepción |
| Game of Magic Tienda | gameofmagictienda.cl | Concepción |
| Planeta Loz | planetaloz.cl | Concepción |
| Gato Arcano | gatoarcano.cl | Viña del Mar |
| La Loseta | laloseta.cl | Viña del Mar |
| Peak Games | peakgames.cl | Viña del Mar |
| Flexogames | flexogames.cl | La Serena |
| La Bóveda del Mago | labovedadelmago.cl | La Serena |
| Mirzu | mirzu.cl | Arica |
| Lamesadevaras | lamesadevaras.cl | Puerto Varas |
| La Fortaleza PUQ | lafortalezapuq.cl | Punta Arenas |
| Ludi Puerto | ludipuerto.cl | Talcahuano |
| Top 8 | top8.cl | Temuco |
| Cardgame | cardgame.cl | Valdivia |
| Búho Juegos de Mesa | buhojuegosdemesa.cl | Valparaíso |



---

## Instalación

```bash
git clone https://github.com/tu-usuario/tablero-cl
cd tablero-cl
pip install -r requirements.txt
```

**Dependencias:**

```
requests
beautifulsoup4
pandas
rapidfuzz
tqdm
```

**Estructura del proyecto:**

```
tablero-cl/
├── main.py       # CLI: búsqueda, filtros, modo actualización
├── scrape.py     # Parsers por tienda + registro de sitios
├── utils.py      # Normalización, precios, ordenamiento, paginación
├── data/         # CSVs generados por el scraper
└── README.md
```

---

## Uso

### Actualizar la base de datos

Scraping completo en paralelo (4 workers por defecto):

```bash
python main.py -u
```

```bash
python main.py -u -w 5                    # 5 workers simultáneos
python main.py -u --dry-run               # solo página 1 por tienda (pruebas)
python main.py -u --sites flexo cartonazo # actualizar tiendas específicas
```

### Buscar un juego

```bash
python main.py --name "pandemic"
python main.py --name "catan" --sort price      # ordenar por precio
python main.py --name "root" --sort store       # ordenar por tienda
python main.py --name "clank" --sort discount   # ordenar por descuento (default)
```

La búsqueda ignora tildes, signos de puntuación, y sufijos de idioma:

| Lo que escribes | Encuentra |
|---|---|
| `catan` | `Catan`, `CATAN`, `Catán` |
| `clank catacumbas` | `Clank!: En las Catacumbas (Español)` |
| `pandemic` | `Pandemic`, `Pandemic (En Español)` |
| `terraforming` | `Terraforming Mars`, `Terraforming Mars: Expedición Ares` |

### Ver todas las ofertas

```bash
python main.py --deals                          # todas las ofertas, mayor descuento primero
python main.py --deals --sort price             # más baratas primero
python main.py --deals --store cartonazo        # una tienda específica
python main.py --deals --in-stock               # solo disponibles
python main.py --deals --price 10000:50000      # rango de precio (oferta)
python main.py --deals --lower-price 20000      # precio mínimo
python main.py --deals --higher-price 40000     # precio máximo
```

### Listar catálogo completo

```bash
python main.py --list                           # todos los productos
python main.py --list --store updown            # catálogo de una tienda
python main.py --list --sort price              # ordenar por precio
python main.py --list --in-stock                # solo disponibles
```

---

## Cómo funciona

### Scraping (`scrape.py`)

Cada tienda tiene su parser. Cuatro plataformas cubren la mayoría:

```
WooCommerce   → <del>/<ins> para precios, clases CSS para stock
PrestaShop    → span.regular-price / span.price, ul.product-flags
Shopify       → varía por tema; clases en grid items
BS-Collection → estructura custom compartida por top8/cardgame/gameofmagic
```

Los parsers comparten helpers:

```python
_txt(el)              # get_text seguro, retorna None si el es None
_url(el, base)        # extrae href, prepende base si es relativo
_norm(orig, curr)     # anula current_price si es igual al original
_woo_prices(pc)       # extrae del/ins/bdi de un contenedor WooCommerce
_presta_prices(item)  # extrae regular-price/price de PrestaShop
```

El loop de paginación detecta páginas duplicadas (cuando el sitio repite la última página en vez de 404) y se detiene solo.

### Búsqueda fuzzy (`utils.py`)

```python
normalize("Clank!: En las Catacumbas (En Español)")
# → "clank en las catacumbas"

normalize("Terraforming Mars Edición Kickstarter")
# → "terraforming mars"
```

El pipeline de normalización:
1. Minúsculas
2. Elimina tags de idioma (`en español`, `en inglés`, `castellano`, etc.)
3. Elimina marcadores de edición (`edición deluxe`, `2da edición`, etc.)
4. Descompone acentos (NFKD → elimina combining marks)
5. Reemplaza puntuación con espacio
6. Colapsa whitespace

El matching usa `token_set_ratio` de rapidfuzz — el orden de las palabras no importa, y palabras extra en el título no penalizan el score.

### Precios chilenos

```python
parse_price("$69.990")    # → 69990.0
parse_price("$69.990,50") # → 69990.5
parse_price("69,990")     # → 69990.0
```

Detecta formato por posición del último separador: si la última coma viene después del último punto, es separador decimal.

---

## Agregar una tienda

1. Escribir el parser en `scrape.py`:

```python
def mi_tienda(html):
    res = []
    for item in (html.find_all('article', class_='product') if html else []):
        try:
            t_elem = item.find('h2', class_='product-title')
            if not t_elem:
                continue
            orig, curr = _norm(*_woo_prices(item.find('span', class_='price')))
            res.append({
                'title':          _txt(t_elem),
                'original_price': orig,
                'current_price':  curr,
                'stock_status':   "Agotado" if 'outofstock' in item.get('class', []) else None,
                'url':            _url(t_elem.find('a', href=True)),
            })
        except Exception as e:
            print(f"  [mi_tienda] skipping item: {e}")
    return res
```

2. Registrar en `sites`:

```python
{
    'name':       'mitienda',
    'base_url':   'https://www.mitienda.cl/juegos-de-mesa',
    'parser':     mi_tienda,
    'pagination': 'woo',        # 'shopify' | 'woo' | 'page_param' | 'gatoarcano' | 'calabozo' | 'devir'
    'output':     '../data/mitienda_jdm.csv',
},
```

---

## Notas

- El scraper espera 1 segundo entre páginas por cortesía con los servidores.
- Los precios reflejan lo que el sitio muestra; precios originales inflados artificialmente son responsabilidad de cada tienda.