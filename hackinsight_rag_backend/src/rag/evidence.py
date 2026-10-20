"""Build citable evidence from the approved HackInsight data sources.

This module is deliberately retrieval-only. It does not call an LLM, compute
embeddings, or infer facts outside the source files. Every item carries a stable
citation ID so downstream answers can point back to an approved source.
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd

from src.rag.external_sources import (
    DEFAULT_METADATA_PATH as DEFAULT_EXTERNAL_METADATA_PATH,
    iter_external_passages,
    source_as_dict,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]

OBSERVATION = "observation"
HISTORICAL_TARGET = "historical_target"
BASELINE_FORECAST = "baseline_forecast"
MODEL_FORECAST = "model_forecast"
EVALUATION_METRIC = "evaluation_metric"
DATA_VALIDITY = "data_validity"
DOCUMENTATION = "documentation"

EVIDENCE_TYPES = (
    OBSERVATION,
    HISTORICAL_TARGET,
    BASELINE_FORECAST,
    MODEL_FORECAST,
    EVALUATION_METRIC,
    DATA_VALIDITY,
    DOCUMENTATION,
)

DOCUMENT_SLUGS = {
    "REPORT.md": "report",
    "GLOSSARY.md": "glossary",
    "0001-warehouse-architecture-and-keys.md": "adr-0001",
}


def _relative_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix()


@dataclass(frozen=True)
class EvidenceSources:
    daily: Path = PROJECT_ROOT / "data/processed/daily.parquet"
    model_metrics: Path = PROJECT_ROOT / "reports/pm25_hist_gradient_boosting_metrics.json"
    baseline_metrics: Path = PROJECT_ROOT / "reports/persistence_baseline_metrics.json"
    model_predictions: Path = (
        PROJECT_ROOT / "data/processed/pm25_hist_gradient_boosting_test_predictions.csv"
    )
    baseline_predictions: Path = (
        PROJECT_ROOT / "data/processed/persistence_baseline_test_predictions.csv"
    )
    station_validity: Path = PROJECT_ROOT / "reports/station_validity.csv"
    external_metadata: Path = DEFAULT_EXTERNAL_METADATA_PATH
    documents: tuple[Path, ...] = (
        PROJECT_ROOT / "REPORT.md",
        PROJECT_ROOT / "GLOSSARY.md",
        PROJECT_ROOT / "docs/adr/0001-warehouse-architecture-and-keys.md",
    )


DEFAULT_SOURCES = EvidenceSources()


@dataclass(frozen=True)
class EvidenceItem:
    citation_id: str
    evidence_type: str
    source: str
    text: str
    station_slug: str | None = None
    station_name: str | None = None
    date: str | None = None
    target_date: str | None = None
    score: float = 0.0
    data: Mapping[str, Any] = field(default_factory=dict)

    @property
    def citation(self) -> str:
        return self.citation_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "citation_id": self.citation_id,
            "evidence_type": self.evidence_type,
            "source": self.source,
            "text": self.text,
            "station_slug": self.station_slug,
            "station_name": self.station_name,
            "date": self.date,
            "target_date": self.target_date,
            "score": self.score,
            "data": dict(self.data),
        }


@dataclass
class EvidenceIndex:
    items: tuple[EvidenceItem, ...]
    sources: EvidenceSources
    latest_observation_date: str | None = None
    latest_target_date: str | None = None
    latest_forecast_date: str | None = None
    _by_id: dict[str, EvidenceItem] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        for item in self.items:
            if item.citation_id in self._by_id:
                raise ValueError(f"Duplicate evidence citation ID: {item.citation_id}")
            self._by_id[item.citation_id] = item

    def get(self, citation_id: str) -> EvidenceItem | None:
        return self._by_id.get(citation_id)

    def by_type(self, evidence_type: str) -> tuple[EvidenceItem, ...]:
        return tuple(item for item in self.items if item.evidence_type == evidence_type)

    def station_names(self) -> dict[str, str]:
        stations: dict[str, str] = {}
        for item in self.items:
            if item.station_slug and item.station_name:
                stations.setdefault(item.station_slug, item.station_name)
        return stations

    def __len__(self) -> int:
        return len(self.items)

    def __iter__(self):
        return iter(self.items)


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _iso_date(value: Any) -> str | None:
    if _is_missing(value):
        return None
    return pd.Timestamp(value).date().isoformat()


def _add_days(value: Any, days: int) -> str | None:
    date_value = _iso_date(value)
    if date_value is None:
        return None
    return (pd.Timestamp(date_value) + pd.Timedelta(days=days)).date().isoformat()


def _number(value: Any) -> float | None:
    if _is_missing(value):
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return number


def _fmt(value: Any, digits: int = 2) -> str:
    number = _number(value)
    if number is None:
        return "not available"
    return f"{number:.{digits}f}"


def _fmt_int(value: Any) -> str:
    number = _number(value)
    if number is None:
        return "not available"
    return str(int(round(number)))


def _bool(value: Any) -> bool:
    return bool(value) if not _is_missing(value) else False


def _slugify(value: str) -> str:
    normalised = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    normalised = normalised.lower().replace("&", " and ")
    slug = re.sub(r"[^a-z0-9]+", "-", normalised).strip("-")
    return slug or "section"


def _date_from_path_source(path: Path) -> str:
    return _relative_path(path)


def _daily_evidence(frame: pd.DataFrame, source: str) -> list[EvidenceItem]:
    items: list[EvidenceItem] = []
    for row in frame.itertuples(index=False):
        record_id = str(row.record_id)
        station_slug = str(row.station_slug)
        station_name = str(row.station_name)
        date = _iso_date(row.pkt_date)
        valid = _bool(row.is_valid_day)
        flag = str(row.validity_flag)
        pm25 = _number(row.pm25_daily_mean)
        n_valid = _fmt_int(row.n_valid_pm25_hours)
        n_total = _fmt_int(row.n_total_hours)

        if pm25 is None:
            text = (
                f"Daily observation record for {station_name} ({station_slug}) on {date}: "
                f"no usable PM2.5 daily mean. Validity: {flag}; "
                f"{n_valid} of {n_total} hours valid."
            )
        else:
            text = (
                f"Daily observation for {station_name} ({station_slug}) on {date}: "
                f"PM2.5 daily mean {_fmt(pm25)} ug/m3. Validity: {flag}; "
                f"{n_valid} of {n_total} hours valid. "
                f"Weather: mean temperature {_fmt(row.weather_temp_mean_c)} C, "
                f"mean relative humidity {_fmt(row.weather_rh_mean_pct)}%, "
                f"mean wind {_fmt(row.weather_wind_mean_kmh)} km/h, "
                f"precipitation {_fmt(row.weather_precip_sum_mm)} mm."
            )

        items.append(
            EvidenceItem(
                citation_id=f"daily:{record_id}",
                evidence_type=OBSERVATION,
                source=source,
                text=text,
                station_slug=station_slug,
                station_name=station_name,
                date=date,
                data={
                    "record_id": record_id,
                    "pkt_date": date,
                    "pm25_daily_mean": pm25,
                    "is_valid_day": valid,
                    "validity_flag": flag,
                    "n_valid_pm25_hours": _number(row.n_valid_pm25_hours),
                    "n_total_hours": _number(row.n_total_hours),
                    "weather_temp_mean_c": _number(row.weather_temp_mean_c),
                    "weather_temp_max_c": _number(row.weather_temp_max_c),
                    "weather_rh_mean_pct": _number(row.weather_rh_mean_pct),
                    "weather_wind_mean_kmh": _number(row.weather_wind_mean_kmh),
                    "weather_wind_max_kmh": _number(row.weather_wind_max_kmh),
                    "weather_precip_sum_mm": _number(row.weather_precip_sum_mm),
                },
            )
        )

        target = _number(row.target_next_day_pm25)
        if target is not None:
            target_date = _add_days(date, 1)
            items.append(
                EvidenceItem(
                    citation_id=f"target:daily:{record_id}",
                    evidence_type=HISTORICAL_TARGET,
                    source=source,
                    text=(
                        f"Observed historical next-day PM2.5 target for {station_name} "
                        f"({station_slug}) from prediction day {date} to target date "
                        f"{target_date}: {_fmt(target)} ug/m3. This is ground-truth "
                        f"outcome data, not a forecast and not available at prediction time."
                    ),
                    station_slug=station_slug,
                    station_name=station_name,
                    date=date,
                    target_date=target_date,
                    data={
                        "record_id": record_id,
                        "pkt_date": date,
                        "target_date": target_date,
                        "target_next_day_pm25": target,
                        "is_valid_day": valid,
                        "ground_truth": True,
                        "available_at_prediction_time": False,
                    },
                )
            )
    return items


def _prediction_evidence(
    frame: pd.DataFrame,
    source: str,
    *,
    evidence_type: str,
    prediction_column: str,
    model_label: str,
    citation_prefix: str,
) -> list[EvidenceItem]:
    items: list[EvidenceItem] = []
    for row in frame.itertuples(index=False):
        record_id = str(row.record_id)
        station_slug = str(row.station_slug)
        station_name = str(row.station_name)
        prediction_date = _iso_date(row.pkt_date)
        target_date = _add_days(prediction_date, 1)
        prediction = _number(getattr(row, prediction_column))
        if prediction is None:
            continue
        items.append(
            EvidenceItem(
                citation_id=f"forecast:{citation_prefix}:{record_id}",
                evidence_type=evidence_type,
                source=source,
                text=(
                    f"{model_label} next-day PM2.5 forecast for {station_name} "
                    f"({station_slug}), issued using the completed prediction day "
                    f"{prediction_date}, for target date {target_date}: "
                    f"{_fmt(prediction)} ug/m3."
                ),
                station_slug=station_slug,
                station_name=station_name,
                date=prediction_date,
                target_date=target_date,
                data={
                    "record_id": record_id,
                    "pkt_date": prediction_date,
                    "target_date": target_date,
                    "prediction": prediction,
                    "prediction_column": prediction_column,
                    "model": model_label,
                },
            )
        )
    return items


def _metric_evidence(
    metrics: Mapping[str, Any],
    source: str,
    *,
    family: str,
    label: str,
) -> list[EvidenceItem]:
    items: list[EvidenceItem] = []
    test_metrics = metrics.get("test_metrics") or {}
    model_name = str(metrics.get("model") or label)

    for split_name, split in (metrics.get("splits") or {}).items():
        start = split.get("start_date")
        end = split.get("end_date")
        items.append(
            EvidenceItem(
                citation_id=f"metrics:{family}:split:{split_name}",
                evidence_type=EVALUATION_METRIC,
                source=source,
                text=(
                    f"{label} evaluation split '{split_name}' ({model_name}): "
                    f"{split.get('start_date')} to {split.get('end_date')}, "
                    f"{_fmt_int(split.get('sample_count'))} samples, "
                    f"{_fmt_int(split.get('unique_dates'))} unique PKT dates, "
                    f"{_fmt_int(split.get('station_count'))} stations."
                ),
                date=_iso_date(start),
                target_date=_iso_date(end),
                data={
                    "family": family,
                    "split": split_name,
                    "start_date": start,
                    "end_date": end,
                    "unique_dates": _number(split.get("unique_dates")),
                    "sample_count": _number(split.get("sample_count")),
                    "station_count": _number(split.get("station_count")),
                    "model": model_name,
                },
            )
        )

    overall = test_metrics.get("overall") or {}
    if overall:
        if family == "model" and "ml" in overall:
            ml = overall.get("ml") or {}
            persistence = overall.get("persistence") or {}
            text = (
                f"Model test metrics for {model_name}: MAE {_fmt(ml.get('mae'))} ug/m3, "
                f"RMSE {_fmt(ml.get('rmse'))} ug/m3, "
                f"{_fmt_int(overall.get('sample_count') or ml.get('sample_count'))} samples. "
                f"Persistence baseline: MAE {_fmt(persistence.get('mae'))}, "
                f"RMSE {_fmt(persistence.get('rmse'))}. "
                f"MAE improvement {_fmt(overall.get('mae_improvement_pct'))}%, "
                f"RMSE improvement {_fmt(overall.get('rmse_improvement_pct'))}%."
            )
            data = {
                "family": family,
                "scope": "overall",
                "model": model_name,
                "mae": _number(ml.get("mae")),
                "rmse": _number(ml.get("rmse")),
                "sample_count": _number(overall.get("sample_count") or ml.get("sample_count")),
                "persistence_mae": _number(persistence.get("mae")),
                "persistence_rmse": _number(persistence.get("rmse")),
                "mae_improvement_pct": _number(overall.get("mae_improvement_pct")),
                "rmse_improvement_pct": _number(overall.get("rmse_improvement_pct")),
            }
        else:
            text = (
                f"Persistence baseline test metrics: MAE {_fmt(overall.get('mae'))} ug/m3, "
                f"RMSE {_fmt(overall.get('rmse'))} ug/m3, "
                f"{_fmt_int(overall.get('sample_count'))} samples."
            )
            data = {
                "family": family,
                "scope": "overall",
                "model": model_name,
                "mae": _number(overall.get("mae")),
                "rmse": _number(overall.get("rmse")),
                "sample_count": _number(overall.get("sample_count")),
            }
        items.append(
            EvidenceItem(
                citation_id=f"metrics:{family}:overall",
                evidence_type=EVALUATION_METRIC,
                source=source,
                text=text,
                data=data,
            )
        )

    for station in test_metrics.get("by_station") or []:
        station_slug = str(station.get("station_slug"))
        station_name = str(station.get("station_name") or station_slug)
        if family == "model":
            ml = station.get("ml") or {}
            persistence = station.get("persistence") or {}
            text = (
                f"Model test metrics for {station_name} ({station_slug}) using {model_name}: "
                f"MAE {_fmt(ml.get('mae'))} ug/m3, RMSE {_fmt(ml.get('rmse'))} ug/m3, "
                f"{_fmt_int(station.get('sample_count'))} samples. "
                f"Station persistence baseline: MAE {_fmt(persistence.get('mae'))}, "
                f"RMSE {_fmt(persistence.get('rmse'))}. "
                f"MAE improvement {_fmt(station.get('mae_improvement_pct'))}%, "
                f"RMSE improvement {_fmt(station.get('rmse_improvement_pct'))}%."
            )
            data = {
                "family": family,
                "scope": "station",
                "station_slug": station_slug,
                "station_name": station_name,
                "model": model_name,
                "mae": _number(ml.get("mae")),
                "rmse": _number(ml.get("rmse")),
                "sample_count": _number(station.get("sample_count")),
                "persistence_mae": _number(persistence.get("mae")),
                "persistence_rmse": _number(persistence.get("rmse")),
                "mae_improvement_pct": _number(station.get("mae_improvement_pct")),
                "rmse_improvement_pct": _number(station.get("rmse_improvement_pct")),
            }
        else:
            text = (
                f"Persistence baseline test metrics for {station_name} ({station_slug}): "
                f"MAE {_fmt(station.get('mae'))} ug/m3, "
                f"RMSE {_fmt(station.get('rmse'))} ug/m3, "
                f"{_fmt_int(station.get('sample_count'))} samples."
            )
            data = {
                "family": family,
                "scope": "station",
                "station_slug": station_slug,
                "station_name": station_name,
                "model": model_name,
                "mae": _number(station.get("mae")),
                "rmse": _number(station.get("rmse")),
                "sample_count": _number(station.get("sample_count")),
            }
        items.append(
            EvidenceItem(
                citation_id=f"metrics:{family}:station:{station_slug}",
                evidence_type=EVALUATION_METRIC,
                source=source,
                text=text,
                station_slug=station_slug,
                station_name=station_name,
                data=data,
            )
        )
    return items


def _validity_evidence(frame: pd.DataFrame, source: str) -> list[EvidenceItem]:
    items: list[EvidenceItem] = []
    for row in frame.itertuples(index=False):
        station_slug = str(row.station_slug)
        station_name = str(row.station_name)
        text = (
            f"Station data validity for {station_name} ({station_slug}): "
            f"{_fmt_int(row.valid_pkt_days)} valid days out of "
            f"{_fmt_int(row.total_pkt_days)} total PKT days "
            f"({_fmt(row.valid_day_pct)}%). "
            f"Coverage runs from {row.first_timestamp_utc} to {row.last_timestamp_utc}; "
            f"missing {_fmt(row.pct_missing)}% of calendar hours, "
            f"{_fmt_int(row.invalid_pkt_days)} invalid PKT days, "
            f"{_fmt_int(row.agreement_mismatches)} agreement mismatches, "
            f"longest gap {_fmt(row.longest_gap_hours)} hours."
        )
        items.append(
            EvidenceItem(
                citation_id=f"validity:{station_slug}",
                evidence_type=DATA_VALIDITY,
                source=source,
                text=text,
                station_slug=station_slug,
                station_name=station_name,
                data={
                    "station_slug": station_slug,
                    "station_name": station_name,
                    "first_timestamp_utc": str(row.first_timestamp_utc),
                    "last_timestamp_utc": str(row.last_timestamp_utc),
                    "calendar_hours": _number(row.calendar_hours),
                    "real_pm25_hours": _number(row.real_pm25_hours),
                    "flagged_hours": _number(row.flagged_hours),
                    "unflagged_valid_hours": _number(row.unflagged_valid_hours),
                    "pct_missing": _number(row.pct_missing),
                    "longest_gap_hours": _number(row.longest_gap_hours),
                    "total_pkt_days": _number(row.total_pkt_days),
                    "valid_pkt_days": _number(row.valid_pkt_days),
                    "invalid_pkt_days": _number(row.invalid_pkt_days),
                    "valid_day_pct": _number(row.valid_day_pct),
                    "agreement_mismatches": _number(row.agreement_mismatches),
                },
            )
        )
    return items


def markdown_sections(
    path: Path,
    source_slug: str | None = None,
) -> list[EvidenceItem]:
    """Parse a markdown document into heading-delimited citable sections."""

    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    source = _date_from_path_source(path)
    source_slug = source_slug or DOCUMENT_SLUGS.get(path.name, _slugify(path.stem))
    headings = list(re.finditer(r"(?m)^(#{1,6})[ \t]+(.+?)[ \t]*$", text))
    if not headings:
        title = path.stem
        return [
            EvidenceItem(
                citation_id=f"doc:{source_slug}:{_slugify(title)}",
                evidence_type=DOCUMENTATION,
                source=source,
                text=text.strip(),
                data={
                    "source_slug": source_slug,
                    "section_title": title,
                    "heading_level": 0,
                },
            )
        ]

    source_title = headings[0].group(2).strip().strip("#").strip()
    items: list[EvidenceItem] = []
    slug_counts: dict[str, int] = {}

    for index, match in enumerate(headings):
        level = len(match.group(1))
        title = match.group(2).strip().strip("#").strip()
        body_start = match.end()
        body_end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        body = text[body_start:body_end].strip()
        if not body:
            continue

        base_slug = _slugify(title)
        slug_counts[base_slug] = slug_counts.get(base_slug, 0) + 1
        section_slug = base_slug
        if slug_counts[base_slug] > 1:
            section_slug = f"{base_slug}-{slug_counts[base_slug]}"

        items.append(
            EvidenceItem(
                citation_id=f"doc:{source_slug}:{section_slug}",
                evidence_type=DOCUMENTATION,
                source=source,
                text=f"{title}\n\n{body}",
                data={
                    "source_slug": source_slug,
                    "source_title": source_title,
                    "section_title": title,
                    "section_slug": section_slug,
                    "heading_level": level,
                },
            )
        )
    return items


def _build_structured_evidence(sources: EvidenceSources) -> list[EvidenceItem]:
    items: list[EvidenceItem] = []

    daily = pd.read_parquet(sources.daily)
    daily_items = _daily_evidence(daily, _relative_path(sources.daily))
    items.extend(daily_items)

    model_metrics = json.loads(sources.model_metrics.read_text(encoding="utf-8"))
    items.extend(
        _metric_evidence(
            model_metrics,
            _relative_path(sources.model_metrics),
            family="model",
            label="HistGradientBoosting model",
        )
    )

    baseline_metrics = json.loads(sources.baseline_metrics.read_text(encoding="utf-8"))
    items.extend(
        _metric_evidence(
            baseline_metrics,
            _relative_path(sources.baseline_metrics),
            family="baseline",
            label="Persistence baseline",
        )
    )

    model_predictions = pd.read_csv(sources.model_predictions, dtype={"record_id": str})
    items.extend(
        _prediction_evidence(
            model_predictions,
            _relative_path(sources.model_predictions),
            evidence_type=MODEL_FORECAST,
            prediction_column="ml_prediction",
            model_label="HistGradientBoosting model",
            citation_prefix="model",
        )
    )

    baseline_predictions = pd.read_csv(sources.baseline_predictions, dtype={"record_id": str})
    items.extend(
        _prediction_evidence(
            baseline_predictions,
            _relative_path(sources.baseline_predictions),
            evidence_type=BASELINE_FORECAST,
            prediction_column="prediction_next_day_pm25",
            model_label="Persistence baseline",
            citation_prefix="baseline",
        )
    )

    validity = pd.read_csv(sources.station_validity)
    items.extend(_validity_evidence(validity, _relative_path(sources.station_validity)))
    return items


def _build_document_evidence(sources: EvidenceSources) -> list[EvidenceItem]:
    items: list[EvidenceItem] = []
    for path in sources.documents:
        items.extend(markdown_sections(path))
    return items


def _build_external_document_evidence(sources: EvidenceSources) -> list[EvidenceItem]:
    items: list[EvidenceItem] = []
    for passage in iter_external_passages(sources.external_metadata):
        source = passage.source
        item_data = source_as_dict(source)
        item_data.update(
            {
                "page": passage.page,
                "part": passage.part,
                "document_title": source.title,
                "document_kind": "official_external_source",
            }
        )
        items.append(
            EvidenceItem(
                citation_id=f"doc:{source.id}:p{passage.page}:c{passage.part}",
                evidence_type=DOCUMENTATION,
                source=_relative_path(source.local_file),
                text=(
                    f"{source.short_title}. Published by {source.publisher} on "
                    f"{source.publication_date}. Page {passage.page}.\n\n"
                    f"{passage.text}"
                ),
                data=item_data,
            )
        )
    return items


def _latest_date(items: Iterable[EvidenceItem], field_name: str) -> str | None:
    values = [
        getattr(item, field_name)
        for item in items
        if getattr(item, field_name) is not None
    ]
    return max(values) if values else None


def build_evidence_index(
    sources: EvidenceSources | None = None,
    *,
    include_documents: bool = True,
    include_external_documents: bool = True,
) -> EvidenceIndex:
    """Build a validated, deterministic index from all approved sources."""

    sources = sources or DEFAULT_SOURCES
    structured = _build_structured_evidence(sources)
    items = list(structured)
    if include_documents:
        items.extend(_build_document_evidence(sources))
    if include_external_documents:
        items.extend(_build_external_document_evidence(sources))

    latest_observation = _latest_date(
        (
            item
            for item in structured
            if item.evidence_type == OBSERVATION
            and item.data.get("is_valid_day")
            and item.data.get("pm25_daily_mean") is not None
        ),
        "date",
    )
    latest_target = _latest_date(
        (item for item in structured if item.evidence_type == HISTORICAL_TARGET),
        "target_date",
    )
    latest_forecast = _latest_date(
        (
            item
            for item in structured
            if item.evidence_type in {BASELINE_FORECAST, MODEL_FORECAST}
        ),
        "target_date",
    )

    items.sort(key=lambda item: (item.evidence_type, item.citation_id))
    return EvidenceIndex(
        items=tuple(items),
        sources=sources,
        latest_observation_date=latest_observation,
        latest_target_date=latest_target,
        latest_forecast_date=latest_forecast,
    )
