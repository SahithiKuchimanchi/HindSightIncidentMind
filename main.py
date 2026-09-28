"""IncidentMind FastAPI backend."""
import os
from typing import Dict

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .agent import IncidentAgent

app = FastAPI(title="IncidentMind API", version="1.0.0")

allowed_origins = [x.strip() for x in os.getenv("CORS_ORIGINS", "*").split(",") if x.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=allowed_origins != ["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

agents: Dict[str, IncidentAgent] = {}

def get_agent(session_id: str) -> IncidentAgent:
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")
    if session_id not in agents:
        agents[session_id] = IncidentAgent()
    return agents[session_id]

class AnalyzeRequest(BaseModel):
    session_id: str = Field(min_length=8, max_length=128)
    error: str = Field(min_length=1, max_length=30000)

class ResolveRequest(BaseModel):
    session_id: str = Field(min_length=8, max_length=128)
    root_cause: str = Field(min_length=1, max_length=10000)
    resolution: str = Field(min_length=1, max_length=10000)
    runbook: str = Field(default="", max_length=2000)
    outcome: str = Field(min_length=1, max_length=100)

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/api/health")
def api_health(session_id: str | None = None):
    return {"status": "ok", **(get_agent(session_id).health() if session_id else {})}

@app.post("/api/analyze")
def analyze(req: AnalyzeRequest):
    try:
        return get_agent(req.session_id).analyze(req.error.strip())
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Incident analysis failed: {exc}")

@app.post("/api/incidents/{incident_id}/resolve")
def resolve(incident_id: str, req: ResolveRequest):
    agent = get_agent(req.session_id)
    try:
        ok = agent.resolve_incident(
            incident_id, req.root_cause, req.resolution, req.runbook, req.outcome
        )
        if not ok:
            raise HTTPException(status_code=404, detail="Incident not found")
        return {"ok": True, "incident": agent.get_incident(incident_id)}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Resolution save failed: {exc}")

@app.get("/api/session")
def session_state(session_id: str):
    agent = get_agent(session_id)
    return {"incidents": agent.incidents, "health": agent.health()}
