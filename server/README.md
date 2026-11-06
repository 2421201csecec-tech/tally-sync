# Tally Sync - Server (FastAPI)

Website (signup, dashboard, "Allow this agent?" page, installer download) + agent API.

## Run with Docker (recommended)
    # edit SECRET_KEY, DB password and PUBLIC_URL in docker-compose.yml first
    docker compose up --build
    # http://localhost:3000

## Run without Docker
    pip install -r requirements.txt
    createdb tallysync && psql tallysync -f schema.sql
    export DATABASE_URL=postgresql://localhost/tallysync SECRET_KEY=<long random string> PUBLIC_URL=http://localhost:3000
    uvicorn main:app --host 0.0.0.0 --port 8000

Start the Next.js frontend separately:

    cd ../frontend
    npm install
    BACKEND_URL=http://localhost:8000 npm run dev

The frontend proxies `/api/*` and `/v1/*` to FastAPI. In production, expose the
frontend URL as `PUBLIC_URL` so the Windows agent opens the Next.js pairing page.

## Deploying to Render and Vercel

Create a managed PostgreSQL database and a Render web service using this
directory as the Docker context. Configure the Render service with:

    DATABASE_URL=<Render internal PostgreSQL URL>
    SECRET_KEY=<long random production secret>
    PUBLIC_URL=https://<your-vercel-domain>
    HTTPS_ONLY=1
    DOWNLOADS_DIR=/app/downloads

Render provides the `PORT` variable; the Dockerfile uses it automatically.
The free tier has no persistent disk, so host `TallySyncSetup.exe` outside
Render, for example as a public GitHub Release asset, and set:

    INSTALLER_URL=https://github.com/<owner>/<repo>/releases/download/<tag>/TallySyncSetup.exe

The dashboard then shows the download button and the API redirects the
authenticated merchant to that external file. A persistent disk is optional;
if `/app/downloads/TallySyncSetup.exe` exists, the API serves that local file
instead.

For Vercel, import the `frontend/` directory and set:

    BACKEND_URL=https://<your-render-service>.onrender.com

The value must be available during the Vercel build because it is used by the
Next.js rewrite for `/api/*` and `/v1/*`. Set the Render `PUBLIC_URL` to the
Vercel URL, not the Render API URL. Build the Windows installer with the Render
service URL:

    build_windows.bat https://<your-render-service>.onrender.com

For the free tier, upload `TallySyncSetup.exe` as the GitHub Release asset and
set `INSTALLER_URL` on Render. No file needs to be copied into the Render
container.

## Serving the installer
Build TallySyncSetup.exe on Windows (see ../agent/BUILD.md) and put it in `downloads/`.

## Dev shortcut (skip pairing)
    python create_agent.py "Merchant name" "Demo Traders"   # prints a token, pre-enables the company

## Production checklist
HTTPS (nginx/Caddy) + HTTPS_ONLY=1, strong SECRET_KEY, rate limiting on /api/auth/* and /v1/pair/*,
database backups, email verification / password reset.
