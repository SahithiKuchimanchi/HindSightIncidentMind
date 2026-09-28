"""
Incident Response Agent — Core Logic
Uses Hindsight (Vectorize) for persistent incident memory + Groq (Qwen3-32b) for reasoning.
"""

import os
import hashlib
import re
import requests
import json
from datetime import datetime
from collections import Counter
from groq import Groq
from dotenv import load_dotenv

load_dotenv()


def get_config(name: str, default: str = "") -> str:
    """Read config from environment first, then Streamlit Cloud secrets."""
    value = os.getenv(name)
    if value:
        return value
    try:
        import streamlit as st
        return str(st.secrets.get(name, default))
    except Exception:
        return default


# ---------------------------------------------------------------------------
# Hindsight Cloud Memory
# ---------------------------------------------------------------------------

class HindsightMemory:
    """Small REST wrapper around Hindsight retain/recall operations."""

    def __init__(self):
        self.api_key = get_config("HINDSIGHT_API_KEY")
        self.base_url = get_config(
            "HINDSIGHT_API_URL",
            get_config("HINDSIGHT_BASE_URL", "https://api.hindsight.vectorize.io"),
        ).rstrip("/")
        self.bank_id = get_config("HINDSIGHT_BANK_ID", "incident-response-agent")
        self.timeout = float(get_config("HINDSIGHT_TIMEOUT_SECONDS", "15"))
        self._headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _bank_url(self, operation: str) -> str:
        return f"{self.base_url}/v1/default/banks/{self.bank_id}/{operation}"

    def retain(self, content: str, metadata: dict | None = None) -> dict:
        """Persist durable incident experience in Hindsight Cloud."""
        if not self.api_key:
            return {}
        body = {"items": [{
            "content": content,
            "context": json.dumps(metadata or {}, ensure_ascii=False),
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }]}
        try:
            r = requests.post(
                self._bank_url("memories"),
                params={"async": "false"},
                headers=self._headers,
                json=body,
                timeout=self.timeout,
            )
            return r.json() if r.ok else {}
        except requests.RequestException:
            return {}

    def recall(self, query: str, budget: str = "mid") -> list[dict]:
        """Retrieve relevant historical experience from Hindsight Cloud."""
        if not self.api_key:
            return []
        body = {
            "query": query,
            "budget": budget,
            "types": ["experience", "observation"],
            "prefer_observations": True,
        }
        try:
            r = requests.post(
                self._bank_url("memories/recall"),
                headers=self._headers,
                json=body,
                timeout=self.timeout,
            )
            if not r.ok:
                return []
            data = r.json()
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                return data.get("results", data.get("memories", []))
            return []
        except requests.RequestException:
            return []

    def reflect(self, query: str, budget: str = "mid") -> str:
        """Synthesize an answer over retained memories using Hindsight Reflect."""
        if not self.api_key:
            return ""
        try:
            r = requests.post(
                self._bank_url("reflect"),
                headers=self._headers,
                json={"query": query, "budget": budget},
                timeout=self.timeout,
            )
            if not r.ok:
                return ""
            data = r.json()
            if isinstance(data, str):
                return data
            if isinstance(data, dict):
                return str(data.get("text") or data.get("answer") or "")
            return ""
        except requests.RequestException:
            return ""



# ---------------------------------------------------------------------------
# Error classification / fingerprinting
# ---------------------------------------------------------------------------

CATEGORY_KEYWORDS = {
    "Database": ["sql", "database", "db", "postgres", "mysql", "mongo", "query",
                 "connection pool", "timeout", "deadlock", "migration", "sequelize",
                 "prisma", "orm", "table", "index", "transaction"],
    "Network": ["network", "dns", "tcp", "http", "socket", "ssl", "tls",
                 "connection refused", "econnrefused", "econnreset", "latency",
                 "502", "503", "504", "gateway", "proxy", "cors", "fetch"],
    "Memory": ["memory", "heap", "oom", "out of memory", "leak", "gc",
                "garbage collect", "allocation", "buffer", "stack overflow"],
    "Auth": ["auth", "token", "jwt", "session", "permission", "401", "403",
              "forbidden", "unauthorized", "oauth", "saml", "credential",
              "login", "password", "rbac", "api key"],
    "Deployment": ["deploy", "docker", "k8s", "kubernetes", "ci/cd", "build",
                   "pipeline", "container", "image", "helm", "terraform", "env var"],
    "Concurrency": ["race condition", "deadlock", "thread", "async", "await",
                    "promise", "concurrent", "mutex", "lock", "semaphore"],
    "Disk/IO": ["disk", "storage", "file", "i/o", "enospc", "permission denied",
                 "read-only", "filesystem"],
}


def classify_error(text: str) -> str:
    text_lower = text.lower()
    scores = {
        cat: sum(1 for kw in keywords if kw in text_lower)
        for cat, keywords in CATEGORY_KEYWORDS.items()
    }
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "Unknown"


def fingerprint_error(text: str) -> str:
    """Create a stable fingerprint while removing common variable values."""
    normalised = re.sub(r"\b\d{1,5}\.\d{1,5}\.\d{1,5}\.\d{1,5}\b", "<IP>", text)
    normalised = re.sub(r"\b[0-9a-f]{8,}\b", "<ID>", normalised, flags=re.I)
    normalised = re.sub(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}[:\d.Z]*", "<TS>", normalised)
    normalised = re.sub(r"\d+", "<N>", normalised)
    return hashlib.sha256(normalised.encode()).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Incident Agent
# ---------------------------------------------------------------------------

class IncidentAgent:
    """Analyze incidents, recall experience, and learn from verified outcomes."""

    def __init__(self):
        self.memory = HindsightMemory()
        self.groq = Groq(api_key=get_config("GROQ_API_KEY"))
        self.model = get_config("GROQ_MODEL", "qwen/qwen3-32b")
        # Session cache. Durable experience is stored in Hindsight.
        self.incidents: list[dict] = []

    # ---- public API -------------------------------------------------------

    def health(self) -> dict:
        return {
            "hindsight_configured": self.memory.configured,
            "groq_configured": bool(get_config("GROQ_API_KEY")),
            "hindsight_bank_id": self.memory.bank_id,
        }

    def analyze(self, error_text: str) -> dict:
        """Analyze a new incident. It is NOT treated as resolved yet."""
        now = datetime.utcnow()
        category = classify_error(error_text)
        fp = fingerprint_error(error_text)

        hindsight_results = self.memory.recall(error_text)
        reflect_context = ""
        if get_config("HINDSIGHT_USE_REFLECT", "true").lower() == "true":
            reflect_context = self.memory.reflect(
                "Production incident analysis context. What verified historical "
                "experience is relevant, and what should an engineer investigate?\n\n"
                + error_text
            )
        similar_local = self._find_similar(fp, category)
        past_context = self._build_past_context(similar_local, hindsight_results)
        patterns = self._detect_patterns(category, fp)
        time_patterns = self._detect_time_patterns()
        confidence = self._compute_confidence(similar_local, hindsight_results)
        runbook_history = self._get_runbook_history(fp, category)

        if reflect_context:
            past_context += f"\n\n=== Hindsight Reflect ===\n{reflect_context[:3000]}"
        llm_response = self._ask_groq(
            error_text,
            category,
            past_context,
            patterns,
            time_patterns,
            confidence,
            runbook_history,
        )

        incident_id = f"INC-{len(self.incidents) + 1:04d}"
        incident_record = {
            "id": incident_id,
            "error": error_text,
            "category": category,
            "fingerprint": fp,
            "timestamp": now.isoformat(),
            "weekday": now.strftime("%A"),
            "hour": now.hour,
            "response": llm_response,
            "confidence": confidence,
            "status": "Investigating",
            "root_cause": "",
            "resolution": "",
            "runbook": "",
            "outcome": "",
        }
        self.incidents.append(incident_record)

        # Store the observation, not a fake resolution.
        self.memory.retain(
            self._format_observation(incident_record),
            metadata={
                "incident_id": incident_id,
                "type": "incident_observation",
                "category": category,
                "fingerprint": fp,
                "status": "investigating",
            },
        )

        return self._build_result(
            incident_record,
            hindsight_results,
            similar_local,
            patterns,
            time_patterns,
            runbook_history,
        )

    def resolve_incident(
        self,
        incident_id: str,
        root_cause: str,
        resolution: str,
        runbook: str,
        outcome: str,
    ) -> bool:
        """Record the engineer-verified resolution and retain it as experience."""
        incident = self.get_incident(incident_id)
        if not incident:
            return False

        incident.update({
            "root_cause": root_cause.strip(),
            "resolution": resolution.strip(),
            "runbook": runbook.strip(),
            "outcome": outcome.strip(),
            "status": "Resolved" if outcome.strip().lower() == "resolved" else "Closed",
        })

        now = datetime.utcnow().isoformat()
        content = f"""[Verified Incident Experience]
Incident ID: {incident['id']}
Category: {incident['category']}
Fingerprint: {incident['fingerprint']}
Original Error:
{incident['error'][:1200]}

Root Cause:
{incident['root_cause'][:800]}

Resolution Applied:
{incident['resolution'][:1000]}

Runbook Used:
{incident['runbook'][:600]}

Outcome:
{incident['outcome']}

Recorded At:
{now}
"""
        self.memory.retain(
            content,
            metadata={
                "incident_id": incident["id"],
                "type": "verified_resolution",
                "category": incident["category"],
                "fingerprint": incident["fingerprint"],
                "outcome": incident["outcome"],
                "runbook": incident["runbook"],
            },
        )
        return True

    def get_incident(self, incident_id: str) -> dict | None:
        return next((i for i in self.incidents if i["id"] == incident_id), None)

    # ---- helpers ----------------------------------------------------------

    def _find_similar(self, fp: str, category: str) -> list[dict]:
        matches = []
        for inc in self.incidents:
            if inc["fingerprint"] == fp:
                matches.append({**inc, "match_type": "fingerprint"})
            elif inc["category"] == category:
                matches.append({**inc, "match_type": "category"})
        return matches

    def _build_past_context(self, local: list[dict], cloud: list) -> str:
        parts = []
        if local:
            parts.append("=== Past incidents from this session ===")
            for i, inc in enumerate(local[-5:], 1):
                resolution = inc.get("resolution") or "No verified resolution yet."
                parts.append(
                    f"{i}. {inc['id']} [{inc['category']}] {inc['error'][:220]}\n"
                    f"   Status: {inc['status']} | Root cause: {inc.get('root_cause') or 'unknown'}\n"
                    f"   Verified resolution: {resolution[:300]}\n"
                    f"   Runbook: {inc.get('runbook') or 'none'} | Outcome: {inc.get('outcome') or 'unknown'}"
                )
        if cloud:
            parts.append("\n=== Historical experience from Hindsight ===")
            for i, mem in enumerate(cloud[:6], 1):
                if isinstance(mem, str):
                    content = mem
                elif isinstance(mem, dict):
                    content = mem.get("content", mem.get("text", str(mem)))
                else:
                    content = str(mem)
                parts.append(f"{i}. {str(content)[:700]}")
        return "\n".join(parts) if parts else "No past incidents found."

    def _detect_patterns(self, category: str, fp: str) -> list[dict]:
        patterns = []
        fp_counts = Counter(inc["fingerprint"] for inc in self.incidents)
        for fingerprint, count in fp_counts.most_common(5):
            if count >= 2:
                sample = next(i for i in self.incidents if i["fingerprint"] == fingerprint)
                patterns.append({
                    "fingerprint": fingerprint,
                    "count": count,
                    "category": sample["category"],
                    "severity": "critical" if count >= 3 else "warning",
                    "message": (
                        f"This {sample['category']} error has appeared {count} times. "
                        f"Review the verified root cause and runbook instead of repeating a patch."
                    ),
                })
        return patterns

    def _detect_time_patterns(self) -> list[str]:
        if len(self.incidents) < 2:
            return []
        findings = []
        weekday_counts = Counter(inc["weekday"] for inc in self.incidents)
        for day, count in weekday_counts.most_common(1):
            if count >= 2:
                findings.append(f"Errors cluster on {day}s ({count} incidents)")
        hour_counts = Counter(inc["hour"] for inc in self.incidents)
        for hour, count in hour_counts.most_common(1):
            if count >= 2:
                findings.append(f"Errors spike around {hour:02d}:00 UTC ({count} incidents)")
        cat_counts = Counter(inc["category"] for inc in self.incidents)
        for cat, count in cat_counts.most_common(3):
            if count >= 2:
                findings.append(f"{cat} issues recur ({count} times)")
        return findings

    def _compute_confidence(self, similar_local: list[dict], cloud_results: list) -> int:
        """Evidence-based heuristic; memory count alone does not equal confidence."""
        if not similar_local and not cloud_results:
            return 10
        exact = sum(1 for i in similar_local if i.get("match_type") == "fingerprint")
        verified = sum(1 for i in similar_local if i.get("resolution") and i.get("outcome"))
        score = 10 + min(exact * 30, 50) + min(verified * 15, 30) + min(len(cloud_results) * 5, 15)
        return min(score, 95)

    def _get_runbook_history(self, fp: str, category: str) -> list[dict]:
        related = [
            i for i in self.incidents
            if (i["fingerprint"] == fp or i["category"] == category)
            and i.get("runbook")
            and i.get("resolution")
        ]
        return [
            {
                "step": idx,
                "label": inc["id"],
                "timestamp": inc["timestamp"],
                "approach": inc["resolution"],
                "runbook": inc["runbook"],
                "outcome": inc["outcome"],
            }
            for idx, inc in enumerate(related[-5:], 1)
        ]

    def _system_weak_points(self) -> dict[str, int]:
        return dict(Counter(inc["category"] for inc in self.incidents))

    def _format_observation(self, incident: dict) -> str:
        return f"""[Incident Observation]
Incident ID: {incident['id']}
Category: {incident['category']}
Fingerprint: {incident['fingerprint']}
Status: Investigating
Original Error:
{incident['error'][:1200]}
AI Investigation:
{incident['response'][:1200]}
"""

    def _build_result(self, incident, hindsight_results, similar_local, patterns, time_patterns, runbook_history):
        return {
            "incident_id": incident["id"],
            "response": incident["response"],
            "category": incident["category"],
            "fingerprint": incident["fingerprint"],
            "confidence": incident["confidence"],
            "num_recalled": len(similar_local) + len(hindsight_results),
            "total_incidents": len(self.incidents),
            "patterns": patterns,
            "time_patterns": time_patterns,
            "runbook_history": runbook_history,
            "weak_points": self._system_weak_points(),
            "similar_count": len(similar_local),
            "memory_evidence": hindsight_results[:6],
        }

    # ---- LLM --------------------------------------------------------------

    def _ask_groq(
        self,
        error_text: str,
        category: str,
        past_context: str,
        patterns: list[dict],
        time_patterns: list[str],
        confidence: int,
        runbook_history: list[dict],
    ) -> str:
        pattern_text = "\n" + "\n".join(
            f"- [{p['severity'].upper()}] {p['message']}" for p in patterns
        ) if patterns else "None"
        time_text = "\n".join(f"- {t}" for t in time_patterns) if time_patterns else "None"
        runbook_text = "\n".join(
            f"- {r['label']}: runbook={r['runbook']}; resolution={r['approach']}; outcome={r['outcome']}"
            for r in runbook_history
        ) if runbook_history else "None"

        system_prompt = f"""/no_think
You are an expert Incident Response Agent for production systems.
Analyze the current incident using current evidence and historical incident
experience retrieved from Hindsight.

Category: {category}
Memory evidence confidence: {confidence}%

HISTORICAL CONTEXT:
{past_context}

RECURRING PATTERNS:
{pattern_text}

TIME PATTERNS:
{time_text}

VERIFIED RUNBOOK HISTORY:
{runbook_text}

Rules:
1. Diagnose likely causes and clearly separate evidence from hypotheses.
2. Use verified historical resolutions when they are relevant.
3. If history conflicts, mention the conflict instead of inventing certainty.
4. Give investigation steps and a proposed fix, but do not claim the incident
   is resolved unless a human records the actual outcome.
5. Never invent a past incident, runbook, or successful outcome.
6. Keep the response concise and actionable.
"""
        if not get_config("GROQ_API_KEY"):
            return "Groq API key is not configured. Add GROQ_API_KEY to your .env file."
        try:
            resp = self.groq.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Production error:\n\n{error_text}"},
                ],
                temperature=0.4,
                max_tokens=1500,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            return f"LLM Error: {e}"
