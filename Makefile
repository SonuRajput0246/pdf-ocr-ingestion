.PHONY: install dev test lint sample-data run ingest evaluate docker-build docker-up clean

install:
	pip install -r requirements.txt

dev:
	pip install -r requirements-dev.txt

test:
	pytest -q

lint:
	ruff check app tests scripts

sample-data:
	python scripts/make_sample_pdfs.py

run:
	python -m app.cli serve

ingest:
	python -m app.cli ingest data/sample_mixed.pdf --tenant demo --application study-001

evaluate:
	python scripts/evaluate.py

docker-build:
	docker compose build

docker-up:
	docker compose up

clean:
	rm -rf .data .pytest_cache .ruff_cache
