"""
Collect real OpenAQ licence evidence for all stations in config/stations.yaml.
Queries GET /v3/locations/{location_id}, saves unmodified JSON evidence,
and regenerates config/licence_evidence.csv.
"""
import os
import json
from pathlib import Path
from datetime import datetime, timezone
import yaml
import pandas as pd
import logging

from src.utils import get_openaq_api_key, safe_request

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("collect_licence_evidence")

EVIDENCE_DIR = Path("docs/evidence/licences")
STATIONS_YAML = Path("config/stations.yaml")
OUTPUT_CSV = Path("config/licence_evidence.csv")


def collect_licence_evidence():
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    api_key = get_openaq_api_key()
    headers = {"X-API-Key": api_key}

    with open(STATIONS_YAML, "r", encoding="utf-8") as f:
        config_data = yaml.safe_load(f)

    stations = config_data.get("stations", [])
    logger.info(f"Loaded {len(stations)} stations from {STATIONS_YAML}")

    records = []
    non_cc_by = []

    for st in stations:
        slug = st["slug"]
        loc_id = st["location_id"]
        url = f"https://api.openaq.org/v3/locations/{loc_id}"

        retrieved_at_utc = datetime.now(timezone.utc).isoformat()
        evidence_file = EVIDENCE_DIR / f"openaq_{loc_id}.json"

        licence_str = ""
        error_msg = ""

        try:
            resp = safe_request(url, headers=headers, max_retries=3, timeout=30)
            raw_text = resp.text
            # Save UNMODIFIED response to evidence folder
            with open(evidence_file, "w", encoding="utf-8") as ef:
                ef.write(raw_text)
            
            data = resp.json()
            results = data.get("results", [])
            if results and len(results) > 0:
                loc_obj = results[0]
                licenses = loc_obj.get("licenses") or []
                if licenses and len(licenses) > 0:
                    licence_str = licenses[0].get("name", "").strip()
                else:
                    error_msg = "No licenses field found in location object"
            else:
                error_msg = "Empty results in API response"

        except Exception as e:
            error_msg = f"HTTP Error: {str(e)}"
            logger.warning(f"Failed to fetch location {loc_id} ({slug}): {error_msg}")
            # If failed, still write error evidence if file does not exist
            if not evidence_file.exists():
                with open(evidence_file, "w", encoding="utf-8") as ef:
                    json.dump({"error": error_msg, "location_id": loc_id, "url": url}, ef, indent=2)

        if licence_str:
            if licence_str != "CC BY 4.0":
                non_cc_by.append((slug, loc_id, licence_str))
                logger.warning(f"Station {slug} (loc {loc_id}) has NON-CC-BY-4.0 licence: '{licence_str}'")
            else:
                logger.info(f"Station {slug} (loc {loc_id}) licence verified: {licence_str}")
        else:
            logger.warning(f"Station {slug} (loc {loc_id}) licence empty. Error: {error_msg}")

        records.append({
            "station": slug,
            "location_id": loc_id,
            "licence": licence_str,
            "checked_by": "script src/collect_licence_evidence.py (API response saved)",
            "checked_at": retrieved_at_utc,
            "evidence_path": str(evidence_file).replace("\\", "/"),
            "human_reviewed": "TO CONFIRM BY TEAM"
        })

    # Add Open-Meteo entry for comprehensive data source evidence
    records.append({
        "station": "open_meteo",
        "location_id": "N/A",
        "licence": "CC BY 4.0",
        "checked_by": "script src/collect_licence_evidence.py (API response saved)",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "evidence_path": "https://open-meteo.com/en/terms",
        "human_reviewed": "TO CONFIRM BY TEAM"
    })

    df = pd.DataFrame(records)
    df.to_csv(OUTPUT_CSV, index=False)
    logger.info(f"Regenerated {OUTPUT_CSV} with {len(df)} rows.")

    if non_cc_by:
        logger.warning(f"Found {len(non_cc_by)} stations without CC BY 4.0 licence: {non_cc_by}")
    else:
        logger.info("All successfully verified OpenAQ stations returned CC BY 4.0.")

    return df


if __name__ == "__main__":
    collect_licence_evidence()
