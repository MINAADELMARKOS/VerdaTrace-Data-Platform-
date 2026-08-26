terraform {
  required_version = ">= 1.5.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.40"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = "~> 5.40"
    }
  }
}

variable "project_id" {
  description = "GCP project ID."
  type        = string
}

variable "region" {
  description = "Primary GCP region."
  type        = string
  default     = "europe-west2"
}

variable "cluster_name" {
  description = "GKE cluster name."
  type        = string
  default     = "verdatrace-data-engineering-gke"
}

variable "retention_days" {
  description = "Retention for raw objects and curated BigQuery partitions."
  type        = number
  default     = 90
  validation {
    condition     = var.retention_days >= 1 && var.retention_days <= 3650
    error_message = "retention_days must be between 1 and 3650."
  }
}

locals {
  services = toset([
    "artifactregistry.googleapis.com",
    "bigquery.googleapis.com",
    "cloudkms.googleapis.com",
    "container.googleapis.com",
    "datacatalog.googleapis.com",
    "dataplex.googleapis.com",
    "dlp.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
    "pubsub.googleapis.com",
    "secretmanager.googleapis.com",
    "storage.googleapis.com"
  ])
  kms_services = toset(["bigquery", "pubsub", "storage"])
}

provider "google" {
  project = var.project_id
  region  = var.region
}

provider "google-beta" {
  project = var.project_id
  region  = var.region
}

data "google_project" "current" {
  project_id = var.project_id
}

resource "google_project_service" "enabled" {
  for_each           = local.services
  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_project_service_identity" "kms_clients" {
  provider   = google-beta
  for_each   = local.kms_services
  project    = var.project_id
  service    = "${each.key}.googleapis.com"
  depends_on = [google_project_service.enabled]
}

resource "google_kms_key_ring" "data_platform" {
  name       = "verdatrace-data-platform"
  location   = var.region
  depends_on = [google_project_service.enabled]
}

resource "google_kms_crypto_key" "data_encryption" {
  name            = "verdatrace-data-encryption"
  key_ring        = google_kms_key_ring.data_platform.id
  rotation_period = "7776000s"
}

resource "google_kms_crypto_key_iam_member" "service_agents" {
  for_each      = google_project_service_identity.kms_clients
  crypto_key_id = google_kms_crypto_key.data_encryption.id
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = "serviceAccount:${each.value.email}"
}

resource "google_storage_bucket" "raw_archive" {
  name                        = "${var.project_id}-verdatrace-raw-event-archive"
  location                    = "EU"
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false

  encryption {
    default_kms_key_name = google_kms_crypto_key.data_encryption.id
  }

  lifecycle_rule {
    condition {
      age = var.retention_days
    }
    action {
      type = "Delete"
    }
  }

  depends_on = [google_kms_crypto_key_iam_member.service_agents]
}

resource "google_pubsub_topic" "transaction_events" {
  name         = "verdatrace-transaction-events"
  kms_key_name = google_kms_crypto_key.data_encryption.id
  depends_on   = [google_kms_crypto_key_iam_member.service_agents]
}

resource "google_pubsub_topic" "dead_letter" {
  name         = "verdatrace-transaction-events-dlq"
  kms_key_name = google_kms_crypto_key.data_encryption.id
  depends_on   = [google_kms_crypto_key_iam_member.service_agents]
}

resource "google_pubsub_subscription" "transaction_worker" {
  name                       = "verdatrace-transaction-worker"
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
  location                   = "EU"
  delete_contents_on_destroy = false

  default_encryption_configuration {
    kms_key_name = google_kms_crypto_key.data_encryption.id
  }

  depends_on = [google_kms_crypto_key_iam_member.service_agents]
}

resource "google_bigquery_table" "processed_events" {
  dataset_id          = google_bigquery_dataset.analytics.dataset_id
  table_id            = "processed_events"
  deletion_protection = true

  time_partitioning {
    type          = "DAY"
    field         = "ingestion_timestamp"
    expiration_ms = var.retention_days * 86400000
  }

  clustering = ["dataset_id", "use_case", "device_id"]

  schema = jsonencode([
    { name = "event_id", type = "STRING", mode = "REQUIRED" },
    { name = "dataset_id", type = "STRING", mode = "NULLABLE" },
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
    { name = "device_id", type = "STRING", mode = "NULLABLE" },
    { name = "route_id", type = "STRING", mode = "NULLABLE" },
    { name = "origin", type = "STRING", mode = "NULLABLE" },
    { name = "destination", type = "STRING", mode = "NULLABLE" },
    { name = "latitude", type = "FLOAT", mode = "NULLABLE" },
    { name = "longitude", type = "FLOAT", mode = "NULLABLE" },
    { name = "speed_kph", type = "FLOAT", mode = "NULLABLE" },
    { name = "heading", type = "FLOAT", mode = "NULLABLE" },
    { name = "temperature_c", type = "FLOAT", mode = "NULLABLE" },
    { name = "humidity_pct", type = "FLOAT", mode = "NULLABLE" },
    { name = "pressure_hpa", type = "FLOAT", mode = "NULLABLE" },
    { name = "co_ppm", type = "FLOAT", mode = "NULLABLE" },
    { name = "co2_ppm", type = "FLOAT", mode = "NULLABLE" },
    { name = "lpg_ppm", type = "FLOAT", mode = "NULLABLE" },
    { name = "smoke_ppm", type = "FLOAT", mode = "NULLABLE" },
    { name = "rainfall_mm", type = "FLOAT", mode = "NULLABLE" },
    { name = "wind_speed_kph", type = "FLOAT", mode = "NULLABLE" },
    { name = "geometry_json", type = "JSON", mode = "NULLABLE" },
    { name = "crs", type = "STRING", mode = "NULLABLE" },
    { name = "schema_version", type = "STRING", mode = "NULLABLE" },
    { name = "quality_flags", type = "STRING", mode = "NULLABLE" }
  ])
}

resource "google_data_loss_prevention_inspect_template" "pii" {
  parent       = "projects/${var.project_id}/locations/${var.region}"
  description  = "Inspect VerdaTrace payloads for common direct identifiers before curation."
  display_name = "verdatrace-pii-inspection"

  inspect_config {
    info_types {
      name = "EMAIL_ADDRESS"
    }
    info_types {
      name = "PHONE_NUMBER"
    }
    info_types {
      name = "PERSON_NAME"
    }
    min_likelihood = "POSSIBLE"
  }
}

resource "google_artifact_registry_repository" "containers" {
  location      = var.region
  repository_id = "verdatrace-data-platform"
  description   = "Container images for VerdaTrace data workloads"
  format        = "DOCKER"
}

resource "google_service_account" "pipeline" {
  account_id   = "verdatrace-data-pipeline"
  display_name = "VerdaTrace pipeline workload"
}

resource "google_service_account" "gke_nodes" {
  account_id   = "verdatrace-gke-nodes"
  display_name = "VerdaTrace GKE nodes"
}

resource "google_pubsub_subscription_iam_member" "pipeline_subscriber" {
  subscription = google_pubsub_subscription.transaction_worker.name
  role         = "roles/pubsub.subscriber"
  member       = "serviceAccount:${google_service_account.pipeline.email}"
}

resource "google_bigquery_dataset_iam_member" "pipeline_editor" {
  dataset_id = google_bigquery_dataset.analytics.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${google_service_account.pipeline.email}"
}

resource "google_storage_bucket_iam_member" "pipeline_archive_creator" {
  bucket = google_storage_bucket.raw_archive.name
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${google_service_account.pipeline.email}"
}

resource "google_secret_manager_secret" "pseudonym_salt" {
  secret_id = "verdatrace-pseudonym-salt"
  replication {
    user_managed {
      replicas {
        location = var.region
      }
    }
  }
}

resource "google_secret_manager_secret_iam_member" "pipeline_secret_reader" {
  secret_id = google_secret_manager_secret.pseudonym_salt.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.pipeline.email}"
}

resource "google_project_iam_member" "node_roles" {
  for_each = toset([
    "roles/artifactregistry.reader",
    "roles/logging.logWriter",
    "roles/monitoring.metricWriter"
  ])
  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.gke_nodes.email}"
}

resource "google_container_cluster" "primary" {
  provider                 = google-beta
  name                     = var.cluster_name
  location                 = var.region
  remove_default_node_pool = true
  initial_node_count       = 1
  deletion_protection      = true

  workload_identity_config {
    workload_pool = "${var.project_id}.svc.id.goog"
  }

  secret_manager_config {
    enabled = true
  }
}

resource "google_container_node_pool" "workers" {
  name       = "worker-pool"
  cluster    = google_container_cluster.primary.name
  location   = var.region
  node_count = 2

  node_config {
    machine_type    = "e2-standard-2"
    service_account = google_service_account.gke_nodes.email
    oauth_scopes    = ["https://www.googleapis.com/auth/cloud-platform"]
    metadata = {
      disable-legacy-endpoints = "true"
    }
    workload_metadata_config {
      mode = "GKE_METADATA"
    }
  }

  depends_on = [google_project_iam_member.node_roles]
}

resource "google_service_account_iam_member" "pipeline_workload_identity" {
  service_account_id = google_service_account.pipeline.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "serviceAccount:${var.project_id}.svc.id.goog[default/verdatrace-data-pipeline]"
}

resource "google_logging_metric" "pipeline_errors" {
  name   = "verdatrace_pipeline_error_count"
  filter = "resource.type=\"k8s_container\" AND severity>=ERROR AND labels.k8s-pod/app=\"verdatrace-data-pipeline\""

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
  }
}

resource "google_monitoring_alert_policy" "pipeline_errors" {
  display_name = "VerdaTrace pipeline processing errors"
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
