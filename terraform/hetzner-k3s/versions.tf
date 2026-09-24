terraform {
  required_version = ">= 1.5.0"

  required_providers {
    hcloud = {
      source  = "hetznercloud/hcloud"
      version = "~> 1.68.0"
    }
  }
}

provider "hcloud" {
  # HCLOUD_TOKEN is read from the workstation environment.
}
