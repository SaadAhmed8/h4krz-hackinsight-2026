"""Deterministic keyword retrieval over approved HackInsight evidence.

The retriever intentionally uses lexical matching only. It ranks citable source
records and refuses requests that the historical data cannot answer safely, such
as current/live air quality or unsupported causal claims.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from enum import Enum
from functools import lru_cache
from typing import Iterable

from src.rag.evidence import (
    BASELINE_FORECAST,
    DATA_VALIDITY,
    DOCUMENTATION,
    EVALUATION_METRIC,
    HISTORICAL_TARGET,
    MODEL_FORECAST,
    OBSERVATION,
    EvidenceIndex,
    EvidenceItem,
    build_evidence_index,
)

STOPWORDS = {
    "a",
    "about",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "can",
    "could",
    "did",
    "do",
    "does",
    "for",
    "from",
    "give",
    "has",
    "have",
    "how",
    "i",
    "in",
    "is",
    "it",
    "me",
    "of",
    "on",
    "or",
    "please",
    "show",
    "tell",
    "that",
    "the",
    "their",
    "there",
    "these",
    "this",
    "to",
    "was",
    "were",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "with",
    "would",
    "you",
}

CURRENT_PATTERNS = (
    r"\btoday\b",
    r"\bcurrent(?:ly)?\b",
    r"\blive\b",
    r"\bnow\b",
    r"\breal[\s-]?time\b",
    r"\bthis\s+(?:morning|afternoon|evening|hour)\b",
    r"\btonight\b",
    r"\bat\s+the\s+moment\b",
    r"\bright\s+now\b",
)

CAUSAL_PATTERN = (
    r"\bwhy\b|"
    r"\bcaus(?:e|es|ed|ing)\b|"
    r"\breason(?:s|ed|ing)?\b|"
    r"\bdue\s+to\b|"
    r"\battribut(?:e|ed|es|ing|ion|able)\b|"
    r"\bexplain(?:s|ed|ing)?\b"
)

TARGET_PATTERN = (
    r"\btargets?\b|"
    r"\bactual(?:s|ly)?\b|"
    r"\bobserved\b|"
    r"\bground[\s-]?truth\b|"
    r"\boutcome(?:s)?\b|"
    r"\brecorded\b|"
    r"\baccuracy\b|"
    r"\berrors?\b|"
    r"\bresiduals?\b"
)

FORECAST_PATTERN = (
    r"\bforecast(?:s|ed|ing)?\b|"
    r"\bpredict(?:s|ed|ion|ions|ing)?\b|"
    r"\bnext[\s-]?day\b|"
    r"\bnext\s+day\b|"
    r"\btomorrow\b"
)

LATEST_PATTERN = (
    r"\blatest\b|"
    r"\bmost\s+recent\b|"
    r"\blast\s+(?:available|observation|forecast|record)\b"
)

CAUSAL_EVIDENCE_PATTERN = (
    r"\bcaus(?:e|es|ed|ing)\b|"
    r"\bbecause\b|"
    r"\bdue\s+to\b|"
    r"\breason(?:s|ed|ing)?\b|"
    r"\battribut(?:e|ed|es|ing|ion|able)\b|"
    r"\bcontribut(?:e|es|ed|ing|ion)\b"
)

METRIC_QUERY_PATTERN = (
    r"\bperformance\b|"
    r"\bmetrics?\b|"
    r"\bmae\b|"
    r"\brmse\b|"
    r"\berrors?\b|"
    r"\baccuracy\b|"
    r"\bimprovement\b|"
    r"\bbenchmark(?:s|ed|ing)?\b|"
    r"\bevaluat(?:e|es|ed|ion)\b"
)

VALIDITY_QUERY_PATTERN = (
    r"\bvalidity\b|"
    r"\bvalid\b|"
    r"\bcoverage\b|"
    r"\bmissing\b|"
    r"\bgaps?\b|"
    r"\bmismatch(?:es)?\b|"
    r"\bcompleteness\b|"
    r"\bunflagged\b"
)

GUIDANCE_QUERY_PATTERN = (
    r"\bwho\b|"
    r"\bworld\s+health\s+organization\b|"
    r"\bguidelines?\b|"
    r"\brecommend(?:s|ed|ation|ations)?\b|"
    r"\badvisory\b|"
    r"\bhealth[\s-]?based\b|"
    r"\bhealth\s+advice\b"
)

TYPE_ALIASES = {
    "forecast": {BASELINE_FORECAST, MODEL_FORECAST},
    "forecasts": {BASELINE_FORECAST, MODEL_FORECAST},
    "metrics": {EVALUATION_METRIC},
    "metric": {EVALUATION_METRIC},
    "evaluation": {EVALUATION_METRIC},
    "validity": {DATA_VALIDITY},
    "coverage": {DATA_VALIDITY},
    "docs": {DOCUMENTATION},
    "documentation": {DOCUMENTATION},
    "target": {HISTORICAL_TARGET},
    "targets": {HISTORICAL_TARGET},
    "observations": {OBSERVATION},
    "observation": {OBSERVATION},
}

STATION_ALIASES = {
    "allama_iqbal_town": ("allama iqbal", "allama"),
    "college_road": ("college road",),
    "forman_christian_college": ("forman", "fcc"),
    "hbfc_society": ("hbfc", "dha phase 5", "hussainy"),
    "ieee_punjab_univ": ("ieee", "punjab university"),
    "model_town": ("model town",),
    "pak_arab": ("pak arab",),
    "sandha_road": ("sandha",),
    "trinity_school": ("trinity",),
}


class RetrievalStatus(str, Enum):
    OK = "ok"
    NO_EVIDENCE = "no_evidence"
    INSUFFICIENT = "insufficient"


@dataclass(frozen=True)
class RetrievalResult:
    query: str
    status: RetrievalStatus
    items: tuple[EvidenceItem, ...] = ()
    message: str = ""
    station_slug: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    latest_observation_date: str | None = None
    latest_target_date: str | None = None
    latest_forecast_date: str | None = None

    @property
    def citations(self) -> tuple[str, ...]:
        return tuple(item.citation_id for item in self.items)

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "status": self.status.value,
            "message": self.message,
            "station_slug": self.station_slug,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "latest_observation_date": self.latest_observation_date,
            "latest_target_date": self.latest_target_date,
            "latest_forecast_date": self.latest_forecast_date,
            "items": [item.to_dict() for item in self.items],
        }


@lru_cache(maxsize=1)
def get_default_index() -> EvidenceIndex:
    return build_evidence_index()


def _normalise(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"\bpm\s*2[.,]?\s*5\b", " pm25 ", text)
    text = text.replace("&", " and ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _tokens(text: str) -> tuple[str, ...]:
    normalised = _normalise(text)
    normalised = re.sub(r"\b20\d{2}-\d{1,2}-\d{1,2}\b", " ", normalised)
    return tuple(
        token
        for token in re.findall(r"[a-z0-9]+", normalised)
        if token not in STOPWORDS
    )


def _as_date(value: str | date | datetime | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"Invalid ISO date: {value!r}") from exc


def _resolve_station(
    query: str,
    station: str | None,
    index: EvidenceIndex,
) -> str | None:
    stations = index.station_names()
    if not stations:
        return _normalise(station).replace(" ", "_") if station else None

    if station:
        candidate = _normalise(station)
        for slug, name in stations.items():
            slug_terms = {
                _normalise(slug),
                _normalise(slug).replace("_", " "),
                _normalise(name),
            }
            if candidate in slug_terms:
                return slug
        slug_candidate = candidate.replace(" ", "_")
        if slug_candidate in stations:
            return slug_candidate
        return slug_candidate

    normalised_query = _normalise(query)
    query_tokens = set(re.findall(r"[a-z0-9]+", normalised_query))
    matches: list[tuple[int, str]] = []

    for slug, name in stations.items():
        phrases = {
            _normalise(slug).replace("_", " "),
            _normalise(name),
            *(_normalise(alias) for alias in STATION_ALIASES.get(slug, ())),
        }
        for phrase in phrases:
            phrase_tokens = set(re.findall(r"[a-z0-9]+", phrase))
            if not phrase_tokens:
                continue
            phrase_in_query = re.search(
                rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])",
                normalised_query,
            )
            if phrase_tokens.issubset(query_tokens) or phrase_in_query:
                matches.append((len(phrase_tokens), slug))

    if not matches:
        return None
    matches.sort(key=lambda pair: (-pair[0], pair[1]))
    return matches[0][1]


def _query_dates(query: str) -> tuple[date | None, date | None]:
    matches = re.findall(r"\b(20\d{2}-\d{2}-\d{2})\b", query)
    if not matches:
        return None, None
    parsed = sorted({date.fromisoformat(value) for value in matches})
    if len(parsed) == 1:
        return parsed[0], parsed[0]
    return parsed[0], parsed[-1]


def _expand_types(value: str | Iterable[str] | None) -> set[str] | None:
    if value is None:
        return None
    values = [value] if isinstance(value, str) else list(value)
    expanded: set[str] = set()
    for item in values:
        key = str(item).strip().lower()
        expanded.update(TYPE_ALIASES.get(key, {key}))
    return expanded or None


def _date_matches(
    item: EvidenceItem,
    start: date | None,
    end: date | None,
    *,
    allow_undated_documents: bool = False,
) -> bool:
    if start is None and end is None:
        return True

    if item.evidence_type in {
        BASELINE_FORECAST,
        MODEL_FORECAST,
        HISTORICAL_TARGET,
    }:
        values = [item.target_date] if item.target_date else [item.date]
    elif item.evidence_type == EVALUATION_METRIC:
        values = [value for value in (item.date, item.target_date) if value]
    elif item.evidence_type == OBSERVATION:
        values = [item.date] if item.date else []
    elif item.evidence_type == DOCUMENTATION:
        return allow_undated_documents
    else:
        values = []

    for value in values:
        try:
            item_date = date.fromisoformat(value)
        except ValueError:
            continue
        if start is not None and item_date < start:
            continue
        if end is not None and item_date > end:
            continue
        return True
    return False


def _type_priority(item: EvidenceItem, forecast_intent: bool) -> int:
    if forecast_intent:
        order = {
            MODEL_FORECAST: 6,
            BASELINE_FORECAST: 6,
            OBSERVATION: 4,
            EVALUATION_METRIC: 3,
            DATA_VALIDITY: 2,
            HISTORICAL_TARGET: 1,
            DOCUMENTATION: 0,
        }
    else:
        order = {
            OBSERVATION: 6,
            HISTORICAL_TARGET: 5,
            EVALUATION_METRIC: 4,
            DATA_VALIDITY: 4,
            BASELINE_FORECAST: 3,
            MODEL_FORECAST: 3,
            DOCUMENTATION: 1,
        }
    return order.get(item.evidence_type, 0)


def _sort_date(item: EvidenceItem) -> str:
    return max(item.date or "", item.target_date or "")


def _latest_message(index: EvidenceIndex) -> str:
    observation = index.latest_observation_date or "not available"
    forecast = index.latest_forecast_date or "not available"
    return (
        "Current or live PM2.5 cannot be determined from the available historical "
        f"data. Latest available observation date: {observation}. "
        f"Latest available forecast target date: {forecast}."
    )


def _coverage_message(index: EvidenceIndex, start: date | None, end: date | None) -> str:
    observation = index.latest_observation_date or "not available"
    forecast = index.latest_forecast_date or "not available"
    requested = ""
    if start or end:
        requested = f" Requested range: {start or 'earliest'} to {end or 'latest'}."
    return (
        "The requested range is outside the available evidence."
        f"{requested} Latest available observation date: {observation}. "
        f"Latest available forecast target date: {forecast}."
    )


def _is_beyond_coverage(
    index: EvidenceIndex,
    start: date | None,
    end: date | None,
) -> bool:
    latest = index.latest_forecast_date or index.latest_observation_date
    if latest is None:
        return False
    latest_date = date.fromisoformat(latest)
    if start is not None and start > latest_date:
        return True
    if end is not None and end > latest_date:
        return True
    return False


def retrieve(
    query: str,
    *,
    station: str | None = None,
    start_date: str | date | datetime | None = None,
    end_date: str | date | datetime | None = None,
    types: str | Iterable[str] | None = None,
    limit: int = 10,
    index: EvidenceIndex | None = None,
) -> RetrievalResult:
    """Retrieve ranked, citable evidence for a query.

    Current/live questions and unsupported causal questions return
    ``insufficient`` rather than guessing. Structured historical targets are
    excluded from ordinary retrieval so a forecast answer cannot leak the
    observed outcome; they are included only when the query explicitly asks for
    actual/observed/target evidence.
    """

    if limit < 0:
        raise ValueError("limit must be non-negative")
    index = index or get_default_index()
    normalised_query = _normalise(query)
    station_slug = _resolve_station(query, station, index)
    query_start, query_end = _query_dates(query)
    if query_start is None and re.search(r"\btomorrow\b", normalised_query):
        query_start = query_end = date.today() + timedelta(days=1)
    start = _as_date(start_date) if start_date is not None else query_start
    end = _as_date(end_date) if end_date is not None else query_end
    if start is not None and end is not None and start > end:
        raise ValueError("start_date must be on or before end_date")

    base_result = dict(
        query=query,
        station_slug=station_slug,
        start_date=start.isoformat() if start else None,
        end_date=end.isoformat() if end else None,
        latest_observation_date=index.latest_observation_date,
        latest_target_date=index.latest_target_date,
        latest_forecast_date=index.latest_forecast_date,
    )

    if any(re.search(pattern, normalised_query) for pattern in CURRENT_PATTERNS):
        return RetrievalResult(
            status=RetrievalStatus.INSUFFICIENT,
            message=_latest_message(index),
            **base_result,
        )

    if _is_beyond_coverage(index, start, end):
        return RetrievalResult(
            status=RetrievalStatus.INSUFFICIENT,
            message=_coverage_message(index, start, end),
            **base_result,
        )

    causal = bool(re.search(CAUSAL_PATTERN, normalised_query))
    has_target_intent = bool(re.search(TARGET_PATTERN, normalised_query))
    has_forecast_intent = bool(re.search(FORECAST_PATTERN, normalised_query))
    latest_intent = bool(re.search(LATEST_PATTERN, normalised_query))
    metric_intent = bool(re.search(METRIC_QUERY_PATTERN, normalised_query))
    validity_intent = bool(re.search(VALIDITY_QUERY_PATTERN, normalised_query))
    guidance_intent = bool(re.search(GUIDANCE_QUERY_PATTERN, normalised_query))

    explicit_types = _expand_types(types)
    effective_types = set(explicit_types) if explicit_types is not None else set(
        type_name
        for type_name in (
            OBSERVATION,
            HISTORICAL_TARGET,
            BASELINE_FORECAST,
            MODEL_FORECAST,
            EVALUATION_METRIC,
            DATA_VALIDITY,
            DOCUMENTATION,
        )
    )
    if causal:
        effective_types = {DOCUMENTATION}

    if (
        not has_target_intent
        and (explicit_types is None or HISTORICAL_TARGET not in explicit_types)
    ):
        effective_types.discard(HISTORICAL_TARGET)

    allow_undated_documents = (
        guidance_intent
        or causal
        or (explicit_types is not None and DOCUMENTATION in explicit_types)
    )
    query_terms = _tokens(query)
    candidates: list[tuple[float, EvidenceItem]] = []

    for item in index.items:
        if item.evidence_type not in effective_types:
            continue
        if station_slug is not None:
            if item.station_slug is not None and item.station_slug != station_slug:
                continue
            if item.station_slug is None and item.evidence_type != DOCUMENTATION:
                continue
        if not _date_matches(
            item,
            start,
            end,
            allow_undated_documents=allow_undated_documents,
        ):
            continue
        if causal and not re.search(CAUSAL_EVIDENCE_PATTERN, item.text, re.IGNORECASE):
            continue
        if causal and station_slug is not None:
            station_name = index.station_names().get(station_slug, station_slug)
            causal_text = _normalise(item.text)
            station_phrases = (
                _normalise(station_name),
                _normalise(station_slug).replace("_", " "),
            )
            if not any(phrase in causal_text for phrase in station_phrases):
                continue

        haystack = _normalise(
            " ".join(
                value
                for value in (
                    item.text,
                    item.station_name or "",
                    item.station_slug or "",
                    item.evidence_type.replace("_", " "),
                )
                if value
            )
        )
        haystack_terms = set(re.findall(r"[a-z0-9]+", haystack))
        matched = sum(1 for term in query_terms if term in haystack_terms)
        if query_terms and matched == 0:
            continue
        if causal and query_terms and matched < len(query_terms):
            continue

        score = float(matched)
        if query_terms:
            phrase = " ".join(query_terms)
            if phrase in haystack:
                score += 0.5
        if has_forecast_intent and item.evidence_type in {BASELINE_FORECAST, MODEL_FORECAST}:
            score += 0.25
        if metric_intent and item.evidence_type == EVALUATION_METRIC:
            score += 1.0
            if item.data.get("scope") == "overall":
                score += 0.25
        if validity_intent and item.evidence_type == DATA_VALIDITY:
            score += 1.0
        if guidance_intent and item.evidence_type == DOCUMENTATION:
            source_type = str(item.data.get("source_type") or "")
            if "guideline" in source_type or "advisory" in source_type:
                score += 1.0
        if latest_intent:
            score += 0.1 if _sort_date(item) else 0.0
        candidates.append((score, item))

    if not candidates:
        if causal:
            message = (
                "The approved evidence does not contain documentary evidence to "
                "support a causal explanation for this query."
            )
        else:
            message = "No approved evidence matched the query and filters."
        return RetrievalResult(
            status=RetrievalStatus.INSUFFICIENT if causal else RetrievalStatus.NO_EVIDENCE,
            message=message,
            **base_result,
        )

    if latest_intent:
        candidates.sort(
            key=lambda pair: (
                _sort_date(pair[1]),
                pair[0],
                _type_priority(pair[1], has_forecast_intent),
                pair[1].citation_id,
            ),
            reverse=True,
        )
    else:
        candidates.sort(
            key=lambda pair: (
                pair[0],
                _type_priority(pair[1], has_forecast_intent),
                _sort_date(pair[1]),
                pair[1].citation_id,
            ),
            reverse=True,
        )

    selected = tuple(
        replace(item, score=score) for score, item in candidates[:limit]
    )
    return RetrievalResult(
        status=RetrievalStatus.OK,
        items=selected,
        message=f"Retrieved {len(selected)} evidence item(s) from approved sources.",
        **base_result,
    )

def retrieve_evidence(
    query: str,
    *,
    station: str | None = None,
    start_date: str | date | datetime | None = None,
    end_date: str | date | datetime | None = None,
    types: str | Iterable[str] | None = None,
    limit: int = 10,
    index: EvidenceIndex | None = None,
) -> RetrievalResult:
    """Backward-compatible name for :func:`retrieve`."""

    return retrieve(
        query,
        station=station,
        start_date=start_date,
        end_date=end_date,
        types=types,
        limit=limit,
        index=index,
    )
