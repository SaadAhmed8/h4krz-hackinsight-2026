# Dataset Declaration

**HackInsight 2026 | Data-to-Decision**

| | |
|---|---|
| **Team name** | H4krz |
| **Members** | M.Saad Ahmed, Arbish, Hasan Shahir, Noman Khursheed |
| **Track** | Air quality |

## Problem

Smog (PM2.5) in Lahore, worst between October and February. Overnight and early-morning PM2.5 can reach very high levels (a tested sensor rose from about 43 to about 240 ug/m3 within 12 hours), but schools get little warning.

## Primary user and decision

A school administrator in Lahore decides the day before whether to cancel or move outdoor activities.

## Target and definitions

- **Target:** Next-day mean PM2.5 (ug/m3) per station.
- **Day definition:** A day runs midnight to midnight in PKT (UTC+5). All data is stored in UTC and converted to PKT only to define days and for display.
- **Daily mean rule:** A day counts only if at least 18 of its 24 hourly values exist.

---

## Source 1: OpenAQ (PM2.5 from Lahore sensors)

- **Publisher:** OpenAQ, aggregating data from the providers below
- **URL:** https://openaq.org (API: https://api.openaq.org/v3)
- **Data providers:** AirGradient (station owner: The Urban Unit) and Hawanama (station owner: Pakistan Air Quality Initiative, PAQI)
- **Licence:** CC BY 4.0 (confirmed on the station pages of 8 stations)
- **Update frequency:** Hourly (all tested stations had updated within the last 2 hours)
- **Measured:** PM2.5 (ug/m3) at all stations. AirGradient stations also report PM1, relative humidity, temperature and PM0.3 particle count.
- **Access:** Through the OpenAQ API with a personal API key, which is stored outside the repository.

### Stations (8)

| # | Station | Provider | Reporting since |
|---|---|---|---|
| 1 | HBFC Society, DHA Phase 5 | AirGradient | 26/05/2025 |
| 2 | Sandha Road | AirGradient | 29/05/2025 |
| 3 | Model Town | AirGradient | 30/05/2025 |
| 4 | College Road | AirGradient | 02/06/2025 |
| 5 | Pak Arab | AirGradient | 19/09/2025 |
| 6 | IEEE, Punjab Univers | AirGradient | 30/05/2025 |
| 7 | Allama Iqbal Town B LHE | Hawanama | 18/11/2025 |
| 8 | Model Town Link Rd B | Hawanama | 23/04/2026 |

---

## Source 2: Open-Meteo Historical Weather API (ERA5 reanalysis)

- **Publisher:** Open-Meteo
- **URL:** https://open-meteo.com (endpoint: archive-api.open-meteo.com)
- **Licence:** CC BY 4.0. Attribution: "Weather data by Open-Meteo.com". The free tier is for non-commercial use, which applies to this event.
- **Update frequency:** Hourly
- **Variables:** temperature_2m, relative_humidity_2m, wind_speed_10m, precipitation (further variables may be added)
- **Tested:** 1 to 7 Oct 2026 for Lahore, 168 hourly rows, no gaps seen, timestamps in UTC.
- **Note:** Gridded model data, not a ground station. Requests are snapped to the nearest grid cell.

---

## Non-track source and why it is credible

Open-Meteo is not on the Air quality track list. It is built on reanalysis and national weather agency data, publishes its methods and its licence openly, and is independent of OpenAQ (a gridded weather model versus ground-level sensors).

---

## Expected volume

8 stations reporting since between May 2025 and April 2026: at most about 82,700 hourly PM2.5 rows. This is close to the 50,000-row minimum once sensor gaps are removed (about 49,600 at 60% completeness, about 57,900 at 70%). To keep a safe margin we will add further Lahore stations from OpenAQ (checked for CC BY 4.0 and listed in manifest.csv). Real counts will be verified after fetching and reported in the quality log.

---

## Why this data fits

Station data covers several areas of Lahore, so we can report errors by station and area. PM2.5 is strongly affected by weather (temperature, wind, humidity, rain), so the weather series gives the model real predictive signal. Both sources update hourly, which fits the hourly pipeline.

---

## Limits and risks

- Most stations are low-cost sensors, which are noisier than reference monitors.
- Only one full winter smog season (2025-26) is available, so the time-based split needs care.
- Five of the eight stations share one owner, so one feed stopping could remove many stations.
- Hawanama stations report PM2.5 only, with no humidity or temperature columns.
- Weather data is modelled on a grid, not measured at the stations.
- Outputs are information, not professional advice.

---

## Baseline (fixed, will not change)

- **Baseline:** Tomorrow's mean PM2.5 = today's mean PM2.5 at the same station.
- **Success measure:** Model MAE at least 15% lower than baseline MAE on a later-dated test set.
