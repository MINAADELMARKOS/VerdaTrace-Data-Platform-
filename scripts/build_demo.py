"""Generate the portal's normalized, traceable demonstration payload."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from verdatrace.ingestion import iter_records
from verdatrace.models import Provenance
from verdatrace.pipeline import MultimodalPipeline

CLIMATE_SOURCE = ROOT / "data" / "samples" / "open_meteo_cairo_2024-01-01_2024-01-03.json"
ROUTE_SOURCE = ROOT / "tests" / "fixtures" / "synthetic_mobility_route.geojson"
OUTPUT = ROOT / "frontend" / "data" / "platform_demo.json"


def main() -> int:
    climate_envelope = json.loads(CLIMATE_SOURCE.read_text(encoding="utf-8"))
    climate_records = climate_envelope["records"]
    climate_provenance = Provenance(**climate_envelope["provenance"])
    climate = MultimodalPipeline(actor="demo-builder", role="steward").run(
        climate_records,
        dataset_id="open_meteo_cairo_historical",
        dataset_name="Cairo historical weather",
        source_format="json",
        provenance=climate_provenance,
        task="climate",
        required_fields=["event_id", "event_timestamp", "latitude", "longitude"],
        governance={
            "owner": "not_provided",
            "sensitivity": "public",
            "retention_policy": "sample retained in source control; refresh reproducibly",
        },
    )

    route_records = list(
        iter_records(
            ROUTE_SOURCE,
            allowed_roots=[ROOT / "tests" / "fixtures"],
        )
    )
    route_provenance = Provenance(
        dataset_name="Synthetic refrigerated shipment route fixture",
        provider="VerdaTrace test suite",
        original_url="repository://tests/fixtures/synthetic_mobility_route.geojson",
        retrieved_at="not_applicable_generated_fixture",
        license="not_applicable_test_fixture",
        geographic_coverage="Synthetic route near Alexandria, Egypt; not operational data",
        temporal_coverage="2024-02-10T08:00:00Z to 2024-02-10T08:44:00Z",
        source_format="GeoJSON",
        original_schema={
            "geometry": "GeoJSON Point EPSG:4326",
            "event_timestamp": "ISO-8601",
            "vehicle_id": "string",
            "route_id": "string",
            "speed_kph": "number",
            "temperature_c": "number",
        },
        transformations=["flattened GeoJSON properties", "derived latitude and longitude from Point geometry"],
        limitations=["Synthetic fixture for deterministic tests and UI demonstration; not a real shipment."],
    )
    route = MultimodalPipeline(actor="demo-builder", role="steward").run(
        route_records,
        dataset_id="synthetic_refrigerated_route",
        dataset_name="Synthetic refrigerated shipment route",
        source_format="geojson",
        provenance=route_provenance,
        task="mobility",
        required_fields=["event_id", "event_timestamp", "latitude", "longitude"],
        governance={
            "owner": "VerdaTrace maintainers",
            "sensitivity": "public_fixture",
            "retention_policy": "repository test fixture",
        },
    )

    payload = {
        "schema_version": "verdatrace_portal_payload_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "datasets": [
            {
                "id": "open_meteo_cairo_historical",
                "title": "Cairo historical weather",
                "domain": "climate_environmental",
                "fixture": False,
                "attribution": {
                    "label": "Weather data by Open-Meteo.com",
                    "url": "https://open-meteo.com/",
                    "license": "CC BY 4.0",
                },
                "records": climate_records,
                "outcome": climate.to_dict(),
            },
            {
                "id": "synthetic_refrigerated_route",
                "title": "Synthetic refrigerated shipment route",
                "domain": "logistics_mobility_sensor",
                "fixture": True,
                "attribution": {
                    "label": "Clearly labeled generated test fixture",
                    "url": "https://github.com/MINAADELMARKOS/VerdaTrace-Data-Platform-",
                    "license": "not_applicable_test_fixture",
                },
                "records": route_records,
                "outcome": route.to_dict(),
            },
        ],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(payload['datasets'])} normalized datasets to {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
