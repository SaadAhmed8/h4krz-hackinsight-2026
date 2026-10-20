"""Tests for deterministic, citation-backed RAG evidence retrieval."""

from __future__ import annotations

import pytest

from src.rag import build_evidence_index, retrieve
from src.rag.evidence import (
    BASELINE_FORECAST,
    DATA_VALIDITY,
    DOCUMENTATION,
    EVALUATION_METRIC,
    HISTORICAL_TARGET,
    MODEL_FORECAST,
    OBSERVATION,
)
from src.rag.retrieval import RetrievalStatus


@pytest.fixture(scope="module")
def index():
    return build_evidence_index()


def test_index_contains_approved_sources_and_latest_dates(index):
    assert len(index) > 7000
    assert index.latest_observation_date == "2026-10-19"
    assert index.latest_target_date == "2026-10-19"
    assert index.latest_forecast_date == "2026-10-19"

    observation = index.get("daily:15600ddfc49b85a1")
    assert observation is not None
    assert observation.evidence_type == OBSERVATION
    assert observation.source == "data/processed/daily.parquet"
    assert observation.station_slug == "allama_iqbal_town"
    assert observation.date == "2025-11-19"
    assert "228.16" in observation.text

    validity = index.get("validity:college_road")
    assert validity is not None
    assert validity.evidence_type == DATA_VALIDITY
    assert validity.source == "reports/station_validity.csv"

    metric = index.get("metrics:model:overall")
    assert metric is not None
    assert metric.evidence_type == EVALUATION_METRIC
    assert metric.data["mae"] == pytest.approx(12.58613650645029)
    assert metric.data["rmse"] == pytest.approx(16.442383812867195)

    forecast = index.get("forecast:model:17f0909a2374e254")
    assert forecast is not None
    assert forecast.evidence_type == MODEL_FORECAST
    assert forecast.date == "2026-08-04"
    assert forecast.target_date == "2026-08-05"
    assert "target_next_day_pm25" not in forecast.data


def test_document_sections_have_stable_citations(index):
    docs = index.by_type(DOCUMENTATION)
    assert docs
    assert any(item.citation_id.startswith("doc:report:") for item in docs)
    assert any(item.citation_id.startswith("doc:glossary:") for item in docs)
    assert any(item.citation_id.startswith("doc:adr-0001:") for item in docs)

    result = retrieve("processed layer data", types="docs", index=index)
    assert result.status == RetrievalStatus.OK
    assert result.items
    assert all(item.evidence_type == DOCUMENTATION for item in result.items)
    for item in result.items:
        assert item.source.endswith(".md")
        assert item.citation_id.startswith("doc:")


def test_observation_query_filters_station_and_date(index):
    result = retrieve(
        "What was the PM2.5 on 2026-10-18?",
        station="Model Town",
        types="observation",
        index=index,
    )

    assert result.status == RetrievalStatus.OK
    assert result.station_slug == "model_town"
    assert result.items
    assert all(item.evidence_type == OBSERVATION for item in result.items)
    assert all(item.station_slug == "model_town" for item in result.items)
    assert all(item.date == "2026-10-18" for item in result.items)
    assert result.items[0].citation_id.startswith("daily:")


def test_forecast_query_excludes_historical_target_evidence(index):
    result = retrieve(
        "Forecast for Model Town on 2026-10-19",
        index=index,
    )

    assert result.status == RetrievalStatus.OK
    assert result.station_slug == "model_town"
    assert result.items
    assert all(item.evidence_type != HISTORICAL_TARGET for item in result.items)
    assert {item.evidence_type for item in result.items} & {
        MODEL_FORECAST,
        BASELINE_FORECAST,
    }
    assert all(
        item.target_date == "2026-10-19"
        for item in result.items
        if item.evidence_type in {MODEL_FORECAST, BASELINE_FORECAST}
    )


def test_explicit_target_query_includes_historical_target(index):
    result = retrieve(
        "What was the observed PM2.5 target for Model Town on 2026-10-18?",
        index=index,
    )

    assert result.status == RetrievalStatus.OK
    assert any(item.evidence_type == HISTORICAL_TARGET for item in result.items)
    targets = [
        item for item in result.items if item.evidence_type == HISTORICAL_TARGET
    ]
    assert targets
    assert all(item.station_slug == "model_town" for item in targets)
    assert all(item.target_date == "2026-10-18" for item in targets)
    assert all(item.data["ground_truth"] is True for item in targets)


def test_current_or_live_query_is_insufficient(index):
    for query in ("What is the current PM2.5?", "Show live air quality now."):
        result = retrieve(query, index=index)
        assert result.status == RetrievalStatus.INSUFFICIENT
        assert result.items == ()
        assert result.latest_observation_date == "2026-10-19"
        assert result.latest_forecast_date == "2026-10-19"
        assert "2026-10-19" in result.message
        assert "cannot be determined" in result.message


def test_causal_query_without_documentary_evidence_is_insufficient(index):
    result = retrieve("Why was PM2.5 high in Model Town?", index=index)

    assert result.status == RetrievalStatus.INSUFFICIENT
    assert result.items == ()
    assert "causal explanation" in result.message


def test_no_matching_evidence_returns_no_evidence(index):
    result = retrieve("quantum entanglement", station="Model Town", index=index)

    assert result.status == RetrievalStatus.NO_EVIDENCE
    assert result.items == ()
    assert "No approved evidence" in result.message


def test_station_and_date_range_filters(index):
    result = retrieve(
        "PM2.5",
        station="college_road",
        start_date="2026-10-01",
        end_date="2026-10-03",
        types="observation",
        index=index,
    )

    assert result.status == RetrievalStatus.OK
    assert result.items
    assert all(item.station_slug == "college_road" for item in result.items)
    assert all(
        "2026-10-01" <= item.date <= "2026-10-03" for item in result.items
    )


def test_query_date_is_parsed_and_applied(index):
    result = retrieve("PM2.5 at College Road on 2026-10-05", index=index)

    assert result.status == RetrievalStatus.OK
    assert result.station_slug == "college_road"
    assert result.start_date == "2026-10-05"
    assert result.end_date == "2026-10-05"
    assert result.items
    assert all(item.evidence_type != HISTORICAL_TARGET for item in result.items)


def test_dates_beyond_latest_available_are_insufficient(index):
    result = retrieve("Forecast for 2026-10-25", index=index)

    assert result.status == RetrievalStatus.INSUFFICIENT
    assert result.items == ()
    assert "outside the available evidence" in result.message
    assert "2026-10-19" in result.message


def test_metrics_and_validity_intents_rank_the_right_evidence(index):
    metrics = retrieve("model performance overall", index=index)
    assert metrics.status == RetrievalStatus.OK
    assert metrics.items[0].evidence_type == EVALUATION_METRIC
    assert metrics.items[0].citation_id == "metrics:model:overall"

    validity = retrieve("station validity College Road", index=index)
    assert validity.status == RetrievalStatus.OK
    assert validity.items[0].evidence_type == DATA_VALIDITY
    assert validity.items[0].citation_id == "validity:college_road"


def test_retrieval_is_deterministic_and_respects_limit(index):
    first = retrieve("PM2.5 Model Town", limit=4, index=index)
    second = retrieve("PM2.5 Model Town", limit=4, index=index)

    assert first.status == RetrievalStatus.OK
    assert len(first.items) == 4
    assert first.citations == second.citations
    assert [item.score for item in first.items] == [
        item.score for item in second.items
    ]
    assert len(set(first.citations)) == len(first.citations)


def test_invalid_date_filter_is_rejected(index):
    with pytest.raises(ValueError, match="Invalid ISO date"):
        retrieve("PM2.5", start_date="not-a-date", index=index)

    with pytest.raises(ValueError, match="start_date"):
        retrieve(
            "PM2.5",
            start_date="2026-10-10",
            end_date="2026-10-01",
            index=index,
        )
