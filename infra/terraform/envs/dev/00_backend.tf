terraform {
  backend "s3" {
    bucket         = "tfstate-bucket-4f95baeb"
    key            = "mak-tf-lock"
    region         = "ap-northeast-2"
    use_lockfile   = true
	encrypt = true # tstate 에는 민감한 정보가 들어있어 암호화
  }
}