from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


SignalLabel = Literal[
    "Señal fuerte",
    "Oportunidad relevante",
    "Watchlist",
    "Señal débil / incierta",
    "Evitar",
]

ConfidenceLevel = Literal["Low", "Medium", "High"]
UpdateDirection = Literal["subir", "bajar", "mantener"]
ScenarioName = Literal["Base", "Ruptura", "Contrario"]
PredictedOutcome = Literal["yes", "no", "neutral", "no_call"]
ExpectedDirection = Literal["yes_up", "yes_down", "neutral"]
PredictionConfidence = Literal["low", "medium", "high"]


class RadarScoreBreakdown(BaseModel):
    movimiento_probabilidad: int
    volumen: int
    liquidez: int
    cercania_cierre: int
    claridad_resolucion: int
    fuerza_narrativa: int
    asimetria_detectada: int
    riesgo_ruido: int


class EntornoDeSenal(BaseModel):
    steep_social: str
    steep_tecnologico: str
    steep_economico: str
    steep_ecologico: str
    steep_politico_regulatorio: str
    sintesis: str


class FiltroDeRuido(BaseModel):
    red_team: str
    sesgos_detectados: str
    riesgo_liquidez: str
    riesgo_resolucion: str
    informacion_ya_descontada: str


class Premortem(BaseModel):
    si_la_tesis_falla_probablemente_seria_por: str
    senales_tempranas_de_invalidacion: list[str]


class MapaDeRuptura(BaseModel):
    confirmacion: str
    ruptura_alcista: str
    ruptura_bajista: str
    invalidacion: str
    evento_detonador: str


class Escenario(BaseModel):
    escenario: ScenarioName
    probabilidad_interna: str
    descripcion: str
    impacto_en_mercado: str


class ActualizacionBayesiana(BaseModel):
    probabilidad_actual_del_mercado: str
    lectura_deepsignal: str
    direccion_sugerida_del_update: UpdateDirection
    razon: str


class PredictionAudit(BaseModel):
    predicted_outcome: PredictedOutcome
    predicted_probability: float | None = Field(default=None, ge=0, le=1)
    expected_direction: ExpectedDirection | None = None
    prediction_confidence: PredictionConfidence | None = None
    prediction_reasoning_summary: str | None = None

    @model_validator(mode="after")
    def validate_prediction_consistency(self):
        if self.predicted_outcome in {"yes", "no"} and self.predicted_probability is None:
            raise ValueError(
                "predicted_probability es obligatoria cuando predicted_outcome es yes o no"
            )

        if self.predicted_outcome == "no_call" and self.predicted_probability is not None:
            raise ValueError(
                "predicted_probability debe ser null cuando predicted_outcome es no_call"
            )

        return self


class DeepBrief(BaseModel):
    lectura_clave: str
    radar_score: int = Field(ge=0, le=100)
    radar_score_breakdown: RadarScoreBreakdown
    signal_label: SignalLabel
    estela_de_capital: str
    entorno_de_senal: EntornoDeSenal
    corriente_narrativa: str
    filtro_de_ruido: FiltroDeRuido
    premortem: Premortem
    mapa_de_ruptura: MapaDeRuptura
    mapa_de_escenarios: list[Escenario]
    actualizacion_bayesiana: ActualizacionBayesiana
    deepsignal_verdict: str
    confidence_level: ConfidenceLevel
    watch_triggers: list[str]
    prediction_audit: PredictionAudit

    @field_validator(
        "lectura_clave",
        "estela_de_capital",
        "corriente_narrativa",
        "deepsignal_verdict",
    )
    @classmethod
    def validate_non_empty_text(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("Campo obligatorio vacío")

        if len(value.strip()) < 8:
            raise ValueError("Campo demasiado corto")

        return value.strip()

    @field_validator("watch_triggers")
    @classmethod
    def validate_watch_triggers(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("watch_triggers debe tener al menos un elemento")

        if len(value) > 5:
            raise ValueError("watch_triggers no debe tener más de 5 elementos")

        return value

    @model_validator(mode="after")
    def validate_scenarios(self):
        if len(self.mapa_de_escenarios) != 3:
            raise ValueError("mapa_de_escenarios debe tener exactamente 3 escenarios")

        expected_order = ["Base", "Ruptura", "Contrario"]
        received_order = [item.escenario for item in self.mapa_de_escenarios]

        if received_order != expected_order:
            raise ValueError(
                f"mapa_de_escenarios debe estar en orden {expected_order}; recibió {received_order}"
            )

        return self
