"""
Climbing Agents PoC — terminal chat UI
Run: python main.py
"""

import asyncio
from datetime import date

from dotenv import load_dotenv
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.styles import Style
from prompt_toolkit.patch_stdout import patch_stdout

from agent.config import load_config
from agent.llm_client import LLMClient
from agent.orchestrator import (
    Orchestrator,
    ThinkingEvent,
    ToolStartEvent,
    ToolDoneEvent,
    AnswerEvent,
    ErrorEvent,
)
from db.schema import init_schema
from db.seed import seed
from memory import SqliteVecStore
from tools import init_all_tools


# ─────────────────────────────────────────────
# Styles
# ─────────────────────────────────────────────

STYLE = Style.from_dict(
    {
        "prompt": "bold #00aaff",
        "confirm": "bold #ffaa00",
        "assistant": "#aaffaa",
        "tool-name": "bold #ffaa00",
        "tool-result": "#888888",
        "thinking": "italic #666666",
        "divider": "#444444",
        "error": "bold #ff4444",
        "usage": "#555555",
        "header": "bold #ffffff",
    }
)


# ─────────────────────────────────────────────
# Print helpers (use plain print to work with patch_stdout)
# ─────────────────────────────────────────────


def print_divider():
    print("\033[90m" + "─" * 60 + "\033[0m")


def print_header(text: str):
    print(f"\033[1;97m{text}\033[0m")


def print_assistant(text: str):
    print(f"\033[92m{text}\033[0m")


def print_tool_start(calls: list) -> None:
    mode = "parallel" if len(calls) > 1 else "sequential"
    print(f"  \033[90m⚙  [{mode}]\033[0m")
    for tc in calls:
        args_str = ", ".join(f"{k}={v!r}" for k, v in tc.arguments.items())
        print(f"  \033[90m   \033[93m{tc.name}\033[90m({args_str})\033[0m")


def print_tool_done(calls, results):
    for tc, result in zip(calls, results):
        status_icon = (
            "✓"
            if result.status == "ok"
            else (
                "∅"
                if result.status == "empty"
                else "⚠" if result.status == "needs_confirmation" else "✗"
            )
        )
        print(f"  \033[90m{status_icon}  {tc.name} → {result.status}\033[0m")


def print_thinking():
    print(f"  \033[2;37m… thinking\033[0m", end="\r")


def print_usage(usage: dict):
    if usage:
        tokens = usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0)
        print(f"\033[90m  [{tokens} tokens]\033[0m")


# ─────────────────────────────────────────────
# Session message persistence helpers
# ─────────────────────────────────────────────


def persist_message(db_path: str, session_date: str, role: str, content: str):
    from db.schema import get_connection

    conn = get_connection(db_path)
    conn.execute(
        "INSERT INTO chat_messages (session_date, role, content) VALUES (?, ?, ?)",
        (session_date, role, content),
    )
    conn.commit()
    conn.close()


def load_today_session(db_path: str, session_date: str) -> list[dict]:
    """Load today's chat messages to restore session context."""
    from db.schema import get_connection

    conn = get_connection(db_path)
    rows = conn.execute(
        """SELECT role, content FROM chat_messages
           WHERE session_date = ? AND role IN ('user', 'assistant')
           ORDER BY created_at ASC""",
        (session_date,),
    ).fetchall()
    conn.close()
    return [{"role": r["role"], "content": r["content"]} for r in rows]


# ─────────────────────────────────────────────
# Main chat loop
# ─────────────────────────────────────────────


async def chat_loop(orchestrator: Orchestrator, db_path: str):
    session_date = date.today().isoformat()
    session_history = load_today_session(db_path, session_date)

    prompt_session = PromptSession(
        history=InMemoryHistory(),
        style=STYLE,
    )

    async def confirm_fn(message: str) -> bool:
        """Ask the user to confirm a proposed mutation before it's committed."""
        print(f"\n\033[93m  ⚠  {message}\033[0m")
        with patch_stdout():
            try:
                answer = await prompt_session.prompt_async(
                    HTML("<confirm>  confirm? [y/N] › </confirm> "),
                    style=STYLE,
                )
            except (EOFError, KeyboardInterrupt):
                return False
        return answer.strip().lower() in ("y", "yes")

    print_header("╔══════════════════════════════════╗")
    print_header("║   Climbing Agents PoC  🧗         ║")
    print_header("╚══════════════════════════════════╝")
    print(
        f"\033[90mSession: {session_date}  |  history: {len(session_history)//2} prior turns\033[0m"
    )
    print(f"\033[90mType your question, or 'exit' / Ctrl-D to quit.\033[0m")
    print_divider()

    if session_history:
        print(
            f"\033[90m(Session restored — {len(session_history)//2} turns from today)\033[0m\n"
        )

    while True:
        try:
            with patch_stdout():
                user_input = await prompt_session.prompt_async(
                    HTML("<prompt>you › </prompt> "),
                    style=STYLE,
                )
        except KeyboardInterrupt:
            # Ctrl+C — clear the current input and reprompt
            print("\r\033[K", end="")  # clear the line in place
            continue
        except EOFError:
            # Ctrl+D — quit
            print("\n\033[90mGoodbye. Keep sending it! 🏔\033[0m")
            break

        user_input = user_input.strip()
        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit", "q"):
            print("\033[90mGoodbye. Keep sending it! 🏔\033[0m")
            break

        print()

        # Persist user message
        persist_message(db_path, session_date, "user", user_input)

        # Run orchestrator, consume events
        answer_content = None
        async for event in orchestrator.run(
            user_input, session_history, confirm_fn=confirm_fn
        ):
            if isinstance(event, ThinkingEvent):
                print_thinking()
            elif isinstance(event, ToolStartEvent):
                print("  " + " " * 12, end="\r")  # clear "thinking" line
                print_tool_start(event.calls)
            elif isinstance(event, ToolDoneEvent):
                print_tool_done(event.calls, event.results)
            elif isinstance(event, AnswerEvent):
                print("  " + " " * 20, end="\r")  # clear last status line
                print_divider()
                print_assistant(event.content)
                print_usage(event.usage)
                answer_content = event.content
            elif isinstance(event, ErrorEvent):
                print(f"\033[91mError: {event.message}\033[0m")

        print_divider()
        print()

        if answer_content:
            # Persist assistant message and update in-memory history
            persist_message(db_path, session_date, "assistant", answer_content)
            session_history.append({"role": "user", "content": user_input})
            session_history.append({"role": "assistant", "content": answer_content})

            # Keep in-memory history bounded (last 20 turns = 40 messages)
            if len(session_history) > 40:
                session_history = session_history[-40:]


# ─────────────────────────────────────────────
# Vector store backfill
# ─────────────────────────────────────────────


async def _backfill_logs(vector_store, db_path: str) -> None:
    """Upsert all existing climb logs into the vector store (idempotent)."""
    from db.schema import get_connection

    conn = get_connection(db_path)
    rows = conn.execute("SELECT * FROM climb_logs").fetchall()
    conn.close()
    if not rows:
        return

    def _log_text(r) -> str:
        parts = []
        for f in ("grade", "style", "outcome"):
            if r[f]:
                parts.append(r[f])
        if r["location"]:
            parts.append(f"at {r['location']}")
        if r["route_name"]:
            parts.append(f'"{r["route_name"]}"')
        if r["notes"]:
            parts.append(f"— {r['notes']}")
        return " ".join(parts) or "(no details)"

    await vector_store.upsert(
        ids=[r["id"] for r in rows],
        texts=[_log_text(r) for r in rows],
        metadata=[{"source": "climb_logs"}] * len(rows),
    )
    print(f"\033[90m[vector store] backfilled {len(rows)} climb log(s)\033[0m")


# ─────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────


async def _async_main() -> None:
    load_dotenv()

    cfg = load_config()
    db_path = cfg["db"]["path"]

    # Init DB
    init_schema(db_path)
    seed(db_path)  # no-op if already seeded

    # Init LLM client (shared for chat + embeddings)
    llm = LLMClient(cfg["llm"])

    # Init vector store
    vector_store = SqliteVecStore(db_path, llm._client)

    # Init tools — pass vector store for write-side upserts on create_log_entry
    init_all_tools(db_path, vector_store=vector_store)

    # Backfill any existing climb logs into the vector store
    await _backfill_logs(vector_store, db_path)

    # Init orchestrator with vector store for proactive context injection
    orc = Orchestrator(llm, cfg["agent"], vector_store=vector_store)

    await chat_loop(orc, db_path)


def main():
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()
