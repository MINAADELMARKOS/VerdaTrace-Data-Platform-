import csv
import json
import os
from pathlib import Path

import pytest

from verdatrace.cohesive import build_cohesive_payload, compare_expected_findings, ingest_and_profile_file, iter_pack_records, rbac_allows


def _write_csv(path: Path, rows):
    rows = list(rows)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _fixture_pack(tmp_path: Path) -> Path:
    root = tmp_path / "pack"
    raw, metadata = root / "raw", root / "metadata"
    raw.mkdir(parents=True)
    metadata.mkdir()
    _write_csv(raw / "zones.csv", [{"zone_id": "Z001", "city": "Cairo", "zone_name": "Test", "centroid_lat": "30.1", "centroid_lon": "31.2", "risk_class": "low"}])
    _write_csv(raw / "sites.csv", [{"site_id": "SITE00001", "zone_id": "Z001", "site_type": "hub", "site_name": "Hub", "latitude": "30.1", "longitude": "31.2", "active": "True"}])
    _write_csv(raw / "vehicles.csv", [{"vehicle_id": "VEH000001", "vehicle_type": "van", "home_zone_id": "Z001", "capacity_kg": "1000", "fuel_type": "electric", "commissioned_year": "2024"}])
    _write_csv(raw / "sensors.csv", [{"sensor_id": "SENS0000001", "site_id": "SITE00001", "zone_id": "Z001", "sensor_type": "temperature_c", "expected_unit": "C", "expected_min": "-10", "expected_max": "60", "install_date": "2024-01-01", "calibration_due_days": "90"}])
    _write_csv(raw / "logistics_shipments.csv", [
        {"shipment_id": "SHP1", "created_at": "2026-01-01T00:00:00+00:00", "pickup_site_id": "SITE00001", "dropoff_site_id": "SITE00001", "vehicle_id": "VEH000001", "weight_kg": "10", "distance_km": "2", "planned_duration_min": "10", "actual_duration_min": "12", "status": "delivered", "priority": "standard", "temperature_controlled": "False"},
        {"shipment_id": "SHP1", "created_at": "2026-01-01T01:00:00+00:00", "pickup_site_id": "SITE00001", "dropoff_site_id": "", "vehicle_id": "VEH000001", "weight_kg": "-1", "distance_km": "3", "planned_duration_min": "10", "actual_duration_min": "0", "status": "DELIVERD", "priority": "express", "temperature_controlled": "True"},
    ])
    (raw / "mobility_stream.jsonl").write_text(json.dumps({"event_id": "M1", "event_time": "2026-01-01T00:00:00+00:00", "vehicle_id": "VEH000001", "zone_id": "Z001", "latitude": 30.1, "longitude": 31.2, "speed_kph": 20, "heading_deg": 10, "source": "fixture"}) + "\n", encoding="utf-8")
    (raw / "iot_sensor_telemetry.jsonl").write_text(json.dumps({"telemetry_id": "T1", "event_time": "2026-01-01T00:00:00+00:00", "sensor_id": "SENS0000001", "site_id": "SITE00001", "zone_id": "Z001", "sensor_type": "temperature_c", "value": 25, "unit": "C", "battery_pct": 90, "ingest_source": "fixture", "quality_flag": "raw"}) + "\n", encoding="utf-8")
    (raw / "industrial_measurements.xml").write_text("<IndustrialMeasurements><Measurement measurement_id='M1'><Timestamp>2026-01-01T00:00:00+00:00</Timestamp><SiteID>SITE00001</SiteID><SensorID>SENS0000001</SensorID><Metric>temperature_c</Metric><Unit>C</Unit><Value>25</Value><EquipmentState>RUNNING</EquipmentState><CalibrationDate>2025-01-01</CalibrationDate></Measurement></IndustrialMeasurements>", encoding="utf-8")
    _write_csv(raw / "climate_environment.csv", [{"observation_id": "C1", "observed_at": "2026-01-01T00:00:00+00:00", "zone_id": "Z001", "temperature_c": "25", "humidity_pct": "50", "wind_speed_kph": "10", "precipitation_mm": "0", "pm25_ugm3": "20", "visibility_km": "12", "source_station_id": "SITE00001"}])
    (raw / "spatial_assets.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": [{"type": "Feature", "id": "G1", "geometry": {"type": "Point", "coordinates": [31.2, 30.1]}, "properties": {"asset_id": "G1", "site_id": "SITE00001", "zone_id": "Z001", "asset_type": "site_point"}}]}), encoding="utf-8")
    _write_csv(raw / "analytical_evaluation.csv", [{"evaluation_id": "E1", "zone_id": "Z001", "evaluation_time": "2026-01-01T00:00:00+00:00", "mobility_access_score": "50", "environment_score": "80", "infrastructure_readiness_score": "90", "data_quality_score": "90", "risk_penalty": "1", "overall_suitability_score": "70", "recommendation": "recommended"}])
    (raw / "governance_access_audit.jsonl").write_text(json.dumps({"audit_id": "A1", "event_time": "2026-01-01T00:00:00+00:00", "principal_id": "analyst", "role": "analyst", "dataset": "zones", "action": "READ", "decision": "ALLOW", "reason": "rbac_policy", "request_id": "r1"}) + "\n", encoding="utf-8")
    (metadata / "expected_quality_findings.csv").write_text("dataset,issue,expected_count,quality_dimension\nlogistics_shipments,missing dropoff_site_id,1,completeness\n", encoding="utf-8")
    (metadata / "lineage_edges.csv").write_text("source_dataset,target_dataset,relationship\nzones,mobility_stream,zone_id enrich\n", encoding="utf-8")
    (metadata / "rbac_policy.csv").write_text("role,resource_pattern,actions,allowed\nanalyst,curated/*,READ,True\n", encoding="utf-8")
    return root


def test_cohesive_payload_runs_all_layers(tmp_path):
    root = _fixture_pack(tmp_path)
    payload = build_cohesive_payload(root, preview_limit=2)
    assert len(payload["datasets"]) == 12
    assert len(payload["platform"]["zone_360"]) == 1
    assert payload["platform"]["zone_360"][0]["explanation"]["evidence"]["shipments"] == 2
    assert payload["platform"]["executive_kpis"]
    assert payload["platform"]["lineage"]["edges"]
    assert payload["platform"]["governance"]["audit_summary"]["allowed"] == 1
    assert payload["platform"]["governance"]["audit_summary"]["sample"][0]["request_id"] == "r1"
    assert payload["platform"]["evaluation_alignment"]["target_record_count"] == 1
    shipment = next(item for item in payload["datasets"] if item["id"] == "pack_logistics_shipments")
    assert len(shipment["outcome"]["manifest"]["checksum_sha256"]) == 64
    assert shipment["outcome"]["manifest"]["source_system"] == "VerdaTrace Cohesive Data Pack"


def test_pack_quality_comparison_is_machine_readable(tmp_path):
    root = _fixture_pack(tmp_path)
    payload = build_cohesive_payload(root, preview_limit=1)
    result = payload["platform"]["quality_summary"]["datasets"]["logistics_shipments"]
    issues = {item["issue"]: item["count"] for item in result["issues"]}
    assert issues["missing dropoff_site_id"] == 1
    assert issues["negative weight_kg"] == 1
    comparison = compare_expected_findings(root, {"logistics_shipments": result})
    assert comparison[0]["validation_status"] == "passed"
    assert "quality_dimensions" in result["metrics"]


def test_streaming_xml_and_jsonl_parsers(tmp_path):
    root = _fixture_pack(tmp_path)
    assert next(iter_pack_records(root, "mobility_stream"))["event_id"] == "M1"
    xml_row = next(iter_pack_records(root, "industrial_measurements"))
    assert xml_row["site_id"] == "SITE00001" and xml_row["value"] == 25.0


def test_generic_upload_hook_discovers_format_and_bounds_preview(tmp_path):
    root = _fixture_pack(tmp_path)
    result = ingest_and_profile_file(root / "raw" / "mobility_stream.jsonl", allowed_root=root / "raw", preview_limit=1)
    assert result["manifest"]["source_format"] == "JSONL"
    assert result["manifest"]["record_count"] == 1
    assert len(result["preview"]) == 1
    assert "apply configured quality rules" in result["next_steps"]


def test_pack_rbac_does_not_grant_raw_access_to_executives():
    policy = [
        {"role": "executive_viewer", "resource_pattern": "serving/*", "actions": "READ", "allowed": "True"},
        {"role": "executive_viewer", "resource_pattern": "raw/*", "actions": "READ", "allowed": "False"},
    ]
    assert rbac_allows(policy, role="executive_viewer", resource="serving/analytical_evaluation", action="READ")
    assert not rbac_allows(policy, role="executive_viewer", resource="raw/logistics_shipments", action="READ")
    assert not rbac_allows(policy, role="executive_viewer", resource="raw/logistics_shipments", action="WRITE")


@pytest.mark.skipif(not os.environ.get("VERDATARACE_PACK_ROOT"), reason="full supplied pack is external to the repository; set VERDATARACE_PACK_ROOT to run the full golden comparison")
def test_full_supplied_pack_golden_targets():
    payload = build_cohesive_payload(os.environ["VERDATARACE_PACK_ROOT"], preview_limit=5)
    comparison = payload["platform"]["quality_summary"]["expected_findings_validation"]
    assert comparison and all(item["validation_status"] == "passed" for item in comparison)
