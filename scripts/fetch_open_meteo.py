"""Retrieve a bounded, attributed Open-Meteo historical weather sample."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from verdatrace.ingestion import fetch_allowlisted_json

DATA_ROOT = (ROOT / "data" / "samples").resolve()
BASE_URL = "https://archive-api.open-meteo.com/v1/archive"


def build_url(latitude: float, longitude: float, start_date: str, end_date: str) -> str:
    query = urlencode(
        {
            "latitude": latitude,
            "longitude": longitude,
            "start_date": start_date,
            "end_date": end_date,
            "hourly": "temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m",
            "timezone": "UTC",
        }
    )
    return f"{BASE_URL}?{query}"


def transform_response(payload: dict, source_url: str) -> dict:
    hourly = payload.get("hourly") or {}
    required = [
        "time",
        "temperature_2m",
        "relative_humidity_2m",
        "precipitation",
        "wind_speed_10m",
    ]
    lengths = {key: len(hourly.get(key, [])) for key in required}
    if not lengths or len(set(lengths.values())) != 1 or not next(iter(lengths.values()), 0):
        raise ValueError(f"Open-Meteo response has incompatible hourly arrays: {lengths}")
    latitude = payload.get("latitude")
    longitude = payload.get("longitude")
    records = []
    for index, timestamp in enumerate(hourly["time"]):
        records.append(
            {
                "event_id": f"open-meteo-cairo-{timestamp}",
                "event_timestamp": f"{timestamp}:00Z" if len(timestamp) == 16 else timestamp,
                "device_id": "open-meteo-grid-cell",
                "latitude": latitude,
                "longitude": longitude,
                "temperature_c": hourly["temperature_2m"][index],
                "humidity_pct": hourly["relative_humidity_2m"][index],
                "rainfall_mm": hourly["precipitation"][index],
                "wind_speed_kph": hourly["wind_speed_10m"][index],
                "source_system": "open_meteo_historical_api",
            }
        )
    retrieved_at = datetime.now(timezone.utc).isoformat()
    return {
        "provenance": {
            "dataset_name": "Open-Meteo Historical Weather API — Cairo sample",
            "provider": "Open-Meteo",
            "original_url": source_url,
            "retrieved_at": retrieved_at,
            "license": "CC BY 4.0",
            "geographic_coverage": f"point sample near {latitude}, {longitude}",
            "temporal_coverage": f"{records[0]['event_timestamp']} to {records[-1]['event_timestamp']}",
            "source_format": "JSON",
            "original_schema": {
                "hourly.time": "ISO-8601",
                "hourly.temperature_2m": "degC",
                "hourly.relative_humidity_2m": "percent",
                "hourly.precipitation": "mm",
                "hourly.wind_speed_10m": "km/h"
            },
            "transformations": [
                "zipped hourly arrays",
                "attached WGS84 query coordinates",
                "renamed fields to VerdaTrace canonical semantics"
            ],
            "target_schema": "verdatrace_multimodal_v1",
            "limitations": [
                "Point sample is not representative of all Cairo microclimates.",
                "Values inherit upstream weather-model and reanalysis limitations."
            ]
        },
        "records": records,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latitude", type=float, default=30.0444)
    parser.add_argument("--longitude", type=float, default=31.2357)
    parser.add_argument("--start-date", default="2024-01-01")
    parser.add_argument("--end-date", default="2024-01-03")
    parser.add_argument(
        "--output",
        type=Path,
        default=DATA_ROOT / "open_meteo_cairo_2024-01-01_2024-01-03.json",
    )
    args = parser.parse_args()
    output = args.output.resolve()
    if output != DATA_ROOT and DATA_ROOT not in output.parents:
        raise ValueError(f"output must stay inside {DATA_ROOT}")
    url = build_url(args.latitude, args.longitude, args.start_date, args.end_date)
    payload = fetch_allowlisted_json(url, allowed_hosts=["archive-api.open-meteo.com"])
    result = transform_response(payload, url)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(result['records'])} attributed records to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
