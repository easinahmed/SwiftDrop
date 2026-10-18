# SwiftDrop developer tasks.  Run `make help` for a summary.
PY ?= .venv/bin/python
PYTHON_BIN ?= /Library/Frameworks/Python.framework/Versions/3.14/bin/python3.14

.PHONY: help setup ui dev run test test-network lint typecheck check binaries app dmg selftest clean

help:
	@echo "setup        create .venv and install Python + frontend dependencies"
	@echo "ui           build the web UI into swiftdrop/ui/web"
	@echo "run          run the app from source"
	@echo "dev          run the UI in a browser with the preview bridge (no engine)"
	@echo "test         run the test suite (local fixtures only)"
	@echo "test-network run tests that reach public websites too"
	@echo "lint         ruff + eslint"
	@echo "typecheck    mypy + tsc"
	@echo "check        lint + typecheck + test"
	@echo "binaries     provision FFmpeg into vendor/bin"
	@echo "app / dmg    build dist/SwiftDrop.app and the DMG (packaging/build_macos.sh)"
	@echo "selftest     run the end-to-end self test from source"

setup:
	$(PYTHON_BIN) -m venv .venv
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -r requirements-dev.txt
	cd frontend && npm ci --no-audit --no-fund

ui:
	cd frontend && npm run build

run: ui
	$(PY) -m swiftdrop

dev:
	cd frontend && npm run dev

test:
	$(PY) -m pytest
	cd frontend && npm test

test-network:
	SWIFTDROP_NETWORK_TESTS=1 $(PY) -m pytest

lint:
	$(PY) -m ruff check swiftdrop tests scripts packaging
	cd frontend && npm run lint

typecheck:
	$(PY) -m mypy
	cd frontend && npm run typecheck

check: lint typecheck test

binaries:
	$(PY) scripts/fetch_binaries.py

app dmg:
	packaging/build_macos.sh

selftest:
	$(PY) -m swiftdrop --self-test

clean:
	rm -rf build dist packaging/generated .pytest_cache .mypy_cache .ruff_cache
