# Use bash para suportar "source"
SHELL := /bin/bash

PY=python
PIP=pip

# -------------------------
# Ajuda
# -------------------------
.PHONY: help
help:
	@echo "Comandos mais usados:"
	@echo "  make venv                 - cria a venv (.venv)"
	@echo "  make install              - instala deps básicas (pytest/black/ruff/mypy/dotenv)"
	@echo "  make run                  - roda a app (python -m src.app.main)"
	@echo "  make test                 - pytest -q"
	@echo "  make lint                 - ruff check ."
	@echo "  make fmt                  - black src tests"
	@echo "  make type                 - mypy src"
	@echo "  make check                - lint + type + test"
	@echo "  make pre-commit-install   - instala hooks (pre-commit e pre-push)"
	@echo "  make pre-commit-run       - roda hooks em todos os arquivos"
	@echo "  make pre-commit-update    - atualiza versões dos hooks"
	@echo "  make pre-commit-clean     - remove hook legado (.git/hooks/pre-push.legacy)"
	@echo "  make clean                - apaga caches (.pytest_cache, .mypy_cache, etc.)"

# -------------------------
# Ambiente
# -------------------------
.PHONY: venv
venv:
	python3 -m venv .venv

.PHONY: install
install:
	. .venv/bin/activate && $(PY) -m pip install --upgrade pip && \
	$(PIP) install pytest black ruff mypy python-dotenv pre-commit

# -------------------------
# Qualidade
# -------------------------
.PHONY: fmt lint type test check
fmt:
	. .venv/bin/activate && black src tests

lint:
	. .venv/bin/activate && ruff check .

type:
	. .venv/bin/activate && mypy src

test:
	. .venv/bin/activate && pytest -q

check: lint type test

# -------------------------
# Execução
# -------------------------
.PHONY: run
run:
	. .venv/bin/activate && $(PY) -m src.app.main

# -------------------------
# pre-commit
# -------------------------
.PHONY: pre-commit-install pre-commit-run pre-commit-update pre-commit-clean
pre-commit-install:
	. .venv/bin/activate && pre-commit install && pre-commit install --hook-type pre-push

pre-commit-run:
	. .venv/bin/activate && pre-commit run --all-files

pre-commit-update:
	. .venv/bin/activate && pre-commit autoupdate && pre-commit migrate-config || true
	@echo "Se necessário, reinstale hooks: make pre-commit-install"

pre-commit-clean:
	@test ! -f .git/hooks/pre-push.legacy || rm .git/hooks/pre-push.legacy && echo "Removido .git/hooks/pre-push.legacy"

# -------------------------
# Limpeza
# -------------------------
.PHONY: clean
clean:
	rm -rf __pycache__ .pytest_cache .mypy_cache .ruff_cache
