#  modules/02-subnet/variables.tf

variable "vpc_id" {
  description = "서브넷들이 소속될 vpc의 id"
  type = string
}

variable "public_subnets" {
  type = list(string)
}


variable "private_subnets" {
  type = list(string)
}

variable "database_subnets" {
  type = list(string)
}