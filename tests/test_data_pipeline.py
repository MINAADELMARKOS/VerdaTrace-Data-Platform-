from data_pipeline import transform_event


def test_transform_event_pseudonymises_identifier_and_drops_raw_id():
    row = transform_event(
        {
            "event_id": "evt-1",
            "customer_id": "customer-1",
            "event_timestamp": "2024-01-01T00:00:00Z",
            "item_category": "grocery",
            "total_amount": 12.5,
            "source_system": "unit_test",
        },
        salt="test-salt",
    )

    assert row["event_id"] == "evt-1"
    assert row["hashed_subject_id"]
    assert row["hashed_subject_id"] != "customer-1"
    assert "customer_id" not in row
    assert row["quality_flags"] == ""


def test_transform_event_adds_emissions_and_quality_flags():
    row = transform_event(
        {
            "trip_id": "trip-1",
            "employee_id": "employee-1",
            "tpep_pickup_datetime": "2024-01-01 08:00:00",
            "service_type": "yellow_taxi",
            "total_amount": 80,
            "trip_distance": 2,
            "source_system": "nyc_tlc_trip_records",
        },
        salt="test-salt",
    )

    assert row["event_id"] == "trip-1"
    assert row["item_category"] == "yellow_taxi"
    assert row["co2e_kg"] == 0.808
    assert row["quality_flags"] == "high_amount_per_mile"
