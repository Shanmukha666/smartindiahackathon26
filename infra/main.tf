locals {
  name_prefix = "ip-sakti-${var.environment}"
}

resource "google_project_service" "required" {
  for_each = toset([
    "artifactregistry.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "sqladmin.googleapis.com",
    "vpcaccess.googleapis.com",
    "servicenetworking.googleapis.com",
  ])

  service            = each.value
  disable_on_destroy = false
}

resource "google_artifact_registry_repository" "containers" {
  location      = var.region
  repository_id = "${local.name_prefix}-containers"
  description   = "Container images for IP-SAKTI Sahayak ${var.environment}."
  format        = "DOCKER"

  depends_on = [google_project_service.required]
}

resource "google_sql_database_instance" "postgres" {
  name             = "${local.name_prefix}-postgres"
  database_version = "POSTGRES_16"
  region           = var.region

  settings {
    tier              = var.db_tier
    availability_type = var.environment == "production" ? "REGIONAL" : "ZONAL"
    disk_type         = "PD_SSD"
    disk_size         = var.environment == "production" ? 50 : 10
    disk_autoresize   = true

    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = var.environment == "production"
    }

    ip_configuration {
      ipv4_enabled    = false
      private_network = "projects/${var.project_id}/global/networks/default"
    }
  }

  deletion_protection = var.environment == "production"
  depends_on          = [google_service_networking_connection.private_services]
}

resource "google_compute_global_address" "private_services" {
  name          = "${local.name_prefix}-private-services"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 16
  network       = "projects/${var.project_id}/global/networks/default"
}

resource "google_service_networking_connection" "private_services" {
  network                 = "projects/${var.project_id}/global/networks/default"
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.private_services.name]
  depends_on              = [google_project_service.required]
}

resource "google_sql_database" "app" {
  name     = "ipsakti"
  instance = google_sql_database_instance.postgres.name
}

resource "google_sql_user" "app" {
  name     = "ipsakti"
  instance = google_sql_database_instance.postgres.name
  password = random_password.db.result
}

resource "google_secret_manager_secret" "database_url" {
  secret_id = "${local.name_prefix}-database-url"

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "database_url" {
  secret      = google_secret_manager_secret.database_url.id
  secret_data = "postgresql://ipsakti:${random_password.db.result}@/${google_sql_database.app.name}?host=/cloudsql/${google_sql_database_instance.postgres.connection_name}"
}

resource "google_secret_manager_secret" "anthropic_api_key" {
  secret_id = "${local.name_prefix}-anthropic-api-key"

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret" "voyage_api_key" {
  secret_id = "${local.name_prefix}-voyage-api-key"

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret" "cohere_api_key" {
  secret_id = "${local.name_prefix}-cohere-api-key"

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret" "bhashini_api_key" {
  secret_id = "${local.name_prefix}-bhashini-api-key"

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret" "jwt_signing_key" {
  secret_id = "${local.name_prefix}-jwt-signing-key"
  replication { auto {} }
}

resource "google_secret_manager_secret" "credential_kek" {
  secret_id = "${local.name_prefix}-credential-kek"
  replication { auto {} }
}

resource "google_secret_manager_secret" "notification_webhook" {
  secret_id = "${local.name_prefix}-notification-webhook"
  replication { auto {} }
}

resource "google_service_account" "backend_runtime" {
  account_id   = "${local.name_prefix}-runtime"
  display_name = "IP-SAKTI Sahayak ${var.environment} runtime"
}

resource "google_secret_manager_secret_iam_member" "run_database_url" {
  secret_id = google_secret_manager_secret.database_url.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.backend_runtime.email}"
}

resource "google_secret_manager_secret_iam_member" "run_anthropic_api_key" {
  secret_id = google_secret_manager_secret.anthropic_api_key.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.backend_runtime.email}"
}

resource "google_secret_manager_secret_iam_member" "run_voyage_api_key" {
  secret_id = google_secret_manager_secret.voyage_api_key.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.backend_runtime.email}"
}

resource "google_secret_manager_secret_iam_member" "run_cohere_api_key" {
  secret_id = google_secret_manager_secret.cohere_api_key.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.backend_runtime.email}"
}

resource "google_secret_manager_secret_iam_member" "run_bhashini_api_key" {
  secret_id = google_secret_manager_secret.bhashini_api_key.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.backend_runtime.email}"
}

resource "google_secret_manager_secret_iam_member" "run_jwt_signing_key" {
  secret_id = google_secret_manager_secret.jwt_signing_key.id
  role = "roles/secretmanager.secretAccessor"
  member = "serviceAccount:${google_service_account.backend_runtime.email}"
}
resource "google_secret_manager_secret_iam_member" "run_credential_kek" {
  secret_id = google_secret_manager_secret.credential_kek.id
  role = "roles/secretmanager.secretAccessor"
  member = "serviceAccount:${google_service_account.backend_runtime.email}"
}
resource "google_secret_manager_secret_iam_member" "run_notification_webhook" {
  secret_id = google_secret_manager_secret.notification_webhook.id
  role = "roles/secretmanager.secretAccessor"
  member = "serviceAccount:${google_service_account.backend_runtime.email}"
}

resource "google_project_iam_member" "run_cloud_sql_client" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.backend_runtime.email}"
}

resource "null_resource" "enable_pgvector" {
  triggers = {
    database_instance = google_sql_database_instance.postgres.connection_name
    database_name     = google_sql_database.app.name
  }

  provisioner "local-exec" {
    command = "gcloud sql databases execute-sql ${google_sql_database_instance.postgres.name} --database=${google_sql_database.app.name} --project=${var.project_id} --sql=\"CREATE EXTENSION IF NOT EXISTS vector;\""
  }
}

resource "random_password" "db" {
  length  = 32
  special = false
}

resource "google_vpc_access_connector" "serverless" {
  name          = "${local.name_prefix}-vpc"
  region        = var.region
  network       = "default"
  ip_cidr_range = "10.8.0.0/28"
  depends_on    = [google_project_service.required]
}

resource "google_cloud_run_v2_service" "backend" {
  name     = "${local.name_prefix}-backend"
  location = var.region

  template {
    service_account = google_service_account.backend_runtime.email

    scaling {
      min_instance_count = var.environment == "production" ? 1 : 0
      max_instance_count = var.environment == "production" ? 10 : 3
    }

    vpc_access {
      connector = google_vpc_access_connector.serverless.id
      egress    = "PRIVATE_RANGES_ONLY"
    }

    containers {
      image = var.backend_image

      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }

      ports {
        container_port = 8000
      }

      env {
        name = "DATABASE_URL"

        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.database_url.id
            version = "latest"
          }
        }
      }

      env {
        name = "ANTHROPIC_API_KEY"

        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.anthropic_api_key.id
            version = "latest"
          }
        }
      }

      env {
        name = "VOYAGE_API_KEY"

        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.voyage_api_key.id
            version = "latest"
          }
        }
      }

      env {
        name = "COHERE_API_KEY"

        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.cohere_api_key.id
            version = "latest"
          }
        }
      }
      env {
        name = "JWT_SIGNING_KEY"
        value_source { secret_key_ref { secret = google_secret_manager_secret.jwt_signing_key.id
                                        version = "latest" } }
      }
      env {
        name = "NOTIFICATION_WEBHOOK_URL"
        value_source { secret_key_ref { secret = google_secret_manager_secret.notification_webhook.id
                                        version = "latest" } }
      }
      env { name = "CREDENTIAL_KEK_SECRET_RESOURCE" value = "${google_secret_manager_secret.credential_kek.id}/versions/latest" }

      env {
        name = "BHASHINI_API_KEY"

        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.bhashini_api_key.id
            version = "latest"
          }
        }
      }

      env {
        name  = "BHASHINI_USER_ID"
        value = var.bhashini_user_id
      }

      env {
        name  = "BHASHINI_API_URL"
        value = "https://dhruva-api.bhashini.gov.in/services/inference/pipeline"
      }

      env {
        name  = "OTEL_SERVICE_NAME"
        value = var.otel_service_name
      }

      env {
        name  = "OTEL_EXPORTER_OTLP_ENDPOINT"
        value = var.otel_exporter_otlp_endpoint
      }

      env {
        name  = "OTEL_TRACES_EXPORTER"
        value = var.otel_traces_exporter
      }

      env {
        name  = "OTEL_METRICS_EXPORTER"
        value = var.otel_metrics_exporter
      }

      env {
        name  = "DEPLOYMENT_ENVIRONMENT"
        value = var.environment
      }

      env {
        name  = "SERVICE_VERSION"
        value = var.service_version
      }
      env { name = "ALLOWED_ORIGINS" value = jsonencode(var.allowed_origins) }
      env { name = "TRUSTED_HOSTS" value = jsonencode(var.trusted_hosts) }
      env { name = "NOTIFICATION_PROVIDER" value = var.notification_provider }
      env { name = "RATE_LIMIT_BACKEND" value = var.rate_limit_backend }
      env { name = "ALLOW_STUB_CONNECTORS" value = "false" }
      env { name = "MAX_REQUEST_BODY_BYTES" value = "9000000" }

      env {
        name  = "VOYAGE_API_URL"
        value = "https://api.voyageai.com/v1/embeddings"
      }

      env {
        name  = "VOYAGE_MODEL"
        value = "voyage-3-large"
      }

      env {
        name  = "COHERE_API_URL"
        value = "https://api.cohere.com/v2/rerank"
      }

      env {
        name  = "COHERE_MODEL"
        value = "rerank-v3.5"
      }

      env {
        name  = "MIN_RELEVANCE"
        value = tostring(var.min_relevance)
      }

      env {
        name  = "ANTHROPIC_API_URL"
        value = "https://api.anthropic.com/v1/messages"
      }

      env {
        name  = "ANTHROPIC_MODEL"
        value = "claude-sonnet-4-6"
      }

      env {
        name  = "ANTHROPIC_API_VERSION"
        value = "2023-06-01"
      }

      env {
        name  = "WEAK_RERANKER_SCORE"
        value = "0.35"
      }
    }

    volumes {
      name = "cloudsql"

      cloud_sql_instance {
        instances = [google_sql_database_instance.postgres.connection_name]
      }
    }
  }

  lifecycle {
    precondition {
      condition = var.environment != "production" || (
        length(var.allowed_origins) > 0 && !contains(var.allowed_origins, "*") &&
        length(var.trusted_hosts) > 0 && !contains(var.trusted_hosts, "*") &&
        var.notification_provider == "webhook" && var.rate_limit_backend == "gateway"
      )
      error_message = "Production requires explicit origins/hosts, webhook notifications, and gateway rate limiting."
    }
  }

  depends_on = [google_project_service.required]
}

