PYTHON ?= .venv/bin/python

.PHONY: verificar humo demo
.PHONY: panel
panel:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m pasteles.panel

verificar:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m pytest -c pyproject.toml

humo: verificar demo
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m pasteles evals validar
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m pasteles evals pagos

.PHONY: verificar-hermes
verificar-hermes:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tools/verificar_hermes.py

demo:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m pasteles demo
