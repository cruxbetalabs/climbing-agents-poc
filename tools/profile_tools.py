"""
User profile tools: read and update the user's profile stored in SQLite.
"""

from db.schema import get_connection
from tools.registry import registry, ToolResult

_db_path: str = ""


def init_profile_tools(db_path: str):
    global _db_path
    _db_path = db_path


@registry.register(
    schema={
        "type": "function",
        "function": {
            "name": "get_user_profile",
            "description": (
                "Retrieve the user's climbing profile: name, home gym, peak grades, "
                "training focus, and other personal attributes. "
                "ALWAYS call this tool — never answer profile questions from session "
                "history or memory, as the profile may have changed since last asked."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    }
)
def get_user_profile() -> ToolResult:
    conn = get_connection(_db_path)
    rows = conn.execute("SELECT key, value FROM user_profile").fetchall()
    conn.close()
    if not rows:
        return ToolResult(data={}, status="empty", message="No profile found.")
    return ToolResult(data={r["key"]: r["value"] for r in rows})


@registry.register(
    schema={
        "type": "function",
        "function": {
            "name": "update_user_profile",
            "description": (
                "Update a single field in the user's climbing profile. "
                "Use this when the user wants to set or change a profile attribute, "
                "e.g. their peak grade, home gym, or training notes. "
                "Always confirm the change with the user before calling this."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "Profile field name, e.g. 'peak_boulder_grade'",
                    },
                    "value": {
                        "type": "string",
                        "description": "New value for the field",
                    },
                },
                "required": ["key", "value"],
            },
        },
    }
)
def update_user_profile(key: str, value: str) -> ToolResult:
    conn = get_connection(_db_path)
    conn.execute(
        "INSERT OR REPLACE INTO user_profile (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
        (key, value),
    )
    conn.commit()
    conn.close()
    return ToolResult(
        data={"key": key, "value": value},
        status="ok",
        message=f"Profile updated: {key} = {value}",
    )
