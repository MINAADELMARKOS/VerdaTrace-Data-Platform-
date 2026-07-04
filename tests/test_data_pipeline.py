from data_pipeline import transform_event


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
    assert row["hashed_subject_id"]
    assert row["hashed_subject_id"] != "customer-1"
    assert "customer_id" not in row
    assert "customer_email" not in row
    assert row["quality_flags"] == "privacy_direct_identifier_present"


def test_transform_event_adds_emissions_and_mobility_quality_flags():
    assert row["quality_flags"] == ""


def test_transform_event_adds_emissions_and_quality_flags():
    row = transform_event(
        {
            "trip_id": "trip-1",
            "employee_id": "employee-1",
            "tpep_pickup_datetime": "2024-01-01 08:00:00",
            "service_type": "yellow_taxi",
            "total_amount": 80,
            "tip_amount": 45,
            "trip_distance": 2,
            "source_dataset": "kaggle_nyc_taxi_trip_duration",
            "trip_distance": 2,
            "source_system": "nyc_tlc_trip_records",
        },
        salt="test-salt",
    )

    assert row["event_id"] == "trip-1"
    assert row["item_category"] == "yellow_taxi"
    assert row["co2e_kg"] == 0.808
    assert "mobility_high_amount_per_mile" in row["quality_flags"]
    assert "mobility_unusual_tip_ratio" in row["quality_flags"]


def test_transform_event_flags_esg_and_duplicate_issues():
    row = transform_event(
        {
            "event_id": "delivery-1",
            "vendor_id": "carrier-99",
            "event_timestamp": "2024-05-01T12:00:00Z",
            "service_type": "last_mile_delivery",
            "total_amount": 20,
            "trip_distance_miles": 300,
            "duplicate_hint": True,
            "source_dataset": "kaggle_supply_chain_logistics",
        },
        salt="test-salt",
    )

    assert row["co2e_kg"] == 121.2
    assert "esg_high_emissions" in row["quality_flags"]
    assert "possible_duplicate_event" in row["quality_flags"]
    assert row["quality_flags"] == "high_amount_per_mile"
