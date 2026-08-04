.PHONY: run dev-setup test lint check validate build lifecycle package clean docker-build

VERSION := $(shell python3 -c 'from version import __version__; print(__version__)')

dev-setup:
	python3 -m venv .venv
	.venv/bin/python -m pip install --disable-pip-version-check --upgrade pip
	.venv/bin/python -m pip install --disable-pip-version-check -e '.[dev]'
	@echo "Developer environment ready. Activate it with: source .venv/bin/activate"

run:
	./start.sh

test:
	python3 -m pytest

lint:
	@if command -v ruff >/dev/null 2>&1; then ruff check server.py help_parser.py storage.py gui.py version.py tests; else echo "ruff not installed; skipping optional lint"; fi

check:
	python3 -m py_compile server.py help_parser.py storage.py gui.py version.py
	python3 -m compileall -q server.py help_parser.py storage.py gui.py version.py tests
	@if command -v node >/dev/null 2>&1; then node --check static/app.js; else echo "node not installed; skipping JavaScript syntax check"; fi
	bash -n install.sh start.sh uninstall.sh build.sh tests/lifecycle.sh

validate: check lint test

build:
	./build.sh

lifecycle:
	bash tests/lifecycle.sh

package: clean
	cd .. && zip -r zeaz-ai-command-center-v$(VERSION).zip zeaz-ai-command-center \
		-x '*/__pycache__/*' '*/.pytest_cache/*' '*/.ruff_cache/*' '*/.git/*' '*.sqlite3*' '*/.venv/*' '*/.venv-build/*' '*/.qwen/*' '*/dist/*' '*/node_modules/*'

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache .coverage htmlcov build dist *.egg-info

docker-build:
	docker build --build-arg APP_VERSION=$(VERSION) -t zeaz-ai-command-center:$(VERSION) .
