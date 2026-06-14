# GCP End-to-End Data Engineering for EY Use Cases

This repository demonstrates a production-style, end-to-end data engineering pattern on Google Cloud Platform (GCP) for EY-relevant analytics workloads. It combines Terraform-managed cloud infrastructure, Pub/Sub ingestion, a Python worker on Google Kubernetes Engine (GKE), BigQuery storage, and governance controls such as pseudonymisation, retention, logging, and least-privilege IAM.

## Why this matters for EY

EY teams commonly help clients modernise data platforms while preserving auditability, privacy, and operational resilience. This project applies the architecture to practical use cases that can be demonstrated with public real-world datasets and adapted to client data later:

| Use case | Public data source | EY business outcome |
| --- | --- | --- |
| **Mobility expense assurance** | NYC Taxi & Limousine Commission trip records | Detect unusual fares, route-cost outliers, and policy exceptions in employee travel or mobility spend. |
| **ESG transport emissions reporting** | NYC TLC trip distance and vehicle-service metadata | Estimate trip-level CO2e and aggregate emissions for sustainability reporting. |
| **Retail transaction privacy pipeline** | Retail/POS-style JSON events | Ingest customer transactions while applying GDPR-aligned minimisation and pseudonymisation. |

See [`docs/use_cases.md`](docs/use_cases.md) for detailed use-case definitions, event contracts, and BigQuery analytics examples.

## Architecture

The solution implements this flow:

1. Upstream applications or data loaders publish JSON events to a Pub/Sub topic.
2. A Python microservice running on GKE consumes messages from the subscription.
3. The service validates and normalises records, hashes identifiers with SHA-256, drops non-required fields, and adds processing metadata.
4. Cleansed records are written to partitioned BigQuery tables.
5. Cloud Logging and Monitoring provide auditability, operational health, and alerting hooks.

Detailed architecture notes are in [`docs/architecture.md`](docs/architecture.md).

## Repository layout

```text
.
├── data_pipeline.py              # Pub/Sub -> transformation -> BigQuery worker
├── deployment.yaml               # Kubernetes deployment for GKE
├── Dockerfile                    # Container image definition
├── main.tf                       # Terraform infrastructure definition
├── requirements.txt              # Python runtime dependencies
├── sample_events/                # Real-data-shaped demo events
├── tests/                        # Unit tests for transformations
└── docs/
    ├── architecture.md
    └── use_cases.md
```

## Local development

Create a virtual environment and install dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Run unit tests:

```bash
python -m pytest
```

Transform a local sample event without connecting to GCP:

```bash
python data_pipeline.py --local-sample sample_events/nyc_taxi_trip.json
```

## Deployment overview

1. Build and push the container image:

   ```bash
   docker build -t gcr.io/$PROJECT_ID/ey-gcp-data-pipeline:latest .
   docker push gcr.io/$PROJECT_ID/ey-gcp-data-pipeline:latest
   ```

2. Provision infrastructure:

   ```bash
   terraform init
   terraform apply -var="project_id=$PROJECT_ID" -var="region=europe-west2"
   ```

3. Deploy the worker to GKE:

   ```bash
   kubectl apply -f deployment.yaml
   ```

4. Publish a sample message:

   ```bash
   gcloud pubsub topics publish ey-transaction-events \
     --message="$(cat sample_events/nyc_taxi_trip.json)"
   ```

## Configuration

The worker reads configuration from environment variables:

| Variable | Description | Default |
| --- | --- | --- |
| `GCP_PROJECT` | GCP project ID | Required for cloud mode |
| `PUBSUB_SUBSCRIPTION` | Pub/Sub subscription name or full path | Required for cloud mode |
| `BQ_DATASET` | BigQuery dataset | `ey_data_engineering` |
| `BQ_TABLE` | BigQuery destination table | `processed_events` |
| `PSEUDONYM_SALT` | Secret salt used before SHA-256 hashing | Empty string for local demo only |

In production, inject `PSEUDONYM_SALT` from Secret Manager rather than storing it in code or Kubernetes manifests.

## Compliance design

* **Data minimisation:** Transformation code only persists analytics-required fields.
* **Pseudonymisation:** Direct identifiers are salted and hashed before BigQuery storage.
* **Retention:** Terraform configures partition expiration on BigQuery tables.
* **Least privilege:** Workload identity is designed around Pub/Sub subscriber and BigQuery data editor roles only.
* **Accountability:** Structured logs capture event type, processing status, and error context without logging raw personal data.
