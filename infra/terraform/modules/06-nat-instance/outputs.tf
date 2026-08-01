output "nat_instance_id" {
  description = "The ID of the NAT instance"
  value       = aws_instance.nat.id
}

output "private_ip" {
  description = "The private IP address of the NAT instance"
  value       = aws_instance.nat.private_ip
}

output "public_ip" {
  description = "The public IP address of the NAT instance"
  value       = aws_eip.nat_eip.public_ip
}

output "primary_network_interface_id" {
  description = "The ID of the primary network interface of the NAT instance"
  value       = aws_instance.nat.primary_network_interface_id
}
