"""Pub/Sub to BigQuery worker for VerdaTrace-aligned data engineering use cases.
"""Pub/Sub to BigQuery worker for EY-aligned data engineering use cases.

The module is intentionally split into pure transformation functions and cloud I/O
functions so that use-case rules can be tested locally without GCP credentials.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

try:
    from google.cloud import bigquery, pubsub_v1, storage
except ImportError:  # pragma: no cover - optional for local unit tests
    bigquery = None
    pubsub_v1 = None
    storage = None

LOGGER = logging.getLogger("verdatrace_data_pipeline")
DEFAULT_DATASET = "verdatrace_data_engineering"
DEFAULT_TABLE = "processed_events"
DEFAULT_EMISSIONS_FACTOR_KG_PER_MILE = 0.404
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_PATTERN = re.compile(r"\+?\d[\d .()\-]{7,}\d")
LOGGER = logging.getLogger("ey_data_pipeline")
DEFAULT_DATASET = "ey_data_engineering"
DEFAULT_TABLE = "processed_events"
DEFAULT_EMISSIONS_FACTOR_KG_PER_MILE = 0.404


class TransformationError(ValueError):
    """Raised when an incoming event cannot be transformed safely."""


def utc_now_iso() -> str:
    """Return the current UTC timestamp in ISO-8601 format."""

    return datetime.now(timezone.utc).isoformat()


def parse_timestamp(value: str) -> str:
    """Validate and normalise a timestamp string to ISO-8601 UTC."""

    if not value:
        raise TransformationError("event timestamp is required")
    normalised = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalised)
    except ValueError as exc:
        raise TransformationError(f"invalid timestamp: {value}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def hash_identifier(identifier: Any, salt: str) -> str:
    """Create a salted SHA-256 pseudonym for direct identifiers."""

    if identifier in (None, ""):
        raise TransformationError("subject identifier is required for pseudonymisation")
    digest = hashlib.sha256(f"{salt}:{identifier}".encode("utf-8")).hexdigest()
    return digest


def as_float(value: Any, field_name: str, default: Optional[float] = None) -> Optional[float]:
    """Convert an input value to float while producing useful validation errors."""

    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise TransformationError(f"{field_name} must be numeric") from exc


def build_quality_flags(
    event: Dict[str, Any],
    total_amount: Optional[float],
    trip_distance: Optional[float],
    co2e_kg: Optional[float],
) -> List[str]:
    """Return row-level issue flags for assurance, ESG and privacy use cases."""

    flags: List[str] = []
    if total_amount is None:
        flags.append("missing_amount")
    elif total_amount < 0:
def build_quality_flags(total_amount: Optional[float], trip_distance: Optional[float]) -> List[str]:
    """Return lightweight data-quality flags for audit and assurance queries."""

    flags: List[str] = []
    if total_amount is not None and total_amount < 0:
        flags.append("negative_amount")
    if trip_distance is not None and trip_distance < 0:
        flags.append("negative_distance")
    if total_amount is not None and trip_distance is not None and trip_distance > 0:
        if total_amount / trip_distance > 25:
            flags.append("mobility_high_amount_per_mile")
    if event.get("tip_amount") not in (None, ""):
        tip_amount = as_float(event.get("tip_amount"), "tip_amount", 0) or 0
        if total_amount and total_amount > 0 and tip_amount / total_amount > 0.5:
            flags.append("mobility_unusual_tip_ratio")
    if co2e_kg is not None and co2e_kg > 100:
        flags.append("esg_high_emissions")
    if not (event.get("item_category") or event.get("category") or event.get("service_type")):
        flags.append("missing_category")
    for pii_field in ("email", "customer_email", "phone", "phone_number"):
        value = str(event.get(pii_field) or "")
        if EMAIL_PATTERN.match(value) or PHONE_PATTERN.search(value):
            flags.append("privacy_direct_identifier_present")
            break
    if event.get("duplicate_hint") is True:
        flags.append("possible_duplicate_event")
            flags.append("high_amount_per_mile")
    return flags


def transform_event(event: Dict[str, Any], salt: str = "") -> Dict[str, Any]:
    """Transform a raw use-case event into the canonical BigQuery row."""

    use_case = event.get("use_case", "retail_transaction_privacy")
    subject_id = event.get("user_id") or event.get("customer_id") or event.get("employee_id") or event.get("vendor_id")
    total_amount = as_float(
        event.get("total_amount", event.get("amount", event.get("fare_amount"))),
        "total_amount",
    )
    trip_distance = as_float(event.get("trip_distance_miles", event.get("trip_distance")), "trip_distance_miles")
    co2e_kg = as_float(event.get("co2e_kg"), "co2e_kg")
    if co2e_kg is None and trip_distance is not None and trip_distance >= 0:
        co2e_kg = round(trip_distance * DEFAULT_EMISSIONS_FACTOR_KG_PER_MILE, 6)

    flags = build_quality_flags(event, total_amount, trip_distance, co2e_kg)
    flags = build_quality_flags(total_amount, trip_distance)
    transformed = {
        "event_id": str(event.get("event_id") or event.get("transaction_id") or event.get("trip_id") or ""),
        "use_case": use_case,
        "hashed_subject_id": hash_identifier(subject_id, salt),
        "event_timestamp": parse_timestamp(str(event.get("event_timestamp") or event.get("timestamp") or event.get("tpep_pickup_datetime") or "")),
        "ingestion_timestamp": utc_now_iso(),
        "item_category": str(event.get("item_category") or event.get("category") or event.get("service_type") or "unknown"),
        "currency": str(event.get("currency") or "USD"),
        "total_amount": total_amount,
        "trip_distance_miles": trip_distance,
        "co2e_kg": co2e_kg,
        "source_system": str(event.get("source_system") or event.get("source_dataset") or "unknown"),
        "source_system": str(event.get("source_system") or "unknown"),
        "quality_flags": ",".join(flags),
    }
    if not transformed["event_id"]:
        raise TransformationError("event_id, transaction_id, or trip_id is required")
    return transformed


def archive_raw_message(event: Dict[str, Any], bucket_name: str, event_id: str) -> None:
    """Archive the raw source event to Cloud Storage for controlled audit replay."""

    if not bucket_name:
        return
    if storage is None:
        raise RuntimeError("google-cloud-storage is not installed")
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(f"raw-events/{event_id}.json")
    blob.upload_from_string(json.dumps(event, sort_keys=True), content_type="application/json")


def insert_rows(rows: Iterable[Dict[str, Any]], project_id: str, dataset: str, table: str) -> None:
    """Insert transformed rows into BigQuery."""

    if bigquery is None:
        raise RuntimeError("google-cloud-bigquery is not installed")
    client = bigquery.Client(project=project_id)
    table_id = f"{project_id}.{dataset}.{table}"
    errors = client.insert_rows_json(table_id, list(rows))
    if errors:
        raise RuntimeError(f"BigQuery insert failed: {errors}")


def handle_message(
    message: Any,
    project_id: str,
    dataset: str,
    table: str,
    salt: str,
    archive_bucket: str = "",
) -> None:
    """Pub/Sub callback that transforms one message and acknowledges it on success."""

    try:
        payload = json.loads(message.data.decode("utf-8"))
        row = transform_event(payload, salt=salt)
        archive_raw_message(payload, archive_bucket, row["event_id"])
        insert_rows([row], project_id=project_id, dataset=dataset, table=table)
        LOGGER.info("processed event_id=%s use_case=%s", row["event_id"], row["use_case"])
        message.ack()
    except Exception:
        LOGGER.exception("failed to process Pub/Sub message")
        message.nack()


def run_worker() -> None:
    """Run the long-lived Pub/Sub subscriber."""

    if pubsub_v1 is None:
        raise RuntimeError("google-cloud-pubsub is not installed")
    project_id = os.environ["GCP_PROJECT"]
    subscription = os.environ["PUBSUB_SUBSCRIPTION"]
    dataset = os.getenv("BQ_DATASET", DEFAULT_DATASET)
    table = os.getenv("BQ_TABLE", DEFAULT_TABLE)
    salt = os.getenv("PSEUDONYM_SALT", "")
    archive_bucket = os.getenv("RAW_ARCHIVE_BUCKET", "")

    subscriber = pubsub_v1.SubscriberClient()
    subscription_path = subscription if subscription.startswith("projects/") else subscriber.subscription_path(project_id, subscription)
    future = subscriber.subscribe(
        subscription_path,
        callback=lambda message: handle_message(message, project_id, dataset, table, salt, archive_bucket),
    )
    LOGGER.info("listening for messages on %s", subscription_path)
    future.result()


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entrypoint for local samples and cloud worker mode."""

    parser = argparse.ArgumentParser(description="VerdaTrace Data Platform pipeline worker")
    parser = argparse.ArgumentParser(description="EY GCP data engineering pipeline")
    parser.add_argument("--local-sample", help="Path to a JSON event to transform locally")
    parser.add_argument("--salt", default=os.getenv("PSEUDONYM_SALT", "local-demo-salt"))
    args = parser.parse_args(argv)

    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    if args.local_sample:
        with open(args.local_sample, "r", encoding="utf-8") as sample_file:
            event = json.load(sample_file)
        print(json.dumps(transform_event(event, salt=args.salt), indent=2, sort_keys=True))
        return 0
    run_worker()
    return 0


if __name__ == "__main__":
    sys.exit(main())
