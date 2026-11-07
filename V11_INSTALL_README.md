# SmartMoney V11 installation

1. Extract the release ZIP.
2. Open PowerShell in the extracted `SmartMoney_V11` folder.
3. Run `Set-ExecutionPolicy -Scope Process Bypass`.
4. Run `./INSTALL_SMARTMONEY_V11.ps1` (or pass `-TargetPath`).
5. The installer backs up the existing target, copies source files while preserving `.env` and runtime data, installs Python/Node dependencies and runs backend tests.
6. Start the API from `backend`: `.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001`.
7. Start the frontend from `frontend`: `npm run dev`.
8. Open `http://localhost:3000/v11`. Register a new user, create a Binance or MT5 paper account and use simulated prices only.

The installer does not create broker credentials and does not enable live trading.
