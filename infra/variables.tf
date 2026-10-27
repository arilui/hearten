variable "region" {
  description = "AWS region; us-west-2 sits next to the Neon database."
  type        = string
  default     = "us-west-2"
}

variable "database_url_parameter" {
  description = "SSM Parameter Store name (SecureString) holding the Neon connection string. Create it by hand; Terraform never sees the value."
  type        = string
  default     = "/hearten/database_url"
}

variable "allowed_origins" {
  description = "Website origins allowed to call the API (CORS)."
  type        = list(string)
  default     = ["http://localhost:3000", "https://hearten-frontend.vercel.app"]
}

variable "github_repository" {
  description = "owner/repo allowed to deploy new code from its main branch."
  type        = string
  default     = "arilui/hearten"
}

variable "github_owner_id" {
  description = "Numeric GitHub account ID of the repo owner. GitHub's OIDC subject now includes it (repo:owner@id/repo@id:...), which keeps the trust tied to this account even if a name is reused."
  type        = string
  default     = "152670736"
}

variable "github_repository_id" {
  description = "Numeric GitHub repository ID (see github_owner_id)."
  type        = string
  default     = "1416514584"
}

variable "create_github_oidc_provider" {
  description = "AWS allows one GitHub OIDC provider per account. Set false if your account already has one (for example, from another project's deploys)."
  type        = bool
  default     = true
}

variable "throttle_rate_per_second" {
  description = "Steady request limit for the public API, which also caps cost."
  type        = number
  default     = 5
}

variable "throttle_burst" {
  type    = number
  default = 10
}
