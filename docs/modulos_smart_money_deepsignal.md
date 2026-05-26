
````md
# Separación de módulos: Smart Money Whales y DeepSignal Engine

## 1. Objetivo

Este documento define la separación técnica entre los módulos **Smart Money Whales** y **DeepSignal Engine** dentro de RadarBallena.

La intención no es mover todo el código a un solo proyecto ni mezclar responsabilidades. La intención es dejar claro qué pertenece a cada módulo, qué datos consume cada uno, qué rutas o vistas debería tener cada producto y cómo podrían conectarse más adelante.

Actualmente el backend principal se mantiene separado y eso está bien. La integración futura ocurrirá principalmente en la capa visual/frontend, posiblemente en Lovable, y mediante datos compartidos.

---

## 2. Separación conceptual

RadarBallena se divide en dos motores principales:

```txt
RadarBallena
├── Smart Money Whales
│   └── Basado en wallets, canales, alertas y resolución de trades.
│
└── DeepSignal Engine
    └── Basado en mercados, contexto externo, análisis y Deep Briefs.
````

La diferencia central es:

```txt
Smart Money = qué hacen las wallets relevantes.
DeepSignal = qué tan relevante/interesante es un mercado.
```

---

## 3. Smart Money Whales

## 3.1 Descripción

Smart Money Whales es el módulo relacionado con wallets, whales, canales y alertas.

Su objetivo es detectar movimientos relevantes de wallets monitoreadas, resolver resultados de alertas pasadas y evaluar si las wallets actuales siguen siendo buenas fuentes de señal.

## 3.2 Componentes actuales

Smart Money está compuesto por tres piezas principales:

```txt
whale-worker
telegram-relay / alert resolver
whale-finder
```

### whale-worker

Responsabilidad:

```txt
Detectar trades nuevos de wallets activas y crear alertas.
```

Función:

* monitorea wallets aprobadas;
* consulta actividad de Polymarket;
* filtra trades relevantes;
* evita duplicados;
* manda alertas al backend;
* alimenta el portal actual de alertas.

### telegram-relay / alert resolver

Responsabilidad actual recomendada:

```txt
Resolver alertas existentes y revisar si los mercados ya cerraron.
```

Antes leía Telegram como fuente principal. Ese rol ya no debe ser el principal.

Función actual esperada:

* revisar alertas unresolved;
* actualizar resultado cuando el mercado termina;
* marcar win/loss o resolved;
* apoyar auditoría de marketId si hace falta.

### whale-finder

Responsabilidad:

```txt
Evaluar wallets actuales y buscar nuevas wallets candidatas.
```

Función:

* analiza wallets existentes;
* calcula salud de wallets;
* busca wallets nuevas;
* genera candidatos;
* recomienda reemplazos;
* no cambia wallets automáticamente.

---

## 4. DeepSignal Engine

## 4.1 Descripción

DeepSignal Engine es el módulo de análisis de mercados.

Su objetivo es identificar mercados relevantes, buscar contexto externo, generar Deep Briefs, calcular Radar Score y producir una lectura estructurada del mercado.

## 4.2 Componentes actuales

DeepSignal está compuesto por:

```txt
Polymarket client
market filter
scoring service
context client
context ranker
deepbrief generator
Supabase persistence
dashboard visual
pipeline maestro
```

## 4.3 Flujo actual

```txt
Polymarket Gamma API
↓
markets
↓
market_snapshots
↓
scoring preliminar
↓
selección de mercados
↓
contexto externo
↓
ranking de fuentes
↓
OpenAI / DeepBrief
↓
scoring híbrido
↓
deepbriefs
↓
dashboard
↓
pipeline_runs / logs
```

## 4.4 Estado actual

DeepSignal ya funciona como motor independiente.

Ya puede:

* obtener mercados reales;
* guardar mercados y snapshots;
* filtrar mercados relevantes;
* calcular preliminary radar score;
* buscar contexto externo;
* ranquear fuentes;
* generar Deep Briefs con OpenAI;
* validar output estructurado;
* calcular final radar score;
* guardar resultados;
* mostrar dashboard;
* registrar logs y pipeline runs;
* correr todo con un solo comando.

---

## 5. Backend actual

El backend productivo actual se mantiene separado.

Responsabilidades actuales:

```txt
auth
users
sessions
channels
alerts
stats
Systeme.io webhooks
invites
CSRF
health
admin sync
```

Rutas actuales relevantes:

```txt
/api/alerts
/api/alerts/update
/api/channels
/api/channels/[channelId]
/api/stats
/api/auth/login
/api/auth/logout
/api/auth/register-with-invite
/api/invites/validate
/api/webhooks/systeme
/api/admin/sync-channels
```

Este backend pertenece principalmente al mundo **Smart Money / Portal actual**.

No se debe mover ni mezclar todavía con DeepSignal.

---

## 6. Frontend actual y frontend futuro

## 6.1 Frontend actual

El frontend actual del portal maneja:

```txt
login
register / crear cuenta
dashboard principal
canales
alertas
traducción visible
```

## 6.2 Frontend futuro / Lovable

La integración futura se planea en la capa visual.

Lovable o el nuevo frontend debería unificar la experiencia de usuario:

```txt
RadarBallena App
├── Smart Money
│   ├── Whale Alerts
│   ├── Channels
│   ├── Resolved Alerts
│   └── Whale Health
│
└── DeepSignal
    ├── Market Radar
    ├── Deep Briefs
    ├── Sources
    └── Pipeline Runs
```

La integración no requiere mover el backend actual. Requiere exponer o consumir datos de ambos módulos de forma ordenada.

---

## 7. Data inputs de Smart Money

Smart Money usa datos basados en wallets y alertas.

Inputs principales:

```txt
wallet address
whale_id
whale_name
channel
trade activity
market_title
market_id
event_slug
polymarket_url
action
answer
size_usd
price_cents
shares
created_at
resolution status
win/loss
```

Fuentes principales:

```txt
whale-worker
Polymarket activity API
backend alerts API
PostgreSQL/Prisma
telegram-relay / resolver
whale-finder outputs
```

Outputs principales:

```txt
alerts
resolved alerts
wallet health
replacement recommendations
channel activity
```

---

## 8. Data inputs de DeepSignal

DeepSignal usa datos basados en mercados.

Inputs principales:

```txt
external_market_id
platform
title
description
category
url
close_date
current_probability
previous_probability_24h
probability_change_24h
volume
liquidity
outcomes
raw_payload
external context sources
```

Fuentes principales:

```txt
Polymarket Gamma API
Supabase
Tavily
OpenAI
```

Outputs principales:

```txt
markets
market_snapshots
market_context
deepbriefs
pipeline_runs
pipeline_errors
final_radar_score
hybrid_score_breakdown
```

---

## 9. Rutas separadas propuestas

## 9.1 Smart Money

Rutas actuales o esperadas:

```txt
/smart-money
/smart-money/alerts
/smart-money/channels
/smart-money/resolved
/smart-money/wallet-health
```

APIs actuales:

```txt
/api/alerts
/api/alerts/update
/api/channels
/api/channels/[channelId]
/api/stats
```

## 9.2 DeepSignal

Rutas propuestas:

```txt
/deepsignal
/deepsignal/markets
/deepsignal/briefs
/deepsignal/sources
/deepsignal/runs
```

APIs futuras sugeridas:

```txt
/api/deepsignal/markets
/api/deepsignal/briefs
/api/deepsignal/runs
/api/deepsignal/context
```

Por ahora DeepSignal corre independiente con Python + Supabase + dashboard Vite.

---

## 10. Componentes compartidos

Aunque Smart Money y DeepSignal deben estar separados, comparten algunos conceptos.

Componentes compartidos:

```txt
usuarios
sesiones
permisos
market_id
market title
Polymarket URL
dashboard shell
logs
error handling
scoring visual
alerting futuro
```

No todo debe mezclarse. Compartido no significa misma lógica.

La regla es:

```txt
Compartir datos cuando tenga sentido.
No mezclar responsabilidades.
```

---

## 11. Criterio para Confluence Score post-MVP

El Confluence Score no debe implementarse todavía como requisito MVP.

Debe quedar preparado para una fase posterior.

Concepto:

```txt
Confluence Score =
DeepSignal market score
+
Smart Money whale activity
+
wallet quality score
+
resolution history
+
context strength
```

Ejemplo:

```txt
Un mercado tiene final_radar_score alto.
Una whale saludable entra fuerte en ese mercado.
El mercado tiene liquidez suficiente.
Las fuentes externas apoyan la narrativa.
Entonces la confluencia sube.
```

Inputs futuros:

```txt
finalRadarScore
preliminaryRadarScore
aiInterpretiveScore
wallet_health_score
whale_alert_strength
alert_recency
market_context_relevance
historical_wallet_accuracy
```

Criterio inicial:

```txt
No usar Confluence Score para reemplazar Radar Score.
Usarlo como capa adicional de confirmación.
```

---

## 12. Esquema simple de navegación

Propuesta de navegación para frontend/Lovable:

```txt
RadarBallena
├── Home / Overview
│
├── Smart Money
│   ├── Whale Alerts
│   ├── Channels
│   ├── Resolved Alerts
│   └── Whale Health
│
├── DeepSignal
│   ├── Market Radar
│   ├── Deep Brief Detail
│   ├── External Sources
│   └── Pipeline Runs
│
└── Settings
    ├── Account
    ├── Access
    └── Billing / Systeme
```

---

## 13. Qué no se debe mover todavía

No mover todavía:

```txt
backend productivo
auth
Systeme.io webhook
alerts API
channels API
workers Docker actuales
```

No mezclar todavía:

```txt
Smart Money alerts con DeepSignal briefs
wallet-finder con DeepSignal scoring
telegram-relay con pipeline DeepSignal
```

Primero se documenta y se estabiliza la frontera.

Después se integra visualmente.

---

## 14. Decisión arquitectónica

La decisión actual es:

```txt
Smart Money y DeepSignal se mantienen como módulos separados.

Smart Money vive alrededor del portal actual, wallets, channels y alerts.

DeepSignal vive como engine independiente basado en mercados, contexto externo y DeepBriefs.

La integración futura se hará desde el frontend/Lovable y, si hace falta, mediante APIs o tablas compartidas.
```

Esto evita duplicar backend y evita mezclar lógica prematuramente.

---

## 15. Estado de la tarjeta

Checklist:

```txt
Smart Money basado en wallets/canales: definido.
DeepSignal basado en mercados: definido.
Rutas separadas: propuestas.
Data inputs de Smart Money: definidos.
Data inputs de DeepSignal: definidos.
Componentes compartidos: definidos.
Criterio para Confluence Score: definido como post-MVP.
Esquema simple de navegación: definido.
```

Definition of Done:

```txt
Documento simple con módulos separados: completado.
```
