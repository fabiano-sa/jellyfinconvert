# ⚙️ Bootstrap Script (`bootstrap.sh`)

The `bootstrap.sh` script automates the initial setup of this Python project.  
It ensures you have a clean, reproducible development environment in **WSL (Ubuntu/Debian)** or Linux.

---

## 🔑 What the script does

1. **Checks Python availability**
   - Verifies if `python3` is installed.
   - Detects Python version (e.g., 3.10.12).

2. **Ensures the `venv` module**
   - Installs `python3-venv` or the version-specific package (e.g., `python3.10-venv`).

3. **Creates the project structure**
   - Folders: `.vscode/`, `src/app/`, `tests/`.
   - Files: `.gitignore`, `.env`, sample `main.py` and `test_main.py`.

4. **Sets up the virtual environment**
   - Creates `.venv/` using `python3 -m venv`.
   - Activates the venv and upgrades `pip`.

5. **Installs base dependencies**
   - `pytest` → testing
   - `black` → code formatting
   - `ruff` → linting
   - `mypy` → type checking
   - `python-dotenv` → load `.env` files
   - `pre-commit` → Git hooks automation

6. **Configures editor integration**
   - `.vscode/settings.json` configured for:
     - Using `.venv/bin/python`
     - Pytest enabled
     - Auto-formatting with Black/Ruff
   - `.env` with `PYTHONPATH=src`.

7. **Generates configuration files**
   - `pyproject.toml` with configs for Black, Ruff, MyPy, and Pytest.
   - `.pre-commit-config.yaml` with hooks:
     - Syntax & whitespace checks
     - Black (formatter)
     - Ruff (linter + autofix)
     - MyPy (type checks)
     - Local hook: run pytest on `git push`

8. **Installs pre-commit hooks**
   - Runs `pre-commit install` (for pre-commit).
   - Runs `pre-commit install --hook-type pre-push` (for pre-push).
   - Updates hook versions automatically (`autoupdate`).

9. **Creates a Makefile** *(if not present)*
   - Commands: `make test`, `make lint`, `make fmt`, `make check`, `make pre-commit-install`, etc.

10. **Runs everything once**
    - Executes `pre-commit run --all-files`.
    - Runs `pytest -q`.

---

## 🚀 How to use

```bash
# Run once after cloning the repo
chmod +x bootstrap.sh
./bootstrap.sh


## After that

```bash
# Activate virtualenv
source .venv/bin/activate

# Run tests, lint, type-check
make check

# Run the application
make run

## 📂 Created Project Structure
```bash
.
├── .env
├── .gitignore
├── .pre-commit-config.yaml
├── Makefile
├── bootstrap.sh
├── pyproject.toml
├── src/
│   └── app/
│       ├── __init__.py
│       └── main.py
├── tests/
│   └── test_main.py
└── .vscode/
    └── settings.json

## ✅ Benefits
Consistency: every developer has the same setup.

Automation: no need to remember manual steps.
Best practices included: formatting, linting, typing, testing.
Safety: code is checked before commits and pushes.
Scalability: easy to extend for CI/CD pipelines later.