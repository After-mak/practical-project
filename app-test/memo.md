```bash
docker build -t yimjongwon/mak-test:1.0 .
docker push yimjongwon/mak-test:1.0

docker run -d \
  -p 8000:8000 \
  --name mak-fastapi-app \
  -e GITOPS_TOKEN="GITOPS_토큰값" \
  -e TELEGRAM_BOT_TOKEN="텔레그램_봇_토큰값" \
  -e TELEGRAM_CHAT_ID="텔레그램_채팅_ID" \
  yimjongwon/mak-test:1.0

docker rm mak-fastapi-app
docker rm -f $(docker ps -aq)
docker ps

http://172.16.8.200:8000/telegram/send-test?replicas=4


k config use kubernetes-admin@kubernetes
k config get-contexts

```