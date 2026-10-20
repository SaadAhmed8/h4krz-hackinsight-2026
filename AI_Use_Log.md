# AI Usage Log - Team H4krz (HackInsight 2026)

This log provides an honest, transparent record of AI tool assistance utilized during the development of the Air Quality Data Warehouse and analytics pipeline.

| Date (PKT) | Tool and version | Task | What we kept or changed | Who can explain it |
| :--- | :--- | :--- | :--- | :--- |
| **2026-10-19** | Antigravity IDE (Gemini 3.8 Flash) | Built data acquisition and warehouse pipeline: OpenAQ v3/Open-Meteo fetchers, station discovery (`config/stations.yaml`), raw/cleaned/processed layers, quality log, manifest ledger, Makefile targets, unit tests, and initial `REPORT.md` (Commits: `2e693fa`, `83120e1`, `d32b481`). | **Kept:** OpenAQ v3 sensor pagination and grid reindexing. **Changed:** Enforced strict UTC bounds and added handling for faulty endpoints (`model_town_link_rd`). | M.Saad Ahmed |
| **2026-10-19** | Claude (version as shown in the app) | Drafted dataset declaration/proposal text and generated structured prompts to direct Antigravity during warehouse build. | **Kept:** Executive summary and benchmark comparison narrative. **Changed:** Refined station counts and licensing details (CC BY 4.0). | M.Saad Ahmed (TO CONFIRM BY TEAM) |
