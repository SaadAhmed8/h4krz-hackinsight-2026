# Dataset Declaration: Lahore Air Quality Forecasting

**HackInsight 2026 | Data-to-Decision | Air Quality Track**  
**Team:** H4krz  
**Members:** M. Saad Ahmed, Arbish, Hasan Shahir, Noman Khursheed  
**Date:** Mon 19 Oct 2026, 12:00 PM PKT  

---

## 1. Problem Statement & Primary Decision
- **Problem:** Severe seasonal smog ($\text{PM}_{2.5}$) in Lahore, peaking from October through February. Overnight and early-morning $\text{PM}_{2.5}$ frequently spikes above $250\ \mu\text{g/m}^3$, yet schools and outdoor workers receive little warning.
- **Primary User & Decision:** A school administrator in Lahore deciding the afternoon prior whether to cancel or move morning outdoor activities/assemblies to protect children's health.
- **Target Variable:** Next-day mean $\text{PM}_{2.5}$ ($\mu\text{g/m}^3$) per station.
- **Time Rule:** Day runs midnight-to-midnight in Pakistan Standard Time (PKT, UTC+5). All timestamps stored in UTC and converted to PKT for aggregation.
- **Valid Day Definition (18/24 Rule):** A day counts as valid if and only if at least 18 of its 24 hourly readings are present.

---

## 2. Independent Data Sources

### Source 1: OpenAQ v3 API (Air Quality Sensors in Lahore)
- **Publisher:** OpenAQ (aggregating AirGradient and Hawanama sensor data)
- **URL:** [https://openaq.org](https://openaq.org) (API: `https://api.openaq.org/v3`)
- **Data Providers:** 
  - AirGradient (station owner: The Urban Unit, Government of Punjab)
  - Hawanama (station owner: Pakistan Air Quality Initiative, PAQI)
- **Licence:** Creative Commons Attribution 4.0 International (CC BY 4.0)
- **Update Frequency:** Hourly
- **Parameters Measured:** $\text{PM}_{2.5}$ ($\mu\text{g/m}^3$), $\text{PM}_{1}$, relative humidity, temperature, and particle count $\text{PM}_{0.3}$.

### Source 2: Open-Meteo Historical Weather API (ERA5 Reanalysis & Forecast)
- **Publisher:** Open-Meteo
- **URL:** [https://open-meteo.com](https://open-meteo.com)
- **Licence:** Creative Commons Attribution 4.0 International (CC BY 4.0)
- **Update Frequency:** Hourly
- **Variables:** `temperature_2m`, `relative_humidity_2m`, `wind_speed_10m`, `precipitation`
- **Why Credible & Independent:** Open-Meteo is an independent non-track meteorological data platform built on ECMWF ERA5 reanalysis and global weather agency numerical models, completely independent of ground sensor networks.

---

## 3. Data Volume & Completeness
- **Volume:** Over 86,000+ hourly rows and 2,600+ valid station-days across 8 verified Lahore stations, exceeding the hackathon's 50,000-row minimum.
- **Manifest:** All raw and processed files are checksummed with SHA-256 in [manifest.csv](manifest.csv).
- **Licensing Contract:** Station `ieee_punjab_univ` is strictly excluded from cleaned/processed layers due to unverified licensing.

---

## 4. Declared Baseline & Success Metric (Fixed in Advance)
- **Baseline:** Persistence baseline ($\hat{y}_{t+1} = y_t$, tomorrow's mean $\text{PM}_{2.5}$ equals today's mean $\text{PM}_{2.5}$ at the same station).
- **Success Measure:** Machine learning model (Histogram Gradient Boosting Regressor) must achieve at least a **15% MAE reduction** over the persistence baseline on the chronological held-out test split.
- **Achieved Result:** Baseline MAE = $13.593\ \mu\text{g/m}^3$, Model MAE = $11.139\ \mu\text{g/m}^3$ (**18.05% improvement**).
