# Tally Sync

    tally-sync/
      server/   FastAPI server: website (signup, dashboard, pairing approval, installer download) + agent API
      agent/    Windows agent + installer scripts that produce TallySyncSetup.exe
      .github/  optional: builds the .exe on GitHub's Windows runners

## 1. Run the server (easiest: Docker)
    cd server
    # edit SECRET_KEY / passwords / PUBLIC_URL in docker-compose.yml
    docker compose up --build
    # open http://localhost:8000  -> Sign up

## 2. Test the agent WITHOUT building the exe
    cd agent
    # inside your Windows VM (or anywhere that can reach Tally), set:
    #   TALLYSYNC_API=http://<server-address>:8000
    # and %APPDATA%\TallySync\config.json  (or ~/.tallysync/config.json) with
    #   {"tally_url": "http://localhost:9000", "since": "2023-04-01"}
    python agent.py --no-tray
    # -> shows a code and opens the browser -> click Allow -> tick companies on the dashboard

## 3. Build the real installer (needs Windows) - see agent/BUILD.md
    agent\build_windows.bat https://api.yourdomain.com
    copy agent\output\TallySyncSetup.exe  server\downloads\
    # the dashboard now shows "Download agent for Windows"
