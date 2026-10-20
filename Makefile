.PHONY: build up down logs

# 构建需要 host 网络（pip 走宿主机 loopback 代理）。Compose v5 的 bake 拒绝在
# 配置文件中持久化 network.host 授权，docker compose build 也不支持 --allow，
# 因此构建入口统一为这里的 buildx bake。
build:
	docker buildx bake -f docker-compose.yml --allow=network.host

up: build
	docker compose up -d --no-build --wait

down:
	docker compose down

logs:
	docker compose logs -f
