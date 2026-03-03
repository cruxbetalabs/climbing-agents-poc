import sqlite3
import os


def get_connection(db_path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_schema(db_path: str) -> None:
    conn = get_connection(db_path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS user_profile (
            key     TEXT PRIMARY KEY,
            value   TEXT NOT NULL,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS climb_logs (
            id          TEXT PRIMARY KEY,
            logged_at   DATETIME NOT NULL,
            location    TEXT,
            route_name  TEXT,
            grade       TEXT,
            style       TEXT CHECK(style IN ('boulder', 'sport', 'trad', 'top_rope', 'other')),
            outcome     TEXT CHECK(outcome IN ('send', 'attempt', 'flash', 'redpoint', 'onsight')),
            attempts    INTEGER DEFAULT 1,
            notes       TEXT,
            tags        TEXT DEFAULT '[]'
        );

        CREATE TABLE IF NOT EXISTS chat_messages (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            session_date TEXT NOT NULL,
            role        TEXT CHECK(role IN ('user', 'assistant', 'tool')) NOT NULL,
            content     TEXT NOT NULL,
            created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_climb_logs_grade     ON climb_logs(grade);
        CREATE INDEX IF NOT EXISTS idx_climb_logs_logged_at ON climb_logs(logged_at);
        CREATE INDEX IF NOT EXISTS idx_climb_logs_location  ON climb_logs(location);
        CREATE INDEX IF NOT EXISTS idx_chat_session_date    ON chat_messages(session_date);
    """)
    conn.commit()
    conn.close()
