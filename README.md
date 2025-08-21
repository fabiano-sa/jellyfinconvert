# Meu Projeto em Python

Base em Python 3.10 no WSL, com testes, lint e format.

## Setup
```bash
python3 --version            # deve mostrar 3.10.x
sudo apt update
sudo apt install -y python3.10-venv

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install pytest black ruff mypy python-dotenv
