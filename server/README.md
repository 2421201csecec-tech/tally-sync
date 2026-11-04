# Tally Sync - Server (FastAPI)

Website (signup, dashboard, "Allow this agent?" page, installer download) + agent API.

## Run with Docker (recommended)
    # edit SECRET_KEY, DB password and PUBLIC_URL in docker-compose.yml first
    docker compose up --build
    # http://localhost:8000

## Run without Docker
    pip install -r requirements.txt
    createdb tallysync && psql tallysync -f schema.sql
    export DATABASE_URL=postgresql://localhost/tallysync SECRET_KEY=<long random string> PUBLIC_URL=http://localhost:8000
    uvicorn main:app --host 0.0.0.0 --port 8000

## Serving the installer
Build TallySyncSetup.exe on Windows (see ../agent/BUILD.md) and put it in `downloads/`.

## Dev shortcut (skip pairing)
    python create_agent.py "Merchant name" "Demo Traders"   # prints a token, pre-enables the company

## Production checklist
HTTPS (nginx/Caddy) + HTTPS_ONLY=1, strong SECRET_KEY, rate limiting on /login and /v1/pair/*,
database backups, email verification / password reset.
