.PHONY: run test check package
run:
	./start.sh

test:
	python3 -m pytest

check:
	python3 -m py_compile server.py help_parser.py
	@if command -v node >/dev/null 2>&1; then node --check static/app.js; fi
	bash -n install.sh start.sh uninstall.sh

package:
	cd .. && zip -r ai-cli-command-center-v2.0.0.zip ai-cli-command-center -x '*/__pycache__/*' '*/.pytest_cache/*'
