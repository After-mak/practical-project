# alb를 삭제하기전에 eks를 삭제하는 부분을 방지하는 부분

``` bash
terraform destroy -target kubectl_manifest.route -target kubectl_manifest.gateway -target kubectl_manifest.gatewayclass -target kubectl_manifest.target_group_config -target kubectl_manifest.lb_config -auto-approve

terraform destroy --auto-approve
```