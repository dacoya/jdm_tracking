# 🎲 tablero-cl

> Precio comparador de juegos de mesa en Chile. Scraping + búsqueda fuzzy desde la terminal.

---

## ¿Qué hace?

Recorre los catálogos de **+30 tiendas chilenas** de juegos de mesa, guarda los precios en CSVs locales, y te deja buscar, comparar, y filtrar ofertas directamente desde la terminal — sin abrir el navegador.

Corre `tablero` sin argumentos para abrir el **menú interactivo**, o pasa los flags directamente:

```
tablero --name "clank"
```
```
Resultados para 'clank' (24 encontrados):

    1. Clank             desde   $47.990 · 14 tiendas           (100%)
    2. Clank Legacy      desde  $109.990 · 2 tiendas · agotado   (75%)
    3. Clank Catacumbas  desde   $58.990 · 12 tiendas            (69%)
    ...

Selecciona un número para ver precios (0 para volver al menú): 3

Clank Catacumbas
Tienda           Precio       Oferta       Descuento  Disponibilidad  URL
---------------  -----------  -----------  ---------  --------------  ----
drjuegos         $49.990      $35.990      -28%       Disponible      https://...
cartonazo        $49.990      $39.990      -20%       Disponible      https://...
aldeajuegos      $49.990      -            -          Disponible      https://...
```

---

## Tiendas cubiertas

46 tiendas activas.

| Tienda | URL | Ubicación |
|---|---|---|
| Aldea Juegos | aldeajuegos.cl | Santiago |
| Café 2d6 | cafe2d6.cl | Santiago |
| Cartonazo | cartonazo.com | Santiago |
| Cartones Pesados | cartonespesados.cl | Santiago |
| DarkHobbies | darkhobbies.cl | Santiago |
| Demente Games | dementegames.cl | Santiago |
| Devir | devir.cl | Santiago |
| DR Juegos | drjuegos.cl | Santiago |
| El Patio Geek | elpatiogeek.cl | Santiago |
| Griffin Games | griffingames.cl | Santiago |
| Guildreams | guildreams.com | Santiago |
| Juegos Enroque | juegosenroque.cl | Santiago |
| Jugones | jugones.cl | Santiago |
| Kaio Juegos | kaiojuegos.cl | Santiago |
| La Madriguera | tiendalamadriguera.cl | Santiago |
| Magic Sur | magicsur.cl | Santiago |
| Mana House | manahouse.cl | Santiago |
| Mangai Games | mangaigames.cl | Santiago |
| Piedra Bruja | piedrabruja.cl | Santiago |
| Play Center | playcenter.cl | Santiago |
| PlayKingdom | playkingdom.cl | Santiago |
| Revaruk | revaruk.cl | Santiago |
| Shivano | shivano.cl | Santiago |
| Tentami | tentami.cl | Santiago |
| Tertulia | tertulia.cl | Santiago |
| Third Impact | thirdimpact.cl | Santiago |
| Updown Juegos | updown.cl | Santiago |
| Vudu Gaming | vudugaming.cl | Santiago |
| Wargaming | wargaming.cl | Santiago |
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
| Lautaro Juegos | lautarojuegos.cl | Villa Alemana |
| Lamesadevaras | lamesadevaras.cl | Puerto Varas |
| La Fortaleza PUQ | lafortalezapuq.cl | Punta Arenas |
| Ludi Puerto | ludipuerto.cl | Talcahuano |
| Araucanía Gaming | araucaniagaming.cl | Temuco |
| Top 8 | top8.cl | Temuco |
| Búho Juegos de Mesa | buhojuegosdemesa.cl | Valparaíso |



---

## Instalación

```bash
git clone https://github.com/tu-usuario/tablero-cl
cd tablero-cl
pip install -e .            # instala las dependencias y el comando `tablero`
```

Tras la instalación, el comando `tablero` queda disponible desde cualquier directorio.
Para desarrollo también puedes correr el módulo directamente: `python scripts/main.py <args>`.

**Dependencias:**

```
requests
beautifulsoup4
pandas
rapidfuzz
tqdm
questionary
```

**Estructura del proyecto:**

```
tablero-cl/
├── pyproject.toml    # empaquetado + comando `tablero`
├── requirements.txt
├── scripts/          # paquete `tablero`
│   ├── __init__.py
│   ├── main.py       # CLI: modos, dispatch, pipeline de actualización
│   ├── tui.py        # menú interactivo (questionary)
│   ├── scrape.py     # parsers por tienda + registro de sitios
│   ├── utils.py      # normalización, precios, ordenamiento, paginación
│   ├── paths.py      # rutas de datos independientes del directorio
│   ├── metadata.py   # estado por tienda + caché de stats (incremental)
│   ├── validation.py # detección de anomalías de precio
│   ├── history.py    # historial de precios + sparklines
│   ├── stats.py      # estadísticas por tienda + resumen de mercado
│   ├── analytics.py  # sorts inteligentes + leaderboard
│   ├── dedup.py      # dedup por URL + agrupación de variantes
│   ├── export.py     # exportar a csv/json/html
│   └── alerts.py     # alertas de precio por palabra clave
├── data/             # products.json, metadata.json, history.json, CSVs, exports/
└── README.md
```

---

## Uso

### Modo interactivo

Corre el comando sin argumentos para navegar con flechas — elige entre buscar, ver ofertas, listar el catálogo o actualizar precios, sin recordar flags:

```bash
tablero
```

Todos los flags de abajo siguen funcionando para uso directo o scripting.

### Actualizar la base de datos

Scraping completo en paralelo (5 workers por defecto — suave con Cloudflare):

```bash
tablero -u
```

```bash
tablero -u -w 12                   # más rápido (sube el riesgo de bloqueo Cloudflare)
tablero -u -w 3                    # aún más suave si te bloquean
tablero -u --dry-run               # solo página 1 por tienda (pruebas)
tablero -u --sites flexo cartonazo # actualizar tiendas específicas
```

### Buscar un juego

```bash
tablero --name "pandemic"
tablero --name "catan"
tablero --name "root"
```

Los resultados se ordenan por relevancia (el juego base primero) y muestran el precio
más bajo, en cuántas tiendas está, y disponibilidad. Escribe el número de un resultado
para ver sus precios por tienda, o `0` para volver al menú principal.

Cada resultado muestra el **precio más bajo**, en **cuántas tiendas** está, y si
hay stock — y el ranking pone el juego base primero (no las expansiones ni los
accesorios). La búsqueda ignora tildes, puntuación y sufijos de idioma, y **tolera
errores de tipeo**:

| Lo que escribes | Encuentra |
|---|---|
| `catan` | `Catan` primero, luego ediciones y expansiones |
| `clank catacumbas` | `Clank Catacumbas` (la expansión exacta, no el base) |
| `pandemc` (con typo) | `Pandemic` |
| `terraformin` (incompleto) | `Terraforming Mars` |

### Ver todas las ofertas

```bash
tablero --deals                          # todas las ofertas, mayor descuento primero
tablero --deals --sort price             # más baratas primero
tablero --deals --store cartonazo        # una tienda específica
tablero --deals --in-stock               # solo disponibles
tablero --deals --price 10000:50000      # rango de precio (oferta)
tablero --deals --lower-price 20000      # precio mínimo
tablero --deals --higher-price 40000     # precio máximo
```

### Listar catálogo completo

```bash
tablero --list                           # todos los productos
tablero --list --store updown            # catálogo de una tienda
tablero --list --sort price              # ordenar por precio
tablero --list --in-stock                # solo disponibles
```

### Novedades (nuevos / restock)

En cada `--update`, cada ítem se compara (por URL) con el snapshot anterior y se marca
como **`new`** (URL nunca vista) o **`restock`** (estaba agotado, ahora disponible). Los
flags se recalculan en cada actualización, así que siempre reflejan el último cambio:

```bash
tablero --new              # todos los ítems nuevos + restock de la última actualización
tablero --new new          # solo nuevos
tablero --new restock      # solo restock
```

Los ítems marcados también aparecen decorados con **🆕** (nuevo) o **🔄** (restock) en los
resultados de búsqueda, en `--list` y en `--deals`.

### Sorts inteligentes

`--deals` y `--list` aceptan, además de `discount/price/offer`, tres órdenes derivados:

```bash
tablero --deals --sort value             # mejor relación precio/stock (la mejor compra real)
tablero --deals --sort scarcity          # juegos en pocas tiendas (demanda concentrada)
tablero --deals --sort volatility        # mayor variación entre tiendas (arbitraje)
```

### Leaderboard de tiendas

```bash
tablero --leaderboard                    # ranking: más barata, mejor descuento, más stock
```

### Historial de precios

El historial se acumula en cada `--update` (en `data/history.json`):

```bash
tablero --history "catan"                # sparklines de precio por tienda (▁▂▃▅▇)
```

### Alertas de precio (para cron)

```bash
tablero --alert --watch "wingspan" "root" --threshold 30000 --alert-out alertas.json
```

### Exportar resultados

```bash
tablero --deals --in-stock --export csv  # → data/exports/*.csv (también json, html)
tablero --list --store updown --export html
```

### Actualización incremental

Rescrapea solo las tiendas obsoletas en vez de todas — más rápido y amable con los servidores:

```bash
tablero --update --incremental           # solo tiendas con datos de > 24h
tablero --update --incremental --max-age 12
```

> Cada `--update` también valida los precios (rechaza ofertas > original, precios ≤ 0,
> descuentos > 90 %, títulos vacíos) y registra metadata por tienda en `data/metadata.json`.

---

## Cómo funciona

### Scraping (`scrape.py`)

Cada tienda tiene su parser. Cuatro plataformas cubren la mayoría:

```
WooCommerce   → <del>/<ins> para precios, clases CSS para stock
PrestaShop    → span.regular-price / span.price, ul.product-flags
Shopify       → varía por tema; clases en grid items
BS-Collection → estructura custom compartida por top8/gameofmagic
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

El matching (en `fuzzy_search`, `main.py`) tiene dos etapas:

1. **Inclusión** — `WRatio` de rapidfuzz (combina ratio parcial + por tokens) con
   corte 80: amplia y tolerante a errores de tipeo (`pandemc` → `Pandemic`).
2. **Ranking** — un score compuesto `0.3·token_set + 0.4·token_sort + 0.3·partial`
   más bonos por coincidencia exacta / prefijo, y desempate por popularidad
   (nº de tiendas) y longitud del título. Así el juego base queda primero en vez
   de empatar todo en 100 %.

Las variantes del mismo juego entre tiendas se agrupan en una sola entrada, y cada
resultado se enriquece con el precio más bajo, el nº de tiendas y disponibilidad.

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

- El scraper espera 1–2.5 s (con jitter) entre páginas por cortesía con los servidores.
- Los precios reflejan lo que el sitio muestra; precios originales inflados artificialmente son responsabilidad de cada tienda.
- **Cloudflare:** varias tiendas usan bot-management de Cloudflare, que es sensible a la
  reputación de tu IP: el scraping agresivo (mucha concurrencia) la degrada y provoca más
  bloqueos `403`/`429`. El default ya es conservador (5 workers); si aún ves "Cloudflare
  block", baja más (`tablero --update -w 3`) y reintenta más tarde. Los bloqueos se registran y **no borran**
  los datos previos. El scraper **no** intenta evadir Cloudflare.