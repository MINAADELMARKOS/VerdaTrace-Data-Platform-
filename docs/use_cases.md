# EY End-to-End Use Cases with Real Data

The architecture can serve many EY client scenarios where raw operational events must be ingested, governed, transformed, and analysed. The examples below use public datasets or public-data-shaped records so teams can run demonstrations without exposing client data.

## 1. Mobility Expense Assurance

**Business problem:** Organisations reimburse employee travel and mobility costs, but finance teams need scalable controls to detect duplicate claims, inflated fares, and policy exceptions.

**Real data source:** NYC Taxi & Limousine Commission trip record data provides trip distance, fare, tip, tolls, timestamps, passenger counts, and location-zone IDs. These fields resemble the structure of corporate mobility or expense events.

**Architecture fit:**

1. Expense-management or mobility systems publish trip events to Pub/Sub.
2. GKE workers validate amount, distance, and timestamp fields.
3. Employee, vendor, or device identifiers are pseudonymised.
4. BigQuery stores curated trips partitioned by ingestion date.
5. Audit teams query anomalies, such as high fare-per-mile, weekend travel, duplicate transaction IDs, or missing receipt metadata.

**Example analytics query:**

```sql
SELECT
  event_id,
  hashed_subject_id,
  trip_distance_miles,
  total_amount,
  SAFE_DIVIDE(total_amount, NULLIF(trip_distance_miles, 0)) AS amount_per_mile
FROM `PROJECT.ey_data_engineering.processed_events`
WHERE use_case = 'mobility_expense_assurance'
  AND SAFE_DIVIDE(total_amount, NULLIF(trip_distance_miles, 0)) > 25
ORDER BY amount_per_mile DESC;
```

## 2. ESG Transport Emissions Reporting

**Business problem:** Companies need transparent and repeatable emissions calculations for transport activity, especially where mobility, field service, and logistics data come from many systems.

**Real data source:** NYC TLC trip distance and taxi-service metadata can be used to demonstrate distance-based Scope 3 transport estimation. Client implementations can replace the public event feed with fleet, rail, air, or logistics-provider feeds.

**Architecture fit:**

1. Transport events are published to Pub/Sub in near real time.
2. The worker standardises distances and stores an estimated `co2e_kg` value.
3. BigQuery partitions support monthly sustainability reporting and retention.
4. Logs and metadata support assurance over calculation lineage.

**Example analytics query:**

```sql
SELECT
  DATE(event_timestamp) AS activity_date,
  item_category AS service_type,
  ROUND(SUM(co2e_kg), 2) AS estimated_co2e_kg
FROM `PROJECT.ey_data_engineering.processed_events`
WHERE use_case = 'esg_transport_emissions'
GROUP BY activity_date, service_type
ORDER BY activity_date;
```

## 3. Privacy-Safe Retail Transaction Analytics

**Business problem:** Retailers need customer, category, and basket analytics, but analytics platforms should avoid storing direct customer identifiers unless strictly necessary.

**Real data source:** Public retail basket datasets and POS exports share a common transaction structure: customer ID, transaction amount, timestamp, and category. This repository includes a minimal JSON event contract that mirrors that structure.

**Architecture fit:**

1. POS, ecommerce, or loyalty applications publish transaction events.
2. The worker hashes `user_id`, drops raw identifiers, and keeps only category and monetary fields.
3. BigQuery supports sales, demand, and anomaly analytics without exposing direct identifiers.
4. Retention and audit logs support GDPR accountability obligations.

**Example analytics query:**

```sql
SELECT
  item_category,
  COUNT(*) AS transactions,
  ROUND(SUM(total_amount), 2) AS revenue
FROM `PROJECT.ey_data_engineering.processed_events`
WHERE use_case = 'retail_transaction_privacy'
GROUP BY item_category
ORDER BY revenue DESC;
```

## Canonical processed event contract

All use cases land in a shared BigQuery table using the following canonical fields:

| Field | Type | Description |
| --- | --- | --- |
| `event_id` | STRING | Upstream event or transaction identifier. |
| `use_case` | STRING | Use-case label used for downstream views and controls. |
| `hashed_subject_id` | STRING | Salted SHA-256 hash of the person, vendor, or customer identifier. |
| `event_timestamp` | TIMESTAMP | Business event timestamp. |
| `ingestion_timestamp` | TIMESTAMP | Time the worker processed the message. |
| `item_category` | STRING | Product, service, or activity category. |
| `currency` | STRING | ISO currency code where money is present. |
| `total_amount` | FLOAT | Normalised transaction amount. |
| `trip_distance_miles` | FLOAT | Distance field used for mobility and ESG calculations. |
| `co2e_kg` | FLOAT | Estimated emissions when distance data is available. |
| `source_system` | STRING | Name of the originating system or dataset. |
| `quality_flags` | STRING | Comma-separated data-quality warnings. |
