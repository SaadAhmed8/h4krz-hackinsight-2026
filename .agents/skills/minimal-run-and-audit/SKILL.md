---
name: minimal-run-and-audit
description: Trusted-lane execution, verification, and audit of reproduction pipelines and outputs.
---

# Minimal Run and Audit

Systematic verification of pipeline execution, integrity auditing, and artifact evidence collection.

## Workflow
1. Execute the minimal command sequence from a clean state (e.g., `make data` or `python -m src.pipeline`).
2. Verify all exit codes, log outputs, and exception traces.
3. Validate output integrity:
   - File presence across all layers (`data/raw/`, `data/cleaned/`, `data/processed/`, `manifest.csv`, `data/cleaned/quality_log.csv`).
   - Checksum validation (SHA-256 integrity checks).
   - Time range completeness, UTC timestamp consistency, and absence of data leakage.
4. Record audit evidence and summary reports.
