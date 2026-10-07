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
output "web_instance_id" {
  value = aws_instance.role["web"].id
}
output "app_instance_id" {
  value = aws_instance.role["app"].id
}
output "broker_instance_id" {
  value = aws_instance.role["broker"].id
}
output "db_instance_id" {
  value = aws_instance.role["db"].id
}
output "run_id" {
  value = var.run_id
}
