-- RadarBallena Supabase schema snapshot
-- Generado desde information_schema.columns
-- Uso: documentación / referencia de estructura
-- No ejecutar sobre producción sin revisar antes.

create extension if not exists pgcrypto;

begin;

-- =========================
-- MARKETS
-- =========================

create table if not exists public.markets (
  id uuid primary key default gen_random_uuid(),
  "externalMarketId" text,
  platform text not null default 'polymarket'
);

-- =========================
-- CHANNELS
-- =========================

create table if not exists public.channels (
  id text primary key,
  name text not null,
  slug text not null,
  "createdAt" timestamp with time zone not null default now(),
  "updatedAt" timestamp with time zone not null default now()
);

-- =========================
-- ALERTS
-- =========================

create table if not exists public.alerts (
  id integer primary key,
  "whaleId" text not null,
  "whaleName" text not null,
  action text not null,
  answer text not null,
  "marketTitle" text not null,
  "marketId" text,
  "deepMarketId" uuid references public.markets(id) on delete set null,
  "polymarketUrl" text,
  "eventSlug" text,
  "telegramDate" timestamp with time zone,
  resolved boolean not null default false,
  result text,
  "isWin" boolean,
  "sizeUsd" double precision not null,
  "priceCents" integer not null,
  shares integer not null,
  "rawText" text not null,
  hash text not null,
  "createdAt" timestamp with time zone not null default now()
);

-- =========================
-- CUSTOMER ACCESS
-- =========================

create table if not exists public.customer_access (
  id text primary key,
  email text not null,
  status text not null default 'active',
  provider text not null default 'systeme',
  "systemeCustomerId" text,
  "systemeContactId" text,
  "systemeOrderId" text,
  "systemeOrderItemId" text,
  "systemePricePlanId" text,
  "productName" text,
  "userId" text,
  "activatedAt" timestamp with time zone,
  "cancelledAt" timestamp with time zone,
  "createdAt" timestamp with time zone not null default now(),
  "updatedAt" timestamp with time zone not null default now()
);

-- =========================
-- INVITE TOKENS
-- =========================

create table if not exists public.invite_tokens (
  id text primary key,
  "accessId" text not null references public.customer_access(id) on delete cascade,
  email text not null,
  "tokenHash" text not null,
  "expiresAt" timestamp with time zone not null,
  "usedAt" timestamp with time zone,
  "createdAt" timestamp with time zone not null default now()
);

-- =========================
-- DEEPBRIEFS
-- =========================

create table if not exists public.deepbriefs (
  id uuid primary key default gen_random_uuid(),
  "marketId" uuid not null references public.markets(id) on delete cascade,
  "pipelineRunId" uuid,
  "lecturaClave" text,
  "radarScore" double precision not null,
  "radarScoreBreakdown" jsonb,
  "signalLabel" text,
  "estelaDeCapital" text,
  "entornoDeSenal" jsonb,
  "corrienteNarrativa" text,
  "filtroDeRuido" jsonb,
  premortem jsonb,
  "mapaDeRuptura" jsonb,
  "mapaDeEscenarios" jsonb,
  "actualizacionBayesiana" jsonb,
  "deepsignalVerdict" text,
  "confidenceLevel" text,
  "watchTriggers" jsonb,
  "rawOutput" jsonb,
  "createdAt" timestamp with time zone not null default now(),
  "preliminaryRadarScore" numeric,
  "aiInterpretiveScore" numeric,
  "finalRadarScore" numeric,
  "hybridScoreBreakdown" jsonb
);

-- =========================
-- MARKET CONTEXT
-- =========================

create table if not exists public.market_context (
  id uuid primary key default gen_random_uuid(),
  "marketId" uuid not null references public.markets(id) on delete cascade,
  "sourceTitle" text not null,
  "sourceUrl" text,
  "publishedDate" timestamp with time zone,
  summary text not null,
  "relevanceScore" double precision,
  "createdAt" timestamp with time zone not null default now(),

  -- Campos snake_case agregados después
  source_title text,
  source_url text,
  published_date timestamp with time zone,
  relevance_score numeric,
  raw_payload jsonb,
  created_at timestamp with time zone default now()
);

-- =========================
-- MARKET SNAPSHOTS
-- =========================

create table if not exists public.market_snapshots (
  id uuid primary key default gen_random_uuid(),
  "marketId" uuid not null references public.markets(id) on delete cascade,
  "currentProbability" double precision,
  volume double precision,
  liquidity double precision,
  "priceYes" double precision,
  "priceNo" double precision,
  "rawData" jsonb,
  "capturedAt" timestamp with time zone not null default now(),

  -- Campos snake_case agregados después
  current_probability numeric,
  previous_probability_24h numeric,
  probability_change_24h numeric
);

-- =========================
-- INDEXES
-- =========================

create index if not exists alerts_whale_id_idx
  on public.alerts ("whaleId");

create index if not exists alerts_market_id_idx
  on public.alerts ("marketId");

create index if not exists alerts_deep_market_id_idx
  on public.alerts ("deepMarketId");

create index if not exists alerts_created_at_idx
  on public.alerts ("createdAt");

create index if not exists invite_tokens_email_idx
  on public.invite_tokens (email);

create index if not exists invite_tokens_access_id_idx
  on public.invite_tokens ("accessId");

create index if not exists customer_access_email_idx
  on public.customer_access (email);

create index if not exists customer_access_user_id_idx
  on public.customer_access ("userId");

create index if not exists deepbriefs_market_id_idx
  on public.deepbriefs ("marketId");

create index if not exists deepbriefs_pipeline_run_id_idx
  on public.deepbriefs ("pipelineRunId");

create index if not exists market_context_market_id_idx
  on public.market_context ("marketId");

create index if not exists market_snapshots_market_id_idx
  on public.market_snapshots ("marketId");

create index if not exists market_snapshots_captured_at_idx
  on public.market_snapshots ("capturedAt");

commit;