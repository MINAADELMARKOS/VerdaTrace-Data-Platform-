## Architecture Overview

The high‑level architecture of this VerdaTrace Data Platform combines infrastructure provisioning, container orchestration and data-pipeline logic on Google Cloud Platform.  The design prioritises scalability, resilience and compliance with European data‑protection regulations.

### Components

| Component | Description |
| --- | --- |
| **Terraform** | Defines and provisions cloud resources: GKE, Pub/Sub, BigQuery, IAM, KMS, Cloud Storage retention, DLP, Artifact Registry and Monitoring. |
| **Google Kubernetes Engine (GKE)** | Hosts the Python microservice that consumes messages from Pub/Sub, pseudonymises sensitive fields and writes to BigQuery.  Each pod runs a container built from the `data_pipeline.py` service. |
| **Pub/Sub** | Serves as the ingestion layer for raw transaction events.  Messages are published by the upstream application and consumed by the worker service. |
| **BigQuery** | Stores cleansed and pseudonymised data.  Tables are partitioned by ingestion date to improve query performance and support retention policies. |
| **Secret Manager** | Securely stores pseudonymisation salts, database URIs and other secrets. |
| **Cloud Storage** | Lands optional raw event archives and batch files with lifecycle retention and CMEK encryption. |
| **Cloud Dataflow** | Optional managed streaming/batch enrichment path for higher-volume workloads before BigQuery. |
| **Cloud DLP** | Inspects sample or production payloads for common PII patterns before curated analytics storage. |
| **Cloud KMS** | Provides customer-managed encryption keys for Pub/Sub, BigQuery and Cloud Storage. |
| **Artifact Registry** | Stores the worker container image used by GKE deployments. |
| **Dataplex / Data Catalog** | Adds governance, discovery and metadata management across curated BigQuery and raw GCS zones. |
| **Cloud Scheduler / Cloud Run** | Supports scheduled public-data loaders and lightweight API ingestion endpoints that publish to Pub/Sub. |
| **Cloud Logging, Monitoring, Error Reporting, Trace & Audit Logs** | Provides observability into pipeline health, throughput, latency and errors. Logs are audited to satisfy GDPR accountability requirements. |

### Data Flow

1. **Event Publishing:** Retail, mobility, ESG, Cloud Run loader or Cloud Scheduler-triggered jobs publish JSON events to the Pub/Sub topic and may land raw batch files in Cloud Storage.
2. **Message Consumption:** The Python microservice running on GKE subscribes to the topic and pulls messages in real time.
3. **Pseudonymisation & Processing:** The service applies a SHA‑256 hash to the user ID, removes unnecessary fields (data minimisation) and adds an ingestion timestamp. Additional transformations (e.g., currency conversion) can be applied here.
4. **Storage:** The processed record is written to the BigQuery table. Optionally, the raw message is archived to Cloud Storage for auditing and replay.
5. **Governance:** Cloud DLP inspection templates, Dataplex/Data Catalog metadata and retention policies support discovery, lineage and privacy controls.
6. **Monitoring:** Cloud Logging records processing status, errors and throughput metrics. Monitoring alert policies can be configured on failure rates or latency.

### Compliance Notes

* **Data minimisation:** Only required fields are persisted.  Identifiers are hashed to prevent re‑identification.
* **Retention:** BigQuery’s table partitioning and GCS lifecycle rules enforce automatic deletion of data after a defined period.
* **Security:** All data is encrypted at rest and in transit, with Cloud KMS customer-managed keys where configured. Service accounts are granted minimal roles (principle of least privilege). Secrets are not stored in code.
* **Transparency & accountability:** The README and this document describe data handling practices clearly.  Logging and audit trails support investigations or GDPR subject‑access requests.