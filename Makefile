PYTHON ?= python

up:
	docker compose up --build -d

down:
	docker compose down

test:
	$(PYTHON) -m pytest -q

lint:
	$(PYTHON) -m compileall -q src tests

seed:
	$(PYTHON) scripts/seed_demo.py

demo:
	$(PYTHON) scripts/attack_demo.py

run:
	$(PYTHON) -m uvicorn app.main:app --reload --app-dir src

real-test:
	RUN_REAL_STACK=1 $(PYTHON) -m pytest -q tests/integration/test_real_stack.py
