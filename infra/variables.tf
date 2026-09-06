variable "project_id" {
  description = "Google Cloud project ID."
  type        = string
}

variable "region" {
  description = "Google Cloud region for regional resources."
  type        = string
  default     = "asia-south1"
}

variable "environment" {
  description = "Deployment environment, normally staging or production."
  type        = string

  validation {
    condition     = contains(["staging", "production"], var.environment)
    error_message = "environment must be staging or production."
  }
}

variable "db_tier" {
  description = "Cloud SQL machine tier."
  type        = string
  default     = "db-f1-micro"
}

variable "backend_image" {
  description = "Fully qualified backend container image in Artifact Registry."
  type        = string
}

variable "otel_service_name" {
  description = "OpenTelemetry service name for the backend."
  type        = string
  default     = "ip-sakti-sahayak-backend"
}

variable "otel_exporter_otlp_endpoint" {
  description = "Generic production OTLP gRPC endpoint; replace for the chosen observability backend."
  type        = string
  default     = "https://otel-collector.example.com:4317"
}

variable "otel_traces_exporter" {
  description = "OpenTelemetry trace exporter mode, for example otlp or none."
  type        = string
  default     = "otlp"
}

variable "min_relevance" {
  description = "Minimum reranker relevance score required for retrieval results."
  type        = number
  default     = 0.35

  validation {
    condition     = var.min_relevance >= 0 && var.min_relevance <= 1
    error_message = "min_relevance must be between 0 and 1."
  }
}

variable "otel_metrics_exporter" {
  description = "OpenTelemetry metrics exporter mode, normally otlp or none."
  type        = string
  default     = "otlp"
}

variable "service_version" {
  description = "Deployed backend version recorded on telemetry resources."
  type        = string
  default     = "0.1.0"
}

variable "allowed_origins" { type = list(string) default = [] }
variable "trusted_hosts" { type = list(string) default = [] }
variable "notification_provider" {
  type    = string
  default = "logging"
  validation {
    condition     = contains(["logging", "webhook"], var.notification_provider)
    error_message = "notification_provider must be logging or webhook."
  }
}
variable "rate_limit_backend" {
  type    = string
  default = "memory"
  validation {
    condition     = contains(["memory", "gateway"], var.rate_limit_backend)
    error_message = "rate_limit_backend must be memory or gateway."
  }
}

variable "bhashini_user_id" {
  description = "Bhashini account user ID sent with Indic-language service requests."
  type        = string
  default     = ""
}
