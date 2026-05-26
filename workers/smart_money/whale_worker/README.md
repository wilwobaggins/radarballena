# Whale Worker

Worker de Smart Money encargado de monitorear wallets activas en Polymarket y crear alertas nuevas en el backend de RadarBallena.

## Responsabilidad

- Consultar actividad de wallets configuradas.
- Filtrar trades relevantes.
- Resolver market_id cuando sea posible.
- Evitar duplicados con `seen_hashes`.
- Enviar alertas a `/api/alerts`.

## No hace

- No resuelve resultados.
- No calcula win/loss.
- No evalúa si una wallet es buena o mala.
- No reemplaza wallets automáticamente.

## Variables de entorno

```env
POLL_SECONDS=30
SEEN_FILE=/data/seen_hashes.json
MAX_AGE_SECONDS=259200
BACKEND_URL=https://app.radarballena.com
INTERNAL_API_KEY=
DRY_RUN=true
SKIP_OLD_ON_START=true

Ejecución local
python discover.py
Payload enviado al backend
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

Después de copiar, prueba desde esa carpeta:

```powershell
cd workers\smart_money\whale_worker
python discover.py