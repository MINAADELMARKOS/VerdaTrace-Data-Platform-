# Security, least privilege, and auditability

## Application permissions

| Role | Read catalog/quality/results/visuals | Ingest | Analyze/export | Update metadata/quality | Administrative |
| --- | --- | --- | --- | --- | --- |
| Viewer | Yes | No | No | No | No |
| Ingestor | Yes | Yes | No | No | No |
| Analyst | Yes | No | Yes | No | No |
| Steward | Yes | Yes | Yes | Yes | No |
| Admin | Yes | Yes | Yes | Yes | Yes |

`authorize` fails closed for unknown roles and ungranted actions. Read operations do not imply write access. The local full-flow CLI defaults to steward because it performs ingestion, quality, and analysis; deployed APIs should derive the role from the repository's established identity boundary rather than user input.

## GCP permissions

- Pipeline workload: subscriber on one Pub/Sub subscription; data editor on one BigQuery dataset; object creator on one raw archive bucket; secret accessor on one salt secret.
- GKE nodes: Artifact Registry reader, Logging writer, and Monitoring metric writer only.
- Pub/Sub, BigQuery, and Storage service agents receive KMS encrypt/decrypt on the single platform key.
- No project-wide BigQuery editor or Storage object creator grant is used for the worker.
- Workload Identity binds the Kubernetes service account to the pipeline Google service account.

## Secrets

The cloud worker reads `PSEUDONYM_SECRET_NAME` from Secret Manager when `PSEUDONYM_SALT` is absent. It rejects an empty salt. Terraform defines the secret container but never creates a secret value. No credentials, tokens, Kaggle files, or `.env` files are committed.

## Input validation

- Local paths are resolved and must remain under explicit landing roots.
- Symlink/path traversal outside a root is rejected after resolution.
- File extensions are allow-listed.
- JSON, NDJSON, GeoJSON, and TIFF headers fail with structured errors.
- The external JSON connector requires HTTPS, an exact trusted hostname, bounded response size, timeout, and no redirects.
- GCS archive object names are sanitized and length-bounded.
- BigQuery table/dataset identifiers come from trusted deployment configuration, not event payloads.

## Audit records

Important stages emit actor/service, operation, resource, timestamp, outcome, and correlation ID. Details are bounded counts and result metadata. Keys resembling secrets, passwords, tokens, credentials, API keys, or raw data are redacted.

The worker logs event IDs/use cases and exceptions, but not raw message bodies. GCP Cloud Audit Logs complement application audit events for infrastructure and data-access operations when enabled in the target organization.

## Container hardening

The worker runs as a non-root numeric user, drops Linux capabilities, forbids privilege escalation, uses a read-only root filesystem, applies RuntimeDefault seccomp, pins requests/limits, and avoids embedding secret values.

## Public portal boundary

The portal contains only a bounded attributed public weather sample and explicit synthetic fixtures. It has no cloud credentials and no write API. A restrictive content security policy limits scripts/styles to self plus pinned Leaflet on unpkg, map images to OpenStreetMap tiles, connections to self, and disables frames, objects, and forms.

For production, self-host Leaflet assets or add subresource-integrity hashes and set equivalent HTTP security headers at the CDN/edge.
