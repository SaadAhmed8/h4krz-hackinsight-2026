# AI_Use_Log.md

Disclosure of material AI-assistant use (HackInsight 2026 Participant Guide, ch.12).
Each team member should append their own entries.

| Date (PKT) | Tool and version | Task | What we kept or changed | Who can explain it |
|---|---|---|---|---|
| 2026-10-20 | Antigravity IDE agent (Claude Opus) | Compliance audit of repo against Participant Guide; fixes: removed synthetic mock fallback (`src/mock_data.py`), labelled unfinished `predict_task`, pointed Prefect flow at `data/processed/hourly_all.parquet`, added `query` column to `manifest.csv`, cross-platform raw path in integrity check, DQ summary step in `make data`, missing deps in `requirements.txt`, un-ignored `data/raw/` | _Team to review diff of this commit and confirm_ | _Team to fill in_ |
