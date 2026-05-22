from pydantic import BaseModel
from typing import Any


class DeepBriefSchema(BaseModel):
    lectura_clave: str
    radar_score: float
    radar_score_breakdown: dict[str, Any]
    signal_label: str
    estela_de_capital: str
    entorno_de_senal: dict[str, Any]
    corriente_narrativa: str
    filtro_de_ruido: dict[str, Any]
    premortem: dict[str, Any]
    mapa_de_ruptura: dict[str, Any]
    mapa_de_escenarios: list[dict[str, Any]]
    actualizacion_bayesiana: dict[str, Any]
    deepsignal_verdict: str
    confidence_level: str
    watch_triggers: list[str]