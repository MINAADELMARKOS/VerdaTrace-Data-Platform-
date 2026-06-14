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
  default     = "ey-data-engineering-gke"
}

provider "google" {
  project = var.project_id
  region  = var.region
}

resource "google_pubsub_topic" "transaction_events" {
  name = "ey-transaction-events"
}

resource "google_pubsub_subscription" "transaction_worker" {
  name                       = "ey-transaction-worker"
  topic                      = google_pubsub_topic.transaction_events.id
  ack_deadline_seconds       = 60
  message_retention_duration = "604800s"
}

resource "google_bigquery_dataset" "analytics" {
  dataset_id                 = "ey_data_engineering"
  location                   = "EU"
  delete_contents_on_destroy = false
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

resource "google_service_account" "pipeline" {
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

resource "google_secret_manager_secret" "pseudonym_salt" {
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

output "pubsub_topic" {
  value = google_pubsub_topic.transaction_events.name
}

output "pubsub_subscription" {
  value = google_pubsub_subscription.transaction_worker.name
}

output "bigquery_table" {
  value = "${var.project_id}.${google_bigquery_dataset.analytics.dataset_id}.${google_bigquery_table.processed_events.table_id}"
}
