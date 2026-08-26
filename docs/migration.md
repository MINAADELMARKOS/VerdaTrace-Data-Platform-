# Migration and backward compatibility

## Compatibility

- Existing callers can continue importing `transform_event` from `data_pipeline.py`.
- Existing canonical columns remain with their prior names and compatible types.
- New multimodal BigQuery columns are nullable.
- Existing Pub/Sub input fields remain accepted, including `trip_id`, `customer_id`, `employee_id`, `tpep_pickup_datetime`, `trip_distance`, and `source_dataset`.
- Quality flags remain a comma-separated string in the compatibility table; full machine-readable reports live in the layered result model.
- The frontend remains static and can still run through Nginx/Cloud Run.

## Baseline repair

The prior repository head could not execute or apply because multiple files contained merged duplicate content. The repair consistently retains the VerdaTrace names and removes duplicate EY-prefixed attributes. If an older valid revision provisioned EY-prefixed resources, do not apply the new Terraform blindly.

## BigQuery migration

Before applying:

1. Back up/export the existing table schema.
2. Run `terraform plan` and inspect replacement actions.
3. Add the nullable columns to an existing table in place when Terraform cannot do so safely.
4. Confirm JSON type availability in the target BigQuery region/provider version.
5. Validate old queries against the unchanged original fields.

The new schema clusters by `dataset_id`, `use_case`, and `device_id`. Re-clustering an existing table may require a controlled copy or provider-specific update.

## IAM migration

Project-wide worker roles were replaced by resource-scoped subscription, dataset, bucket, and secret bindings. Confirm that no unrelated workload depended on the old bindings before removing them from an existing project.

The node service account is now separate from the pipeline workload account. Existing clusters may require a new node pool and workload-identity verification.

## Secret migration

Create a version for `verdatrace-pseudonym-salt` before starting workers. The application no longer permits an empty cloud salt. Rotate deliberately because changing the salt changes pseudonymous identifiers and affects longitudinal joins.

## Rollout

1. Run unit/integration validation locally.
2. Apply BigQuery nullable columns.
3. Create/verify the Secret Manager value.
4. Apply scoped IAM and Workload Identity.
5. Deploy one worker replica with a versioned image tag.
6. Publish test events and verify BigQuery, GCS, audit, DLQ, and dashboards.
7. Scale to the configured replica count.
8. Remove obsolete broad roles only after access logs confirm no dependency.

Rollback uses the previous versioned container image. Do not roll back the salt independently of data written with it.
