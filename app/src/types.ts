export type Market = {
  id: string;
  external_market_id: string | null;
  platform: string | null;
  title: string | null;
  description: string | null;
  category: string | null;
  url: string | null;
  close_date: string | null;
  current_probability: number | null;
  previous_probability_24h: number | null;
  probability_change_24h: number | null;
  volume: number | null;
  liquidity: number | null;
};

export type DeepBrief = {
  id: string;
  marketId: string;
  lecturaClave: string | null;
  radarScore: number | null;
  radarScoreBreakdown: Record<string, unknown> | null;
  signalLabel: string | null;
  estelaDeCapital: string | null;
  entornoDeSenal: Record<string, string> | null;
  corrienteNarrativa: string | null;
  filtroDeRuido: Record<string, string> | null;
  premortem: Record<string, unknown> | null;
  mapaDeRuptura: Record<string, string> | null;
  mapaDeEscenarios: Array<Record<string, string>> | null;
  actualizacionBayesiana: Record<string, string> | null;
  deepsignalVerdict: string | null;
  confidenceLevel: string | null;
  watchTriggers: string[] | null;
  rawOutput: Record<string, unknown> | null;
  createdAt: string | null;
  preliminaryRadarScore: number | null;
  aiInterpretiveScore: number | null;
  finalRadarScore: number | null;
  hybridScoreBreakdown: Record<string, unknown> | null;
};

export type DashboardRow = Market & {
  deepbriefs?: DeepBrief[];
};