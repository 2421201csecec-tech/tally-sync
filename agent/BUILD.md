# Building TallySyncSetup.exe

A Windows .exe can only be built on Windows. Two options:

## A) On your Windows VM / PC
1. Install Python 3.10+ and Inno Setup 6.
2. Copy the `agent/` folder there.
3. Run:  `build_windows.bat https://your-server-url`
4. Result: `output\TallySyncSetup.exe`
5. Copy it to the server's `downloads/` folder. The dashboard's Download button appears automatically.

## B) GitHub Actions (no Windows machine needed)
Push this project to GitHub -> Actions -> "Build Windows installer" -> Run workflow, enter your server URL.
Download the `TallySyncSetup` artifact and put it in `server/downloads/`.

## Important
- The server URL is baked into the exe, so build it for your real public (HTTPS) URL.
- Unsigned exes trigger SmartScreen. Buy a code-signing certificate (or use Azure Trusted Signing)
  and enable the SignTool lines in installer.iss.
- Without the exe, you can still test everything by running `python agent.py` (see README).
