# 🎲 tablero-cl

> Precio comparador de juegos de mesa en Chile. Scraping + búsqueda fuzzy desde la terminal.

---

## ¿Qué hace?

Recorre los catálogos de **46 tiendas chilenas** de juegos de mesa, guarda todo en
una base SQLite local, y te deja buscar, comparar y filtrar ofertas directamente
desde la terminal — sin abrir el navegador.

Corre `tablero` sin argumentos para abrir el **menú interactivo**, o usa los
subcomandos directamente:

```
tablero search "clank"
```
```
Resultados para 'clank' (4 encontrados):

    1. Clank                             desde    $47.990 · 14 tiendas
    2. Clank Catacumbas                  desde    $58.990 · 12 tiendas +exp
    3. Clank Legacy                      desde   $109.990 ·  2 tiendas · agotado
    ...

Clank Catacumbas
Tienda      Precio   Oferta   Desc.  Disponibilidad  URL
----------  -------  -------  -----  --------------  ---------------------------
drjuegos    $49.990  $35.990  -28%   Disponible      https://…
cartonazo   $49.990  $39.990  -20%   Disponible      https://…
aldeajuegos $49.990  -        -      Disponible      https://…
```

Además de comparar precios, sabe **qué cambió desde la última vez que miraste**,
mantiene una **lista de seguimiento** con precios objetivo, y calcula **en qué
combinación de tiendas conviene comprar** una lista de juegos considerando el
costo de envío.

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
Para desarrollo también puedes correr el módulo directamente: `python scripts/cli.py <args>`.

> **Si `tablero` falla con `ModuleNotFoundError`**, el script instalado quedó
> apuntando a un punto de entrada viejo. Vuelve a instalar para regenerarlo:
>
> ```bash
> pip install -e .
> ```
>
> `pip install -e .` no regenera el script en cada cambio del código —solo cuando
> cambia `pyproject.toml`—, así que hay que repetirlo tras mover el entry point.

Los tests corren con `python -m pytest` (requiere `pip install pytest`).

### ¿Dónde se guardan los datos?

En este orden:

1. `TABLERO_DATA_DIR`, si está definida.
2. `<repo>/data` cuando corres desde un clon del proyecto (instalación editable
   o `python scripts/cli.py`), que es lo que mantiene los CSV versionados en uso.
3. Un directorio de usuario en cualquier otro caso —en macOS
   `~/Library/Application Support/tablero-cl`—. Una instalación normal deja el
   paquete en `site-packages`, y escribir ahí una base de 15 MB estaría mal: no
   son datos del paquete, y una reinstalación los borraría.

`tablero doctor` muestra cuál se está usando.

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
├── scripts/          # paquete `tablero`
│   ├── cli.py        # subcomandos (punto de entrada)
│   ├── tui.py        # menú interactivo (questionary)
│   ├── render.py     # formato de tablas para terminal
│   │
│   ├── db.py         # conexión SQLite + esquema
│   ├── schema.sql    # DDL canónico
│   ├── migrate.py    # importación única JSON → SQLite
│   ├── ingest.py     # escritura de scrapes en la base
│   ├── derive.py     # registro scrapeado → fila de base de datos
│   ├── repo.py       # capa de consultas (todo el SQL vive aquí)
│   │
│   ├── search.py     # búsqueda FTS + ranking difuso
│   ├── classify.py   # tipo de producto (juego/expansión/accesorio/tcg/puzzle)
│   ├── basket.py     # optimizador de carrito multi-tienda
│   ├── watchlist.py  # lista de seguimiento persistente
│   ├── changes.py    # bajadas de precio desde la última revisión
│   │
│   ├── scrape.py     # parsers por tienda + registro de sitios
│   ├── utils.py      # normalización, precios, ordenamiento
│   ├── paths.py      # rutas (respeta TABLERO_DATA_DIR)
│   ├── stats.py      # estadísticas por tienda + resumen de mercado
│   ├── analytics.py  # sorts inteligentes + leaderboard
│   ├── validation.py # detección de anomalías de precio
│   ├── dedup.py      # URL canónica + agrupación de variantes
│   ├── export.py     # exportar a csv/json/html
│   └── alerts.py     # alertas de precio por palabra clave
├── tests/            # pytest
├── data/
│   ├── tablero.db    # base de datos canónica (SQLite)
│   └── *.csv         # respaldo por tienda de cada scrape
└── README.md
```

### La base de datos

Desde esta versión el almacén canónico es **`data/tablero.db`** (SQLite), no
`products.json`. Eso cambia tres cosas que importan:

- **Los precios se guardan como números**, ya parseados. Ningún consumidor
  necesita reimplementar el parseo de precios chilenos.
- **La clave de comparación (`norm`) se persiste**, en vez de recalcularse en
  memoria en cada arranque.
- **La identidad de un producto es estable** (`tienda` + URL canónica), que es
  lo que hace que el historial de precios y las marcas nuevo/restock signifiquen
  algo entre ejecuciones.

Como efecto secundario, el archivo se puede leer tal cual desde cualquier
cliente SQLite — incluida una app Android vía Room — sin capa de traducción.

`TABLERO_DATA_DIR` permite mover el directorio de datos sin tocar el código.

---

## Uso

El comando usa **subcomandos**. Corre `tablero` sin argumentos para el menú
interactivo, o `tablero <comando> --help` para las opciones de cada uno.

```
tablero search <juego>     buscar y comparar precios
tablero deals              productos en oferta
tablero list               listar el catálogo
tablero stores             tiendas cubiertas y su estado
tablero leaderboard        ranking de tiendas (más barata primero)
tablero history <juego>    evolución de precios con sparklines
tablero new                qué cambió desde tu última revisión
tablero watch              lista de seguimiento
tablero alerts             avisos de precio (para cron)
tablero basket             dónde comprar una lista de juegos
tablero update             scrapear y actualizar la base
tablero migrate            construir/reconstruir la base SQLite
tablero doctor             estado de la base + precios atípicos
```

### Primera vez

```bash
tablero migrate            # construye data/tablero.db desde los JSON existentes
```

### Buscar un juego

```bash
tablero search "catan"
tablero search "pandemic" --first    # muestra directo la tabla de precios
tablero search "fundas" --all-kinds  # incluye accesorios (ocultos por defecto)
```

Los resultados se ordenan por relevancia y toleran errores de tipeo
(`pandemc` → `Pandemic`, `terraformin` → `Terraforming Mars`). Cada resultado
muestra el precio más bajo, en cuántas tiendas está, y si hay stock.

Los accesorios se ocultan por defecto: buscar `catan` devuelve el juego, no
cuarenta fundas que lo mencionan en el título.

### Ver ofertas y catálogo

```bash
tablero deals --in-stock --sort discount
tablero deals --store cartonazo --max-price 30000
tablero list --store updown --sort price
tablero list --kind expansion             # juego | expansion | tcg | puzzle | accessory
```

`--store` acepta coincidencias parciales: `--store carton` te dirá cuáles
coinciden en vez de fallar con un error sin salida.

### Órdenes derivados

Además de `discount/price/price_desc/store/title`, `deals` y `list` aceptan tres
órdenes que se calculan comparando entre tiendas, no leyendo una sola columna:

```bash
tablero deals --sort value        # más barato respecto a su propia mediana
tablero deals --sort scarcity     # disponible en pocas tiendas
tablero deals --sort volatility   # mayor diferencia de precio entre tiendas
```

`value` es el más útil en la práctica: encuentra el juego que una tienda vende
muy por debajo de lo que cobran las demás, que no es lo mismo que el mayor
descuento nominal.

### Exportar

Cualquier listado se puede escribir a `data/exports/`:

```bash
tablero deals --in-stock --export csv
tablero list --store updown --export html
tablero leaderboard --export json
```

### Leaderboard de tiendas

```bash
tablero leaderboard --limit 20
```

Ordena las tiendas por **competitividad**: el porcentaje de juegos *disputados*
(los que comparte con al menos otra tienda) en que esa tienda cobra más que la
mediana. Comparar solo lo disputado es lo que evita que una tienda parezca
barata por vender productos distintos y más baratos.

### Historial de precios

```bash
tablero history "catan"
tablero history "catan" --min-points 1   # incluir tiendas con una sola observación
```

Muestra un sparkline (`▁▂▃▅▇`) por tienda con el precio inicial, el final y el
rango. Por defecto oculta las tiendas con una sola observación: un punto es un
precio, no una tendencia, y dibujarlo como línea plana sugiere una estabilidad
que nunca se midió. El historial se acumula con cada `tablero update`.

### Avisos de precio (para cron)

```bash
tablero alerts                                        # usa la lista de seguimiento
tablero alerts --watch "wingspan" "root" --threshold 30000
tablero alerts --out alertas.json --in-stock
```

Sin argumentos usa los precios objetivo que ya guardaste con `tablero watch`, así
que una tarea programada no necesita repetir nada ni puede quedar desincronizada
de lo que realmente querías. Devuelve código de salida `1` cuando no hay avisos,
para que cron pueda actuar según el resultado.

### Qué cambió desde la última vez

```bash
tablero new --reset        # fija el marcador "última revisión"
tablero new                # bajadas de precio + productos nuevos desde entonces
tablero new --min-pct 10   # solo bajadas de 10% o más
```

A diferencia de las marcas nuevo/restock —que se recalculan en cada scrape y
solo describen la última actualización— esto se mide contra el momento en que
*tú* miraste por última vez, así que no se pierde nada por no haber estado.

### Lista de seguimiento

```bash
tablero watch add "wingspan" --target 55000
tablero watch list                       # marca los que alcanzaron su objetivo
tablero watch rm "wingspan"
```

### Dónde comprar (optimizador de carrito)

Comprar cada juego donde está más barato suele *no* ser lo más barato: cada
tienda extra agrega un envío. Este comando compara las tres estrategias:

```bash
tablero basket "catan" "wingspan" "azul"
tablero basket --from-watchlist --shipping 5000
```

```
  Cada juego en su tienda más barata   5 tienda(s)  $174.960 + envío $20.000 = $194.960
  Todo en una sola tienda              1 tienda(s)  $178.960 + envío  $4.000 = $182.960 · faltan 1
  Combinación óptima                   3 tienda(s)  $177.960 + envío $12.000 = $189.960 ←  MEJOR
```

Un pedido completo gana sobre uno más barato pero incompleto.

### Actualizar precios

```bash
tablero update                          # todas las tiendas, 5 workers
tablero update --incremental            # solo las obsoletas (> 24 h)
tablero update --sites tertulia top8    # tiendas específicas
tablero update --dry-run                # solo la primera página (pruebas)
tablero update -w 3                     # más suave si Cloudflare bloquea
```

Cada tienda se escribe por separado, así que un scrape fallido nunca borra los
datos de otra. Un scrape vacío se trata como fallo: una caída de red no debe
parecerse a una tienda que vació su catálogo.

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

El matching (`search.py`) tiene dos etapas, deliberadamente separadas:

1. **Candidatos** — el índice FTS5 de SQLite decide qué es *plausible*. Es
   indexado y barato, y reemplaza el escaneo completo que antes corría rapidfuzz
   sobre cada título único en cada búsqueda.
2. **Ranking** — rapidfuzz decide qué es *relevante*: score compuesto
   `0.3·token_set + 0.4·token_sort + 0.3·partial`, más bonos por coincidencia
   exacta / prefijo, una penalización por tipo de producto, y desempate por
   popularidad (nº de tiendas) y longitud del título.

FTS solo hace coincidencia por prefijo, así que no puede salvar un error de
tipeo — `pandemc` no es prefijo de `pandemic`. Cuando devuelve pocos candidatos
se cae a un escaneo difuso sobre los ~11 mil juegos (no los ~29 mil productos),
que es lo que mantiene la tolerancia a typos sin pagar el costo en cada consulta.

La penalización por tipo es lo que evita que los accesorios tapen al juego:
buscar `catan` devuelve Catan, no las fundas que lo nombran en el título.

Las variantes del mismo juego entre tiendas ya vienen agrupadas por la tabla
`game`, y cada resultado se enriquece con el precio más bajo, el nº de tiendas y
disponibilidad.

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