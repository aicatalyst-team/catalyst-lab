.PHONY: setup lint lint-python lint-markdown test pre-commit

setup:
	pip install pre-commit ruff pylint
	npm install -g markdownlint-cli
	pre-commit install
	@echo "Setup complete. Run 'make lint' to verify."

lint: lint-python lint-markdown

lint-python:
	ruff check .
	ruff format --check .
	pylint project-golem/*.py scripts/*.py

lint-markdown:
	markdownlint '**/*.md' --ignore node_modules

test:
	pre-commit run --all-files

pre-commit:
	pre-commit run --all-files
