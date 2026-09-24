.PHONY: run test check
run:
	python -m uvicorn app.main:app --reload --port 8000

test:
	pytest -q

check:
	python -m compileall -q app tests
	ruff check app tests
	pytest -q
