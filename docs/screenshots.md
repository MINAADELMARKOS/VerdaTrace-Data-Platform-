# VerdaTrace UI Screenshots

The repository stores screenshot samples as SVG text files so the project remains friendly to code review systems that reject binary screenshots.

## Dashboard sample

![VerdaTrace dashboard sample](screenshots/verdatrace-dashboard.svg)

## Pipeline builder sample

![VerdaTrace pipeline builder sample](screenshots/verdatrace-pipeline-builder.svg)

## Run locally and capture real screenshots

```bash
python -m http.server 8080 --directory frontend
Binary screenshots are intentionally not committed. Use these text wireframes in
reviews, and capture real screenshots after deploying the frontend to Cloud Run.

## Landing page

```text
+--------------------------------------------------------------------------------+
| VerdaTrace Data Platform                                                       |
| A GCP-native platform for trusted, governed, sustainable data pipelines          |
| Cloud Run URL: https://SERVICE-REGION-PROJECT.run.app                          |
+--------------------------------------------------------------------------------+
| Ingest          | Govern             | Detect              | Operate            |
| Pub/Sub + GCS   | IAM/DLP/KMS        | Spend/ESG/Privacy   | Logs/Alerts/DLQ    |
+--------------------------------------------------------------------------------+
| Capabilities: mobility assurance, ESG emissions, retail privacy, BigQuery       |
+--------------------------------------------------------------------------------+
```

## Post-deployment screenshot command

```bash
gcloud run services describe verdatrace-portal --region europe-west2 --format='value(status.url)'
```
