import pytest

from data_pipeline import TransformationError, transform_event


def test_transform_event_pseudonymises_identifier_and_drops_raw_id():
    row = transform_event(
        {
            "event_id": "evt-1",
            "customer_id": "customer-1",
            "customer_email": "person@example.com",
            "event_timestamp": "2024-01-01T00:00:00Z",
            "item_category": "grocery",
            "total_amount": 12.5,
            "source_system": "unit_test",
        },
        salt="test-salt",
    )
    assert row["event_id"] == "evt-1"
    assert row["hashed_subject_id"] != "customer-1"
    assert "customer_id" not in row
    assert "customer_email" not in row
    assert row["quality_flags"] == "privacy_direct_identifier_present"


def test_transform_event_adds_emissions_and_mobility_quality_flags():
    row = transform_event(
        {
            "trip_id": "trip-1",
            "employee_id": "employee-1",
            "tpep_pickup_datetime": "2024-01-01 08:00:00",
            "service_type": "yellow_taxi",
            "use_case": "mobility_expense_assurance",
            "total_amount": 80,
            "tip_amount": 45,
            "trip_distance": 2,
            "source_dataset": "nyc_tlc_trip_records",
        },
        salt="test-salt",
    )
    assert row["co2e_kg"] == 0.808
    assert "mobility_high_amount_per_mile" in row["quality_flags"]
    assert "mobility_unusual_tip_ratio" in row["quality_flags"]


def test_transform_event_supports_sensor_and_geospatial_fields():
    row = transform_event(
        {
            "event_id": "sensor-1",
            "device_id": "device-1",
            "ts": 1594419195.292461,
            "latitude": 30.0,
            "longitude": 31.0,
            "temperature_f": 77,
            "humidity": 50,
            "co": 0.004,
        },
        salt="test-salt",
    )
    assert row["temperature_c"] == 25
    assert row["humidity_pct"] == 50
    assert row["crs"] == "EPSG:4326"
    assert row["schema_version"] == "verdatrace_multimodal_v1"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("latitude", 138.4, "latitude"),
        ("longitude", -245.1, "longitude"),
        ("humidity", 130, "humidity"),
    ],
)
def test_transform_event_rejects_invalid_physical_values(field, value, message):
    event = {
        "event_id": "bad-1",
        "device_id": "device-1",
        "event_timestamp": "2024-01-01T00:00:00Z",
        field: value,
    }
    with pytest.raises(TransformationError, match=message):
        transform_event(event, salt="test-salt")


def test_transform_event_requires_salt_and_timestamp():
    with pytest.raises(TransformationError, match="timestamp"):
        transform_event({"event_id": "x", "device_id": "d"}, salt="test")
    with pytest.raises(TransformationError, match="salt"):
        transform_event(
            {"event_id": "x", "device_id": "d", "event_timestamp": "2024-01-01T00:00:00Z"},
            salt="",
        )
