output "artifact_registry_repository" {
  value = google_artifact_registry_repository.containers.name
}

output "backend_service_url" {
  value = google_cloud_run_v2_service.backend.uri
}

output "database_connection_name" {
  value = google_sql_database_instance.postgres.connection_name
}
