Pega esto:

# Validación DeepSignal Pipeline End-to-End

## Objetivo

Confirmar que el pipeline real de DeepSignal sigue corriendo desde cero y genera datos reales visibles en el frontend nuevo.

## Fecha

YYYY-MM-DD

## Comando ejecutado

```bash
python -m scripts.run_daily_pipeline
Entorno
Repo: RADARBALLENA
Branch:
Máquina:
Supabase project:
Modelo IA:
Context provider:
Resultado general
Pipeline run id:
Status:
Started at:
Finished at:
Duración:
Mercados obtenidos:
Mercados filtrados:
Markets guardados:
Snapshots guardados:
Context rows guardados:
DeepBriefs generados:
Errores controlados:
Evidencia Supabase
Últimos pipeline runs

Query:

select *
from pipeline_runs
order by "startedAt" desc
limit 5;

Resultado:

PEGAR RESULTADO AQUÍ
DeepBriefs generados por este run

Query:

select count(*)
from deepbriefs
where "pipelineRunId" = 'PEGAR_RUN_ID';

Resultado:

PEGAR RESULTADO AQUÍ
Conteo de tablas principales

Query:

select count(*) from markets;
select count(*) from market_snapshots;
select count(*) from market_context;
select count(*) from deepbriefs;

Resultado:

PEGAR RESULTADO AQUÍ
Errores controlados

Query:

select *
from pipeline_errors
order by "createdAt" desc
limit 20;

Resultado:

PEGAR RESULTADO AQUÍ
Validación frontend/backend
Markets reales

Endpoint:

GET /api/deepsignal/markets

Resultado esperado:

{
  "ok": true,
  "markets": []
}

Resultado observado:

PEGAR RESULTADO O CAPTURA AQUÍ
DeepSignal por mercado

Endpoint:

GET /api/deepsignal/markets/:id/deep-signal

Resultado esperado:

{
  "ok": true,
  "report": {
    "marketId": "...",
    "thesis": "...",
    "modules": [],
    "scenarios": []
  }
}