# Yesterday Timeline — developer commands.
#
# Everything runs locally. `make dev` is the one command you normally need.

PY := server/.venv/Scripts/python.exe
ifeq ($(OS),)
PY := server/.venv/bin/python
endif

.DEFAULT_GOAL := help
.PHONY: help install install-server install-frontend dev dev-backend dev-frontend \
        build sync open test test-server test-frontend test-e2e clean-data discover

help:  ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

install: install-server install-frontend  ## Install backend and frontend dependencies

install-server:  ## Create the Python venv and install the server
	uv venv --python 3.12 server/.venv
	uv pip install --python $(PY) -e "server[dev]"

install-frontend:  ## Install frontend dependencies
	cd frontend && npm install

dev:  ## Start the backend API and the frontend dev server together
	@echo "Backend  -> http://127.0.0.1:8000"
	@echo "Frontend -> http://127.0.0.1:3000"
	@$(MAKE) -j2 dev-backend dev-frontend

dev-backend:  ## Start only the FastAPI backend (with reload)
	cd server && ../$(PY) -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

dev-frontend:  ## Start only the Vite dev server
	cd frontend && npm run dev

build:  ## Build the frontend so the backend can serve it on one URL
	cd frontend && npm run build

sync:  ## Fetch and process yesterday from the configured sources
	$(PY) -c "import sys; sys.path.insert(0,'server'); \
	import asyncio; from app.storage.repository import Repository; \
	from app.services.sync import SyncService; from app.config.settings import get_settings; \
	s=get_settings(); r=Repository(s.database_url, s.database_path); \
	t=asyncio.run(SyncService(r).sync(force_refresh=True)); \
	print(t.date, t.summary.raw_record_count, 'raw records,', t.summary.normalized_event_count, 'events')"

open:  ## Open the timeline in the default browser
	$(PY) -c "import webbrowser; webbrowser.open('http://127.0.0.1:8000')"

discover:  ## List Home Assistant entities the timeline can use
	$(PY) scripts/discover_home_assistant.py --yaml

test: test-server test-frontend  ## Run backend and frontend unit tests

test-server:  ## Run the pytest suite
	cd server && ../$(PY) -m pytest -q

test-frontend:  ## Run the vitest suite
	cd frontend && npm test

test-e2e:  ## Run the Playwright end-to-end suite (needs a running app)
	cd frontend && npm run test:e2e

clean-data:  ## Delete every locally cached record
	$(PY) -c "import sys; sys.path.insert(0,'server'); \
	from app.storage.repository import Repository; from app.config.settings import get_settings; \
	s=get_settings(); print(Repository(s.database_url, s.database_path).clear())"
