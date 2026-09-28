# 🧠 IncidentMind — Deployment Ready

This version preserves the existing Streamlit UI and user flow while moving
agent execution behind FastAPI. Hindsight remains the durable memory layer.

## Architecture
```text
Browser → Streamlit UI → FastAPI → IncidentAgent → Hindsight + Groq
```

## What was changed
- Existing Streamlit interface retained; no React/Next/Lovable frontend.
- Added FastAPI backend with `/health`, `/api/health`, `/api/analyze`,
  `/api/incidents/{id}/resolve`, and `/api/session`.
- Streamlit now uses configurable `BACKEND_URL` instead of direct agent calls.
- Hindsight updated to current bank-scoped Retain and Recall endpoints.
- Added Hindsight Reflect as optional supplementary historical context.
- API keys remain server-side; frontend receives only analysis/results.
- Added `.env.example`, `.gitignore`, Dockerfile, docker-compose, and deployment docs.

## Environment
Set these on the **backend**:
```text
GROQ_API_KEY
GROQ_MODEL=ur_api_key
HINDSIGHT_API_URL=https://api.hindsight.vectorize.io
HINDSIGHT_API_KEY
HINDSIGHT_BANK_ID=incident-response-agent
HINDSIGHT_USE_REFLECT=true
HINDSIGHT_TIMEOUT_SECONDS=15
CORS_ORIGINS=https://YOUR-STREAMLIT-APP
```

Set these on the **frontend**:
```text
BACKEND_URL=https://YOUR-BACKEND
BACKEND_TIMEOUT_SECONDS=45
```

## Local run
Create and activate a virtual environment, then:
```bash
pip install -r requirements.txt
```

Backend:
```bash
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

Frontend, in a second terminal:
```bash
streamlit run frontend/app.py
```

Open `http://localhost:8501`.

For local use, `.env` can contain all variables. The frontend only uses
`BACKEND_URL`; the backend uses the Groq/Hindsight secrets.

## Streamlit Cloud
Deploy this repository and select:
```text
frontend/app.py
```
Add only:
```toml
BACKEND_URL = "https://YOUR-BACKEND"
BACKEND_TIMEOUT_SECONDS = "45"
```
under App Settings → Secrets.

## Backend deployment
Recommended beginner-friendly choices: Render or Railway.

Start command:
```bash
uvicorn backend.main:app --host 0.0.0.0 --port $PORT
```

Add all backend environment variables above. Set `CORS_ORIGINS` to the exact
Streamlit HTTPS origin.

## Docker
```bash
cp .env.example .env
# fill in GROQ_API_KEY and HINDSIGHT_API_KEY
docker compose up --build
```
Then Streamlit is on `http://localhost:8501` and FastAPI on `http://localhost:8000`.

## Test
1. Open Streamlit.
2. Enter the first demo PostgreSQL connection-pool incident.
3. Click Analyze Incident.
4. Record an engineer-verified resolution.
5. Enter the second related PostgreSQL incident.
6. Confirm Memory Evidence / recalled experience is displayed.
7. Check backend `/health`.

## Troubleshooting
- **Backend unavailable:** verify `BACKEND_URL` and open its `/health` URL.
- **CORS:** set `CORS_ORIGINS` to the exact Streamlit origin.
- **Groq error:** configure `GROQ_API_KEY` on the backend only.
- **Hindsight 404:** use the included current bank-scoped endpoints; do not revert
  to `/v1/retain` or `/v1/recall`.
- **No memory immediately after retain:** Hindsight processing may be asynchronous;
  wait briefly before testing recall.
- **Deployed frontend calling localhost:** change `BACKEND_URL` to the public
  HTTPS backend URL.
