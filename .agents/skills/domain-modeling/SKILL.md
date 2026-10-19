---
name: domain-modeling
description: Build and sharpen a project's domain model. Use when discussing codebase terminology, schema definitions, writing GLOSSARY.md, or recording an ADR.
---

# Domain Modeling

Actively build and sharpen the project's domain model as you design.
Challenge terms, model edge-case scenarios, and record schemas, ubiquitous language, and decisions down the moment they crystallise.

## File structure
```
/
├── GLOSSARY.md
├── docs/
│   └── adr/
│       ├── 0001-architecture-decision.md
└── src/
```

## Principles
1. Ubiquitous Language: Ensure consistent nomenclature across code, schemas, and documentation.
2. Deterministic Identifiers: Primary keys across tables and layers must be stable, collision-free, and reproducible across runs.
3. Explicit Bounded Contexts: Clear separation between Raw (ingestion), Cleaned (standardized/validated), and Processed (feature-engineered/model-ready).
