# iPracticom Sweeper — common tasks
# Use: make <target>

.PHONY: help install test test-fast run status logs uninstall dashboard clean quickstart lint

PYTHON ?= python3
PIP ?= $(PYTHON) -m pip
PKG := ipracticom_sweeper

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

install:  ## Install package in editable mode
	$(PIP) install -e .

quickstart:  ## Run sweeper once (no systemd, no install)
	bash quickstart.sh

test:  ## Run full test suite
	$(PYTHON) -m pytest -v

test-fast:  ## Run tests, stop on first failure
	$(PYTHON) -m pytest -x -q

run:  ## Run a single sweep via CLI
	$(PYTHON) -m $(PKG).sweeper

status:  ## Check systemd timer status
	systemctl status ipracticom-sweeper.timer --no-pager

logs:  ## Tail systemd service logs
	journalctl -u ipracticom-sweeper.service -f

uninstall:  ## Remove systemd units
	bash scripts/install-systemd.sh --uninstall

dashboard:  ## Run the local dashboard
	$(PYTHON) -m $(PKG).dashboard --port 8790

agent-api:  ## Run the standalone agent API
	$(PYTHON) -m $(PKG).agent_api --port 8787

lint:  ## Syntax check all Python files
	$(PYTHON) -m compileall src/

clean:  ## Remove caches and build artifacts
	rm -rf src/*.egg-info .pytest_cache __pycache__ */__pycache__ */*/__pycache__
