.PHONY: gen backfill backend frontend test demo

# Continuous normal traffic, polling data/control.json for demo injections.
# Run as a module (not `python generator/generate.py`) so its `from
# generator.scenarios import ...` resolves with the repo root on sys.path.
gen:
	python -m generator.generate --rate 30

# 24h of normal historical logs so every (service, hour_of_day) baseline is warm.
backfill:
	python -m generator.generate --backfill-hours 24

# Wired up in Milestone 5 (API + WebSocket).
backend:
	cd backend && uvicorn app.main:app --reload

# Wired up in Milestone 6 (Frontend).
frontend:
	cd frontend && npm run dev

test:
	python -m pytest backend/tests -q

# Wired up in Milestone 7: backfill + generator + backend + frontend together.
demo:
	@echo "make demo is assembled in Milestone 7 once the backend and frontend exist."
