#!/usr/bin/env bash
set -euo pipefail

PROJECT_NAME="${PROJECT_NAME:-meu-projeto}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
PKGS="pytest black ruff mypy python-dotenv pre-commit"
VENV_DIR=".venv"

echo "🔎 Checking Python..."
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "❌ $PYTHON_BIN not found. Install Python 3 first."; exit 1
fi

PY_VER="$($PYTHON_BIN -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')"
echo "✅ Found Python $PY_VER"

echo "🔧 Ensuring venv module..."
if ! $PYTHON_BIN -m venv --help >/dev/null 2>&1; then
  if command -v apt >/dev/null 2>&1; then
    echo "📦 Installing python$PY_VER-venv (requires sudo)..."
    sudo apt update -y
    if ! sudo apt install -y "python${PY_VER}-venv"; then
      sudo apt install -y python3-venv
    fi
  else
    echo "❌ venv not available and no apt found. Install the venv package for your distro."; exit 1
  fi
fi

echo "📁 Creating folders..."
mkdir -p .vscode src/app tests

echo "🐍 Creating virtualenv..."
if [ ! -d "$VENV_DIR" ]; then
  $PYTHON_BIN -m venv "$VENV_DIR"
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

echo "⬆️  Upgrading pip..."
$PYTHON_BIN -m pip install --upgrade pip

echo "📦 Installing base packages..."
pip install $PKGS

echo "🧹 Writing .gitignore (if missing)..."
if [ ! -f .gitignore ]; then
  cat > .gitignore <<'EOF'
.venv/
__pycache__/
*.pyc
*.pyo
.pytest_cache/
.mypy_cache/
.ruff_cache/
.env
EOF
fi

echo "📝 Creating sample app & test (if missing)..."
[ -f src/app/__init__.py ] || : > src/app/__init__.py
if [ ! -f src/app/main.py ]; then
  cat > src/app/main.py <<'EOF'
def hello(name: str) -> str:
    return f"Olá, {name}!"

if __name__ == "__main__":
    print(hello("Fabi"))
EOF
fi
if [ ! -f tests/test_main.py ]; then
  cat > tests/test_main.py <<'EOF'
from app.main import hello

def test_hello():
    assert hello("Fabi") == "Olá, Fabi!"
EOF
fi

echo "⚙️  Configuring VSCode (WSL-friendly)..."
cat > .vscode/settings.json <<'EOF'
{
  "python.defaultInterpreterPath": "${workspaceFolder}/.venv/bin/python",
  "python.testing.pytestEnabled": true,
  "python.testing.pytestArgs": ["tests"],
  "editor.formatOnSave": true,
  "editor.codeActionsOnSave": {
    "source.organizeImports.ruff": "explicit",
    "source.fixAll.ruff": "explicit"
  },
  "python.envFile": "${workspaceFolder}/.env"
}
EOF

# Ensure PYTHONPATH for IDE/debug sessions
[ -f .env ] || echo "PYTHONPATH=src" > .env

echo "📦 Writing pyproject.toml (only if missing)..."
if [ ! -f pyproject.toml ]; then
  cat > pyproject.toml <<'EOF'
[project]
name = "meu-projeto"
version = "0.1.0"
requires-python = ">=3.10"

[tool.black]
line-length = 100
target-version = ["py310"]

[tool.ruff]
line-length = 100
fix = true

[tool.ruff.lint]
select = ["E", "F", "I", "UP"]
ignore = []

[tool.mypy]
python_version = "3.10"
strict = false
warn_unused_ignores = true
warn_redundant_casts = true
warn_unused_configs = true
disallow_untyped_defs = true
no_implicit_optional = true
exclude = ["tests/"]

[tool.pytest.ini_options]
addopts = "-q"
testpaths = ["tests"]
pythonpath = ["src"]
EOF
else
  echo "  (pyproject.toml already exists; not overwriting)"
fi

echo "🪝 Configuring pre-commit..."
cat > .pre-commit-config.yaml <<'EOF'
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.6.0
    hooks:
      - id: check-ast
      - id: check-yaml
      - id: end-of-file-fixer
      - id: trailing-whitespace

  - repo: https://github.com/psf/black
    rev: 24.8.0
    hooks:
      - id: black
        args: ["--line-length=100"]

  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.6.9
    hooks:
      - id: ruff
        args: ["--fix"]
      - id: ruff-format

  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.11.2
    hooks:
      - id: mypy
        args: ["--config-file=pyproject.toml"]
        files: "^src/"

  - repo: local
    hooks:
      - id: pytest-on-push
        name: pytest (pre-push)
        entry: bash -c 'pytest -q'
        language: system
        pass_filenames: false
        stages: [pre-push]

default_stages: [pre-commit]
EOF

pre-commit install
pre-commit install --hook-type pre-push
pre-commit autoupdate || true
pre-commit migrate-config || true

echo "🛠  Creating Makefile (only if missing)..."
if [ ! -f Makefile ]; then
  cat > Makefile <<'EOF'
# Use bash for "source"
SHELL := /bin/bash

PY=python
PIP=pip

.PHONY: help
help:
	@echo "Comandos:"
	@echo "  make venv                 - cria a venv (.venv)"
	@echo "  make install              - instala deps (pytest/black/ruff/mypy/dotenv/pre-commit)"
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
	@echo "  make clean                - apaga caches"

.PHONY: venv
venv:
	python3 -m venv .venv

.PHONY: install
install:
	. .venv/bin/activate && $(PY) -m pip install --upgrade pip && \
	$(PIP) install pytest black ruff mypy python-dotenv pre-commit

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

.PHONY: run
run:
	. .venv/bin/activate && $(PY) -m src.app.main

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

.PHONY: clean
clean:
	rm -rf __pycache__ .pytest_cache .mypy_cache .ruff_cache
EOF
else
  echo "  (Makefile already exists; not overwriting)"
fi

echo "🏃 Running hooks on all files once..."
pre-commit run --all-files || true

echo "🧪 Running tests..."
pytest -q || true

echo ""
echo "✅ Bootstrap finished!"
echo "Next steps:"
echo "  1) source .venv/bin/activate"
echo "  2) make check   # (or) ruff/mypy/pytest manually"
echo "  3) python -m src.app.main"
echo ""
