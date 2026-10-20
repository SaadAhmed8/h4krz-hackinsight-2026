# HackInsight RAG Backend

A self-contained, cited retrieval-augmented-generation backend for Lahore PM2.5
observations, model forecasts, evaluation reports, WHO guidance, and EPA Punjab
advisories. It can be imported by a separate dashboard without changing this
repository's pipeline.

The backend has two layers:

- **Deterministic retrieval** uses local files only. It needs no API key.
- **Cited answer generation** calls a configured LLM. It is optional; retrieval and
  tests work without credentials.

## Package Layout

```text
hackinsight_rag_backend/
├── src/rag/
│   ├── __init__.py            # Public API
│   ├── answer.py              # LLM providers, prompts, citations, abstention
│   ├── evidence.py            # Evidence index and source loading
│   ├── external_sources.py    # WHO/EPA metadata and page text cache
│   └── retrieval.py           # Deterministic ranking, filters, date handling
├── tests/
│   ├── conftest.py            # Prevents tests from mutating data/reports
│   ├── test_rag_answer.py
│   └── test_rag_evidence.py
├── data/
│   ├── processed/             # daily observations and forecast predictions
│   └── external/              # official source metadata, PDFs, extracted text
├── reports/                   # metrics and station validity evidence
├── docs/adr/                  # architecture decision record evidence
├── REPORT.md
├── GLOSSARY.md
├── .env.example
├── requirements.txt
└── pytest.ini
```

The PDFs are retained because the external-source loader validates both the PDF
and extracted text cache. Retrieval itself reads the `.txt` caches and does not
parse PDFs.

## Setup

Requires Python 3.11 or newer.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

On Linux/macOS:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and set a provider and credential. Never commit the resulting `.env`.

### Gemini

```env
RAG_LLM_PROVIDER=gemini
GEMINI_API_KEY=your_key_here
RAG_LLM_MODEL=gemini-3.8-flash
RAG_LLM_TIMEOUT=300
```

### OpenAI

```env
RAG_LLM_PROVIDER=openai
OPENAI_API_KEY=your_key_here
RAG_LLM_MODEL=gpt-4o-mini
```

### Anthropic

```env
RAG_LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=your_key_here
RAG_LLM_MODEL=claude-3-5-haiku-latest
```

### OpenAI-compatible endpoint

```env
RAG_LLM_PROVIDER=openai_compatible
RAG_LLM_API_KEY=your_key_here
RAG_LLM_MODEL=your_model
RAG_LLM_BASE_URL=https://your-provider.example/v1
```

`RAG_LLM_API_KEY` takes precedence. If it is empty, the provider-specific key above
is used. `RAG_LLM_TIMEOUT`, `RAG_LLM_MAX_TOKENS`, and
`RAG_LLM_TEMPERATURE` are optional numeric controls.

## Calling `answer_question()`

Run Python from the package root, or put this package root on `PYTHONPATH`, so
`import src.rag` resolves correctly.

```python
from src.rag import answer_question

result = answer_question(
    "What was the observed PM2.5 at Model Town, Lahore on 2026-10-18?"
)

print(result.status.value)
print(result.answer)
print(result.citations)
```

`answer_question` loads `.env` from the current working directory by default. If
the dashboard already loaded environment variables, they are used as-is. You may
also pass an explicit environment mapping:

```python
result = answer_question(question, env=my_environment_mapping)
```

Build the index once and reuse it to avoid reparsing source files per question:

```python
from src.rag import answer_question, build_evidence_index

index = build_evidence_index()
result = answer_question(question, index=index)
```

Useful optional arguments include `station`, `start_date`, `end_date`, `limit`,
`index`, `llm`, and `config`. `llm` accepts any object implementing the
`LLMProvider` protocol, which is useful for dependency injection and testing.

## Response Format

`answer_question()` returns a `RAGAnswer`:

| Field | Meaning |
| :--- | :--- |
| `question` | Original question |
| `status` | `ok`, `abstained`, `llm_unavailable`, `invalid_citations`, or `llm_error` |
| `answer` | Generated answer, or an explicit safe abstention |
| `citations` | Unique citation IDs used in the answer |
| `evidence` | Retrieved `EvidenceItem` objects |
| `retrieval` | Retrieval metadata and status |
| `provider` | Selected provider, if an LLM was configured |
| `model` | Selected model, if an LLM was configured |
| `error` | Error category or validation problem, if any |

`result.to_dict()` returns a JSON-serializable dictionary suitable for a dashboard
API response.

### Citation Format

Every factual sentence in a successful answer must include at least one citation
in square brackets. Citation IDs are stable strings:

- Observation: `daily:ed338fb8d0685ea5`
- Historical target: `target:daily:44cc2efcd86f3467`
- Model forecast: `forecast:model:44cc2efcd86f3467`
- Persistence forecast: `forecast:baseline:44cc2efcd86f3467`
- WHO/EPA document: `doc:who-aqg-2021:p160:c1`
- Report/glossary/ADR: `doc:report:...`, `doc:glossary:...`, `doc:adr-0001:...`

Example answer:

```text
The observed daily mean PM2.5 at Model Town on 2026-10-18 was 86.28 µg/m³
[daily:ed338fb8d0685ea5].
```

If citations are missing, invented, or not present in the retrieved evidence, the
backend discards the model output and returns an abstention with status
`invalid_citations`. If retrieval finds no sufficient evidence, it abstains without
calling the LLM.

## Path Configuration

`src/rag/evidence.py` and `src/rag/external_sources.py` resolve defaults relative to
the package root, calculated from `src/rag/*.py`. Preserve this layout when
copying the package:

```text
<project-root>/src/rag/
<project-root>/data/processed/...
<project-root>/data/external/...
<project-root>/reports/...
<project-root>/docs/adr/...
<project-root>/REPORT.md
<project-root>/GLOSSARY.md
```

If your dashboard uses different locations, pass custom `EvidenceSources` instead
of moving files:

```python
from pathlib import Path
from src.rag import EvidenceSources, answer_question, build_evidence_index

root = Path("/path/to/rag-assets")
sources = EvidenceSources(
    daily=root / "data/processed/daily.parquet",
    model_metrics=root / "reports/pm25_hist_gradient_boosting_metrics.json",
    baseline_metrics=root / "reports/persistence_baseline_metrics.json",
    model_predictions=root / "data/processed/pm25_hist_gradient_boosting_test_predictions.csv",
    baseline_predictions=root / "data/processed/persistence_baseline_test_predictions.csv",
    station_validity=root / "reports/station_validity.csv",
    external_metadata=root / "data/external/rag_sources.json",
    documents=(
        root / "REPORT.md",
        root / "GLOSSARY.md",
        root / "docs/adr/0001-warehouse-architecture-and-keys.md",
    ),
)
index = build_evidence_index(sources)
result = answer_question(question, index=index)
```

External metadata stores `local_file` and `text_file` paths relative to the RAG
package root. If you relocate `data/external`, update those fields in
`rag_sources.json`; absolute paths also work.

## Running Tests

From the package root:

```powershell
python -m pytest -p no:cacheprovider tests/test_rag_evidence.py tests/test_rag_answer.py -q
```

Or run the packaged test directory:

```powershell
python -m pytest -p no:cacheprovider tests/ -q
```

The tests use local data and mocked/fake LLMs. They do not require network access
or live API credentials.

## Data and Safety Notes

- The data is historical; current/live air-quality questions abstain rather than
  claiming real-time conditions.
- `target_next_day_pm25` is observed ground-truth outcome data and is never treated
  as a forecast or prediction-time input.
- WHO guidelines are health-based recommendations, not automatically local legal
  limits.
- The package excludes `.env`, API keys, unrelated pipeline outputs, raw source
  JSON, cleaned layers, and model binaries.
