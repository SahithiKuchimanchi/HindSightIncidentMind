"""IncidentMind Streamlit UI — original presentation routed through FastAPI."""
import os
import uuid
import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(
    page_title="IncidentMind | Incident Response Agent",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""<style>
.block-container { padding-top: 1.5rem; }
.memory-badge { display:inline-block; padding:4px 14px; border-radius:20px; font-weight:700; font-size:.85rem; margin:2px 4px; }
.badge-green { background:#00c85322; color:#00c853; border:1px solid #00c853; }
.badge-blue { background:#2196f322; color:#2196f3; border:1px solid #2196f3; }
.badge-amber { background:#ffa50022; color:#ffa500; border:1px solid #ffa500; }
.badge-red { background:#ff4b4b22; color:#ff4b4b; border:1px solid #ff4b4b; }
.conf-bar { height:28px; border-radius:14px; overflow:hidden; background:#ffffff10; margin:8px 0; }
.conf-fill { height:100%; border-radius:14px; display:flex; align-items:center; justify-content:center; font-weight:700; font-size:.85rem; color:#fff; }
.pattern-card { padding:10px 14px; border-radius:10px; margin:6px 0; border-left:4px solid; font-size:.88rem; }
.pattern-critical { border-color:#ff4b4b; background:#ff4b4b10; }
.pattern-warning { border-color:#ffa500; background:#ffa50010; }
.wp-row { display:flex; align-items:center; gap:8px; margin:4px 0; }
.wp-label { min-width:100px; font-weight:600; font-size:.85rem; }
.wp-bar { height:16px; border-radius:8px; }
.inc-item { padding:8px 12px; border-radius:8px; margin:4px 0; font-size:.82rem; border:1px solid #ffffff15; }
.section-hdr { font-size:.95rem; font-weight:700; margin:18px 0 6px 0; padding-bottom:4px; border-bottom:2px solid #ffffff15; }
.memory-card { padding:10px 12px; border:1px solid #ffffff18; border-radius:10px; margin:6px 0; }
</style>""", unsafe_allow_html=True)

def get_config(name: str, default: str = "") -> str:
    value = os.getenv(name)
    if value:
        return value
    try:
        return str(st.secrets.get(name, default))
    except Exception:
        return default

BACKEND_URL = get_config("BACKEND_URL", "http://localhost:8000").rstrip("/")
REQUEST_TIMEOUT = float(get_config("BACKEND_TIMEOUT_SECONDS", "45"))

def backend_request(method: str, path: str, **kwargs):
    try:
        r = requests.request(method, f"{BACKEND_URL}{path}", timeout=REQUEST_TIMEOUT, **kwargs)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as exc:
        detail = ""
        if getattr(exc, "response", None) is not None:
            try:
                detail = exc.response.json().get("detail", "")
            except Exception:
                detail = exc.response.text[:300]
        raise RuntimeError(
            f"Backend unavailable at {BACKEND_URL}. {detail or str(exc)}"
        ) from exc

if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())
if "history" not in st.session_state:
    st.session_state.history = []
if "last_result" not in st.session_state:
    st.session_state.last_result = None
if "incidents" not in st.session_state:
    st.session_state.incidents = []

def refresh_state():
    data = backend_request(
        "GET", "/api/session",
        params={"session_id": st.session_state.session_id},
    )
    st.session_state.incidents = data.get("incidents", [])

try:
    refresh_state()
except RuntimeError:
    pass

incidents = st.session_state.incidents
st.markdown("## 🧠 IncidentMind")
st.caption("AI Incident Response Agent — Hindsight Memory + Groq (Qwen3-32b)")

left, right = st.columns([3, 2], gap="large")

with left:
    total = len(incidents)
    last = st.session_state.last_result or {}
    if total == 0:
        st.markdown('<span class="memory-badge badge-green">No incidents yet — memory will grow from verified outcomes</span>', unsafe_allow_html=True)
    else:
        recalled = last.get("num_recalled", 0)
        conf = last.get("confidence", 10)
        cls = "badge-red" if conf >= 70 else ("badge-amber" if conf >= 40 else "badge-blue")
        st.markdown(
            f'<span class="memory-badge {cls}">Memory active — {total} incidents | {recalled} recalled | Evidence {conf}%</span>',
            unsafe_allow_html=True,
        )

    st.markdown("---")
    error_input = st.text_area(
        "Paste your production error / stack trace",
        height=180,
        placeholder="e.g. psycopg2.OperationalError: connection pool exhausted...",
        key="error_input",
    )

    if st.button("Analyze Incident", type="primary", use_container_width=True):
        if error_input.strip():
            with st.spinner("Recalling historical incidents and analyzing..."):
                try:
                    result = backend_request(
                        "POST", "/api/analyze",
                        json={"session_id": st.session_state.session_id, "error": error_input.strip()},
                    )
                    st.session_state.last_result = result
                    st.session_state.history.append(result)
                    refresh_state()
                    st.rerun()
                except RuntimeError as exc:
                    st.error(str(exc))
        else:
            st.warning("Please paste an error message first.")

    if st.session_state.last_result:
        res = st.session_state.last_result
        incident = next((i for i in incidents if i["id"] == res["incident_id"]), None)
        st.markdown("---")
        st.markdown(f"### Incident `{res['incident_id']}`")

        status = incident["status"] if incident else "Investigating"
        if status == "Investigating":
            st.info("🟡 Investigating — AI has suggested a response. Record the real resolution after an engineer verifies it.")
        else:
            st.success(f"🟢 {status}")

        conf = res["confidence"]
        bar_color = "#ff4b4b" if conf >= 70 else ("#ffa500" if conf >= 40 else "#2196f3")
        st.markdown(
            f'<div class="conf-bar"><div class="conf-fill" style="width:{conf}%; background:{bar_color};">{conf}% evidence confidence</div></div>',
            unsafe_allow_html=True,
        )

        c1, c2, c3 = st.columns(3)
        c1.metric("Category", res["category"])
        c2.metric("Memory Matches", res["num_recalled"])
        c3.metric("Status", status)

        st.markdown("### Agent Investigation")
        st.markdown(res["response"])

        if res.get("memory_evidence"):
            st.markdown('<div class="section-hdr">🧠 Memory Evidence</div>', unsafe_allow_html=True)
            for idx, mem in enumerate(res["memory_evidence"][:4], 1):
                content = mem if isinstance(mem, str) else mem.get("content", mem.get("text", str(mem)))
                st.markdown(f'<div class="memory-card"><b>Historical memory {idx}</b><br>{str(content)[:650]}</div>', unsafe_allow_html=True)
        else:
            st.caption("No cloud memory matched this incident yet.")

        if res.get("runbook_history"):
            st.markdown('<div class="section-hdr">🔧 Verified Runbook History</div>', unsafe_allow_html=True)
            for step in res["runbook_history"]:
                st.markdown(
                    f"**{step['label']}** — `{step['runbook']}`  \n"
                    f"Resolution: {step['approach'][:250]}  \n"
                    f"Outcome: **{step['outcome']}**"
                )

        if incident and incident["status"] == "Investigating":
            st.markdown('<div class="section-hdr">📝 Record Actual Resolution / Post-Mortem</div>', unsafe_allow_html=True)
            st.caption("Only save facts verified by the engineer. This becomes long-term Hindsight experience.")
            with st.form(f"resolve_{incident['id']}"):
                root_cause = st.text_area("Actual Root Cause", placeholder="What actually caused the incident?")
                resolution = st.text_area("Resolution Applied", placeholder="What did the engineer actually do to resolve it?")
                runbook = st.text_input("Runbook Used / Created", placeholder="e.g. DB-CONNECTION-001")
                outcome = st.selectbox("Outcome", ["Resolved", "Partially Resolved", "Unresolved"])
                save = st.form_submit_button("🧠 Save Verified Resolution to Hindsight", use_container_width=True)
                if save:
                    if not root_cause.strip() or not resolution.strip():
                        st.warning("Root cause and resolution are required.")
                    else:
                        try:
                            backend_request(
                                "POST",
                                f"/api/incidents/{incident['id']}/resolve",
                                json={
                                    "session_id": st.session_state.session_id,
                                    "root_cause": root_cause,
                                    "resolution": resolution,
                                    "runbook": runbook,
                                    "outcome": outcome,
                                },
                            )
                            st.success("Verified incident experience saved to Hindsight Memory.")
                            refresh_state()
                            st.rerun()
                        except RuntimeError as exc:
                            st.error(str(exc))

    with st.expander("🎬 Demo: use these two incidents in sequence"):
        st.markdown("**Incident 1 — resolve it first**")
        st.code("psycopg2.OperationalError: connection pool exhausted\nDETAIL: remaining connection slots are reserved", language="text")
        st.markdown("Record a real root cause, resolution, runbook and `Resolved` outcome.")
        st.markdown("**Incident 2 — test memory recall**")
        st.code("sqlalchemy.exc.OperationalError: could not connect to server: Connection timed out\nIs the server accepting TCP connections on port 5432?", language="text")

with right:
    st.markdown("### 🧠 Memory Brain")
    total_incidents = len(incidents)
    resolved = sum(1 for i in incidents if i["status"] == "Resolved")
    runbooks = len(set(i["runbook"] for i in incidents if i.get("runbook")))
    matches = (st.session_state.last_result or {}).get("num_recalled", 0)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Incidents", total_incidents)
    m2.metric("Resolved", resolved)
    m3.metric("Runbooks", runbooks)
    m4.metric("Matches", matches)

    st.markdown('<div class="section-hdr">Learning Loop</div>', unsafe_allow_html=True)
    st.markdown("`Incident → Recall → Analyze → Human Resolution → Post-Mortem → Retain → Recall again`")

    st.markdown('<div class="section-hdr">Detected Patterns</div>', unsafe_allow_html=True)
    if st.session_state.last_result and st.session_state.last_result.get("patterns"):
        for p in st.session_state.last_result["patterns"]:
            sev_cls = "pattern-critical" if p["severity"] == "critical" else "pattern-warning"
            icon = "🔴" if p["severity"] == "critical" else "🟡"
            st.markdown(
                f'<div class="pattern-card {sev_cls}">{icon} <b>{p["category"]}</b> — seen {p["count"]}x<br>{p["message"]}</div>',
                unsafe_allow_html=True,
            )
    else:
        st.caption("No recurring patterns detected yet.")

    st.markdown('<div class="section-hdr">Time-Based Insights</div>', unsafe_allow_html=True)
    if st.session_state.last_result and st.session_state.last_result.get("time_patterns"):
        for tp in st.session_state.last_result["time_patterns"]:
            st.markdown(f"⏰ {tp}")
    else:
        st.caption("Need multiple incidents to detect time correlations.")

    st.markdown('<div class="section-hdr">System Weak Points</div>', unsafe_allow_html=True)
    wp = (st.session_state.last_result or {}).get("weak_points", {})
    if wp:
        max_count = max(wp.values()) or 1
        for cat, count in sorted(wp.items(), key=lambda x: -x[1]):
            pct = int((count / max_count) * 100)
            st.markdown(
                f'<div class="wp-row"><span class="wp-label">{cat}</span><div class="wp-bar" style="width:{pct}%; background:#2196f3;">&nbsp;</div><span>{count}</span></div>',
                unsafe_allow_html=True,
            )
    else:
        st.caption("Weak points appear as incidents accumulate.")

    st.markdown('<div class="section-hdr">Incident Timeline</div>', unsafe_allow_html=True)
    if incidents:
        for inc in reversed(incidents[-10:]):
            status = inc["status"]
            badge = "#00c853" if status == "Resolved" else "#ffa500"
            st.markdown(
                f'<div class="inc-item" style="border-left:3px solid {badge};">'
                f'<b>{inc["id"]}</b> · {inc["category"]} '
                f'<span class="memory-badge" style="background:{badge}22;color:{badge};border:1px solid {badge};font-size:.7rem;padding:1px 8px;">{status.upper()}</span><br>'
                f'{inc["error"][:110]}...'
                f'</div>',
                unsafe_allow_html=True,
            )
    else:
        st.caption("No incidents recorded yet.")

st.markdown("---")
st.caption("Built for the Hindsight Hackathon | Persistent memory powered by Hindsight | Reasoning by Groq Qwen3-32b")
