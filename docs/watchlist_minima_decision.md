# Watchlist mínima real — Decisión Beta

## Objetivo

Definir si beta users pueden guardar mercados en una watchlist persistente.

## Decisión

Para esta etapa se difiere la persistencia real de watchlist.

La watchlist queda temporalmente como read-only/mock o se ocultan acciones que prometan persistencia.

## Motivo

La auth beta todavía no está completamente validada end-to-end.

Falta confirmar:

```txt
invite válido → crear cuenta → login → dashboard

Sin auth confirmada, no conviene implementar:

GET /watchlist
POST /watchlist
DELETE /watchlist/:marketId

porque la watchlist debe estar necesariamente scopeada por userId.

Regla de producto

La UI no debe mentir.

Si no hay persistencia real:

no mostrar botón “Guardar” como si funcionara;
no prometer que el mercado queda guardado;
si se muestra watchlist mock, marcarla como demo/read-only.
Implementación futura

Cuando auth esté validada:

GET /watchlist
POST /watchlist
DELETE /watchlist/:marketId

Todos los registros deben guardarse con:

userId
marketId
createdAt
Decisión final

Watchlist persistente se difiere.

Para beta actual:

read-only mock, o
ocultar acciones de guardar.