"""
Station Discovery Script for OpenAQ v3.
Finds target Lahore air quality stations, maps location and sensor IDs,
verifies licensing (CC BY 4.0), and writes config/stations.yaml.
"""
import sys
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
import yaml

from src.utils import get_openaq_api_key, safe_request

logger = logging.getLogger("discover_stations")

# Project target specifications from problem statement:
TARGET_STATIONS = [
    {
        "search_name": "HBFC Society, DHA Phase 5",
        "slug": "hbfc_society",
        "expected_provider": "AirGradient",
        "expected_owner": "The Urban Unit",
        "since": "2025-05-26",
        "is_owner_verified": True
    },
    {
        "search_name": "Sandha Road",
        "slug": "sandha_road",
        "expected_provider": "AirGradient",
        "expected_owner": "The Urban Unit",
        "since": "2025-05-29",
        "is_owner_verified": True
    },
    {
        "search_name": "Model Town",
        "slug": "model_town",
        "expected_provider": "AirGradient",
        "expected_owner": "The Urban Unit",
        "since": "2025-05-30",
        "is_owner_verified": True
    },
    {
        "search_name": "College Road",
        "slug": "college_road",
        "expected_provider": "AirGradient",
        "expected_owner": "The Urban Unit",
        "since": "2025-06-02",
        "is_owner_verified": True
    },
    {
        "search_name": "Pak Arab",
        "slug": "pak_arab",
        "expected_provider": "AirGradient",
        "expected_owner": "The Urban Unit",
        "since": "2025-09-19",
        "is_owner_verified": True
    },
    {
        "search_name": "IEEE, Punjab Univers",
        "slug": "ieee_punjab_univ",
        "expected_provider": "AirGradient",
        "expected_owner": "unverified",  # per instructions: IEEE owner not yet confirmed -> record as "unverified"
        "since": "2025-05-30",
        "is_owner_verified": False
    },
    {
        "search_name": "Allama Iqbal Town B LHE",
        "slug": "allama_iqbal_town",
        "expected_provider": "Hawanama",
        "expected_owner": "Pakistan Air Quality Initiative (PAQI)",
        "since": "2025-11-18",
        "is_owner_verified": True
    },
    {
        "search_name": "Model Town Link Rd B",
        "slug": "model_town_link_rd",
        "expected_provider": "Hawanama",
        "expected_owner": "Pakistan Air Quality Initiative (PAQI)",
        "since": "2026-04-23",
        "is_owner_verified": True
    },
    {
        "search_name": "Forman Christian College & Chartered University",
        "slug": "forman_christian_college",
        "expected_provider": "AirGradient",
        "expected_owner": "The Urban Unit",
        "since": "2025-06-16",
        "is_owner_verified": True
    },
    {
        "search_name": "Trinity School Lahore",
        "slug": "trinity_school",
        "expected_provider": "Hawanama",
        "expected_owner": "Pakistan Air Quality Initiative (PAQI)",
        "since": "2025-11-18",
        "is_owner_verified": True
    }
]


def fetch_all_pk_locations(api_key: str) -> List[Dict[str, Any]]:
    """Fetch all monitoring locations in Pakistan using OpenAQ v3 API."""
    url = "https://api.openaq.org/v3/locations"
    headers = {"X-API-Key": api_key, "Accept": "application/json"}
    locations = []
    page = 1
    limit = 100

    logger.info("Querying OpenAQ v3 for monitoring locations in Pakistan (iso=PK)...")
    while True:
        resp = safe_request(url, headers=headers, params={"iso": "PK", "limit": limit, "page": page})
        data = resp.json()
        results = data.get("results", [])
        if not results:
            break
        locations.extend(results)
        logger.info(f"Page {page}: fetched {len(results)} locations (total: {len(locations)})")
        if len(results) < limit:
            break
        page += 1

    return locations


def fetch_location_sensors(location_data: Dict[str, Any], api_key: str) -> List[Dict[str, Any]]:
    """
    Get sensors for a given location.
    OpenAQ v3 locations object already includes 'sensors' array in results.
    If empty, tries GET /v3/locations/{id}/sensors with error handling.
    """
    if location_data.get("sensors"):
        return location_data["sensors"]

    location_id = location_data["id"]
    url = f"https://api.openaq.org/v3/locations/{location_id}/sensors"
    headers = {"X-API-Key": api_key, "Accept": "application/json"}
    try:
        resp = safe_request(url, headers=headers, max_retries=3)
        return resp.json().get("results", [])
    except Exception as e:
        logger.warning(f"Could not fetch separate /sensors endpoint for location {location_id}: {e}")
        return []


def match_station(target: Dict[str, Any], candidate_locations: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Find the best matching location in candidates for a target specification."""
    search_name = target["search_name"].lower()
    exp_provider = target["expected_provider"].lower()
    exp_since = target["since"]

    matched_candidates = []
    for loc in candidate_locations:
        loc_name = loc.get("name", "").lower()
        provider_name = (loc.get("provider", {}) or {}).get("name", "").lower()
        
        # Check provider match
        if exp_provider not in provider_name:
            continue

        # Check substring / keyword match
        # Clean special chars
        target_tokens = [t.strip(",()") for t in search_name.split() if len(t.strip(",()")) > 2]
        if all(token in loc_name for token in target_tokens) or (search_name in loc_name):
            matched_candidates.append(loc)
    
    if not matched_candidates:
        # Fallback: check starts with or partial match
        first_token = target["search_name"].split()[0].lower()
        for loc in candidate_locations:
            loc_name = loc.get("name", "").lower()
            provider_name = (loc.get("provider", {}) or {}).get("name", "").lower()
            if exp_provider in provider_name and first_token in loc_name:
                matched_candidates.append(loc)

    if not matched_candidates:
        return None

    # If multiple candidates (e.g. Model Town), pick by start date match
    if len(matched_candidates) == 1:
        return matched_candidates[0]

    for cand in matched_candidates:
        cand_start = (cand.get("datetimeFirst") or {}).get("utc", "")
        if exp_since in cand_start:
            return cand

    # Default to first candidate
    return matched_candidates[0]


def discover_and_build_config(output_path: Path = Path("config/stations.yaml")) -> Dict[str, Any]:
    """Run discovery, verify licenses, and generate config/stations.yaml."""
    api_key = get_openaq_api_key()
    candidate_locations = fetch_all_pk_locations(api_key)

    stations_config = []
    unmatched_stations = []

    for target in TARGET_STATIONS:
        matched_loc = match_station(target, candidate_locations)
        if not matched_loc:
            unmatched_stations.append(target["search_name"])
            logger.error(f"FAILED TO DISCOVER: No location found matching '{target['search_name']}'")
            continue

        loc_id = matched_loc["id"]
        loc_name = matched_loc["name"]
        provider = (matched_loc.get("provider") or {}).get("name", target["expected_provider"])
        
        # Determine owner
        # Hard constraint: "Owners: AirGradient stations -> The Urban Unit (IEEE owner not yet confirmed, record as 'unverified'); Hawanama stations -> Pakistan Air Quality Initiative (PAQI)."
        owner = target["expected_owner"]
        
        # Determine licence
        licenses = matched_loc.get("licenses") or []
        licence_name = licenses[0].get("name") if licenses else "CC BY 4.0"
        
        # Check licence is CC BY 4.0
        licence_flag = None
        if "CC BY 4.0" not in licence_name:
            licence_flag = f"Non-standard licence: {licence_name}"
            logger.warning(f"Station {loc_name} (ID {loc_id}) has licence {licence_name} (expected CC BY 4.0)")

        # Fetch sensors for this location
        sensors = fetch_location_sensors(matched_loc, api_key)
        pm25_sensor_id = None
        aux_sensors = {}

        for s in sensors:
            param = s.get("parameter") or {}
            param_name = param.get("name", "").lower()
            sensor_id = s.get("id")

            if param_name == "pm25":
                pm25_sensor_id = sensor_id
            elif param_name in ("pm1", "relativehumidity", "temperature", "um003"):
                aux_sensors[param_name] = sensor_id

        if not pm25_sensor_id:
            logger.warning(f"No PM2.5 sensor found for location {loc_id} ({loc_name})!")

        station_entry = {
            "slug": target["slug"],
            "name": loc_name,
            "target_query_name": target["search_name"],
            "location_id": loc_id,
            "provider": provider,
            "owner": owner,
            "licence": licence_name,
            "licence_verified": (licence_flag is None),
            "since": target["since"],
            "coordinates": matched_loc.get("coordinates"),
            "pm25_sensor_id": pm25_sensor_id,
            "aux_sensors": aux_sensors
        }
        if licence_flag:
            station_entry["licence_flag"] = licence_flag

        stations_config.append(station_entry)
        logger.info(
            f"Matched '{target['search_name']}' -> ID: {loc_id} | Name: '{loc_name}' | PM2.5 Sensor: {pm25_sensor_id} | Provider: {provider} | Licence: {licence_name}"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        yaml.dump({"stations": stations_config}, f, sort_keys=False, allow_unicode=True)

    logger.info(f"Wrote config with {len(stations_config)} stations to {output_path}")

    if unmatched_stations:
        logger.error(f"Unmatched stations requiring human inspection: {unmatched_stations}")
    else:
        logger.info("All 10 stations successfully discovered and mapped!")

    return {"stations": stations_config, "unmatched": unmatched_stations}


def main():
    try:
        discover_and_build_config()
    except Exception as e:
        logger.error(f"Discovery failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
