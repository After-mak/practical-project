
# 프로젝트명 & 부제

## GitOps 기반 Kubernetes 리소스 라이트사이징 자동화 시스템 구축

> 부제: Prometheus·KRR 분석 결과를 운영자 승인 후 GitOps로 반영하고 절감 효과를 검증하는 Closed-Loop FinOps 파이프라인


### 💠 팀명

- 일과후 막걸리

### 💠 팀원

- 임종원(팀장), 이성규(부팀장), 김민규, 송민기, 한윤성, 최상우, 오영식

### 💠 프로젝트 배경

클라우드 환경에서는 사용량에 따라 비용이 발생하기 때문에, 리소스를 과하게 할당하거나 사용하지 않는 서비스를 계속 운영하면 불필요한 비용이 증가한다.

특히 Kubernetes 환경에서는 Pod, Deployment, Namespace, Node 단위로 리소스가 동적으로 생성되고 확장되기 때문에, 단순히 AWS Budget이나 Cost Explorer만으로는 어떤 애플리케이션이 리소스 낭비를 유발하는지 파악하기 어렵다.

기존 OpenCost, KRR, Goldilocks와 같은 도구는 Kubernetes 리소스 사용량과 비용 낭비 요소를 분석하고 권장값을 제시할 수 있지만, 실제 운영 환경에 리소스 설정을 반영하는 과정은 운영자의 수동 작업에 의존한다. 또한 비업무 시간대나 트래픽 변동에 따른 동적 스케일링까지 비용 최적화 관점에서 통합 관리하는 체계는 부재한 경우가 많다.

본 프로젝트는 이러한 한계를 보완하기 위해 Prometheus와 KRR을 통해 수집·분석된 리소스 권장값을 FastAPI 기반 FinOps 분석 엔진에서 정책 검증한 뒤, 운영자 승인 과정을 거쳐 Helm values에 반영하고 Argo CD를 통해 Kubernetes 클러스터에 자동 배포하는 Closed-Loop FinOps 파이프라인을 구축한다. 나아가 KEDA를 활용한 이벤트 기반 오토스케일링과 Chronos2를 활용한 시간대별 스케줄 스케일링을 결합하여, 트래픽 패턴과 업무 시간에 따라 Pod 수를 자동으로 조절함으로써 유휴 리소스로 인한 비용 낭비를 최소화한다.

이를 통해 단순한 비용 가시화가 아니라, **탐지 → 권장 → 운영자 승인 → GitOps 반영 → 전후 검증**까지 이어지는 리소스 Right-Sizing 자동화와, **KEDA·Chronos2 기반의 동적 스케일링**을 통한 런타임 비용 최적화를 하나의 파이프라인으로 통합하는 운영 자동화 구조를 구현하고자 한다.

### 💠 프로젝트 구조

```text
practical-project/
├── ☁️ infra/                      # 인프라스트럭처 정의 (IaC & Scaling)
│   ├── KEDA/                       # KEDA 이벤트 기반 Autoscaling 설정
│   └── terraform/                  # AWS Terraform 구성
│       ├── envs/                   # 환경별 구성 (dev / prod)
│       ├── init/                   # S3, DynamoDB 등 Terraform 백엔드 및 초기화
│       └── modules/                # 재사용 가능한 인프라 모듈
│           ├── 01-vpc ~ 06-nat     # 네트워크 및 보안 모듈
│           ├── 08-eks ~ 10-rds     # 컴퓨팅 및 데이터베이스 (EKS, ECR, RDS)
│           ├── 11-karpenter_setup  # 노드 오토스케일러 (Karpenter)
│           ├── 12-alb ~ 14-gateway # 로드밸런서 및 Route53
│           └── 15-argocd ~ 17-...  # CI/CD 및 ElastiCache
│
├── 🚀 apps/ & app-test/           # Bank Of Anthos 마이크로서비스
│   ├── apps/
│   │   └── sample-fastapi/         # FastAPI 메인 서비스 (API, Worker, Redis Queue)
│   └── app-test/                   # Bank of Anthos 기반 테스트 마이크로서비스
│       ├── accounts/               # 계정 서비스 & Accounts DB 
│       ├── contacts/               # Contacts Python 서비스
│       ├── userservice/            # UserService Python 서비스
│       ├── frontend/               # Web Frontend (Flask, Static Assets, Templates)
│       ├── ledger/                 # Java/Spring 기반 원장 서비스
│       │   ├── balancereader/      # 잔액 조회 서비스
│       │   ├── ledgerwriter/       # 원장 기록 서비스
│       │   └── transactionhistory/ # 거래 내역 서비스
│       └── components/             # Kustomize 공통 컴포넌트 (Cloud SQL, Ingress 등)
│
├── ☸️ k8s/                        # Kubernetes 배포 매니페스트
│   └── sample-fastapi/             # Deployment, Service, ServiceMonitor 설정
│
├── 📈 chronos/ & alarm/           # 예측 오토스케일링 & 알림 시스템
│   ├── chronos/                    # Prometheus 연동 시계열 예측 오토스케일러
│   └── alarm/                      # 모니터링 리포트 생성 및 전송 스크립트
│
├── 💰 finops/                     # 비용 최적화 (FinOps)
│   ├── app/                        # FinOps 분석 및 리포팅 엔진
│   ├── charts/finops/              # FinOps K8s Helm Chart
│   └── scripts/                    # KRR(Kubernetes Resource Recommendation) 백필 스크립트
│
├── 🧪 k6/                         # 성능 및 부하 테스트
│   ├── cpu-load.js / memory-load.js# 리소스 부하 테스트
│   ├── karpenter-stress.js         # Karpenter 노드 증설 테스트
│   └── queue-scale-*.js            # 큐 기반 스케일링 테스트
│
├── 📚 docs/                       # 프로젝트 문서 및 테스트 결과
│   ├── *-runbook.md                # 운영 런북 (Chronos, Redis Queue 등)
│   └── test-results/               # 부하 테스트 결과 (JSON/MD)
│
└── 🛠️ Root Scripts & Configs      # 로컬 개발 및 제어 스크립트
    ├── docker-compose.yml          # 로컬 컨테이너 실행 환경
    ├── Makefile / setup.sh         # 프로젝트 설정 및 자동화 명령
    └── memo.md                     # 메모
```

## 🔐 Repository Secrets

GitHub Actions 워크플로우 실행 및 GitOps/ECR 연동을 위해 설정된 Repository Secrets 목록입니다.

| Name | Description | 
| :--- | :--- |
| `AWS_ACCESS_KEY_ID` | AWS IAM 봇 계정 액세스 키 | 
| `AWS_SECRET_ACCESS_KEY` | AWS IAM 봇 계정 시크릿 키 | 
| `GITOPS_TOKEN` | ECR 이미지 푸시 및 GitOps CI/CD 파이프라인 전용 AWS IAM 액세스 토큰 | 

---

### 👥 IAM 계정 권한 및 운용 체계

본 프로젝트는 단일 AWS Root 계정 환경에서 최소 권한 원칙(Principle of Least Privilege)을 준수하여 IAM 유저를 분리·운용

* **팀원 개인 계정 (7명):** 팀원 7명(임종원, 이성규, 김민규, 송민기, 한윤성, 최상우, 오영식)은 각각 개별 IAM User 계정을 할당받아 인프라 구축 및 개발 작업 역할에 맞게 분업 진행
* **CI/CD 전용 봇 계정 (1개):** GitHub Actions 워크플로우 및 GitOps 파이프라인 자동화를 위해 팀원 개인 계정과 분리된 `ECR 전용 IAM Bot 계정`을 별도로 생성
  * 해당 봇 계정에는 보안 최적화를 위해 **Amazon ECR 권한만 최소한으로 부여**하여 Secrets (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `GITOPS_TOKEN`)로 안전하게 관리