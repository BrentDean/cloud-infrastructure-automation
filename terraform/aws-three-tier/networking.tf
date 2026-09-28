data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  availability_zone = data.aws_availability_zones.available.names[0]
  role_cidrs = {
    web = "10.20.1.0/24"
    app = "10.20.2.0/24"
    db  = "10.20.3.0/24"
  }
}

resource "aws_vpc" "lab" {
  cidr_block           = "10.20.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = { Name = "aws-three-tier-${var.run_id}" }
}

resource "aws_internet_gateway" "lab" {
  vpc_id = aws_vpc.lab.id
  tags   = { Name = "lab-igw-${var.run_id}" }
}

resource "aws_subnet" "role" {
  for_each                = local.role_cidrs
  vpc_id                  = aws_vpc.lab.id
  cidr_block              = each.value
  availability_zone       = local.availability_zone
  map_public_ip_on_launch = false
  tags                    = { Name = "lab-${each.key}-${var.run_id}", Tier = each.key }
}

resource "aws_eip" "nat" {
  domain = "vpc"
  tags   = { Name = "lab-nat-ip-${var.run_id}" }
}

resource "aws_nat_gateway" "lab" {
  allocation_id = aws_eip.nat.id
  subnet_id     = aws_subnet.role["web"].id
  depends_on    = [aws_internet_gateway.lab]
  tags          = { Name = "lab-nat-${var.run_id}" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.lab.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.lab.id
  }
  tags = { Name = "lab-public-${var.run_id}" }
}

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.lab.id
  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.lab.id
  }
  tags = { Name = "lab-private-${var.run_id}" }
}

resource "aws_route_table_association" "public" {
  subnet_id      = aws_subnet.role["web"].id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table_association" "private" {
  for_each       = toset(["app", "db"])
  subnet_id      = aws_subnet.role[each.key].id
  route_table_id = aws_route_table.private.id
}

resource "aws_security_group" "web" {
  name_prefix = "lab-web-${var.run_id}-"
  description = "SSH and demo HTTP only from workstation"
  vpc_id      = aws_vpc.lab.id
  tags        = { Name = "lab-web-${var.run_id}" }
}
resource "aws_security_group" "app" {
  name_prefix = "lab-app-${var.run_id}-"
  description = "SSH and HTTP backend only from web SG"
  vpc_id      = aws_vpc.lab.id
  tags        = { Name = "lab-app-${var.run_id}" }
}
resource "aws_security_group" "db" {
  name_prefix = "lab-db-${var.run_id}-"
  description = "SSH from web, PostgreSQL only from app SG"
  vpc_id      = aws_vpc.lab.id
  tags        = { Name = "lab-db-${var.run_id}" }
}

resource "aws_vpc_security_group_ingress_rule" "web_ssh" {
  security_group_id = aws_security_group.web.id
  cidr_ipv4         = var.allowed_cidr
  ip_protocol       = "tcp"
  from_port         = 22
  to_port           = 22
}
resource "aws_vpc_security_group_ingress_rule" "web_http" {
  security_group_id = aws_security_group.web.id
  cidr_ipv4         = var.allowed_cidr
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
}
resource "aws_vpc_security_group_ingress_rule" "private_ssh" {
  for_each                     = { app = aws_security_group.app.id, db = aws_security_group.db.id }
  security_group_id            = each.value
  referenced_security_group_id = aws_security_group.web.id
  ip_protocol                  = "tcp"
  from_port                    = 22
  to_port                      = 22
}
resource "aws_vpc_security_group_ingress_rule" "app_http" {
  security_group_id            = aws_security_group.app.id
  referenced_security_group_id = aws_security_group.web.id
  ip_protocol                  = "tcp"
  from_port                    = var.app_runtime == "k3s" ? 30080 : 8000
  to_port                      = var.app_runtime == "k3s" ? 30080 : 8000
}
resource "aws_vpc_security_group_ingress_rule" "db_postgres" {
  security_group_id            = aws_security_group.db.id
  referenced_security_group_id = aws_security_group.app.id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}
resource "aws_vpc_security_group_egress_rule" "outbound" {
  for_each          = { web = aws_security_group.web.id, app = aws_security_group.app.id, db = aws_security_group.db.id }
  security_group_id = each.value
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
}
