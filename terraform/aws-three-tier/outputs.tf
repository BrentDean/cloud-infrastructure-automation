output "web_public_ip" {
  value = aws_instance.role["web"].public_ip
}
output "web_private_ip" {
  value = aws_instance.role["web"].private_ip
}
output "app_private_ip" {
  value = aws_instance.role["app"].private_ip
}
output "db_private_ip" {
  value = aws_instance.role["db"].private_ip
}
output "run_id" {
  value = var.run_id
}
