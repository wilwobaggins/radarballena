import { useEffect, useMemo, useState } from "react";
import { supabase } from "./lib/supabase";
import type { DashboardRow, DeepBrief } from "./types";
import "./App.css";

type ContextSource = {
  sourceTitle?: string;
  source_title?: string;
  sourceUrl?: string;
  source_url?: string;
  summary?: string;
  relevanceScore?: number;
  relevance_score?: number;
};

function formatPercent(value: number | null | undefined) {
  if (value === null || value === undefined) return "—";
  return `${(value * 100).toFixed(1)}%`;
}

function formatMoney(value: number | null | undefined) {
  if (value === null || value === undefined) return "—";
  return `$${Math.round(value).toLocaleString()}`;
}

function getLatestDeepBrief(row: DashboardRow): DeepBrief | null {
  return row.deepbriefs?.[0] ?? null;
}

export default function App() {
  const [rows, setRows] = useState<DashboardRow[]>([]);
  const [selected, setSelected] = useState<DashboardRow | null>(null);
  const [loading, setLoading] = useState(true);
  const [errorText, setErrorText] = useState("");

  async function loadDashboard() {
  setLoading(true);
  setErrorText("");

  const { data: briefs, error: briefsError } = await supabase
    .from("deepbriefs")
    .select("*")
    .order("createdAt", { ascending: false })
    .limit(5);

  if (briefsError) {
    setErrorText(briefsError.message);
    setLoading(false);
    return;
  }

  const safeBriefs = (briefs ?? []) as DeepBrief[];

  const marketIds = safeBriefs
    .map((brief) => brief.marketId)
    .filter(Boolean);

  if (marketIds.length === 0) {
    setRows([]);
    setSelected(null);
    setLoading(false);
    return;
  }

  const { data: markets, error: marketsError } = await supabase
    .from("markets")
    .select("*")
    .in("id", marketIds);

  if (marketsError) {
    setErrorText(marketsError.message);
    setLoading(false);
    return;
  }

  const safeMarkets = (markets ?? []) as DashboardRow[];

  const mergedRows = safeBriefs
    .map((brief) => {
      const market = safeMarkets.find((item) => item.id === brief.marketId);

      if (!market) return null;

      return {
        ...market,
        deepbriefs: [brief],
      };
    })
    .filter(Boolean) as DashboardRow[];

  setRows(mergedRows);
  setSelected(mergedRows[0] ?? null);
  setLoading(false);
}

  useEffect(() => {
    loadDashboard();
  }, []);

  const selectedBrief = useMemo(() => {
    if (!selected) return null;
    return getLatestDeepBrief(selected);
  }, [selected]);

  const contextSources = useMemo(() => {
  const rawSources = selectedBrief?.rawOutput?.context_sources;

  if (!Array.isArray(rawSources)) return [];

  return rawSources as ContextSource[];
}, [selectedBrief]);

  if (loading) {
    return <main className="page">Cargando dashboard...</main>;
  }

  if (errorText) {
    return (
      <main className="page">
        <h1>RadarBallena</h1>
        <p className="error">Error Supabase: {errorText}</p>
      </main>
    );
  }

  return (
    <main className="page">
      <header className="header">
        <div>
          <p className="eyebrow">RadarBallena</p>
          <h1>DeepSignal Dashboard</h1>
          <p className="muted">
            Vista básica de mercados reales, Radar Score y Deep Briefs guardados en Supabase.
          </p>
        </div>

        <button onClick={loadDashboard}>Recargar</button>
      </header>

      <section className="grid">
        <aside className="panel panel-sidebar">
          <h2>Mercados analizados</h2>

          <div className="table">
            <div className="table-row table-head">
              <span>Mercado</span>
              <span>Prob.</span>
              <span>Volumen</span>
              <span>Radar</span>
            </div>

            {rows.map((row) => {
              const brief = getLatestDeepBrief(row);
              const active = selected?.id === row.id;

              return (
                <button
                  key={row.id}
                  className={`table-row table-button ${active ? "active" : ""}`}
                  onClick={() => setSelected(row)}
                >
                  <span className="market-title">{row.title ?? "Sin título"}</span>
                  <span>{formatPercent(row.current_probability)}</span>
                  <span>{formatMoney(row.volume)}</span>
                  <span className="score">
                    {brief?.finalRadarScore ?? brief?.radarScore ?? "—"}
                  </span>
                </button>
              );
            })}
          </div>
        </aside>

        <section className="panel detail">
          {!selected || !selectedBrief ? (
            <>
              <h2>Detalle</h2>
              <p className="muted">Selecciona un mercado con Deep Brief disponible.</p>
            </>
          ) : (
            <div className="detail-layout">
              <div className="detail-top">
                <div>
                  <p className="eyebrow">{selected.category ?? "general"}</p>
                  <h2>{selected.title}</h2>
                  <p className="muted">{selected.url}</p>
                </div>

                <div className="score-card">
                  <span>Radar Score</span>
                  <strong>{selectedBrief.finalRadarScore ?? selectedBrief.radarScore}</strong>
                  <small>{selectedBrief.signalLabel}</small>
                </div>
              </div>

              <section className="module module-scores">
                <h3>Score Híbrido</h3>

                <div className="score-grid">
                  <div>
                    <span>Preliminary</span>
                    <strong>{selectedBrief.preliminaryRadarScore ?? "—"}</strong>
                  </div>

                  <div>
                    <span>AI Interpretive</span>
                    <strong>{selectedBrief.aiInterpretiveScore ?? "—"}</strong>
                  </div>

                  <div>
                    <span>Final</span>
                    <strong>{selectedBrief.finalRadarScore ?? selectedBrief.radarScore ?? "—"}</strong>
                  </div>
                </div>
              </section>

              <div className="detail-body">
                <section className="module">
                  <h3>Lectura Clave</h3>
                  <p>{selectedBrief.lecturaClave}</p>
                </section>

                <section className="module">
                  <h3>Estela de Capital</h3>
                  <p>{selectedBrief.estelaDeCapital}</p>
                </section>

                <section className="module">
                  <h3>Corriente Narrativa</h3>
                  <p>{selectedBrief.corrienteNarrativa}</p>
                </section>

                <section className="module">
                  <h3>DeepSignal Verdict</h3>
                  <p>{selectedBrief.deepsignalVerdict}</p>
                </section>

                <section className="module">
                  <h3>Watch Triggers</h3>
                  <ul>
                    {(selectedBrief.watchTriggers ?? []).map((trigger, index) => (
                      <li key={index}>{trigger}</li>
                    ))}
                  </ul>
                </section>
              </div>

              <section className="module">
                <h3>Fuentes externas</h3>

                {!contextSources.length ? (
                  <p className="muted">Sin fuentes externas registradas.</p>
                ) : (
                  <div className="sources">
                    {contextSources.map((source, index) => {
                      const title =
                        source.sourceTitle ??
                        source.source_title ??
                        "Fuente sin título";

                      const url = source.sourceUrl ?? source.source_url;
                      const score = source.relevanceScore ?? source.relevance_score;

                      return (
                        <article key={index}>
                          <strong>{title}</strong>

                          {score !== undefined && (
                            <small>Relevancia: {Number(score).toFixed(2)}</small>
                          )}

                          <p>{source.summary}</p>

                          {url && (
                            <a href={url} target="_blank" rel="noreferrer">
                              Ver fuente
                            </a>
                          )}
                        </article>
                      );
                    })}
                  </div>
                )}
              </section>

              <section className="module">
                <h3>Mapa de Escenarios</h3>
                <div className="scenarios">
                  {(selectedBrief.mapaDeEscenarios ?? []).map((scenario, index) => (
                    <article key={index}>
                      <strong>{scenario.escenario}</strong>
                      <p>{scenario.descripcion}</p>
                    </article>
                  ))} 
                </div>
              </section>
            </div>
          )}
        </section>
      </section>
    </main>
  );
}