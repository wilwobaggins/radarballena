from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


AnalysisMode = Literal["closing_recheck"]
ScoreDirection = Literal["UP", "DOWN", "UNCHANGED"]
ScoreChangeMagnitude = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
RecheckStatus = Literal[
    "STILL_VALID",
    "WEAKENED",
    "CONTRADICTED",
    "RADICAL_CHANGE",
    "NO_MEANINGFUL_CHANGE",
    "INSUFFICIENT_SNAPSHOT",
]
Importance = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]


class ClosingContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    daysToClose: int | None = Field(default=None, ge=0)
    closingTime: str | None = None


class Reevaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    previousRadarScore: float | None = Field(default=None, ge=0, le=100)
    newRadarScore: int = Field(ge=0, le=100)
    radarScoreDelta: float | None = None
    previousSignalLabel: str | None = None
    newSignalLabel: str
    scoreDirection: ScoreDirection
    scoreChangeMagnitude: ScoreChangeMagnitude
    scoreChangeReasons: list[str]


class MetricItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    score: int | None = Field(default=None, ge=0, le=100)
    reason: str


class CapitalTrailImpact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    score: int | None = Field(default=None, ge=0, le=100)
    reason: str


class MetricBreakdown(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signalStrength: MetricItem
    informationQuality: MetricItem
    marketConsistency: MetricItem
    timingAndClosureRisk: MetricItem
    noiseRisk: MetricItem
    capitalTrailImpact: CapitalTrailImpact


class Comparison(BaseModel):
    model_config = ConfigDict(extra="forbid")

    previousThesis: str | None = None
    latestThesis: str | None = None
    newThesis: str
    whatChanged: list[str]
    whatStayedTheSame: list[str]
    contradictionDetected: bool
    contradictionExplanation: str | None = None
    probabilityChangeSincePreviousAnalysis: float | None = None
    radarScoreChangeSincePreviousAnalysis: float | None = None


class ClosingRecheckSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analysisMode: AnalysisMode
    marketId: str
    previousAnalysisId: str | None = None
    latestAnalysisId: str
    closingContext: ClosingContext
    reevaluation: Reevaluation
    metricBreakdown: MetricBreakdown
    comparison: Comparison
    recheckStatus: RecheckStatus
    importance: Importance
    recommendation: str
    thesis: str
    confidence: int = Field(ge=0, le=100)
    riskFlags: list[str]

    @field_validator("recommendation", "thesis")
    @classmethod
    def validate_non_empty_text(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("Campo obligatorio vacio")
        return value.strip()

    @field_validator("riskFlags")
    @classmethod
    def validate_risk_flags(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value if str(item).strip()]
        return cleaned

    @model_validator(mode="after")
    def validate_consistency(self):
        if self.recheckStatus == "INSUFFICIENT_SNAPSHOT":
            if self.previousAnalysisId is not None and self.comparison.previousThesis:
                return self

        if self.comparison.contradictionDetected and self.recheckStatus == "STILL_VALID":
            raise ValueError(
                "recheckStatus no puede ser STILL_VALID si contradictionDetected es true"
            )

        return self
