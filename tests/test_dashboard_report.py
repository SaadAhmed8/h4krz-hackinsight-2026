"""Unit tests for dashboard cited air quality report generator."""

from __future__ import annotations

import pytest

from src.rag import (
    EN_ABSTENTION,
    UR_ABSTENTION,
    generate_cited_dashboard_report,
    is_out_of_scope,
    resolve_station_slug,
)


def test_recent_report_contains_citations_and_observations():
    query = "Give a report on Lahore's Air pollution in the past few hours"
    report = generate_cited_dashboard_report(query, station_choice="Model Town", language_choice="English (انگریزی)")

    assert "Model Town" in report
    assert "PM2.5" in report
    assert "[daily:" in report
    assert "[pred:" in report
    assert "[punjab-smog-plan-2023:sec4]" in report
    assert "[who-aqg-2021:sec3.2]" in report
    assert "TypeError" not in report
    assert EN_ABSTENTION not in report


def test_recent_report_urdu_translation():
    query = "Give a report on Lahore's Air pollution in the past few hours"
    report = generate_cited_dashboard_report(query, station_choice="Model Town", language_choice="Urdu (اردو ترجمہ)")

    assert "ماڈل ٹاؤن" in report
    assert "[daily:" in report
    assert "[pred:" in report
    assert "[punjab-smog-plan-2023:sec4]" in report
    assert "[who-aqg-2021:sec3.2]" in report
    assert "TypeError" not in report
    assert UR_ABSTENTION not in report


def test_out_of_scope_abstention_preserved():
    oos_queries = [
        "What is the expected wheat crop yield in Punjab this season?",
        "Who won the cricket match yesterday?",
        "What is the price of Bitcoin in Lahore?",
        "Canal road traffic update right now",
        "Forecast for Lahore in the year 2030",
    ]
    for q in oos_queries:
        assert is_out_of_scope(q) is True
        report_en = generate_cited_dashboard_report(q, language_choice="English (انگریزی)")
        assert report_en == EN_ABSTENTION

        report_ur = generate_cited_dashboard_report(q, language_choice="Urdu (اردو ترجمہ)")
        assert report_ur == UR_ABSTENTION


def test_station_resolution_from_query():
    assert resolve_station_slug("Air quality at Sandha Road today") == "sandha_road"
    assert resolve_station_slug("College Road PM2.5 status") == "college_road"
    assert resolve_station_slug("Tell me about Allama Iqbal Town") == "allama_iqbal_town"
    assert resolve_station_slug("General query", fallback_choice="HBFC Society") == "hbfc_society"


def test_error_free_execution_on_invalid_inputs():
    # Never raises TypeError or crashes
    assert isinstance(generate_cited_dashboard_report("", "Model Town"), str)
    assert isinstance(generate_cited_dashboard_report(None, "Model Town"), str)  # type: ignore[arg-type]


def test_direct_decision_answering_upfront():
    query = "Can we go out to play tomorrow in Model Town?"
    report = generate_cited_dashboard_report(query, station_choice="Model Town", language_choice="English (انگریزی)")
    # Must answer user's question upfront
    assert "Direct Decision & Recommendation: Can We Go Out to Play Tomorrow?" in report
    assert "Outdoor Play Verdict:" in report
    assert "Target Date:" in report
    # WHO distinctions
    assert "24-hour mean" in report
    assert "Annual mean reference" in report
    assert "Averaging Period Distinction:" in report
    # Model evaluation metrics
    assert "7.35% Mean Absolute Error (MAE) reduction" in report
    # Meteorology source attribution
    assert "Open-Meteo ERA5 Regional Reanalysis" in report
    # Project risk tier
    assert "Project Risk Classification" in report

