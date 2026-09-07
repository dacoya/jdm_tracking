# 🎲 tablero-cl — Resumen de funciones

Referencia rápida de lo que hace `tablero` y de las funciones internas que lo
componen. Comparador de precios de juegos de mesa en Chile: scrapea +50 tiendas,
guarda los precios en `data/products.json`, y permite buscar / comparar / filtrar
desde la terminal.

---

## Inicio rápido

```bash
pip install -e .     # instala dependencias + el comando `tablero`
tablero              # abre el menú interactivo
tablero --name catan # uso directo por flags
```

---

## Comandos (capa de usuario)

Al correr `tablero` sin argumentos se abre un **menú interactivo** (flechas) con
las cuatro operaciones. Cada operación también está disponible por flags.

| Modo | Flag | Qué hace |
|---|---|---|
| **Buscar** | `--name / -n QUERY` | Búsqueda fuzzy de un juego; muestra coincidencias y la tabla de precios por tienda |
| **Ofertas** | `--deals` | Lista todos los productos con descuento, mejor descuento primero |
| **Listar** | `--list` | Listado paginado del catálogo completo |
| **Leaderboard** | `--leaderboard` | Ranking de tiendas: más barata / mejor descuento / más stock |
| **Historial** | `--history QUERY` | Sparklines de evolución de precio por tienda para un juego |
| **Alertas** | `--alert` | Vigila una lista de juegos y avisa si bajan de un umbral |
| **Actualizar** | `--update / -u` | Scrapea las tiendas y reconstruye la base de datos |

### Flags disponibles

| Flag | Aplica a | Descripción |
|---|---|---|
| `-n, --name QUERY` | buscar | Término de búsqueda fuzzy |
| `--deals` | ofertas | Mostrar solo productos en oferta |
| `--list` | listar | Listar todo el catálogo |
| `-u, --update` | actualizar | Scrapear y actualizar `products.json` |
| `-w, --workers N` | actualizar | Hilos concurrentes (default: 20) |
| `--dry-run` | actualizar | Solo página 1 por tienda (pruebas) |
| `--sites NAME...` | actualizar | Actualizar solo estas tiendas |
| `--sort {discount,price,offer,original,store,value,scarcity,volatility}` | ofertas, listar | Orden de salida (default: `discount`) |
| `--store NAME` | ofertas, listar | Filtrar a una sola tienda |
| `--in-stock` | ofertas, listar | Solo productos disponibles |
| `--lower-price N` | ofertas | Precio mínimo (oferta) |
| `--higher-price N` | ofertas | Precio máximo (oferta) |
| `--price MIN:MAX` | ofertas | Rango de precio |
| `--export {csv,json,html}` | ofertas, listar | Exporta los resultados a `data/exports/` |
| `--incremental` | actualizar | Rescrapea solo tiendas obsoletas (ver `--max-age`) |
| `--max-age H` | actualizar | Antigüedad máxima en horas para incremental (default: 24) |
| `--leaderboard` | leaderboard | Ranking de tiendas |
| `--new [KIND]` | novedades | Ítems marcados new/restock en la última actualización (`new` o `restock` para filtrar) |
| `--history QUERY` | historial | Historial de precios de un juego |
| `--alert --watch G... --threshold N [--alert-out FILE]` | alertas | Vigilancia de precios |

> Nota: la búsqueda por nombre (`--name`) se ordena por relevancia (no acepta `--sort`).
> `--deals` y `--list` aceptan, además de `discount/price/offer`, los **sorts inteligentes**:
> `value` (mejor relación precio/stock), `scarcity` (en pocas tiendas),
> `volatility` (mayor variación de precio entre tiendas — oportunidad de arbitraje).

---

## Referencia de funciones

### `main.py` — orquestación CLI y modos

| Función | Firma | Descripción |
|---|---|---|
| `main` | `main()` | Parsea los flags y despacha a un modo; sin flags lanza la TUI |
| `search_mode` | `search_mode(query, limit=30)` | Lista resultados rankeados con precio/tiendas/stock (tope `limit`). En la TUI se vuelve al menú con cualquier tecla (sin selección numérica) |
| `deals_mode` | `deals_mode(store_filter, in_stock_only, lower_price, higher_price, price_range, sort_by)` | Lista los productos en oferta aplicando filtros |
| `list_mode` | `list_mode(store_filter=None, sort_by='store', in_stock_only=False)` | Listado paginado del catálogo (opcionalmente una tienda) |
| `update_mode` | `update_mode(workers=5, dry_run=False, site_names=None)` | Scrapea en paralelo, mergea al JSON, y registra metadata + historial + stats |
| `incremental_update` | `incremental_update(site_names=None, max_age_hours=24, ...)` | Rescrapea solo tiendas obsoletas (nunca scrapeadas, fallidas, o > max_age) |
| `leaderboard_mode` | `leaderboard_mode()` | Renderiza el ranking de tiendas |
| `history_mode` | `history_mode(query)` | Muestra sparklines de precio por tienda para el juego que matchea |
| `alerts_mode` | `alerts_mode(queries, threshold, output_file=None)` | Chequea una watchlist contra un umbral e imprime/escribe alertas |
| `novedades_mode` | `novedades_mode(kind=None)` | Lista los ítems marcados `new` / `restock` en la última actualización (`kind` filtra) |
| `fuzzy_search` | `fuzzy_search(query, df, score_cutoff=80)` | Inclusión `WRatio` (tolera typos) + ranking compuesto (`token_set/sort/partial` + bonos exacto/prefijo + popularidad). Agrupa variantes y devuelve dicts rankeados con `title, norm, score, n_stores, min_price, in_stock` |
| `_relevance / _rank_boost` | — | Helpers de scoring: relevancia mezclada 0–100 y bonos de orden (exacto/prefijo/token) |
| `print_price_table` | `print_price_table(df, norm_key, sort_by='discount')` | Renderiza la tabla de precios por tienda de un juego (agrupa variantes). Disponible pero no enganchado al flujo de búsqueda actual |
| `load_all_csvs` | `load_all_csvs()` | Carga `products.json` a un DataFrame (cols `store/title/norm`); fallback a los CSV por tienda si el JSON no existe |
| `scrape_site` | `scrape_site(site, dry_run=False, position=0)` | Scrapea todas las páginas de una tienda, deduplica, escribe su CSV y devuelve un DataFrame |
| `merge_to_json` | `merge_to_json(results, targets)` | Mergea resultados en `products.json` por tienda; updates parciales dejan intactas las demás; ignora resultados vacíos para no borrar datos ante fallos de red |

### `tui.py` — menú interactivo (questionary)

| Función | Descripción |
|---|---|
| `run_tui()` | Bucle del menú principal con navegación por flechas; sale limpio con *Salir* o Ctrl-C |
| `_search_flow / _deals_flow / _list_flow / _update_flow` | Recogen los inputs de cada modo y despachan a las funciones de `main.py` |
| `_leaderboard_flow / _history_flow / _alert_flow` | Flujos de los modos nuevos (leaderboard, historial, alertas) |
| `_offer_export(df)` | Tras mostrar ofertas/listado, ofrece exportar a csv/json/html |
| `_ask_store()` | Selector de tienda; "Todas las tiendas" → `None`; distingue cancelar (ESC) de "todas" con un centinela |
| `_ask_sort(options, default)` | Selector de orden (incluye sorts inteligentes en ofertas/listado) |
| `_ask_optional_price(label)` | Prompt de precio opcional (vacío → `None`) |

### `utils.py` — normalización, precios y render

| Función | Firma | Descripción |
|---|---|---|
| `normalize` | `normalize(text) -> str` | Minúsculas, quita tags de idioma/edición, acentos y puntuación → clave de matching fuzzy |
| `clean_title` | `clean_title(text) -> str` | Quita ruido de categoría ("Juego de Mesa", etc.) para mostrar, preservando subtítulos reales |
| `parse_price` | `parse_price(text) -> float \| None` | Parsea precios chilenos (`$69.990`, `69.990,50`) → float |
| `calc_discount_pct` | `calc_discount_pct(original, current) -> float \| None` | Porcentaje de descuento entre dos precios |
| `format_discount` | `format_discount(original, current) -> str` | Cadena de descuento formateada (`-28%` o `-`) |
| `sort_table` | `sort_table(df, by)` | Ordena un DataFrame por `discount/price/offer/original/store` |
| `render_table` | `render_table(df, title, col_order, col_names)` | Formatea un DataFrame como tabla de texto alineada (anchos acotados) y la pagina |
| `paginate` | `paginate(lines, page_size=50)` | Paginador "Enter para continuar"; sale limpio con Ctrl-C/EOF |

Constantes: `SORT_OPTIONS = ('discount','price','offer','original','store')`,
`LIST_DEAL_SORT_OPTIONS = ('discount','price','offer')`.

### `scrape.py` — motor de scraping

| Función | Descripción |
|---|---|
| `fetch_html(url)` | GET con sesión reutilizable + reintentos/backoff; devuelve `BeautifulSoup` o `None` |
| `build_url(base_url, pagination, page)` | Construye URLs paginadas según 7 estilos (`woo`, `shopify`, `page_param`, `gatoarcano`, `calabozo`, `devir`, …) |
| `_parse_woo_li / _parse_presta / _parse_bs / _parse_product_block(_simple)` | Parsers genéricos reutilizables por plataforma |
| `_woo_prices / _presta_prices / _old_new_prices` | Extraen precio original/oferta del HTML de cada plataforma |
| `_stock_flags / _stock_cls / _oos` | Determinan disponibilidad (agotado / oferta) desde clases CSS |
| `_txt / _url / _norm / _make_session` | Helpers: texto seguro, URL absoluta, anular precio actual si == original, sesión HTTP |
| *(≈47 parsers por tienda)* | Una función por tienda + el registro `sites` (47 entradas: `name`, `base_url`, `parser`, `pagination`, `output`) |

### `paths.py` — rutas independientes del directorio

| Símbolo | Descripción |
|---|---|
| `PKG_DIR / REPO_ROOT / DATA_DIR / JSON_PATH` | Rutas absolutas derivadas de la ubicación del paquete (no del CWD) |
| `resolve_output(output)` | Resuelve un `site['output']` (`'../data/x.csv'`) a ruta absoluta |

### Módulos de análisis y caché

| Módulo | Funciones clave | Descripción |
|---|---|---|
| `metadata.py` | `load/save_metadata`, `record_scrape`, `site_age_hours`, `stale_sites`, `set_price_stats` | Estado por tienda en `data/metadata.json` (última fecha, conteo, éxito); base del modo incremental. Updates inmutables |
| `validation.py` | `validate_prices(df)` | Marca `is_anomaly` + `anomaly_reason`: título vacío, precio ≤ 0, oferta > original, descuento > 90%, outlier > 5σ por juego |
| `history.py` | `track_price_history`, `record_dataframe_history`, `price_trend`, `sparkline` | Serie de precios en `data/history.json` (clave `norm\|store`); colapsa precios repetidos; sparkline ASCII |
| `dedup.py` | `deduplicate_by_url(df)`, `merge_variants(df, similarity_threshold=0.92)` | Colapsa URLs canónicas (precio más bajo) y agrupa variantes casi idénticas bajo un título canónico |
| `stats.py` | `price_stats_per_store(df)`, `market_summary(df)`, `effective_price(df)` | Mediana/desv/descuento/agotados/competitividad por tienda; resumen de mercado para el caché |
| `analytics.py` | `smart_sort(df, by)`, `render_store_leaderboard(df)` | Sorts derivados (`value`/`scarcity`/`volatility`) y leaderboard de tiendas. `SMART_SORT_OPTIONS` |
| `export.py` | `export_comparison(df, fmt, path=None)` | Exporta a CSV / JSON / HTML estilizado en `data/exports/` |
| `alerts.py` | `alert_on_keywords(queries, threshold, df, output_file=None)` | Vigila juegos y emite alertas JSON cuando el mejor precio ≤ umbral |
| `flags.py` | `flag_changes(new_df, prev_records)`, `flag_counts(df)` | Marca cada ítem `new` (URL no vista antes) o `restock` (estaba agotado, ahora disponible) comparando con el snapshot previo. Se recalcula en cada `--update`, así los flags anteriores se borran solos |

### Archivos de datos

| Archivo | Generado por | Contenido |
|---|---|---|
| `data/products.json` | `merge_to_json` | Catálogo mergeado por tienda (fuente primaria de lectura); los ítems `new`/`restock` llevan un campo `flag` |
| `data/metadata.json` | `update_mode` | Estado de scraping por tienda + stats de mercado cacheadas |
| `data/history.json` | `update_mode` | Historial de precios (`norm\|store` → observaciones) |
| `data/exports/` | `export_comparison` | Exportaciones bajo demanda (csv/json/html) |

---

## Flujo de datos

```
update_mode ─> scrape_site (×N) ─> validate_prices ─> merge_to_json ─> data/products.json
      │                                                                        │
      ├─> record_scrape ───────────────────────────────────> data/metadata.json
      └─> record_dataframe_history ────────────────────────> data/history.json

search / deals / list ─> load_all_csvs ─> normalize + clean_title
      │                                          │
      │                          ┌───────────────┴───────────────┐
      │                   fuzzy_search / sort_table          smart_sort
      │                          └───────────────┬───────────────┘
      │                                   render_table ─> terminal ─> export_comparison
      └─> leaderboard / history / alerts ─> stats · price_trend · alert_on_keywords
```
