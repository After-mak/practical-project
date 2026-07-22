variable "az" {
  description = "사용할 가용영역"
  type        = string
}
variable "cidr_block" {

}
variable "map_public_ip" {

}
variable "name" {

}

variable "vpc_id" {

}
variable "cluster_role_subnet" {
  default = null
  description = "Discern subnet to use the aws lb controller "
}