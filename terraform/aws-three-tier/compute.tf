data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"] # Canonical
  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*"]
  }
  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

resource "aws_key_pair" "lab" {
  key_name_prefix = "aws-three-tier-${var.run_id}-"
  public_key      = trimspace(var.ssh_public_key)
  tags            = { Name = "lab-key-${var.run_id}" }
}

locals {
  instances = {
    web = { subnet_id = aws_subnet.role["web"].id, sg_id = aws_security_group.web.id, public_ip = true }
    app = { subnet_id = aws_subnet.role["app"].id, sg_id = aws_security_group.app.id, public_ip = false }
    db  = { subnet_id = aws_subnet.role["db"].id, sg_id = aws_security_group.db.id, public_ip = false }
  }
}

resource "aws_instance" "role" {
  for_each                    = local.instances
  ami                         = data.aws_ami.ubuntu.id
  instance_type               = var.app_runtime == "k3s" && each.key == "app" ? var.k3s_app_instance_type : var.instance_type
  subnet_id                   = each.value.subnet_id
  vpc_security_group_ids      = [each.value.sg_id]
  associate_public_ip_address = each.value.public_ip
  key_name                    = aws_key_pair.lab.key_name
  user_data                   = file("${path.module}/cloud-init.yaml")

  metadata_options {
    http_endpoint = "enabled"
    http_tokens   = "required"
  }
  credit_specification {
    cpu_credits = "standard"
  }
  root_block_device {
    volume_type           = "gp3"
    volume_size           = var.app_runtime == "k3s" && each.key == "app" ? 24 : 12
    encrypted             = true
    delete_on_termination = true
  }
  tags = { Name = "lab-${each.key}-${var.run_id}", Tier = each.key, Runtime = each.key == "app" ? var.app_runtime : "native" }
  depends_on = [
    aws_route_table_association.public,
    aws_route_table_association.private,
    aws_vpc_security_group_egress_rule.outbound
  ]
}
