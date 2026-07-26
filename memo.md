# alb를 삭제하기전에 eks를 삭제하는 부분을 방지하는 부분

``` bash
terraform destroy -target kubectl_manifest.route -target kubectl_manifest.gateway -target kubectl_manifest.gatewayclass -target kubectl_manifest.target_group_config -target kubectl_manifest.lb_config -auto-approve

terraform destroy --auto-approve
```


# 클러스터를 새로 만들었거나 재배포시 update-kubeconfig

```bash
aws eks update-kubeconfig \
  --region ap-northeast-2 \
  --name project03-eks \
  --profile admin-이름
```

# 테스트용
kubectl logs -n default -l app=userservice -f --tail=50

kubectl rollout restart deployment/userservice -n default

kubectl get pod -n default -l app=userservice