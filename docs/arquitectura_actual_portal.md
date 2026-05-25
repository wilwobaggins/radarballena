
# Arquitectura actual del portal RadarBallena

## 1. Estado general

RadarBallena es una app de inteligencia para mercados de predicción, enfocada inicialmente en alertas de whales de Polymarket y, ahora, en análisis estructurado mediante DeepSignal Engine.

Actualmente existen dos líneas funcionales:

1. Portal principal de alertas:
   - Recibe alertas de whales.
   - Las guarda en base de datos.
   - Las muestra por canales en el frontend.
   - Permite acceso controlado por usuario/canal.

2. DeepSignal Engine:
   - Obtiene mercados reales de Polymarket.
   - Filtra y puntúa mercados.
   - Busca contexto externo.
   - Genera Deep Briefs con OpenAI.
   - Guarda resultados en Supabase.
   - Muestra análisis en dashboard.

El sistema ya no debe entenderse como solo “whale alerts”. Está evolucionando hacia un portal de inteligencia de mercados.

---

## 2. Stack actual

### Frontend

El frontend principal está desplegado en Vercel bajo:

- `portal.radarballena.com`

La pantalla de canal usa `DashboardLayout`. Las alertas vienen desde backend y se muestran paginadas, con 6 alertas visibles por página/canal.

También existe un dashboard básico de DeepSignal construido como módulo visual separado para mostrar mercados, Radar Score, Score Híbrido, fuentes externas y Deep Briefs.

### Backend

El backend principal corre en VPS bajo:

- `app.radarballena.com`

Usa Next.js App Router y corre en Docker.

El backend expone rutas para:

- recibir alertas;
- consultar canales;
- validar invitaciones;
- registrar usuarios con token;
- recibir webhooks de Systeme.io;
- manejar traducciones;
- recibir datos de workers internos.

### Base de datos

El portal principal usa PostgreSQL con Prisma.

Las tablas base conocidas incluyen:

- `Whale`
- `Alert`
- `User`
- `Channel`
- `UserChannel`
- `UserSession`

Para DeepSignal se está usando Supabase/Postgres con tablas como:

- `markets`
- `market_snapshots`
- `deepbriefs`
- `market_context`
- `pipeline_runs`
- `pipeline_errors`

---

## 3. Servicios actuales

### whale-worker

`whale-worker` es la fuente principal actual de nuevas alertas.

Consulta actividad directamente desde Polymarket y detecta trades relevantes de wallets configuradas. Después manda las alertas al backend.

Responsabilidades:

- monitorear wallets activas;
- filtrar trades por tamaño, categoría, antigüedad y tipo;
- evitar duplicados;
- resolver datos básicos del mercado;
- mandar payload compatible a `/api/alerts`.

El worker no debe mandar `channel_id` directamente. El backend debe resolver la relación con whales/canales.

### telegram-relay

Antes Telegram era la fuente principal de alertas. El flujo anterior era:

`Telegram → bot Python/Telethon → backend → PostgreSQL/Prisma → frontend`

Ese diseño cambió.

Ahora Telegram ya no debe ser la fuente principal. El rol recomendado de `telegram-relay` es auxiliar:

- resolver alerts unresolved;
- actualizar resultados win/loss;
- auditar marketIds si hace falta;
- no crear nuevas alertas desde Telegram como flujo principal.

### DeepSignal Engine

DeepSignal es un módulo separado que corre por scripts Python.

Flujo actual:

`Polymarket → Supabase → scoring → contexto externo → OpenAI → DeepBrief → dashboard`

El pipeline maestro ya puede correr con un solo comando:

```bash
python -m scripts.run_daily_pipeline
````

En la corrida validada, el pipeline hizo:

* 100 mercados obtenidos;
* 52 mercados filtrados;
* 10 mercados analizados;
* 10 Deep Briefs generados;
* 0 errores;
* registro correcto en `pipeline_runs`.

---

## 4. Rutas y endpoints relevantes

### Alertas

```txt
POST /api/alerts
```

Recibe alertas desde workers internos.

Payload esperado:

```txt
whale_id
whale_name
action
answer
market_title
market_id opcional
event_slug
polymarket_url
size_usd
price_cents
shares
raw_text
```

El backend guarda la alerta y debe evitar duplicados.

### Canales

```txt
GET /api/channels
```

Lee datos desde `Channel`.

Importante: los canales no se crean automáticamente al crear alerts. Existe lógica de sincronización desde whales hacia channels.

También existe ruta admin:

```txt
/api/admin/sync-channels
```

pero exige sesión admin; no usa `x-api-key`.

### Traducción

```txt
/api/translate-alerts
```

Ruta usada por frontend/Vercel para traducir alertas visibles.

Reglas actuales recomendadas:

* traducir solo las 6 alertas visibles;
* no traducir todo el canal completo;
* no cachear traducciones malas;
* detectar fallback no traducido y forzar nueva traducción.

### Systeme.io webhook

```txt
POST /api/webhooks/systeme
```

Recibe eventos comerciales desde Systeme.io.

Eventos esperados:

* `New sale`: crea/activa acceso;
* `Sale cancelled` / refund: cancela acceso;
* `Contact created` / `Opt-In`: se ignoran para acceso.

### Invitaciones

```txt
GET /api/invites/validate?token=xxx
POST /api/auth/register-with-invite
```

El frontend debe permitir crear cuenta solo con token válido.

---

## 5. Sistema de autenticación y usuarios

Usuarios normales:

* usan sesión/cookie;
* entran al portal después de crear cuenta con invitación;
* reciben permisos por `UserChannel`.

Workers internos:

* no usan sesión normal;
* usan header interno:

```txt
x-api-key: INTERNAL_API_KEY
```

Systeme.io no debe ser autoridad de usuarios. Systeme cobra y dispara webhook. RadarBallena decide acceso, permisos, sesiones y canales.

Flujo de compra recomendado:

```txt
Cliente paga en Systeme
↓
Systeme dispara webhook New sale
↓
Backend valida evento
↓
Backend genera inviteUrl
↓
Backend guarda inviteUrl en Systeme como custom field
↓
Backend agrega tag RB_INVITE_READY
↓
Systeme manda email automático
↓
Usuario crea cuenta con token
```

---

## 6. Estructura de usuarios y acceso

Entidades relevantes:

* `User`: usuario real de RadarBallena.
* `UserSession`: sesión activa.
* `CustomerAccess`: acceso comercial asociado a pago.
* `InviteToken`: token único para crear cuenta.
* `UserChannel`: relación entre usuario y canales desbloqueados.
* `Channel`: canal visible en portal.
* `Whale`: fuente/cartera monitoreada.

Regla clave:

Un usuario no debe poder registrarse libremente sin token. El registro público debe estar bloqueado o redirigido a “crear cuenta con invitación”.

---

## 7. Cómo se cargan los canales

Los canales vienen de la tabla `Channel`.

No se crean automáticamente al crear una alerta.

Existe una lógica llamada conceptualmente:

```txt
syncWhalesToChannels()
```

que crea canales desde whales y asigna:

```txt
Whale.channelId = Whale.id
```

Punto frágil: si se agregan whales nuevas y no se sincronizan canales, el frontend puede no mostrar correctamente el canal aunque existan alertas.

---

## 8. Cómo se cargan las alertas

Las alertas actuales deben venir principalmente de `whale-worker`.

Flujo:

```txt
Polymarket activity
↓
whale-worker
↓
POST /api/alerts
↓
Backend
↓
PostgreSQL/Prisma
↓
Frontend
```

La fuente anterior basada en Telegram quedó como histórica/auxiliar.

El frontend consume alertas desde backend, no directamente desde la base de datos.

---

## 9. Estructura de datos de cada alerta

Cada alerta debe mantener, como mínimo:

```txt
whale_id
whale_name
action
answer
market_title
market_id
event_slug
polymarket_url
size_usd
price_cents
shares
raw_text
createdAt
status/resolution si aplica
```

Puntos importantes:

* `conditionId` no debe usarse directamente como `market_id`.
* `market_id` debe resolverse correctamente cuando sea posible.
* `channel_id` no debe venir desde el worker como fuente de verdad.
* El backend debe deduplicar alertas.

---

## 10. Origen de datos

### Alertas whale

Fuente principal:

```txt
https://data-api.polymarket.com/activity
```

Procesado por `whale-worker`.

### Resolución de mercados

Se apoya en Polymarket/Gamma API cuando hace falta resolver información del mercado.

### DeepSignal

Fuentes:

* Polymarket Gamma API para mercados.
* Supabase para persistencia.
* Tavily para contexto externo.
* OpenAI para generación de Deep Briefs.
* Supabase dashboard o frontend Vite para visualización.

### Pagos y acceso

Fuente:

* Systeme.io webhook.

RadarBallena conserva la autoridad de acceso.

---

## 11. DeepSignal Engine — arquitectura actual

DeepSignal ya cumple el flujo principal recomendado:

```txt
Mercados activos
↓
Filtro de relevancia
↓
Scoring inicial
↓
Búsqueda de contexto externo
↓
Análisis con OpenAI
↓
Validación estructurada
↓
Guardado en Supabase
↓
Visualización en dashboard
```

Componentes implementados o equivalentes:

```txt
scripts/fetch_markets.py
scripts/fetch_context.py
scripts/generate_deepbrief.py
scripts/run_daily_pipeline.py

services/polymarket_client.py
services/scoring_service.py
services/context_client.py
services/context_ranker.py
services/deepbrief_generator.py
services/supabase_service.py
services/logger_service.py
services/error_types.py

prompts/deepbrief_master_prompt.txt
prompts/json_repair_prompt.txt

schemas/deepbrief_schema.py
```

El output visible usa nombres propios de RadarBallena:

* Lectura Clave
* Radar Score
* Estela de Capital
* Entorno de Señal
* Corriente Narrativa
* Filtro de Ruido
* Mapa de Ruptura
* Mapa de Escenarios
* DeepSignal Verdict

Internamente puede usar metodologías como STEEP, Premortem, Red Team, Scenario Planning, Weak Signals, Bayesian Update y Narrative Intelligence.

---

## 12. Qué ya está listo para MVP

### Portal de alertas

Listo o casi listo:

* Backend en VPS.
* Frontend en Vercel.
* Workers internos con `x-api-key`.
* `whale-worker` como fuente principal de alertas.
* Payload compatible con `/api/alerts`.
* Estructura básica de whales, alerts, users, channels y sessions.
* Traducción visible por canal con paginación.

### Acceso comercial

Listo parcialmente:

* Systeme.io como checkout.
* Webhook manual probado.
* Custom field `rb_invite_url`.
* Tag `RB_INVITE_READY`.
* Automation rule para email.
* Email automático funcionando cuando se agrega el tag.
* Falta validar completamente pago real → webhook real → tag automático.

### DeepSignal

Listo para MVP técnico:

* Obtiene mercados reales.
* Guarda markets y snapshots.
* Filtra mercados relevantes.
* Calcula preliminary score.
* Busca contexto externo.
* Ranquea fuentes.
* Genera Deep Briefs con OpenAI.
* Valida output con schema.
* Aplica scoring híbrido.
* Guarda raw output.
* Registra logs.
* Registra pipeline runs.
* Muestra dashboard con 5+ mercados reales.
* Pipeline maestro genera 10 Deep Briefs reales en una sola corrida.

---

## 13. Puntos frágiles y riesgos actuales

### 1. Mezcla de nombres camelCase y snake_case

Hay tablas donde conviven columnas como:

```txt
startedAt / started_at
marketsFetched / markets_fetched
marketId / market_id
```

Riesgo: errores de schema cache, inserts fallidos o confusión entre frontend/backend.

Recomendación futura: estandarizar por módulo. En Supabase actual se está usando mucho camelCase para relaciones y deepbriefs.

### 2. Systeme.io pago real no confirmado end-to-end

El flujo manual funciona, pero hubo un caso donde el contacto se creó y no recibió tag. Eso sugiere que el webhook real de `New sale` no llegó al backend o no ejecutó `sendInviteEmail()`.

### 3. Canales no se crean automáticamente

Si se agregan whales nuevas sin sincronizar channels, puede haber alerts sin canal visible.

### 4. Traducciones cacheadas incorrectamente

El frontend usa cache local/global. Si se cachea una mala traducción, puede quedarse pegada.

### 5. Performance del pipeline

Guardar 100 markets + 100 snapshots uno por uno tarda varios minutos. Funciona para MVP, pero conviene optimizar con batch upsert.

### 6. Contexto externo puede ser desigual

Algunos mercados consiguen 3 fuentes útiles; otros pueden tener fuentes débiles o cero fuentes si la query no encuentra resultados. El ranker ayuda, pero la búsqueda todavía puede mejorar.

### 7. Alertas candidatas no necesariamente están persistidas

`create_alerts()` existe en el pipeline maestro como MVP lógico, pero debe definirse si las alertas DeepSignal se guardarán en tabla propia, se enviarán por Telegram/email o solo se mostrarán en dashboard.

---

## 14. Diagnóstico rápido

RadarBallena ya tiene dos motores:

1. Motor de alertas whale:

   * orientado a detectar trades relevantes.
   * fuente principal: `whale-worker`.
   * salida: alerts por canal.

2. Motor DeepSignal:

   * orientado a análisis estratégico de mercados.
   * fuente principal: mercados Polymarket + contexto externo.
   * salida: Deep Briefs y Radar Score.

El riesgo principal no es falta de backend. El riesgo actual es integración/producto: que el portal no muestre claramente todo lo que el motor ya produce.

---

## 15. Recomendación de documentación futura

Separar documentación en:

```txt
docs/arquitectura_actual_portal.md
docs/deepsignal_engine.md
docs/systeme_access_flow.md
docs/whale_worker.md
docs/riesgos_tecnicos.md
```

Este documento debe considerarse fotografía del estado actual, no contrato final.

```

Base usada: arquitectura actual del portal/backend/worker, flujo original de Telegram a backend, integración Systeme.io y brief técnico DeepSignal. :contentReference[oaicite:0]{index=0} :contentReference[oaicite:1]{index=1} :contentReference[oaicite:2]{index=2} :contentReference[oaicite:3]{index=3}
```
