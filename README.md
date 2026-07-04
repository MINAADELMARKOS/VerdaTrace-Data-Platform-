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


```mermaid
flowchart LR
  subgraph Sources[Sources and scheduling]
    APP[Client apps / POS / mobility systems]
    RUN[Cloud Run loaders]
    SCH[Cloud Scheduler]
    GCSRAW[Cloud Storage raw files]
  end

  subgraph Ingest[Ingestion and inspection]
    PUB[Pub/Sub topic]
    DLQ[Pub/Sub dead-letter topic]
    DLP[Cloud DLP inspect template]
    DF[Dataflow optional enrichment]
  end

  subgraph Process[Backend processing]
    GKE[GKE worker pods]
    SM[Secret Manager pseudonym salt]
    KMS[Cloud KMS CMEK]
    AR[Artifact Registry images]
  end

  subgraph Data[Governed storage and analytics]
    ARCH[Cloud Storage raw evidence archive]
    BQ[BigQuery partitioned curated table]
    DP[Dataplex / Data Catalog]
  end

  subgraph Ops[IAM, logging, monitoring and retention]
  subgraph Process[Processing and orchestration]
    GKE[GKE worker pods]
    SM[Secret Manager pseudonym salt]
    KMS[Cloud KMS CMEK]
    AR[Artifact Registry image]
  end

  subgraph Data[Governed storage and analytics]
    ARCH[Cloud Storage raw archive]
    BQ[BigQuery partitioned table]
    DP[Dataplex / Data Catalog]
  end

  subgraph Ops[Security and operations]
    IAM[IAM least privilege]
    LOG[Cloud Logging]
    MON[Cloud Monitoring alerts]
    AUD[Cloud Audit Logs / Error Reporting / Trace]
    RET[BigQuery and GCS retention]
  end

  APP --> PUB
  KAG --> PUB
  RUN --> PUB
  SCH --> RUN
  GCSRAW --> DF
  PUB --> DLP
  PUB --> GKE
  PUB --> DLQ
  DLP --> DF
  DF --> BQ
  AR --> GKE
  SM --> GKE
  KMS --> PUB
  KMS --> ARCH
  KMS --> BQ
  GKE --> ARCH
  GKE --> BQ
  ARCH --> DP
  BQ --> DP
  GKE --> LOG
  LOG --> MON
  IAM --> GKE
  AUD --> MON
  RET --> ARCH
  RET --> BQ
```

## How the backend detects issues

The `data_pipeline.py` worker transforms each raw event into a canonical BigQuery row and adds `quality_flags` for downstream dashboards and alerts:

* `mobility_high_amount_per_mile` for unusually expensive trips.
* `mobility_unusual_tip_ratio` for suspicious mobility expense tips.
* `esg_high_emissions` for high estimated transport emissions.
* `privacy_direct_identifier_present` when raw ecommerce/retail events contain email or phone fields.
* `possible_duplicate_event`, `missing_amount`, `missing_category`, `negative_amount`, and `negative_distance` for common data-quality failures.

## Apply inside GCP environments

1. **Provision security, storage and processing**

   ```bash
   terraform init
   terraform apply -var="project_id=$PROJECT_ID" -var="region=europe-west2"
   ```

   Terraform configures IAM, Cloud Logging/Monitoring, BigQuery partition retention, Cloud Storage lifecycle retention, Pub/Sub DLQ, Cloud KMS encryption, Artifact Registry, GKE, DLP, and the raw archive bucket.

2. **Build and deploy the backend worker**

   ```bash
   docker build -t gcr.io/$PROJECT_ID/verdatrace-data-pipeline:latest .
   docker push gcr.io/$PROJECT_ID/verdatrace-data-pipeline:latest
   kubectl apply -f deployment.yaml
   ```

3. **Download huge Kaggle data in GCP**

   ```bash
   pip install kaggle
   export KAGGLE_CONFIG_DIR=/secrets/kaggle
   kaggle datasets download -d elemento/nyc-yellow-taxi-trip-data -p /data --unzip
   ```

4. **Stream Kaggle rows into Pub/Sub**

   ```bash
   python scripts/kaggle_to_pubsub.py \
     --project "$PROJECT_ID" \
     --topic verdatrace-transaction-events \
     --use-case mobility_expense_assurance \
     --csv /data/yellow_tripdata_2016-01.csv \
     --limit 100000
   ```

5. **Query detected issues in BigQuery**

   ```sql
   SELECT use_case, quality_flags, COUNT(*) AS flagged_rows
   FROM `PROJECT.verdatrace_data_engineering.processed_events`
   WHERE quality_flags != ''
   GROUP BY use_case, quality_flags
   ORDER BY flagged_rows DESC;
   ```

6. **Deploy the frontend portal and capture its URL**

   ```bash
   gcloud run deploy verdatrace-portal \
     --source frontend \
     --region europe-west2 \
     --allow-unauthenticated

   gcloud run services describe verdatrace-portal \
     --region europe-west2 \
     --format='value(status.url)'
   ```

   Put the returned Cloud Run URL in demos and screenshots. The static portal is in `frontend/index.html`, and text screenshot wireframes are in `docs/screenshots.md` so the repository remains binary-free.

## Repository layout

```text
.
├── data_pipeline.py              # Pub/Sub -> transformation -> BigQuery worker
├── deployment.yaml               # Kubernetes deployment for GKE
├── Dockerfile                    # Backend container image definition
├── frontend/                     # Cloud Run portal frontend
├── main.tf                       # Terraform infrastructure definition
├── requirements.txt              # Python runtime dependencies
├── config/kaggle_datasets.yml    # External huge-data dataset registry
├── sample_events/                # Small problematic sample events
├── scripts/kaggle_to_pubsub.py   # Kaggle CSV -> Pub/Sub loader
├── tests/                        # Unit tests for transformations
└── docs/
    ├── architecture.md
    ├── screenshots.md
    └── use_cases.md
```

## Local development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m pytest
python data_pipeline.py --local-sample sample_events/nyc_taxi_trip.json
```

## Runtime configuration

| Variable | Description | Default |
| --- | --- | --- |
| `GCP_PROJECT` | GCP project ID | Required for cloud mode |
| `PUBSUB_SUBSCRIPTION` | Pub/Sub subscription name or full path | Required for cloud mode |
| `BQ_DATASET` | BigQuery dataset | `verdatrace_data_engineering` |
| `BQ_TABLE` | BigQuery destination table | `processed_events` |
| `PSEUDONYM_SALT` | Secret salt used before SHA-256 hashing | Empty string for local demo only |
| `RAW_ARCHIVE_BUCKET` | Optional Cloud Storage bucket for encrypted raw-message audit archive | Disabled |

## Governance controls

* **IAM:** Terraform grants the worker only Pub/Sub subscriber, BigQuery data editor, Storage object creator, and KMS encrypter/decrypter permissions required by the pipeline.
* **Logging:** The worker emits structured processing logs without raw personal data.
* **Monitoring:** Terraform creates a log-based metric and alert policy for backend processing errors.
* **Retention:** BigQuery partitions expire after the configured retention period, and the raw Cloud Storage archive uses lifecycle deletion.
* **Privacy:** Direct identifiers are salted and hashed before curated BigQuery storage, while raw events are retained only in the controlled evidence archive.
