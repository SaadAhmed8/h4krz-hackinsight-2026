---
name: codebase-design
description: Shared vocabulary and principles for designing deep modules, clean seams, and high locality.
---

# Codebase Design — Deep Modules

Shared vocabulary for designing deep modules with high leverage and strong locality.

## Principles
1. **Deep Modules**: High leverage at the interface. Substantial behavior, error recovery, and data transformations hidden behind a simple, intuitive function or class signature.
2. **Clean Seams**: Explicit boundaries where components interact, allowing independent unit testing, replacement, or orchestration (e.g. wrapping functions as Prefect tasks).
3. **Locality**: Related logic, validation rules, and schema definitions live together rather than scattered across unrelated files.
4. **The Deletion Test**: If deleting a module makes complexity reappear across multiple callers, it was earning its keep.
