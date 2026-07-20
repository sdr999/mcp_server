from __future__ import annotations
from typing import Optional, Dict, Any, List, Tuple
import json
import threading
import time
from datetime import datetime, timezone, timedelta

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

try:
    # Only import if available in env
    from azure.servicebus import ServiceBusClient, ServiceBusMessage
except Exception:
    ServiceBusClient = None  # type: ignore
    ServiceBusMessage = None  # type: ignore

from config.servicenow_settings import settings

# from utils.logger import get_logger
# log = get_logger("sn.runtime")

# =============================================================================
# Globals 
# =============================================================================
_listen_thread: Optional[threading.Thread] = None
_poller_thread: Optional[threading.Thread] = None

_listen_stop = threading.Event()
_poller_stop = threading.Event()

_SB_CONN: Optional[str] = None
_SB_QUEUE: Optional[str] = None

# =============================================================================
# Core helpers  
# =============================================================================
def _sn_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"Accept": "application/json", "Content-Type": "application/json"})
    retry = Retry(total=3, backoff_factor=0.5, status_forcelist=(429, 500, 502, 503, 504))
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.mount("http://", HTTPAdapter(max_retries=retry))
    return s

def _sn_base() -> str:
    return getattr(settings, "SN_BASE_URL", "").rstrip("/")

def _sn_auth():
    return (getattr(settings, "SN_USERNAME", ""),
            getattr(settings, "SN_PASSWORD", ""))

def _sn_verify() -> bool:
    return bool(getattr(settings, "VERIFY_TLS", True))

def _sn_get(path: str, **kw) -> Dict[str, Any]:
    r = _sn_session().get(_sn_base() + path, auth=_sn_auth(),
                          verify=_sn_verify(), timeout=30, **kw)
    r.raise_for_status()
    return r.json()

def _sn_post(path: str, json: Dict[str, Any]) -> Dict[str, Any]:
    r = _sn_session().post(_sn_base() + path, auth=_sn_auth(), json=json,
                           verify=_sn_verify(), timeout=30)
    r.raise_for_status()
    return r.json()

def _sn_patch(path: str, json: Dict[str, Any]) -> Dict[str, Any]:
    r = _sn_session().patch(_sn_base() + path, auth=_sn_auth(), json=json,
                            verify=_sn_verify(), timeout=30)
    r.raise_for_status()
    return r.json()

# =============================================================================
# Utility & shared SN actions  
# =============================================================================
def get_status() -> Dict[str, Any]:
    """Return runtime status of listener/poller threads & queue."""
    mode = "stopped"
    if _listen_thread and _listen_thread.is_alive() and _poller_thread and _poller_thread.is_alive():
        mode = "poller+listener"
    elif _listen_thread and _listen_thread.is_alive():
        mode = "listener-only"
    return {
        "listener_running": bool(_listen_thread and _listen_thread.is_alive()),
        "poller_running": bool(_poller_thread and _poller_thread.is_alive()),
        "queue": _SB_QUEUE,
        "mode": mode,
    }

def _lookup_user_sys_id_by_email(email: str) -> Optional[str]:
    """Resolve ServiceNow user sys_id from email."""
    if not email:
        return None
    try:
        res = _sn_get("/api/now/table/sys_user", params={
            "sysparm_query": f"email={email}",
            "sysparm_fields": "sys_id",
            "sysparm_limit": "1",
            "sysparm_display_value": "false",
        })
        rows = res.get("result", [])
        return rows[0]["sys_id"] if rows else None
    except Exception as e:
        return None

def add_comment(message: str, *,
                number: Optional[str] = None,
                sys_id: Optional[str] = None,
                visibility: str = "public") -> Dict[str, Any]:
    """Add public or internal comment/work_notes to an incident."""
    if not message or not message.strip():
        return {"status": "error", "message": "message cannot be empty", "data": {}}

    try:
        if not sys_id and number:
            rows = _sn_get("/api/now/table/incident", params={
                "sysparm_query": f"number={number}",
                "sysparm_fields": "sys_id,number",
                "sysparm_limit": "1",
                "sysparm_display_value": "false",
            }).get("result", [])
            if rows:
                sys_id = rows[0]["sys_id"]
            else:
                return {"status": "error", "message": f"incident not found: {number}", "data": {}}

        if not sys_id:
            return {"status": "error", "message": "provide number or sys_id", "data": {}}

        field = "comments" if visibility.lower() in ("public", "customer", "external") else "work_notes"
        data = _sn_patch(f"/api/now/table/incident/{sys_id}", json={field: message})
        return {"status": "success", "message": "comment added",
                "data": {"sys_id": sys_id, "number": number, "visibility": visibility, "raw": data}}
    except Exception as e:
        return {"status": "error", "message": str(e), "data": {}}

# def create_incident(short_description: str, *, caller_id: Optional[str] = None) -> Dict[str, Any]:
#     if not short_description or not short_description.strip():
#         return {"status": "error", "message": "short_description required", "data": {}}
#     try:
#         payload = {"short_description": short_description}
#         if caller_id:
#             payload["caller_id"] = caller_id
#         data = _sn_post("/api/now/table/incident", json=payload)
#         return {"status": "success", "message": "incident created", "data": data}
#     except Exception as e:
#         return {"status": "error", "message": str(e), "data": {}}
def create_incident(
   short_description: str,
   *,
   caller_email: Optional[str] = None,
   caller_id: Optional[str] = None,
   additional: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
   """
   Create a ServiceNow incident.
   Args:
       short_description: Text for the incident.
       caller_email: (preferred) email of the SN user; we resolve sys_id.
       caller_id: Optional sys_id of the caller (if you already have it).
       additional: Optional dict of extra fields to include in payload
                   (e.g., {"category": "inquiry", "subcategory": "..."}).
   Returns:
       {"status": "success"|"error", "message": str, "data": {...}}
   """
   if not short_description or not short_description.strip():
       return {"status": "error", "message": "short_description required", "data": {}}
   try:
       payload: Dict[str, Any] = {"short_description": short_description.strip()}
       # Prefer explicit sys_id, else resolve from email (if provided)
       cid: Optional[str] = None
       if caller_id:
           cid = caller_id.strip()
       elif caller_email:
           try:
               cid = _lookup_user_sys_id_by_email(caller_email.strip())
           except Exception as e:
               # don’t fail creation solely due to lookup; return clear message
               return {"status": "error", "message": f"caller lookup failed: {e}", "data": {}}
       if cid:
           payload["caller_id"] = cid
       # Allow callers to pass any extra SN fields
       if additional:
           payload.update(additional)
       data = _sn_post("/api/now/table/incident", json=payload)
       return {"status": "success", "message": "incident created", "data": data}
   except Exception as e:
       return {"status": "error", "message": str(e), "data": {}}

def get_incident_data(*, number: Optional[str] = None, sys_id: Optional[str] = None) -> Dict[str, Any]:
    try:
        if sys_id:
            res = _sn_get(f"/api/now/table/incident/{sys_id}")
            return {"status": "success", "message": "ok", "data": res}
        if number:
            res = _sn_get("/api/now/table/incident", params={
                "sysparm_query": f"number={number}",
                "sysparm_limit": "1",
                "sysparm_display_value": "false",
            })
            return {"status": "success", "message": "ok", "data": res}
        return {"status": "error", "message": "provide number or sys_id", "data": {}}
    except Exception as e:
        return {"status": "error", "message": str(e), "data": {}}

# def get_incident_history(sys_id: str, limit: int = 10) -> Dict[str, Any]:
#    """Fetch last N comments/work_notes for an incident"""
#    try:
#        res = _sn_get("/api/now/table/sys_journal_field", params={
#            "sysparm_query": f"element_id={sys_id}^ORDERBYDESCsys_created_on",
#            "sysparm_fields": "sys_created_on,element,sys_created_by,value",
#            "sysparm_limit": str(limit),
#            "sysparm_display_value": "true",
#        })
#        return {"status": "success", "data": res.get("result", [])}
#    except Exception as e:
#        return {"status": "error", "message": str(e), "data": []}

def get_incident_history(
   sys_id: Optional[str] = None,
   number: Optional[str] = None,
   limit: int = 10,
   retries: int = 3,
   retry_delay_sec: float = 2.0,
) -> Dict[str, Any]:
   """
   Fetch the latest N journal entries (comments + work_notes) for an incident.
   Accepts either sys_id or number.
   Tries several query variants and retries a few times to tolerate eventual consistency.
   Returns:
     {"status":"success","data":[...]}  # list of rows from sys_journal_field
     or {"status":"error","message":..., "data":[]}
   """
   try:
       # Resolve sys_id if only number was given
       if not sys_id:
           if not number:
               return {"status": "error", "message": "provide number or sys_id", "data": []}
           lookup = _sn_get("/api/now/table/incident", params={
               "sysparm_query": f"number={number}",
               "sysparm_fields": "sys_id",
               "sysparm_limit": "1",
               "sysparm_display_value": "false",
           })
           rows = lookup.get("result", []) or []
           if not rows:
               return {"status": "error", "message": f"incident not found: {number}", "data": []}
           sys_id = rows[0].get("sys_id")
           if not sys_id:
               return {"status": "error", "message": f"sys_id missing for incident: {number}", "data": []}
       # Build a few query variants (some instances need element filter, some don't)
       queries = [
           f"element_id={sys_id}^ORDERBYDESCsys_created_on",                   # any journal
           f"element_id={sys_id}^element=comments^ORDERBYDESCsys_created_on",  # only public
           f"element_id={sys_id}^element=work_notes^ORDERBYDESCsys_created_on" # only internal
       ]
       # Try different display settings too
       display_opts = ["true", "false"]
       def _try_once() -> List[Dict[str, Any]]:
           for q in queries:
               for disp in display_opts:
                   res = _sn_get("/api/now/table/sys_journal_field", params={
                       "sysparm_query": q,
                       "sysparm_fields": "sys_created_on,element,sys_created_by,value",
                       "sysparm_limit": str(limit),
                       "sysparm_display_value": disp,
                   })
                   got = res.get("result", []) or []
                   if got:
                       return got
           return []
       # Retry loop
       out: List[Dict[str, Any]] = []
       for _ in range(max(1, retries)):
           out = _try_once()
           if out:
               break
           try:
               import time; time.sleep(retry_delay_sec)
           except Exception:
               pass
       return {"status": "success", "data": out}
   except Exception as e:
       return {"status": "error", "message": str(e), "data": []}
    
def close_incident(*, sys_id: Optional[str] = None, number: Optional[str] = None,
                   resolution: Optional[str] = None, target_state: Optional[str] = None,
                   close_code: Optional[str] = None, work_note_prefix: Optional[str] = None,
                   score: Optional[float] = None) -> Dict[str, Any]:
    try:
        if not sys_id and number:
            rows = _sn_get("/api/now/table/incident", params={
                "sysparm_query": f"number={number}",
                "sysparm_fields": "sys_id,number",
                "sysparm_limit": "1",
                "sysparm_display_value": "false",
            }).get("result", [])
            if rows:
                sys_id = rows[0]["sys_id"]
        if not sys_id:
            return {"status": "error", "message": "missing sys_id/number", "data": {}}

        tgt = str(target_state or getattr(settings, "RAG_CLOSE_STATE", "6"))
        prefix = work_note_prefix or "AI auto-action"
        score_txt = "" if score is None else f" [score={score:.2f}]"
        payload = {
            "state": tgt,
            "work_notes": f"{prefix}{score_txt}{'' if not resolution else f' {resolution.strip()}'}"
        }
        # Only set close fields when moving to 6/7
        if tgt in ("6", "7"):
            default_code = getattr(settings, "RAG_CLOSE_CODE", None)
            if default_code:
                payload.setdefault("close_code", default_code)
            if close_code is not None:
                payload["close_code"] = close_code
            payload["close_notes"] = (resolution or "Resolved by AI").strip()

        data = _sn_patch(f"/api/now/table/incident/{sys_id}", json=payload)
        return {"status": "success", "message": "incident closed", "data": {"sys_id": sys_id, "raw": data}}
    except Exception as e:
        return {"status": "error", "message": str(e), "data": {}}

def list_recent_incidents(limit: int = 10, query: str = "") -> Dict[str, Any]:
    try:
        q = query or "ORDERBYDESCsys_created_on"
        res = _sn_get("/api/now/table/incident", params={
            "sysparm_query": q,
            "sysparm_fields": "sys_id,number,short_description,sys_created_on,state,assigned_to",
            "sysparm_display_value": "false",
            "sysparm_limit": str(limit),
        })
        return {"status": "success", "message": "ok", "data": res}
    except Exception as e:
        return {"status": "error", "message": str(e), "data": {}}

def rag_autoreply(sys_id: str, number: str, short_description: str) -> Dict[str, Any]:
    """
    Wrapper to your existing tool (lazy import avoids circular deps).
    Expected to return a dict with keys like: ok, posted, score, reason, resolution.
    """
    from tools.sn_rag_autoreply import sn_rag_autoreply  # type: ignore
    return sn_rag_autoreply(sys_id=sys_id, number=number, short_description=short_description)

# =============================================================================
# Bus helpers
# =============================================================================
def _clean_conn_str(raw: Optional[str]) -> str:
    return (raw or "").replace("Endpoint=Endpoint=", "Endpoint=")

def _send_to_bus(payload: Dict[str, Any]):
    conn = _clean_conn_str(_SB_CONN or "")
    if not conn or ServiceBusClient is None or ServiceBusMessage is None:
        raise RuntimeError("Service Bus client not available or connection string empty")
    with ServiceBusClient.from_connection_string(conn) as client:
        with client.get_queue_sender(queue_name=_SB_QUEUE) as sender:  # type: ignore[arg-type]
            sender.send_messages(ServiceBusMessage(json.dumps(payload)))

# =============================================================================
# ServiceNow helpers used by loops
# =============================================================================
def _ack_incident(sys_id: str, number: Optional[str], short_desc: Optional[str]) -> None:
    comment = getattr(settings, "ACK_TEMPLATE", "Acknowledged: {number} {short_description}")
    msg = comment.format(number=number or "", short_description=short_desc or "")
    try:
        _sn_patch(f"/api/now/table/incident/{sys_id}", json={"comments": msg})
    except Exception as e:
        print(f"ACK error: {e}")

# =============================================================================
# Listener loop (reads from Bus, does ACK -> RAG -> optional close)
# =============================================================================
def _listen_loop():
    if ServiceBusClient is None:
        return

    conn = _clean_conn_str(_SB_CONN or "")
    if not conn:
        return

    try:
        with ServiceBusClient.from_connection_string(conn) as client:
            with client.get_queue_receiver(queue_name=_SB_QUEUE, max_wait_time=10) as receiver:  # type: ignore[arg-type]
                while not _listen_stop.is_set():
                    messages = receiver.receive_messages(max_wait_time=10)
                    if not messages:
                        continue
                    for msg in messages:
                        try:
                            raw = b"".join(part for part in msg.body)
                            data = json.loads(raw.decode("utf-8"))
                            sys_id = data.get("sys_id")
                            number = data.get("number")
                            short = data.get("short_description", "")

                            if not sys_id:
                                # Nothing actionable; just complete
                                continue

                            # 1) ACK
                            _ack_incident(sys_id, number, short)

                            # 2) RAG auto-reply (guarded)
                            if bool(getattr(settings, "RAG_AUTOREPLY", False)):
                                try:
                                    rag_res = rag_autoreply(sys_id=sys_id, number=number or "", short_description=short)
                                except Exception as re:
                                    rag_res = {}

                                # 3) Optional auto-close
                                if bool(getattr(settings, "RAG_AUTOCLOSE", False)):
                                    try:
                                        score = float(rag_res.get("score", 0.0))  # type: ignore
                                    except Exception:
                                        score = 0.0
                                    threshold = float(getattr(settings, "RAG_CLOSE_THRESHOLD", 0.5))
                                    if score >= threshold:
                                        try:
                                            close_res = close_incident(
                                                sys_id=sys_id,
                                                number=number,
                                                resolution=str(rag_res.get("resolution") or "Resolved by AI").strip(),
                                                target_state=str(getattr(settings, "RAG_CLOSE_STATE", "6")),
                                                work_note_prefix="AI suggested resolution",
                                                score=score,
                                            )
                                        except Exception as ce:
                                            print(f"Auto-close error: {ce}")
                        except Exception as e:
                            print(f"listener error: {e}", exc_info=True)
                        finally:
                            try:
                                receiver.complete_message(msg)
                            except Exception:
                                pass
    except Exception as e:
        print(f"listener loop fatal: {e}")

# =============================================================================
# Poller loop (polls SN for new incidents since last_check, pushes to Bus)
# =============================================================================
def _poller_loop(allowed_caller_email: Optional[str] = None):
    lookback = int(getattr(settings, "POLL_LOOKBACK_SEC", 3600))
    poll_interval = max(3, int(getattr(settings, "POLL_INTERVAL_SEC", 15)))

    last_check = datetime.now(timezone.utc) - timedelta(seconds=lookback)
    allowed_caller_sys_id: Optional[str] = None

    if allowed_caller_email:
        try:
            allowed_caller_sys_id = _lookup_user_sys_id_by_email(allowed_caller_email)
        except Exception as e:
            print(f"Poller error: {e}")

    seen: set[str] = set()

    while not _poller_stop.is_set():
        try:
            query = f"state=1^sys_created_on>{last_check.strftime('%Y-%m-%d %H:%M:%S')}"
            if allowed_caller_sys_id:
                query += f"^caller_id={allowed_caller_sys_id}"

            params = {
                "sysparm_query": query,
                "sysparm_fields": "sys_id,number,short_description,sys_created_on",
                "sysparm_display_value": "false",
                "sysparm_limit": "20",
            }

            res = _sn_get("/api/now/table/incident", params=params)
            rows = res.get("result", []) or []
            new_cnt = 0
            for inc in rows:
                sid = inc.get("sys_id")
                if not sid or sid in seen:
                    continue
                payload = {
                    "sys_id": sid,
                    "number": inc.get("number"),
                    "short_description": inc.get("short_description", ""),
                }
                try:
                    _send_to_bus(payload)
                    seen.add(sid)
                    new_cnt += 1
                except Exception as bus_e:
                    print(f"Bus error: {bus_e}")
            last_check = datetime.now(timezone.utc)
        except Exception as e:
            print(f"Poller error: {e}")
        # Wait (interruptible)
        _poller_stop.wait(timeout=poll_interval)


def start_poller(allowed_caller_email: Optional[str] = None) -> Dict[str, Any]:
   """
   Start the ServiceNow poller loop in its own thread.
   If already running, returns status without starting another.
   allowed_caller_email: optional filter; if provided, only incidents from this caller are queued.
   """
   global _poller_thread
   try:
       if _poller_thread and _poller_thread.is_alive():
           return {"status": "success", "message": "poller already running"}
       _poller_stop.clear()
       t = threading.Thread(target=_poller_loop, args=(allowed_caller_email,), daemon=True)
       t.start()
       globals()["_poller_thread"] = t
       return {"status": "success", "message": "poller started"}
   except Exception as e:
       return {"status": "error", "message": str(e)}
   
def stop_poller() -> Dict[str, Any]:
   """
   Stop the poller thread (if running) and wait briefly for it to join.
   """
   global _poller_thread
   try:
       _poller_stop.set()
       if _poller_thread and _poller_thread.is_alive():
           _poller_thread.join(timeout=5)
       return {"status": "success", "message": "poller stopped"}
   except Exception as e:
       return {"status": "error", "message": str(e)}
   
def poller_status() -> Dict[str, Any]:
   """
   Return whether the poller is running.
   """
   running = bool(_poller_thread and _poller_thread.is_alive())
   return {"status": "success", "running": running}

# =============================================================================
# Public API (called by tools)
# =============================================================================
def start_agent(mode: str = "listener-only",
                caller_email: Optional[str] = None,
                sb_connection_str: Optional[str] = None,
                sb_queue_name: Optional[str] = None) -> Dict[str, Any]:
    """
    mode: "listener-only" or "poller+listener"
    """
    global _SB_CONN, _SB_QUEUE, _listen_thread, _poller_thread

    _SB_CONN = sb_connection_str or getattr(settings, "SB_CONNECTION_STR", "")
    _SB_QUEUE = sb_queue_name or getattr(settings, "SB_QUEUE_NAME", "")

    # Start listener
    if not (_listen_thread and _listen_thread.is_alive()):
        _listen_stop.clear()
        t = threading.Thread(target=_listen_loop, daemon=True)
        _listen_thread = t
        t.start()
    
    # Start poller (if requested)
    if "poller" in mode and not (_poller_thread and _poller_thread.is_alive()):
        _poller_stop.clear()
        t2 = threading.Thread(target=_poller_loop, args=(caller_email,), daemon=True)
        _poller_thread = t2
        t2.start()    
    return {"ok": True, "mode": mode, "queue": _SB_QUEUE}

def stop_agent():
    # stop poller
    _poller_stop.set()
    if _poller_thread:
        _poller_thread.join(timeout=5)
    # stop listener
    _listen_stop.set()
    if _listen_thread:
        _listen_thread.join(timeout=5)