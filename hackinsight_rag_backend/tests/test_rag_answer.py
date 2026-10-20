"""Tests for the cited LLM RAG answer layer.

LLM calls are injected with fakes. Tests do not use network access or credentials.
"""

from __future__ import annotations

import pytest

from src.rag import (
    ABSTENTION,
    AnswerStatus,
    GeminiLLMProvider,
    LLMConfigurationError,
    answer_question,
    build_evidence_index,
    build_llm_provider,
    extract_citation_ids,
    load_llm_config,
    retrieve_evidence,
    validate_answer_citations,
)
from src.rag.answer import _wants_who_guidance
from src.rag.external_sources import load_external_sources


@pytest.fixture(scope="module")
def index():
    return build_evidence_index()


class FakeLLM:
    provider_name = "fake"
    model_name = "fake-rag-model"

    def __init__(self, builder):
        self.builder = builder
        self.calls: list[tuple[str, str]] = []

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        self.calls.append((system_prompt, user_prompt))
        return self.builder(system_prompt, user_prompt)


def _first_id(prompt: str) -> str:
    ids = extract_citation_ids(prompt)
    if not ids:
        raise AssertionError("Prompt did not contain any evidence citation IDs")
    return ids[0]


def test_external_source_metadata_is_official_and_checksummed():
    sources = load_external_sources()
    by_id = {source.id: source for source in sources}

    who = by_id["who-aqg-2021"]
    assert "who.int" in who.url
    assert who.publisher == "World Health Organization"
    assert who.publication_date == "2021-09-22"
    assert who.pdf_sha256
    assert who.local_file.exists()

    government = [
        source for source in sources if source.source_type.startswith("government_")
    ]
    assert len(government) >= 2
    assert all("epd.punjab.gov.pk" in source.url for source in government)


def test_supported_observation_answer_is_cited(index):
    def builder(system_prompt, user_prompt):
        assert "target_next_day_pm25" in system_prompt
        assert "type=observation" in user_prompt
        citation = _first_id(user_prompt)
        return (
            "The observed PM2.5 daily mean at Model Town on 2026-10-18 was "
            f"86.28 ug/m3 [{citation}]."
        )

    fake = FakeLLM(builder)
    result = answer_question(
        "What was PM2.5 at Model Town on 2026-10-18?",
        llm=fake,
        index=index,
        limit=5,
    )

    assert result.status == AnswerStatus.OK
    assert len(fake.calls) == 1
    assert result.citations
    assert set(result.citations).issubset(
        {item.citation_id for item in result.evidence}
    )
    assert result.provider == "fake"
    assert result.model == "fake-rag-model"


def test_who_intent_does_not_match_ordinary_who_questions():
    assert not _wants_who_guidance("Who measured PM2.5 at Model Town on 2026-10-18?")
    assert _wants_who_guidance("What is the WHO annual PM2.5 guideline?")
    assert _wants_who_guidance("Compare the observation with health-based guidelines.")


def test_government_advisory_is_retrieved_and_citable(index):
    def builder(system_prompt, user_prompt):
        advisory_ids = [
            citation
            for citation in extract_citation_ids(user_prompt)
            if citation.startswith("doc:epd-punjab-general-public-advice")
        ]
        assert advisory_ids
        assert "source_type=government_public_advisory" in user_prompt
        return (
            "The official EPA Punjab public advisory includes public health "
            f"protection actions for smog conditions [{advisory_ids[0]}]."
        )

    fake = FakeLLM(builder)
    result = answer_question(
        "What does the EPA Punjab public advisory recommend for smog?",
        llm=fake,
        index=index,
        limit=8,
    )

    assert result.status == AnswerStatus.OK
    assert any(
        item.data.get("source_type") == "government_public_advisory"
        for item in result.evidence
    )
    assert any(
        citation.startswith("doc:epd-punjab-general-public-advice")
        for citation in result.citations
    )


def test_who_guidelines_are_retrieved_and_citable(index):
    retrieval = retrieve_evidence(
        "WHO PM2.5 annual mean guideline 5 and 24-hour guideline 15",
        types="documentation",
        limit=10,
        index=index,
    )
    assert retrieval.status.value == "ok"
    who_items = [
        item for item in retrieval.items if item.data.get("source_id") == "who-aqg-2021"
    ]
    assert who_items
    assert any("Table 3.26" in item.text for item in who_items)
    assert any("5" in item.text and "15" in item.text for item in who_items)

    def builder(system_prompt, user_prompt):
        who_ids = [
            citation
            for citation in extract_citation_ids(user_prompt)
            if "who-aqg-2021" in citation
        ]
        assert who_ids
        assert "annual mean" in user_prompt.lower()
        assert "24-hour" in user_prompt.lower()
        citation = who_ids[0]
        return (
            "WHO recommends an annual mean PM2.5 guideline of 5 ug/m3 and a "
            "24-hour guideline of 15 ug/m3 defined at the 99th percentile "
            f"[{citation}]. WHO guidelines are health-based recommendations, not "
            f"automatically local legal limits [{citation}]."
        )

    fake = FakeLLM(builder)
    result = answer_question(
        "What are the WHO PM2.5 guideline values for annual and 24-hour averages?",
        llm=fake,
        index=index,
        limit=10,
    )

    assert result.status == AnswerStatus.OK
    assert any("who-aqg-2021" in citation for citation in result.citations)
    assert all(citation in {item.citation_id for item in result.evidence} for citation in result.citations)
    assert "5 ug/m3" in result.answer
    assert "15 ug/m3" in result.answer


def test_who_comparison_keeps_observation_and_guideline_citations(index):
    def builder(system_prompt, user_prompt):
        ids = extract_citation_ids(user_prompt)
        observation = next(citation for citation in ids if citation.startswith("daily:"))
        guideline = next(citation for citation in ids if "who-aqg-2021" in citation)
        assert "type=observation" in user_prompt
        assert "type=documentation" in user_prompt
        return (
            f"The Model Town observation was 86.28 ug/m3 on 2026-10-18 [{observation}]. "
            "WHO's annual PM2.5 guideline is 5 ug/m3, but an annual mean is not "
            f"directly comparable with a single 24-hour observation [{guideline}]."
        )

    fake = FakeLLM(builder)
    result = answer_question(
        "Compare Model Town PM2.5 on 2026-10-18 with WHO recommendations",
        llm=fake,
        index=index,
        limit=8,
    )

    assert result.status == AnswerStatus.OK
    assert any(citation.startswith("daily:") for citation in result.citations)
    assert any("who-aqg-2021" in citation for citation in result.citations)


def test_forecast_prompt_excludes_historical_target(index):
    def builder(system_prompt, user_prompt):
        assert "target_next_day_pm25" not in user_prompt
        assert "type=historical_target" not in user_prompt
        assert "target:daily:" not in user_prompt
        assert "type=model_forecast" in user_prompt or "type=baseline_forecast" in user_prompt
        citation = _first_id(user_prompt)
        return f"The ML forecast for the target date was generated from prior-day data [{citation}]."

    fake = FakeLLM(builder)
    result = answer_question(
        "What is the next-day forecast for Model Town on 2026-10-19?",
        llm=fake,
        index=index,
        limit=6,
    )

    assert result.status == AnswerStatus.OK
    assert all(item.evidence_type != "historical_target" for item in result.evidence)
    assert all(not item.citation_id.startswith("target:daily:") for item in result.evidence)


def test_explicit_target_question_includes_ground_truth(index):
    def builder(system_prompt, user_prompt):
        assert "type=historical_target" in user_prompt
        target_ids = [
            citation
            for citation in extract_citation_ids(user_prompt)
            if citation.startswith("target:daily:")
        ]
        assert target_ids
        return (
            "The observed next-day target was ground-truth outcome data, not a "
            f"forecast [{target_ids[0]}]."
        )

    fake = FakeLLM(builder)
    result = answer_question(
        "What was the actual observed next-day target for Model Town on 2026-10-18?",
        llm=fake,
        index=index,
        limit=8,
    )

    assert result.status == AnswerStatus.OK
    assert any(item.evidence_type == "historical_target" for item in result.evidence)


def test_invalid_llm_citation_causes_abstention(index):
    fake = FakeLLM(
        lambda system_prompt, user_prompt: (
            "Model Town had dangerous air quality [invented:citation]."
        )
    )
    result = answer_question(
        "What was PM2.5 at Model Town on 2026-10-18?",
        llm=fake,
        index=index,
        limit=4,
    )

    assert result.status == AnswerStatus.INVALID_CITATIONS
    assert result.answer.startswith(ABSTENTION)
    assert "invalid citation" in result.answer
    assert "invented:citation" not in result.citations
    assert "dangerous air quality" not in result.answer


def test_uncited_factual_sentence_causes_abstention(index):
    def builder(system_prompt, user_prompt):
        citation = _first_id(user_prompt)
        return f"PM2.5 was 86.28 ug/m3 [{citation}]. This proves the air was dangerous."

    fake = FakeLLM(builder)
    result = answer_question(
        "What was PM2.5 at Model Town on 2026-10-18?",
        llm=fake,
        index=index,
        limit=4,
    )

    assert result.status == AnswerStatus.INVALID_CITATIONS
    assert "uncited" in (result.error or "")


def test_missing_evidence_abstains_without_calling_llm(index):
    fake = FakeLLM(lambda system_prompt, user_prompt: "should not be called")
    result = answer_question(
        "quantum entanglement",
        station="Model Town",
        llm=fake,
        index=index,
    )

    assert result.status == AnswerStatus.ABSTAINED
    assert result.answer.startswith(ABSTENTION)
    assert fake.calls == []
    assert result.citations == ()


def test_current_air_quality_abstains_without_calling_llm(index):
    fake = FakeLLM(lambda system_prompt, user_prompt: "should not be called")
    result = answer_question(
        "What is the current PM2.5 in Lahore?",
        llm=fake,
        index=index,
    )

    assert result.status == AnswerStatus.ABSTAINED
    assert result.answer.startswith(ABSTENTION)
    assert "2026-10-19" in result.answer
    assert fake.calls == []


def test_missing_llm_credentials_are_reported(index):
    result = answer_question(
        "What was PM2.5 at Model Town on 2026-10-18?",
        index=index,
        env={},
    )

    assert result.status == AnswerStatus.LLM_UNAVAILABLE
    assert result.answer.startswith(ABSTENTION)
    assert "credentials are unavailable" in result.answer.lower()
    assert "RAG_LLM_API_KEY" in result.answer


def test_llm_config_uses_environment_and_does_not_expose_key():
    config = load_llm_config(
        {
            "RAG_LLM_PROVIDER": "openai",
            "RAG_LLM_MODEL": "test-model",
            "RAG_LLM_API_KEY": "test-secret",
            "RAG_LLM_TIMEOUT": "12",
        }
    )
    assert config.provider == "openai"
    assert config.model == "test-model"
    assert config.api_key == "test-secret"
    assert "test-secret" not in repr(config)
    assert config.timeout == 12.0

    with pytest.raises(LLMConfigurationError):
        load_llm_config({})

    with pytest.raises(LLMConfigurationError):
        load_llm_config(
            {
                "RAG_LLM_PROVIDER": "unknown",
                "RAG_LLM_MODEL": "model",
                "RAG_LLM_API_KEY": "key",
            }
        )


def test_gemini_provider_selection_and_default_model():
    config = load_llm_config({"GEMINI_API_KEY": "test-gemini-key"})
    assert config.provider == "gemini"
    assert config.model == "gemini-3.8-flash"
    assert config.base_url == ""

    provider = build_llm_provider(config)
    assert isinstance(provider, GeminiLLMProvider)
    assert provider.provider_name == "gemini"
    assert provider.model_name == "gemini-3.8-flash"

    explicit = load_llm_config(
        {
            "RAG_LLM_PROVIDER": "gemini",
            "RAG_LLM_API_KEY": "test-rag-key",
            "RAG_LLM_MODEL": "gemini-3.8-flash",
        }
    )
    assert explicit.api_key == "test-rag-key"
    assert build_llm_provider(explicit).model_name == "gemini-3.8-flash"


def test_gemini_missing_or_placeholder_api_key_is_rejected():
    with pytest.raises(LLMConfigurationError, match="GEMINI_API_KEY"):
        load_llm_config({"RAG_LLM_PROVIDER": "gemini"})

    with pytest.raises(LLMConfigurationError, match="placeholder"):
        load_llm_config(
            {
                "RAG_LLM_PROVIDER": "gemini",
                "GEMINI_API_KEY": "your_gemini_api_key_here",
            }
        )


def test_gemini_provider_uses_official_sdk_without_network(monkeypatch):
    from google import genai

    captured = {}

    class FakeResponse:
        text = "The observation was 86.28 ug/m3 [daily:test]."

    class FakeModels:
        def generate_content(self, **kwargs):
            captured["generate_content"] = kwargs
            return FakeResponse()

    class FakeClient:
        def __init__(self, **kwargs):
            captured["client"] = kwargs
            self.models = FakeModels()

    monkeypatch.setattr(genai, "Client", FakeClient)

    config = load_llm_config(
        {
            "RAG_LLM_PROVIDER": "gemini",
            "GEMINI_API_KEY": "test-gemini-key",
            "RAG_LLM_TIMEOUT": "12",
        }
    )
    answer = build_llm_provider(config).complete("system rules", "user evidence")

    assert answer == FakeResponse.text
    assert captured["client"]["api_key"] == "test-gemini-key"
    assert captured["client"]["http_options"].timeout == 12000
    call = captured["generate_content"]
    assert call["model"] == "gemini-3.8-flash"
    assert call["contents"] == "user evidence"
    assert call["config"].system_instruction == "system rules"
    assert call["config"].max_output_tokens == 700
    assert call["config"].temperature == 0.0
    assert call["config"].thinking_config.thinking_level.value == "LOW"


def test_comma_separated_citations_are_parsed_individually():
    assert extract_citation_ids(
        "Values are 5 and 15 [doc:who-aqg-2021:p160:c1, doc:who-aqg-2021:p19:c1]."
    ) == ("doc:who-aqg-2021:p160:c1", "doc:who-aqg-2021:p19:c1")


def test_citation_validation_rejects_unknown_and_uncited_claims(index):
    retrieval = retrieve_evidence(
        "PM2.5 Model Town 2026-10-18", types="observation", index=index, limit=1
    )
    evidence = retrieval.items
    valid_id = evidence[0].citation_id

    good = validate_answer_citations(
        f"PM2.5 was 86.28 ug/m3 [{valid_id}].", evidence
    )
    assert good.valid

    bad = validate_answer_citations(
        f"PM2.5 was 86.28 ug/m3 [{valid_id}]. The cause was traffic.", evidence
    )
    assert not bad.valid
    assert bad.uncited_sentences

    unknown = validate_answer_citations(
        f"PM2.5 was 86.28 ug/m3 [made:up].", evidence
    )
    assert not unknown.valid
    assert unknown.invalid_citations == ("made:up",)


def test_retrieve_evidence_alias_is_compatible(index):
    result = retrieve_evidence(
        "PM2.5 at College Road on 2026-10-05",
        index=index,
        limit=3,
    )
    assert result.status.value == "ok"
    assert result.station_slug == "college_road"
    assert result.items
