output "web_public_ip" {
  value = aws_instance.role["web"].public_ip
}
output "web_private_ip" {
  value = aws_instance.role["web"].private_ip
}
output "app_private_ip" {
  value = aws_instance.role["app"].private_ip
}
output "broker_private_ip" {
  value = aws_instance.role["broker"].private_ip
}
output "db_private_ip" {
  value = aws_instance.role["db"].private_ip
}
output "run_id" {
  value = var.run_id
}


output "instance_ids" {
  description = "Terraform-owned EC2 instance IDs for the optional CDK operations layer."
  value = {
    web    = aws_instance.role["web"].id
    app    = aws_instance.role["app"].id
    broker = aws_instance.role["broker"].id
    db     = aws_instance.role["db"].id
  }
}
