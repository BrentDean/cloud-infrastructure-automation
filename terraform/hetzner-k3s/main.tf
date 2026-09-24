locals {
  operator_key = trimspace(file(pathexpand(var.ssh_public_key_path)))
}

resource "hcloud_ssh_key" "operator" {
  name       = "${var.name}-operator"
  public_key = local.operator_key
}

resource "hcloud_firewall" "k3s" {
  name = "${var.name}-ssh-only"

  rule {
    direction   = "in"
    protocol    = "tcp"
    port        = "22"
    source_ips  = [var.operator_cidr]
    description = "SSH from the operator IPv4 only"
  }
}

resource "hcloud_server" "k3s" {
  name        = var.name
  image       = "ubuntu-24.04"
  server_type = var.server_type
  location    = var.location
  ssh_keys    = [hcloud_ssh_key.operator.id]
  firewall_ids = [
    hcloud_firewall.k3s.id
  ]

  public_net {
    ipv4_enabled = true
    ipv6_enabled = false
  }

  backups = false

  user_data = templatefile("${path.module}/cloud-init.yaml.tftpl", {
    ssh_public_key = local.operator_key
  })

  labels = {
    purpose     = "portfolio-k3s-disposable"
    managed_by  = "terraform"
    environment = "isolated-lab"
  }

  lifecycle {
    precondition {
      condition     = startswith(var.name, "k3s-lab-")
      error_message = "Refusing to target non-lab server names."
    }
  }
}
