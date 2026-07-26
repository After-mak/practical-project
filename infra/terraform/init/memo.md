### 버전이 안 맞아서 init이나 plan 실패시 대처방법

```bash
terraform init -upgrade

```

### Error: Backend configuration changed 대처방법

```bash
[user1@mgmt infra]$ terraform init -reconfigure -backend-config="profile=admin-프로필명"
```