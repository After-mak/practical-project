# alb를 삭제하기전에 eks를 삭제하는 부분을 방지하는 부분

``` bash
# 사용을 마친 후 깔끔하게 지우기 위한 옵션
kubectl delete applications --all -n argocd
# 해당 위치에서 실행practical-project\infra\terraform\envs\dev\k8s
terraform destroy "-target=kubectl_manifest.gateway" "-target=kubectl_manifest.gatewayclass" "-target=kubectl_manifest.lb_config" -auto-approve
# 이후 terraform destroy --auto-approve


terraform destroy --auto-approve
```
# inflate.yaml 파일로 karpenter가 작동하는지 확인하는 방법
kubectl apply -f inflate.yaml
이후
kubectl scale deployment inflate --replicas=10
테스트를 종료하고싶다면
kubectl scale deployment inflate --replicas=0
이후
kubectl delete -f inflate.yaml

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