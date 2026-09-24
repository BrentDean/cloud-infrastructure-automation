output "server_ipv4" {
  description = "Public IPv4; the provider firewall admits only operator SSH."
  value       = hcloud_server.k3s.ipv4_address
}

output "server_name" {
  description = "Safety gate for scripts: must have k3s-lab- prefix."
  value       = hcloud_server.k3s.name
}

output "ssh_command" {
  description = "Connect using the private counterpart of ssh_public_key_path."
  value       = "ssh labops@${hcloud_server.k3s.ipv4_address}"
}

output "server_id" {
  description = "Dedicated lab server resource ID (not the staging server)."
  value       = hcloud_server.k3s.id
}
