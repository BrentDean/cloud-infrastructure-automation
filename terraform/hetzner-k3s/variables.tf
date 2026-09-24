variable "name" {
  description = "Dedicated throwaway node name; never use the existing staging-vps name."
  type        = string
  default     = "k3s-lab-portfolio"

  validation {
    condition     = can(regex("^k3s-lab-[a-z0-9-]+$", var.name))
    error_message = "The name must start with k3s-lab- to prevent collisions with staging."
  }
}

variable "operator_cidr" {
  description = "Operator public IPv4 address as a /32. Only SSH is allowed."
  type        = string

  validation {
    condition     = can(cidrhost(var.operator_cidr, 0)) && endswith(var.operator_cidr, "/32") && length(split(".", split("/", var.operator_cidr)[0])) == 4
    error_message = "operator_cidr must be a valid IPv4 /32, such as 203.0.113.10/32."
  }
}

variable "ssh_public_key_path" {
  description = "Path to a local operator SSH public key, never a private key."
  type        = string
  default     = "~/.ssh/id_ed25519.pub"
}

variable "location" {
  description = "Hetzner Cloud location; choose a location supporting the server type."
  type        = string
  default     = "nbg1"
}

variable "server_type" {
  description = "Disposable single-node k3s machine; check Hetzner pricing before apply."
  type        = string
  default     = "cx23"
}

variable "existing_ssh_key_id" {
  description = "Optional ID of an already registered Hetzner SSH key; avoids duplicate fingerprint errors when sharing an operator key with another VPS."
  type        = number
  default     = null
}
