.PHONY: setup start stop test grade clean logs health grade-infra grade-agent grade-rag grade-accuracy grade-guardrails grade-ui grade-multimodal grade-smoke check-access
PYTHON ?= python
CHECK_PORTKEY ?= 0
GRADER = docker compose -f ../auto-grader/docker-compose.grade.yml run --rm --build grader

setup: check-access
	docker compose up --build -d --wait --wait-timeout 120
	@$(MAKE) health
start:
	docker compose up -d --wait --wait-timeout 120
stop:
	docker compose down
# Implement your own application test command.
test:
	@echo "Implement your application test command here."
	@exit 1
health:
	curl --fail --silent --show-error --retry 10 --retry-connrefused --retry-delay 2 http://localhost:8000/api/v1/health
	curl --fail --silent --show-error http://localhost:3000 > /dev/null
logs:
	docker compose logs -f
# Stops only this project. Persistent volumes are preserved.
clean:
	docker compose down --remove-orphans

# Public evaluation helpers. Report suspected defects; do not weaken checks to inflate scores.
# Interviewer evaluation uses a clean evaluator copy, independent of candidate edits.
grade:
	$(GRADER)
grade-infra:
	$(GRADER) python -m pytest tests/test_infrastructure.py -q
grade-agent:
	$(GRADER) python -m pytest tests/test_agent_loop.py -q
grade-rag:
	$(GRADER) python -m pytest tests/test_rag.py -q
grade-accuracy:
	$(GRADER) python -m pytest tests/test_accuracy.py -q -s
grade-guardrails:
	$(GRADER) python -m pytest tests/test_guardrails.py -q
grade-ui:
	$(GRADER) python -m pytest tests/test_ui.py -q
grade-multimodal:
	$(GRADER) python -m pytest tests/test_multimodal.py -q

# Three varied positive cases for iteration; never a substitute for make grade.
grade-smoke:
	$(GRADER) python -m pytest tests/test_accuracy.py -q -s --accuracy-smoke

# One small request before Docker starts; a failed check stops setup.
check-access:
ifeq ($(CHECK_PORTKEY),1)
	$(PYTHON) ../configure_access.py application-check --env-file .env
else
	@echo "Portkey application check skipped (CHECK_PORTKEY=0); running the equivalent Claude readiness check."
	$(PYTHON) scripts/check_claude_access.py --env-file .env
endif

check-claude-access:
	$(PYTHON) scripts/check_claude_access.py --env-file .env