terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.40"
    }
    archive = {
      source  = "hashicorp/archive"
      version = ">= 2.4"
    }
  }
  # State is kept locally (infra/terraform.tfstate, git-ignored). To share it,
  # move it to an S3 backend.
}

provider "aws" {
  region = var.region
  default_tags {
    tags = { Project = "hearten" }
  }
}
