terraform {
  required_version = ">= 1.5.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.40"
    }
  }
}

variable "project_id" {
  description = "GCP project ID."
  type        = string
}

variable "region" {
  description = "Primary GCP region. Use a European region for GDPR-aligned deployments."
  type        = string
  default     = "europe-west2"
}

variable "cluster_name" {
  description = "GKE cluster name."
  type        = string
  default     = "verdatrace-data-engineering-gke"
  default     = "ey-data-engineering-gke"
}

locals {
  services = toset([
    "artifactregistry.googleapis.com",
    "bigquery.googleapis.com",
    "cloudkms.googleapis.com",
    "cloudscheduler.googleapis.com",
    "composer.googleapis.com",
    "container.googleapis.com",
    "datacatalog.googleapis.com",
    "dataplex.googleapis.com",
    "dataflow.googleapis.com",
    "dlp.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
    "pubsub.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "storage.googleapis.com"
  ])
}

provider "google" {
  project = var.project_id
  region  = var.region
}

resource "google_project_service" "enabled" {
  for_each           = local.services
  service            = each.value
  disable_on_destroy = false
}

resource "google_kms_key_ring" "data_platform" {
  name     = "verdatrace-data-platform"
  name     = "ey-data-platform"
  location = var.region
}

resource "google_kms_crypto_key" "data_encryption" {
  name            = "verdatrace-data-encryption"
  name            = "ey-data-encryption"
  key_ring        = google_kms_key_ring.data_platform.id
  rotation_period = "7776000s"
}

resource "google_storage_bucket" "raw_archive" {
  name                        = "${var.project_id}-verdatrace-raw-event-archive"
  name                        = "${var.project_id}-ey-raw-event-archive"
  location                    = "EU"
  uniform_bucket_level_access = true

  encryption {
    default_kms_key_name = google_kms_crypto_key.data_encryption.id
  }

  lifecycle_rule {
    condition { age = 90 }
    action { type = "Delete" }
  }
}

resource "google_pubsub_topic" "transaction_events" {
  name = "verdatrace-transaction-events"
  name = "ey-transaction-events"

  kms_key_name = google_kms_crypto_key.data_encryption.id
}

resource "google_pubsub_topic" "dead_letter" {
  name         = "verdatrace-transaction-events-dlq"
  name         = "ey-transaction-events-dlq"
  kms_key_name = google_kms_crypto_key.data_encryption.id
}

resource "google_pubsub_subscription" "transaction_worker" {
  name                       = "verdatrace-transaction-worker"
  name                       = "ey-transaction-worker"
  topic                      = google_pubsub_topic.transaction_events.id
  ack_deadline_seconds       = 60
  message_retention_duration = "604800s"

  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.dead_letter.id
    max_delivery_attempts = 5
  }
}

resource "google_bigquery_dataset" "analytics" {
  dataset_id                 = "verdatrace_data_engineering"
  dataset_id                 = "ey_data_engineering"
  location                   = "EU"
  delete_contents_on_destroy = false

  default_encryption_configuration {
    kms_key_name = google_kms_crypto_key.data_encryption.id
  }
}

resource "google_bigquery_table" "processed_events" {
  dataset_id          = google_bigquery_dataset.analytics.dataset_id
  table_id            = "processed_events"
  deletion_protection = true

  time_partitioning {
    type          = "DAY"
    field         = "ingestion_timestamp"
    expiration_ms = 7776000000
  }

  schema = jsonencode([
    { name = "event_id", type = "STRING", mode = "REQUIRED" },
    { name = "use_case", type = "STRING", mode = "REQUIRED" },
    { name = "hashed_subject_id", type = "STRING", mode = "REQUIRED" },
    { name = "event_timestamp", type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "ingestion_timestamp", type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "item_category", type = "STRING", mode = "NULLABLE" },
    { name = "currency", type = "STRING", mode = "NULLABLE" },
    { name = "total_amount", type = "FLOAT", mode = "NULLABLE" },
    { name = "trip_distance_miles", type = "FLOAT", mode = "NULLABLE" },
    { name = "co2e_kg", type = "FLOAT", mode = "NULLABLE" },
    { name = "source_system", type = "STRING", mode = "NULLABLE" },
    { name = "quality_flags", type = "STRING", mode = "NULLABLE" }
  ])
}

resource "google_data_loss_prevention_inspect_template" "pii" {
  parent       = "projects/${var.project_id}/locations/${var.region}"
  description  = "Inspect incoming VerdaTrace demo payloads for common PII before analytics curation."
  display_name = "verdatrace-pii-inspection"
  description  = "Inspect incoming EY demo payloads for common PII before analytics curation."
  display_name = "ey-pii-inspection"

  inspect_config {
    info_types { name = "EMAIL_ADDRESS" }
    info_types { name = "PHONE_NUMBER" }
    info_types { name = "PERSON_NAME" }
    min_likelihood = "POSSIBLE"
  }
}

resource "google_artifact_registry_repository" "containers" {
  location      = var.region
  repository_id = "verdatrace-data-platform"
  description   = "Container images for VerdaTrace data engineering workloads"
  repository_id = "ey-data-platform"
  description   = "Container images for EY data engineering workloads"
  format        = "DOCKER"
}

resource "google_service_account" "pipeline" {
  account_id   = "verdatrace-data-pipeline"
  display_name = "VerdaTrace data pipeline worker"
  account_id   = "ey-data-pipeline"
  display_name = "EY data pipeline worker"
}

resource "google_project_iam_member" "pipeline_pubsub" {
  project = var.project_id
  role    = "roles/pubsub.subscriber"
  member  = "serviceAccount:${google_service_account.pipeline.email}"
}

resource "google_project_iam_member" "pipeline_bigquery" {
  project = var.project_id
  role    = "roles/bigquery.dataEditor"
  member  = "serviceAccount:${google_service_account.pipeline.email}"
}

resource "google_project_iam_member" "pipeline_storage" {
  project = var.project_id
  role    = "roles/storage.objectCreator"
  member  = "serviceAccount:${google_service_account.pipeline.email}"
}

resource "google_project_iam_member" "pipeline_kms" {
  project = var.project_id
  role    = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member  = "serviceAccount:${google_service_account.pipeline.email}"
}

resource "google_secret_manager_secret" "pseudonym_salt" {
  secret_id = "verdatrace-pseudonym-salt"
  secret_id = "ey-pseudonym-salt"
  replication {
    user_managed {
      replicas { location = var.region }
    }
  }
}

resource "google_container_cluster" "primary" {
  name                     = var.cluster_name
  location                 = var.region
  remove_default_node_pool = true
  initial_node_count       = 1
  workload_identity_config {
    workload_pool = "${var.project_id}.svc.id.goog"
  }
}

resource "google_container_node_pool" "workers" {
  name       = "worker-pool"
  cluster    = google_container_cluster.primary.name
  location   = var.region
  node_count = 2

  node_config {
    machine_type    = "e2-standard-2"
    service_account = google_service_account.pipeline.email
    oauth_scopes    = ["https://www.googleapis.com/auth/cloud-platform"]
  }
}

resource "google_logging_metric" "pipeline_errors" {
  name   = "verdatrace_pipeline_error_count"
  filter = "resource.type=\"k8s_container\" AND severity>=ERROR AND labels.k8s-pod/app=\"verdatrace-data-pipeline\""
  name   = "ey_pipeline_error_count"
  filter = "resource.type=\"k8s_container\" AND severity>=ERROR AND labels.k8s-pod/app=\"ey-data-pipeline\""

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
  }
}

resource "google_monitoring_alert_policy" "pipeline_errors" {
  display_name = "VerdaTrace data pipeline processing errors"
  display_name = "EY data pipeline processing errors"
  combiner     = "OR"

  conditions {
    display_name = "Pipeline error log entries"
    condition_threshold {
      filter          = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.pipeline_errors.name}\""
      duration        = "300s"
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      aggregations {
        alignment_period   = "300s"
        per_series_aligner = "ALIGN_DELTA"
      }
    }
  }
}

output "pubsub_topic" {
  value = google_pubsub_topic.transaction_events.name
}

output "pubsub_subscription" {
  value = google_pubsub_subscription.transaction_worker.name
}

output "raw_archive_bucket" {
  value = google_storage_bucket.raw_archive.name
}

output "bigquery_table" {
  value = "${var.project_id}.${google_bigquery_dataset.analytics.dataset_id}.${google_bigquery_table.processed_events.table_id}"
}
