````md
# Integration Map — Backend viejo ↔ Frontend nuevo

## Objetivo

Auditar qué partes del backend/productivo y Supabase pueden alimentar el frontend nuevo sin romper el sistema actual.

## Decisión

La integración debe hacerse con **API/adapter intermedio**, no con Supabase directo desde el frontend.

Razón: el frontend espera shapes normalizados (`Market`, `DeepSignalReport`, `WhaleMovement`, `Alert`) y las tablas actuales no coinciden 1:1 con esos tipos.

Además, la estrategia actual del proyecto sigue siendo:

```txt
Prisma / DB VPS = fuente principal actual
Supabase = espejo secundario progresivo
````

No se debe mover auth, pagos, sesiones, invitaciones ni Systeme todavía. 

---

## Mock client actual

Funciones detectadas:

```ts
getMarkets()
getMarketById(id)
getDeepSignalByMarketId(marketId)
getWhaleMovements()
getWhaleMovementsByMarketId(marketId)
getWatchlist()
getAlerts()
```

Estas funciones ya están preparadas para reemplazarse por fetch real sin cambiar firmas. 

---

## Mapa de integración

| mockClient function                     | Tipo esperado frontend     | Fuente real posible                                  | Endpoint recomendado                                 | Adapter necesario | Status   |
| --------------------------------------- | -------------------------- | ---------------------------------------------------- | ---------------------------------------------------- | ----------------- | -------- |
| `getMarkets()`                          | `Market[]`                 | `markets` + último `market_snapshots` + `deepbriefs` | `GET /api/deepsignal/markets`                        | Sí                | Parcial  |
| `getMarketById(id)`                     | `Market \| null`           | `markets` + último `market_snapshots` + `deepbriefs` | `GET /api/deepsignal/markets/:id`                    | Sí                | Parcial  |
| `getDeepSignalByMarketId(marketId)`     | `DeepSignalReport \| null` | `deepbriefs` + `market_context`                      | `GET /api/deepsignal/markets/:id/report`             | Sí                | Viable   |
| `getWhaleMovements()`                   | `WhaleMovement[]`          | `alerts`                                             | `GET /api/whale-movements`                           | Sí                | Parcial  |
| `getWhaleMovementsByMarketId(marketId)` | `WhaleMovement[]`          | `alerts WHERE marketId/deepMarketId`                 | `GET /api/whale-movements?marketId=`                 | Sí                | Parcial  |
| `getWatchlist()`                        | `WatchlistItem[]`          | No existe tabla clara                                | Pendiente                                            | Sí                | No listo |
| `getAlerts()`                           | `Alert[]`                  | `alerts`                                             | `GET /api/alerts/feed` o adapter sobre `/api/alerts` | Sí                | Parcial  |

---

## Gaps detectados

### 1. `Market`

El frontend espera:

```ts
id
title
category
platform
probability
prevProbability
change24h
radarScore
smartBias
closingTime
closingLabel
volume
liquidity
whaleVolume
noiseRisk
```

Pero en el schema entregado, `markets` solo muestra:

```txt
id
externalMarketId
platform
```

Y `market_snapshots` tiene probabilidad, volumen y liquidez, pero no `title`, `category`, `closingTime`, `smartBias` ni `noiseRisk`. 

Conclusión: `Market` necesita adapter y probablemente enriquecer tabla `markets` o leer campos desde `rawData`.

---

### 2. `DeepSignalReport`

El frontend espera:

```ts
marketId
generatedAt
modelVersion
thesis
modules
scenarios
disclaimer
radarBreakdown
capitalTrail
environment
noiseFilter
narrativeMap
breakingPoint
brief
```

La tabla `deepbriefs` sí tiene buena base:

```txt
lecturaClave
radarScore
radarScoreBreakdown
signalLabel
estelaDeCapital
entornoDeSenal
corrienteNarrativa
filtroDeRuido
mapaDeRuptura
mapaDeEscenarios
deepsignalVerdict
watchTriggers
rawOutput
finalRadarScore
hybridScoreBreakdown
```

Conclusión: viable, pero requiere transformar campos españoles/DB hacia `DeepSignalReport`. 

---

### 3. `WhaleMovement`

El frontend espera:

```ts
wallet
direction
amount
impact
quality
timestamp
tier
```

La tabla `alerts` tiene:

```txt
whaleId
whaleName
action
answer
marketTitle
marketId
sizeUsd
priceCents
shares
createdAt
isWin
resolved
```

Conclusión: se puede construir una versión inicial usando `alerts`, pero faltan `impact`, `quality`, `tier` y wallet real. Es parcial. 

---

### 4. `Alert`

El frontend espera alertas tipo evento de UI:

```ts
id
marketId
title
type
message
severity
timestamp
read
```

La tabla `alerts` actual realmente representa whale alerts/product signals, no notificaciones de usuario.

Conclusión: usar adapter temporal. No confundir con sistema futuro de notificaciones.

---

### 5. `Watchlist`

No hay tabla clara para watchlist.

Conclusión: mantener mock por ahora o crear tabla futura:

```txt
watchlist_items
- id
- userId
- marketId
- savedAt
- status
```

No implementarlo en esta tarjeta.

---

## Rutas backend vistas

Backend actual expone rutas bajo:

```txt
/api/admin
/api/alerts
/api/alerts/update
/api/auth/login
/api/auth/logout
/api/auth/me
/api/auth/register
/api/auth/register-with-invite
/api/channels
/api/channels/[channelId]
/api/csrf-token
/api/deepsignal
/api/health
/api/invites
/api/me
/api/stats
/api/webhooks
```

Para esta integración, las rutas importantes son:

```txt
/api/deepsignal
/api/alerts
/api/stats
/api/channels
```

Auth, pagos, invites y Systeme no se tocan.

---

## Recomendación final

Crear endpoints nuevos de lectura para el frontend nuevo:

```txt
GET /api/deepsignal/markets
GET /api/deepsignal/markets/:id
GET /api/deepsignal/markets/:id/report
GET /api/whale-movements
GET /api/alerts/feed
```

Estos endpoints deben devolver exactamente los tipos definidos en `src/types/domain.ts`.

No modificar todavía:

```txt
auth
users
sessions
Systeme
register-with-invite
pagos
mockClient signatures
```
