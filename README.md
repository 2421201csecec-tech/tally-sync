# Tally Sync

    tally-sync/
      server/   FastAPI server: merchant JSON API + agent API
      frontend/ Next.js merchant UI
      agent/    Windows agent + installer scripts that produce TallySyncSetup.exe
      .github/  optional: builds the .exe on GitHub's Windows runners

## 1. Run the server (easiest: Docker)
    cd server
    # edit SECRET_KEY / passwords / PUBLIC_URL in docker-compose.yml
    docker compose up --build
    # open http://localhost:3000  -> Sign up

## 2. Test the agent WITHOUT building the exe
    cd agent
    # inside your Windows VM (or anywhere that can reach Tally), set:
    #   TALLYSYNC_API=http://<server-address>:8000
    # and %APPDATA%\TallySync\config.json  (or ~/.tallysync/config.json) with
    #   {"tally_url": "http://localhost:9000", "since": "2023-04-01"}
    python agent.py --no-tray
    # -> shows a code and opens the browser -> click Allow -> tick companies on the dashboard

## 3. Build the real installer (needs Windows) - see agent/BUILD.md
    agent\build_windows.bat https://app.yourdomain.com
    copy agent\output\TallySyncSetup.exe  server\downloads\
    # the dashboard now shows "Download agent for Windows"

The Next.js frontend owns the merchant pages and proxies `/api/*` and `/v1/*`
traffic to FastAPI. FastAPI remains the database-backed service and continues
to own the agent ingestion API.

For production, deploy `server/` as a Render web service with a managed
PostgreSQL database, and deploy `frontend/` to Vercel. Set the Vercel
`BACKEND_URL` to the Render service URL, and set Render `PUBLIC_URL` to the
Vercel URL. See `server/README.md` for the required environment variables and
installer storage setup. On Render's free tier, host the Windows installer as
a GitHub Release asset and configure `INSTALLER_URL`.
