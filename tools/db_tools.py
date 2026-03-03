"""
Database tools: structured queries over climb_logs and chat_messages.
"""

import json
from db.schema import get_connection
from tools.registry import registry, ToolResult

_db_path: str = ""


def init_db_tools(db_path: str):
    global _db_path
    _db_path = db_path


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
                "or 'how many sends did I have at Movement last month?'"
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
                "or to find a particular climb the user mentioned."
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
