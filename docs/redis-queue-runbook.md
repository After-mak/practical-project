# Redis Queue 및 Worker 로컬 실행

## 구성

- `redis`: AOF가 활성화된 Redis 7.4
- `sample-api-1`: `http://localhost:8000`
- `sample-api-2`: `http://localhost:8001`
- `queue-worker`: `worker` 프로필을 지정할 때 실행

두 API는 `dev:sample:queue`를 공유합니다. API 컨테이너를 재시작해도 Redis가 유지되는 동안 Queue 데이터는 남습니다.

## API와 Redis 실행

```powershell
docker compose up -d --build redis sample-api-1 sample-api-2
Invoke-RestMethod http://localhost:8000/ready
Invoke-RestMethod -Method Post http://localhost:8000/api/queue/join
Invoke-RestMethod http://localhost:8001/api/queue/status
docker compose exec redis redis-cli LLEN dev:sample:queue
```

## Worker 실행

```powershell
docker compose --profile worker up -d --scale queue-worker=2 queue-worker
docker compose --profile worker logs -f queue-worker
```

Worker는 Redis `BLPOP`으로 작업을 가져옵니다. 하나의 작업은 하나의 Worker만 가져가지만, `BLPOP` 이후 Worker 프로세스가 비정상 종료되면 해당 작업을 잃을 수 있습니다. 운영용 신뢰성 Queue가 필요하면 processing list 또는 Redis Streams 도입이 필요합니다.

## 종료

```powershell
docker compose --profile worker down
```

Redis 데이터까지 삭제하려면 명시적으로 `-v`를 추가합니다.

```powershell
docker compose --profile worker down -v
```
