"""Pub/Sub-to-BigQuery worker for the VerdaTrace multimodal platform.

Cloud I/O is kept at the module boundary while transformation functions remain
pure and unit-testable without GCP credentials.
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
    from google.cloud import bigquery, pubsub_v1, secretmanager, storage
except ImportError:  # pragma: no cover - optional for local-only validation
    bigquery = None
    pubsub_v1 = None
    secretmanager = None
    storage = None

LOGGER = logging.getLogger("verdatrace_data_pipeline")
DEFAULT_DATASET = "verdatrace_data_engineering"
DEFAULT_TABLE = "processed_events"
DEFAULT_EMISSIONS_FACTOR_KG_PER_MILE = 0.404
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_PATTERN = re.compile(r"\+?\d[\d .()\-]{7,}\d")
SAFE_OBJECT_NAME = re.compile(r"[^A-Za-z0-9._-]+")


class TransformationError(ValueError):
    """Raised when an incoming event cannot be transformed safely."""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_timestamp(value: Any) -> str:
    if value in (None, ""):
        raise TransformationError("event timestamp is required")
    if isinstance(value, (int, float)) or re.fullmatch(r"\d{10}(?:\.\d+)?", str(value)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()
        except (ValueError, OSError, OverflowError) as exc:
            raise TransformationError(f"invalid epoch timestamp: {value}") from exc
    normalised = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalised)
    except ValueError as exc:
        raise TransformationError(f"invalid timestamp: {value}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def hash_identifier(identifier: Any, salt: str) -> str:
    if identifier in (None, ""):
        raise TransformationError("subject or device identifier is required for pseudonymisation")
    if not salt:
        raise TransformationError("a non-empty pseudonymisation salt is required")
    return hashlib.sha256(f"{salt}:{identifier}".encode("utf-8")).hexdigest()


def as_float(value: Any, field_name: str, default: Optional[float] = None) -> Optional[float]:
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise TransformationError(f"{field_name} must be numeric") from exc


def first_value(event: Dict[str, Any], *names: str) -> Any:
    for name in names:
        if event.get(name) not in (None, ""):
            return event[name]
    return None


def build_quality_flags(
    event: Dict[str, Any],
    total_amount: Optional[float],
    trip_distance: Optional[float],
    co2e_kg: Optional[float],
) -> List[str]:
    """Return compatibility flags for the canonical BigQuery event table."""

    flags: List[str] = []
    use_case = str(event.get("use_case") or "")
    commerce_or_trip = use_case in {
        "mobility_expense_assurance",
        "esg_transport_emissions",
        "retail_transaction_privacy",
    }
    if commerce_or_trip and total_amount is None:
        flags.append("missing_amount")
    elif total_amount is not None and total_amount < 0:
        flags.append("negative_amount")
    if trip_distance is not None and trip_distance < 0:
        flags.append("negative_distance")
    if total_amount is not None and trip_distance is not None and trip_distance > 0:
        if total_amount / trip_distance > 25:
            flags.append("mobility_high_amount_per_mile")
    tip_amount = as_float(event.get("tip_amount"), "tip_amount", 0) or 0
    if total_amount and total_amount > 0 and tip_amount / total_amount > 0.5:
        flags.append("mobility_unusual_tip_ratio")
    if co2e_kg is not None and co2e_kg > 100:
        flags.append("esg_high_emissions")
    if commerce_or_trip and not first_value(event, "item_category", "category", "service_type"):
        flags.append("missing_category")
    for pii_field in ("email", "customer_email", "phone", "phone_number"):
        value = str(event.get(pii_field) or "")
        if EMAIL_PATTERN.match(value) or PHONE_PATTERN.search(value):
            flags.append("privacy_direct_identifier_present")
            break
    if event.get("duplicate_hint") is True:
        flags.append("possible_duplicate_event")
    return flags


def transform_event(event: Dict[str, Any], salt: str = "") -> Dict[str, Any]:
    """Transform one event into the backward-compatible multimodal table row."""

    if not isinstance(event, dict):
        raise TransformationError("event payload must be a JSON object")
    event_id = str(first_value(event, "event_id", "transaction_id", "trip_id", "shipment_id") or "")
    if not event_id:
        raise TransformationError("event_id, transaction_id, trip_id, or shipment_id is required")
    timestamp = parse_timestamp(
        first_value(event, "event_timestamp", "timestamp", "ts", "tpep_pickup_datetime", "observed_at")
    )
    subject_id = first_value(
        event,
        "user_id",
        "customer_id",
        "employee_id",
        "vendor_id",
        "vehicle_id",
        "device_id",
    ) or event_id
    total_amount = as_float(first_value(event, "total_amount", "amount", "fare_amount"), "total_amount")
    trip_distance = as_float(
        first_value(event, "trip_distance_miles", "trip_distance", "distance_miles"),
        "trip_distance_miles",
    )
    co2e_kg = as_float(event.get("co2e_kg"), "co2e_kg")
    if co2e_kg is None and trip_distance is not None and trip_distance >= 0:
        co2e_kg = round(trip_distance * DEFAULT_EMISSIONS_FACTOR_KG_PER_MILE, 6)

    latitude = as_float(first_value(event, "latitude", "lat", "pickup_latitude"), "latitude")
    longitude = as_float(first_value(event, "longitude", "lon", "lng", "pickup_longitude"), "longitude")
    if latitude is not None and not -90 <= latitude <= 90:
        raise TransformationError("latitude must be between -90 and 90")
    if longitude is not None and not -180 <= longitude <= 180:
        raise TransformationError("longitude must be between -180 and 180")
    humidity = as_float(first_value(event, "humidity_pct", "humidity", "relative_humidity"), "humidity_pct")
    if humidity is not None and not 0 <= humidity <= 100:
        raise TransformationError("humidity_pct must be between 0 and 100")
    temperature_c = as_float(
        first_value(event, "temperature_c", "air_temperature", "temperature"),
        "temperature_c",
    )
    temperature_f = as_float(event.get("temperature_f"), "temperature_f")
    if temperature_c is None and temperature_f is not None:
        temperature_c = round((temperature_f - 32) * 5 / 9, 6)

    flags = build_quality_flags(event, total_amount, trip_distance, co2e_kg)
    geometry = event.get("geometry")
    return {
        "event_id": event_id,
        "dataset_id": str(event.get("dataset_id") or event.get("source_dataset") or "unknown"),
        "use_case": str(event.get("use_case") or "multimodal_observation"),
        "hashed_subject_id": hash_identifier(subject_id, salt),
        "event_timestamp": timestamp,
        "ingestion_timestamp": utc_now_iso(),
        "item_category": str(first_value(event, "item_category", "category", "service_type") or "unknown"),
        "currency": str(event.get("currency") or "USD"),
        "total_amount": total_amount,
        "trip_distance_miles": trip_distance,
        "co2e_kg": co2e_kg,
        "source_system": str(first_value(event, "source_system", "source_dataset") or "unknown"),
        "device_id": str(first_value(event, "device_id", "vehicle_id") or ""),
        "route_id": str(first_value(event, "route_id", "route") or ""),
        "origin": str(first_value(event, "origin", "pickup_location") or ""),
        "destination": str(first_value(event, "destination", "dropoff_location") or ""),
        "latitude": latitude,
        "longitude": longitude,
        "speed_kph": as_float(first_value(event, "speed_kph", "speed"), "speed_kph"),
        "heading": as_float(first_value(event, "heading", "bearing"), "heading"),
        "temperature_c": temperature_c,
        "humidity_pct": humidity,
        "pressure_hpa": as_float(first_value(event, "pressure_hpa", "pressure"), "pressure_hpa"),
        "co_ppm": as_float(first_value(event, "co_ppm", "co"), "co_ppm"),
        "co2_ppm": as_float(first_value(event, "co2_ppm", "co2"), "co2_ppm"),
        "lpg_ppm": as_float(first_value(event, "lpg_ppm", "lpg"), "lpg_ppm"),
        "smoke_ppm": as_float(first_value(event, "smoke_ppm", "smoke"), "smoke_ppm"),
        "rainfall_mm": as_float(first_value(event, "rainfall_mm", "rainfall", "precipitation"), "rainfall_mm"),
        "wind_speed_kph": as_float(first_value(event, "wind_speed_kph", "wind_speed"), "wind_speed_kph"),
        "geometry_json": json.dumps(geometry, separators=(",", ":")) if geometry else None,
        "crs": str(event.get("crs") or ("EPSG:4326" if latitude is not None and longitude is not None else "")),
        "schema_version": "verdatrace_multimodal_v1",
        "quality_flags": ",".join(flags),
    }


def archive_raw_message(event: Dict[str, Any], bucket_name: str, event_id: str) -> None:
    if not bucket_name:
        return
    if storage is None:
        raise RuntimeError("google-cloud-storage is not installed")
    safe_id = SAFE_OBJECT_NAME.sub("_", event_id)[:180]
    client = storage.Client()
    client.bucket(bucket_name).blob(f"raw-events/{safe_id}.json").upload_from_string(
        json.dumps(event, sort_keys=True),
        content_type="application/json",
    )


def insert_rows(rows: Iterable[Dict[str, Any]], project_id: str, dataset: str, table: str) -> None:
    if bigquery is None:
        raise RuntimeError("google-cloud-bigquery is not installed")
    client = bigquery.Client(project=project_id)
    errors = client.insert_rows_json(f"{project_id}.{dataset}.{table}", list(rows))
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


def load_pseudonym_salt(project_id: str) -> str:
    direct = os.getenv("PSEUDONYM_SALT", "")
    if direct:
        return direct
    secret_name = os.getenv("PSEUDONYM_SECRET_NAME", "verdatrace-pseudonym-salt")
    if secretmanager is None:
        raise RuntimeError("google-cloud-secret-manager is required when PSEUDONYM_SALT is unset")
    client = secretmanager.SecretManagerServiceClient()
    resource = f"projects/{project_id}/secrets/{secret_name}/versions/latest"
    salt = client.access_secret_version(request={"name": resource}).payload.data.decode("utf-8")
    if not salt:
        raise RuntimeError("pseudonymisation secret is empty")
    return salt


def run_worker() -> None:
    if pubsub_v1 is None:
        raise RuntimeError("google-cloud-pubsub is not installed")
    project_id = os.environ["GCP_PROJECT"]
    subscription = os.environ["PUBSUB_SUBSCRIPTION"]
    dataset = os.getenv("BQ_DATASET", DEFAULT_DATASET)
    table = os.getenv("BQ_TABLE", DEFAULT_TABLE)
    salt = load_pseudonym_salt(project_id)
    archive_bucket = os.getenv("RAW_ARCHIVE_BUCKET", "")
    subscriber = pubsub_v1.SubscriberClient()
    subscription_path = (
        subscription
        if subscription.startswith("projects/")
        else subscriber.subscription_path(project_id, subscription)
    )
    future = subscriber.subscribe(
        subscription_path,
        callback=lambda message: handle_message(
            message, project_id, dataset, table, salt, archive_bucket
        ),
    )
    LOGGER.info("listening for messages on %s", subscription_path)
    future.result()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="VerdaTrace Data Platform pipeline worker")
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
