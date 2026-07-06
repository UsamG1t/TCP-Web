.PHONY: dev build push deploy logs stop clean

# Development
dev:
	docker compose -f docker-compose.dev.yml up --build

dev-down:
	docker compose -f docker-compose.dev.yml down

# Production build
build:
	docker compose -f docker-compose.yml build

# Push to registry (requires login)
push:
	docker compose -f docker-compose.yml push

# Deploy on VPS (requires SSH)
deploy:
	ssh $(VPS_USER)@$(VPS_HOST) "cd /opt/tcp-simulator && git pull && docker compose pull && docker compose up -d"

# View logs
logs:
	docker compose -f docker-compose.yml logs -f

# Stop all
stop:
	docker compose -f docker-compose.yml down
	docker compose -f docker-compose.dev.yml down

# Clean everything
clean:
	docker system prune -af
	docker volume prune -f
