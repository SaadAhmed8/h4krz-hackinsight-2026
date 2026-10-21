# Viva Defense Guide & 3-Minute Demo Video Script

**HackInsight 2026: Data-to-Decision Challenge**  
**Track:** Air Quality  
**Team:** H4krz  
**Members:** M. Saad Ahmed, Arbish, Hasan Shahir, Noman Khursheed  

---

## Part 1: 10 Practice Viva Questions (1-Sentence Spoken Answers)

As instructed by Chapter 11 of the Participant Guide, memorize and rehearse these crisp 1-sentence answers for the jury:

1. **Why did you choose this problem, and who is the user?**  
   > *"We chose Lahore’s winter smog crisis because hazardous overnight $\text{PM}_{2.5}$ spikes threaten schoolchildren, and our primary user is a school administrator who must decide by 4:00 PM whether to cancel morning outdoor assemblies and sports the next day."*

2. **How do you know the problem is real in Pakistan? What evidence did you use?**  
   > *"Official EPA Punjab Smog Action Plan notifications and verified Lahore air quality sensors document frequent winter $\text{PM}_{2.5}$ surges exceeding $250\ \mu\text{g/m}^3$, which force emergency school closures every November and December across Lahore district."*

3. **Why these sources? What licence applies and who is the original publisher?**  
   > *"We selected OpenAQ v3 ground sensors (published by The Urban Unit and PAQI) and Open-Meteo ERA5 reanalysis weather data, both published under open Creative Commons Attribution 4.0 International (CC BY 4.0) licenses."*

4. **What was the worst problem in your raw data and how did you handle it?**  
   > *"The most critical challenges were irregular sensor reporting timestamps and an upstream HTTP 500 failure from the Model Town Link Road sensor; we resolved this by reindexing onto a strict 1-hour regular UTC grid, gracefully bypassing the offline sensor without inventing data, and logging all gaps in `quality_log.csv`."*

5. **Why did the Data Quality Agent flag instead of fill in one case?**  
   > *"When sensor gaps exceeded 3 consecutive hours or when the IEEE Punjab University station lacked verifiable ownership licensing, the DQ Agent strictly flagged the data rather than guessing values or contaminating the warehouse."*

6. **What is your baseline, and by how much does your model beat it?**  
   > *"Our declared baseline is tomorrow equals today persistence ($\text{MAE} = 13.593\ \mu\text{g/m}^3$), and our Histogram Gradient Boosting Regressor beats it by **18.05%** ($\text{MAE} = 11.139\ \mu\text{g/m}^3$) on a strictly chronological, untouched test split."*

7. **Where does your model perform worst, and who might be affected?**  
   > *"Our model exhibits its highest absolute error during the peak winter smog season ($\text{MAE} = 12.13\ \mu\text{g/m}^3$) and at Trinity School due to sparse historical samples; to protect vulnerable children, we communicate wide 80% prediction intervals so administrators err on the side of safety."*

8. **How do you make sure the Insight Agent never invents a number?**  
   > *"The RAG architecture programmatically injects numerical facts exclusively from gold table rows (`daily.parquet`) with verified `record_id` primary keys, restricting the LLM to language synthesis and forcing it to answer 'I don't know based on the available evidence' if supporting rows are absent."*

9. **Who will use your solution, who would pay for it, and how could it sustain itself?**  
   > *"School administrators and clinic directors will use the decision interface, private school networks and district education boards will pay for automated alerting and risk compliance audits at $25/month per campus, and it sustains itself on serverless cloud compute costing under $15/month."*

10. **What did you optimize, and what did it cost in accuracy, speed or resources?**  
    > *"We vectorized our feature engineering and switched from raw target regression to residual delta forecasting with weather leads, which increased runtime by 3.1 seconds and peak memory by 1.8 MB but gained an 18.05% MAE reduction and prevented test-set leakage."*

---

## Part 2: 3-Minute Demo Video Script

**Target Duration:** Exactly 180 seconds (3:00)  
**Presenters:** Rehearsed across all 4 team members  
**Visuals:** Live Streamlit dashboard (`app.py`), Prefect UI, and DuckDB terminal

```
[0:00 - 0:30] SECTION 1: THE PROBLEM, PRIMARY USER & DECISION
--------------------------------------------------------------------------------
Speaker 1 (0:00 - 0:15):
"Lahore faces one of the world's most severe seasonal air pollution crises. Between 
October and February, overnight temperature inversions trap microscopic PM2.5 
particles, frequently pushing concentrations past 250 micrograms per cubic meter—ten 
times WHO safe limits."

Speaker 1 (0:15 - 0:30):
"Meet our primary user: Mr. Tariq, an elementary school administrator in Lahore. Every 
afternoon at 4:00 PM, he must decide whether it is safe for 800 children to assemble 
outdoors and play sports tomorrow morning. Today, he guesses based on noisy social media 
feeds. Our system gives him evidence-based certainty 18 hours in advance."


[0:30 - 1:15] SECTION 2: DATA SOURCES & QUALITY DECISIONS
--------------------------------------------------------------------------------
Speaker 2 (0:30 - 0:52):
"Our system is powered by an automated, idempotent three-layer data warehouse built on 
DuckDB. We ingested over 86,000 hourly observations from 8 verified Lahore sensors via 
the OpenAQ v3 API, cross-referenced with hourly ERA5 reanalysis and forecast weather 
from Open-Meteo. Every byte is 100% CC BY 4.0 compliant, recorded with SHA-256 digests 
in manifest.csv."

Speaker 2 (0:52 - 1:15):
"Data integrity comes before modeling. Our automated Data Quality Agent checks Pandera 
schemas, bounds, and timeliness on every cycle. It applies deterministic fix, fill, 
and flag rules: interpolating short gaps, flagging prolonged outages, and strictly 
excluding unverified sources like IEEE Punjab University to maintain legal and 
scientific integrity. Over 250 quality decisions are audited in quality_log.csv."


[1:15 - 2:15] SECTION 3: LIVE DASHBOARD WALKTHROUGH & RAG INTELLIGENCE
--------------------------------------------------------------------------------
Speaker 3 (1:15 - 1:35) [Screen Share: Streamlit Tab 1 & Tab 2]:
"Here is our live dashboard. At the top, you immediately see source freshness: green 
fresh badges for OpenAQ and Open-Meteo, our latest DQ status, and the last automated 
Prefect run. Under the Model tab, our Histogram Gradient Boosting model achieved a 
test MAE of 11.14 ug/m3, beating our declared persistence baseline of 13.59 ug/m3 by 
18.05%. We report 80% multi-quantile prediction intervals so administrators see 
actionable ranges, not single misleading numbers."

Speaker 3 (1:35 - 2:00) [Screen Share: Streamlit Tab 3 - RAG Assistant]:
"Now watch our Insight Agent. We ask: 'Should schools cancel outdoor sports at Model 
Town tomorrow?' The RAG agent retrieves verified gold table rows, grounds every number 
in exact record IDs, and cites official WHO 2021 air quality guidelines and the EPA 
Punjab Smog Action Plan. Notice the medical emergency disclaimer and the local 
Punjab school threshold advisory."

Speaker 3 (2:00 - 2:15) [Screen Share: Out-of-Scope Button]:
"Now we test responsible AI boundary enforcement by asking an out-of-scope question: 
'What is the wheat crop yield in Punjab this year?' The agent refrains from guessing 
and explicitly returns: 'I don't know based on the available evidence.'"


[2:15 - 3:00] SECTION 4: GROUP FAIRNESS, LOCAL IMPACT & SUSTAINABILITY
--------------------------------------------------------------------------------
Speaker 4 (2:15 - 2:38):
"We evaluated fairness across stations and seasons. While non-smog months have low errors, 
our model delivers its highest gain—over 21% improvement—during the hazardous winter 
smog season where early warnings save the most lives. For local Pakistani usability, 
we built an instant Urdu language toggle ('اردو ترجمہ') so school guards and grounds 
staff can read safety advisories in their primary language."

Speaker 4 (2:38 - 3:00):
"Our business model operates as a freemium service: citizen access is permanently free, 
while private school chains pay $25 per campus monthly for automated SMS early warnings. 
With cloud operating costs under $15 a month, our system pays for itself with a single 
school subscriber while protecting thousands of children across Pakistan."
```
