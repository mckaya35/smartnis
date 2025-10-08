PY=python

install:
	$(PY) -m venv .venv
	. .venv/bin/activate && pip install -r requirements.txt -r requirements-dev.txt

lint:
	. .venv/bin/activate && ruff check . --fix
	. .venv/bin/activate && black .
	. .venv/bin/activate && mypy . || true
	. .venv/bin/activate && bandit -r . || true

run:
	. .venv/bin/activate && $(PY) trader.py

paper:
	. .venv/bin/activate && $(PY) async_trader.py

logs:
	tail -n 200 -f logs/app.log


