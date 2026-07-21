terraform {
  backend "s3" {
    bucket       = "tfstate-bucket-95ada58d"
    key          = "mak-tf-lock"
    region       = "ap-northeast-2"
    profile      = "kt_cloud_infra2"
    use_lockfile = true
    encrypt      = true # tstate 에는 민감한 정보가 들어있어 암호화
  }
}
