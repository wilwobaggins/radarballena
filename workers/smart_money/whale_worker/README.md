# Whale Worker

Worker de Smart Money encargado de monitorear wallets activas en Polymarket y
crear alertas nuevas en el backend de RadarBallena.

## Responsabilidad

- Consultar actividad de wallets configuradas.
- Filtrar trades relevantes.
- Resolver `market_id` cuando sea posible.
- Evitar duplicados con el archivo de operaciones vistas.
- Enviar alertas a `/api/alerts`.

No resuelve resultados, calcula win/loss, evalúa la calidad de wallets ni las
reemplaza automáticamente.

## Ejecución del worker

El proceso de alertas se ejecuta con `whale_worker.py`. `discover.py` es una
utilidad separada y no es importada ni ejecutada por el worker.

```bash
python -u whale_worker.py
```

El Dockerfile de esta carpeta copia únicamente `whale_worker.py`. El worker usa
solo la biblioteca estándar de Python y no requiere `requirements.txt`. El
contexto de Docker debe ser esta carpeta; confirma que el Compose real use este
contexto y este Dockerfile antes de construir.

## Configuración del worker

```env
POLL_SECONDS=30
SEEN_FILE=/data/seen_hashes.json
MAX_AGE_SECONDS=259200
BACKEND_URL=https://app.radarballena.com
INTERNAL_API_KEY=
DRY_RUN=true
SKIP_OLD_ON_START=true
```

`DRY_RUN=true` no envía alertas ni actualiza el checkpoint. `SEEN_FILE` debe
apuntar al montaje persistente verificado para conservar la deduplicación en
ejecuciones reales. El worker actualiza ese archivo mediante reemplazo atómico.

## Descubrimiento manual

`discover.py` es una herramienta independiente para descubrimiento manual de
wallets. No forma parte de la imagen runtime ni del arranque de alertas. Puede
consultar Polymarket y generar solicitudes; ejecútala solo cuando esa tarea sea
necesaria.

```bash
python discover.py
```

## Ejemplo de payload de alerta

```json
{
  "whale_id": "nba_volume",
  "whale_name": "NBA Volume Trader Theta",
  "action": "BUY",
  "answer": "Yes",
  "market_title": "Example market",
  "market_id": "123456",
  "event_slug": "example-event",
  "polymarket_url": "https://polymarket.com/event/example-event",
  "size_usd": 500,
  "price_cents": 45,
  "shares": 1000,
  "raw_text": "..."
}
```
