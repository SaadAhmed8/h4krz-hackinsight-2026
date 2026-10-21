"""Deterministic evidence retrieval and cited answer generation."""

from src.rag.evidence import (
    DEFAULT_SOURCES,
    EvidenceIndex,
    EvidenceItem,
    EvidenceSources,
    build_evidence_index,
)
from src.rag.retrieval import (
    RetrievalResult,
    RetrievalStatus,
    get_default_index,
    retrieve,
    retrieve_evidence,
)
from src.rag.answer import (
    ABSTENTION,
    AnswerStatus,
    CitationValidation,
    GeminiLLMProvider,
    LLMConfig,
    LLMConfigurationError,
    LLMProvider,
    LLMProviderError,
    RAGAnswer,
    answer_question,
    build_llm_provider,
    build_user_prompt,
    extract_citation_ids,
    load_llm_config,
    validate_answer_citations,
)

from src.rag.dashboard_report import (
    EN_ABSTENTION,
    UR_ABSTENTION,
    evaluate_epa_punjab_tier,
    generate_cited_dashboard_report,
    is_out_of_scope,
    resolve_station_slug,
)

__all__ = [
    "ABSTENTION",
    "AnswerStatus",
    "CitationValidation",
    "DEFAULT_SOURCES",
    "EN_ABSTENTION",
    "EvidenceIndex",
    "EvidenceItem",
    "EvidenceSources",
    "GeminiLLMProvider",
    "LLMConfig",
    "LLMConfigurationError",
    "LLMProvider",
    "LLMProviderError",
    "RAGAnswer",
    "RetrievalResult",
    "RetrievalStatus",
    "UR_ABSTENTION",
    "answer_question",
    "build_evidence_index",
    "build_llm_provider",
    "build_user_prompt",
    "evaluate_epa_punjab_tier",
    "extract_citation_ids",
    "generate_cited_dashboard_report",
    "get_default_index",
    "is_out_of_scope",
    "load_llm_config",
    "resolve_station_slug",
    "retrieve",
    "retrieve_evidence",
    "validate_answer_citations",
]

