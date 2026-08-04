.PHONY: run test lint check validate package clean docker-build

VERSION := 3.4.1

run:
	./start.sh

test:
	python3 -m pytest

lint:
	@if command -v ruff >/dev/null 2>&1; then ruff check server.py help_parser.py storage.py tests; else echo "ruff not installed; skipping optional lint"; fi

check:
	python3 -m py_compile server.py help_parser.py storage.py
	python3 -m compileall -q server.py help_parser.py storage.py tests
	@if command -v node >/dev/null 2>&1; then node --check static/app.js; else echo "node not installed; skipping JavaScript syntax check"; fi
	bash -n install.sh start.sh uninstall.sh

validate: check lint test

package: clean
	cd .. && zip -r zeaz-ai-command-center-v$(VERSION).zip zeaz-ai-command-center \
		-x '*/__pycache__/*' '*/.pytest_cache/*' '*/.ruff_cache/*' '*/.git/*' '*.sqlite3*' '*/.venv/*' '*/.qwen/*' '*/dist/*' '*/node_modules/*'

build:
	./build.sh

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache .coverage htmlcov

docker-build:
	docker build -t zeaz-ai-command-center:$(VERSION) .
