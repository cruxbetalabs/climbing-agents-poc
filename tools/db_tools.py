"""
Database tools: structured queries over climb_logs and chat_messages.
"""

import json
import logging
import uuid
from datetime import datetime
from typing import Any

from db.schema import get_connection
from tools.registry import registry, ToolResult

log = logging.getLogger(__name__)

_db_path: str = ""
_vector_store: Any = None


def init_db_tools(db_path: str, vector_store: Any = None) -> None:
    global _db_path, _vector_store
    _db_path = db_path
    _vector_store = vector_store


def _log_text(entry: dict) -> str:
    """Build a searchable text string from a climb log entry for embedding."""
    parts = []
    for field in ("grade", "style", "outcome"):
        if entry.get(field):
            parts.append(entry[field])
    if entry.get("location"):
        parts.append(f"at {entry['location']}")
    if entry.get("route_name"):
        parts.append(f"\"{entry['route_name']}\"")
    if entry.get("notes"):
        parts.append(f"— {entry['notes']}")
    return " ".join(parts) or "(no details)"


# ─────────────────────────────────────────────
# count_climb_logs
# ─────────────────────────────────────────────


@registry.register(
    schema={
        "type": "function",
        "function": {
            "name": "count_climb_logs",
            "description": (
                "Count the number of climb log entries matching optional filters. "
                "Use this to answer questions like 'how many V6 climbs did I do?' "
                "or 'how many sends did I have at Movement last month?'. "
                "ALWAYS call this tool — never answer count questions from session history."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "grade": {
                        "type": "string",
                        "description": "Boulder grade e.g. 'V6', or sport grade e.g. '5.12a'",
                    },
                    "location": {
                        "type": "string",
                        "description": "Gym or crag name, partial match ok",
                    },
                    "outcome": {
                        "type": "string",
                        "enum": ["send", "attempt", "flash", "redpoint", "onsight"],
                    },
                    "style": {
                        "type": "string",
                        "enum": ["boulder", "sport", "trad", "top_rope", "other"],
                    },
                    "start_date": {
                        "type": "string",
                        "description": "ISO date string YYYY-MM-DD, inclusive",
                    },
                    "end_date": {
                        "type": "string",
                        "description": "ISO date string YYYY-MM-DD, inclusive",
                    },
                },
                "required": [],
            },
        },
    }
)
def count_climb_logs(
    grade: str | None = None,
    location: str | None = None,
    outcome: str | None = None,
    style: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> ToolResult:
    conn = get_connection(_db_path)
    clauses, params = [], []

    if grade:
        clauses.append("grade = ?")
        params.append(grade)
    if location:
        clauses.append("location LIKE ?")
        params.append(f"%{location}%")
    if outcome:
        clauses.append("outcome = ?")
        params.append(outcome)
    if style:
        clauses.append("style = ?")
        params.append(style)
    if start_date:
        clauses.append("DATE(logged_at) >= ?")
        params.append(start_date)
    if end_date:
        clauses.append("DATE(logged_at) <= ?")
        params.append(end_date)

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    row = conn.execute(f"SELECT COUNT(*) FROM climb_logs {where}", params).fetchone()
    conn.close()
    count = row[0]
    return ToolResult(data={"count": count}, status="ok" if count > 0 else "empty")


# ─────────────────────────────────────────────
# query_climb_logs
# ─────────────────────────────────────────────


@registry.register(
    schema={
        "type": "function",
        "function": {
            "name": "query_climb_logs",
            "description": (
                "Retrieve individual climb log entries with optional filters. "
                "Use this to get details about specific climbs, recent sessions, "
                "or to find a particular climb the user mentioned. "
                "ALWAYS call this tool — never answer from session history or prior responses."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "grade": {"type": "string"},
                    "location": {"type": "string", "description": "Partial match"},
                    "outcome": {
                        "type": "string",
                        "enum": ["send", "attempt", "flash", "redpoint", "onsight"],
                    },
                    "style": {
                        "type": "string",
                        "enum": ["boulder", "sport", "trad", "top_rope", "other"],
                    },
                    "start_date": {"type": "string", "description": "YYYY-MM-DD"},
                    "end_date": {"type": "string", "description": "YYYY-MM-DD"},
                    "keyword": {
                        "type": "string",
                        "description": "Search notes and route_name for this keyword",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results to return, default 10",
                    },
                },
                "required": [],
            },
        },
    }
)
def query_climb_logs(
    grade: str | None = None,
    location: str | None = None,
    outcome: str | None = None,
    style: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    keyword: str | None = None,
    limit: int = 10,
) -> ToolResult:
    conn = get_connection(_db_path)
    clauses, params = [], []

    if grade:
        clauses.append("grade = ?")
        params.append(grade)
    if location:
        clauses.append("location LIKE ?")
        params.append(f"%{location}%")
    if outcome:
        clauses.append("outcome = ?")
        params.append(outcome)
    if style:
        clauses.append("style = ?")
        params.append(style)
    if start_date:
        clauses.append("DATE(logged_at) >= ?")
        params.append(start_date)
    if end_date:
        clauses.append("DATE(logged_at) <= ?")
        params.append(end_date)
    if keyword:
        clauses.append("(notes LIKE ? OR route_name LIKE ?)")
        params += [f"%{keyword}%", f"%{keyword}%"]

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = conn.execute(
        f"SELECT * FROM climb_logs {where} ORDER BY logged_at DESC LIMIT ?",
        params + [limit],
    ).fetchall()
    conn.close()

    data = [dict(r) for r in rows]
    return ToolResult(data=data, status="ok" if data else "empty")


# ─────────────────────────────────────────────
# search_chat_history
# ─────────────────────────────────────────────


@registry.register(
    schema={
        "type": "function",
        "function": {
            "name": "search_chat_history",
            "description": (
                "Search past chat messages for a keyword or topic. "
                "Use this when the user references something they mentioned before, "
                "e.g. 'did I tell you about that crux move?'. "
                "ALWAYS call this tool to search — do not rely on what you recall "
                "from the current context window, as the database contains the full history. "
                "NOTE: this only searches conversation history. "
                "Always pair this with query_climb_logs(keyword=...) in parallel "
                "to also check climb log notes — the user may have logged it there instead."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "Word or phrase to search for in past messages",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results, default 5",
                    },
                },
                "required": ["keyword"],
            },
        },
    }
)
def search_chat_history(keyword: str, limit: int = 5) -> ToolResult:
    conn = get_connection(_db_path)
    rows = conn.execute(
        """SELECT session_date, role, content, created_at
           FROM chat_messages
           WHERE content LIKE ?
           ORDER BY created_at DESC
           LIMIT ?""",
        (f"%{keyword}%", limit),
    ).fetchall()
    conn.close()

    data = [dict(r) for r in rows]
    return ToolResult(data=data, status="ok" if data else "empty")


# ─────────────────────────────────────────────
# create_log_entry  (two-phase: propose → confirm → commit)
# ─────────────────────────────────────────────


async def _do_create_log_entry(entry: dict) -> ToolResult:
    """Phase 2: actually INSERT the entry. Called by registry.commit() after user confirms."""
    conn = get_connection(_db_path)
    conn.execute(
        """INSERT INTO climb_logs
               (id, logged_at, location, route_name, grade, style, outcome, attempts, notes, tags)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            entry["id"],
            entry["logged_at"],
            entry.get("location"),
            entry.get("route_name"),
            entry.get("grade"),
            entry.get("style"),
            entry.get("outcome"),
            entry.get("attempts", 1),
            entry.get("notes"),
            entry.get("tags", "[]"),
        ),
    )
    conn.commit()
    conn.close()

    if _vector_store is not None:
        try:
            await _vector_store.upsert(
                ids=[entry["id"]],
                texts=[_log_text(entry)],
                metadata=[{"source": "climb_logs"}],
            )
        except Exception as exc:
            log.warning("vector store upsert skipped: %s", exc)

    grade = entry.get("grade") or "?"
    loc = entry.get("location") or "unknown location"
    return ToolResult(
        data=entry,
        status="ok",
        message=f"Log entry created: {grade} at {loc}.",
    )


@registry.register(
    schema={
        "type": "function",
        "function": {
            "name": "create_log_entry",
            "description": (
                "Create a new climb log entry. Use this when the user says they climbed "
                "something, wants to log a session, or asks to record a send or attempt. "
                "The entry is shown to the user for confirmation before being saved."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "grade": {
                        "type": "string",
                        "description": "Boulder grade e.g. 'V6', or sport grade e.g. '5.12a'",
                    },
                    "location": {
                        "type": "string",
                        "description": "Gym or crag name",
                    },
                    "route_name": {
                        "type": "string",
                        "description": "Name of the route or problem, if mentioned",
                    },
                    "style": {
                        "type": "string",
                        "enum": ["boulder", "sport", "trad", "top_rope", "other"],
                    },
                    "outcome": {
                        "type": "string",
                        "enum": ["send", "attempt", "flash", "redpoint", "onsight"],
                    },
                    "attempts": {
                        "type": "integer",
                        "description": "Number of attempts. Defaults to 1.",
                    },
                    "notes": {
                        "type": "string",
                        "description": "Any notes the user mentioned about the climb",
                    },
                    "logged_at": {
                        "type": "string",
                        "description": "ISO datetime YYYY-MM-DDTHH:MM:SS. Defaults to now.",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional tags, e.g. ['heel hook', 'overhang']",
                    },
                },
                "required": [],
            },
        },
    },
    commit_fn=_do_create_log_entry,
)
def create_log_entry(
    grade: str | None = None,
    location: str | None = None,
    route_name: str | None = None,
    style: str | None = None,
    outcome: str | None = None,
    attempts: int = 1,
    notes: str | None = None,
    logged_at: str | None = None,
    tags: list[str] | None = None,
) -> ToolResult:
    """Phase 1: builds a proposed entry and returns needs_confirmation."""
    entry = {
        "id": str(uuid.uuid4()),
        "logged_at": logged_at or datetime.now().isoformat(timespec="seconds"),
        "location": location,
        "route_name": route_name,
        "grade": grade,
        "style": style,
        "outcome": outcome,
        "attempts": attempts,
        "notes": notes,
        "tags": json.dumps(tags or []),
    }
    # Build a human-readable confirmation summary
    parts = []
    if grade:
        parts.append(grade)
    if style:
        parts.append(style)
    if outcome:
        parts.append(outcome)
    if location:
        parts.append(f"at {location}")
    if route_name:
        parts.append(f'"{route_name}"')
    if attempts and attempts != 1:
        parts.append(f"{attempts} attempts")
    summary = (
        "Create log entry: " + " ".join(parts) if parts else "Create new log entry"
    )
    if notes:
        summary += f'\n  Notes: "{notes}"'
    return ToolResult(data=entry, status="needs_confirmation", message=summary)
