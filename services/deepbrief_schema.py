from typing import Literal
from pydantic import BaseModel, ConfigDict


class StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RadarScoreBreakdown(StrictBaseModel):
    movimiento_probabilidad: float
    volumen: float
    liquidez: float
    cercania_cierre: float
    claridad_resolucion: float
    fuerza_narrativa: float
    asimetria_detectada: float
    riesgo_ruido: float


class EntornoDeSenal(StrictBaseModel):
    steep_social: str
    steep_tecnologico: str
    steep_economico: str
    steep_ecologico: str
    steep_politico_regulatorio: str
    sintesis: str


class FiltroDeRuido(StrictBaseModel):
    red_team: str
    sesgos_detectados: str
    riesgo_liquidez: str
    riesgo_resolucion: str
    informacion_ya_descontada: str


class Premortem(StrictBaseModel):
    si_la_tesis_falla_probablemente_seria_por: str
    senales_tempranas_de_invalidacion: list[str]


class MapaDeRuptura(StrictBaseModel):
    confirmacion: str
    ruptura_alcista: str
    ruptura_bajista: str
    invalidacion: str
    evento_detonador: str


class Escenario(StrictBaseModel):
    escenario: str
    probabilidad_interna: str
    descripcion: str
    impacto_en_mercado: str


class ActualizacionBayesiana(StrictBaseModel):
    probabilidad_actual_del_mercado: str
    lectura_deepsignal: str
    direccion_sugerida_del_update: str
    razon: str


class DeepBriefSchema(StrictBaseModel):
    lectura_clave: str
    radar_score: float
    radar_score_breakdown: RadarScoreBreakdown
    signal_label: Literal["Ignore", "Watchlist", "Strong Watch", "High Conviction"]
    estela_de_capital: str
    entorno_de_senal: EntornoDeSenal
    corriente_narrativa: str
    filtro_de_ruido: FiltroDeRuido
    premortem: Premortem
    mapa_de_ruptura: MapaDeRuptura
    mapa_de_escenarios: list[Escenario]
    actualizacion_bayesiana: ActualizacionBayesiana
    deepsignal_verdict: str
    confidence_level: Literal["Low", "Medium", "High"]
    watch_triggers: list[str]