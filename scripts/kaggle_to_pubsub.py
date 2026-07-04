"""Publish Kaggle CSV rows to Pub/Sub using the VerdaTrace canonical event shape.

Usage in GCP after downloading a Kaggle dataset to Cloud Shell, Cloud Run Job or
GKE:
    python scripts/kaggle_to_pubsub.py \
      --project "$PROJECT_ID" \
      --topic verdatrace-transaction-events \
      --use-case mobility_expense_assurance \
      --csv /data/yellow_tripdata_2016-01.csv \
      --limit 100000
"""

from __future__ import annotations

import argparse
import csv
import json
from typing import Any, Dict, Iterable

from google.cloud import pubsub_v1


def map_row(row: Dict[str, str], use_case: str, row_number: int) -> Dict[str, Any]:
    """Map different Kaggle CSV structures to the canonical input contract."""

    if use_case == "mobility_expense_assurance":
        return {
            "event_id": f"{row.get('VendorID')}-{row.get('tpep_pickup_datetime', row_number)}",
            "use_case": use_case,
            "employee_id": row.get("VendorID") or f"vendor-{row_number}",
            "event_timestamp": row.get("tpep_pickup_datetime") or row.get("pickup_datetime"),
            "service_type": "yellow_taxi",
            "currency": "USD",
            "total_amount": row.get("total_amount") or row.get("fare_amount"),
            "tip_amount": row.get("tip_amount"),
            "trip_distance": row.get("trip_distance"),
            "source_dataset": "kaggle_nyc_yellow_taxi_trip_data",
        }
    if use_case == "esg_transport_emissions":
        return {
            "event_id": row.get("Order Id") or row.get("order_id") or f"shipment-{row_number}",
            "use_case": use_case,
            "vendor_id": row.get("Customer Id") or row.get("Carrier") or f"carrier-{row_number}",
            "event_timestamp": row.get("shipping date (DateOrders)") or row.get("order date (DateOrders)"),
            "service_type": row.get("Shipping Mode") or "shipment",
            "currency": "USD",
            "total_amount": row.get("Sales") or row.get("Benefit per order"),
            "trip_distance_miles": row.get("Distance") or row.get("shipping_distance_miles"),
            "source_dataset": "kaggle_dataco_supply_chain",
        }
    if use_case == "retail_transaction_privacy":
        return {
            "event_id": f"{row.get('event_time', '')}-{row.get('user_id', row_number)}",
            "use_case": use_case,
            "customer_id": row.get("user_id") or f"customer-{row_number}",
            "event_timestamp": row.get("event_time"),
            "item_category": row.get("category_code") or row.get("category_id"),
            "currency": "USD",
            "total_amount": row.get("price"),
            "source_dataset": "kaggle_ecommerce_behavior_data",
        }
    raise ValueError(f"unsupported use case: {use_case}")


def iter_events(csv_path: str, use_case: str, limit: int) -> Iterable[Dict[str, Any]]:
    with open(csv_path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for row_number, row in enumerate(reader, start=1):
            if limit and row_number > limit:
                break
            yield map_row(row, use_case, row_number)


def publish_events(project: str, topic: str, events: Iterable[Dict[str, Any]]) -> int:
    publisher = pubsub_v1.PublisherClient()
    topic_path = topic if topic.startswith("projects/") else publisher.topic_path(project, topic)
    count = 0
    for event in events:
        publisher.publish(topic_path, json.dumps(event).encode("utf-8"))
        count += 1
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish Kaggle data to VerdaTrace Pub/Sub")
    parser.add_argument("--project", required=True)
    parser.add_argument("--topic", default="verdatrace-transaction-events")
    parser.add_argument("--use-case", required=True, choices=["mobility_expense_assurance", "esg_transport_emissions", "retail_transaction_privacy"])
    parser.add_argument("--csv", required=True)
    parser.add_argument("--limit", type=int, default=10000)
    args = parser.parse_args()
    count = publish_events(args.project, args.topic, iter_events(args.csv, args.use_case, args.limit))
    print(f"published {count} events to {args.topic}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
