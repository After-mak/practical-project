terraform {
  backend "s3" {
    bucket       = "tfstate-bucket-95ada58e"
    key          = "dev-k8s/terraform.tfstate"
    region       = "ap-northeast-2"
    use_lockfile = true
    encrypt      = true
  }
}
