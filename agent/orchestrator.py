"""
ReAct orchestrator.

Loop:
  think → act (tool calls, sequential or parallel) → observe → think → ...

Stopping conditions (in priority order):
  1. model emits finish_reason="stop" with no tool calls  → clean answer
  2. tool returns ToolResult(terminal=True)               → surface immediately
  3. cycle detected (same tool + args called twice)       → force synthesis
  4. max_steps or max_tool_calls budget exhausted         → force synthesis
"""

from __future__ import annotations
import asyncio
import json
import logging
from datetime import date
from typing import AsyncIterator, Awaitable, Callable

from agent.llm_client import LLMClient, LLMResponse, ToolCall
from tools.registry import registry, ToolResult

log = logging.getLogger(__name__)


SYSTEM_PROMPT = """\
You are a climbing training assistant. You help climbers track their progress,
analyze their logs, and answer questions about climbing.

Today's date: {today}

You have access to tools to query the user's climb logs, profile, chat history,
and external climber databases. Use them as needed. When you have enough
information, respond directly and concisely.

Important rules:
- ALWAYS use the appropriate tool to answer questions about climb logs, profile, or
  external climbers — never answer from session history or memory, even if a similar
  question was answered earlier in the conversation. The database is the source of
  truth; prior answers in chat may be stale.
- For any action that modifies data (update profile, create log), describe the
  change you're about to make and wait for the user to confirm before calling
  the mutating tool.
- When multiple tools can be called independently, call them together —
  the system will run them in parallel. Prefer breadth: if a question
  could be answered by more than one data source, query all relevant
  sources in the same step rather than waiting for one result before
  deciding to call the next.
- If a tool returns no data, say so clearly rather than guessing.
"""


def _build_messages(
    session_history: list[dict],
    user_message: str,
    proactive_context: str | None = None,
) -> list[dict]:
    """Build the messages list for the LLM call."""
    system = SYSTEM_PROMPT.format(today=date.today().isoformat())
    if proactive_context:
        system += (
            f"\n\nRELEVANT CONTEXT (retrieved automatically):\n{proactive_context}"
        )

    messages = [{"role": "system", "content": system}]
    messages.extend(session_history)
    messages.append({"role": "user", "content": user_message})
    return messages


def _is_cycle(tool_call: ToolCall, call_log: list[tuple[str, str]]) -> bool:
    """True if the exact same (name, args) has been called before this step."""
    key = (tool_call.name, json.dumps(tool_call.arguments, sort_keys=True))
    return key in call_log


def _tool_call_to_message(response: LLMResponse) -> dict:
    """Convert an LLM response with tool calls into the 'assistant' message format."""
    return {
        "role": "assistant",
        "content": response.content,
        "tool_calls": [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.name,
                    "arguments": json.dumps(tc.arguments),
                },
            }
            for tc in response.tool_calls
        ],
    }


def _tool_result_to_message(tc: ToolCall, result: ToolResult) -> dict:
    """Convert a ToolResult into a 'tool' role message."""
    if result.status == "error":
        content = f"Error: {result.message}"
    elif result.status == "empty":
        content = "No results found."
    else:
        content = json.dumps(result.data, default=str)
    return {"role": "tool", "tool_call_id": tc.id, "content": content}


class OrchestratorEvent:
    """Streamed events from the orchestrator for the UI to render."""


class ThinkingEvent(OrchestratorEvent):
    pass


class ToolStartEvent(OrchestratorEvent):
    def __init__(self, calls: list[ToolCall]):
        self.calls = calls


class ToolDoneEvent(OrchestratorEvent):
    def __init__(self, calls: list[ToolCall], results: list[ToolResult]):
        self.calls = calls
        self.results = results


class AnswerEvent(OrchestratorEvent):
    def __init__(self, content: str, usage: dict):
        self.content = content
        self.usage = usage


class ErrorEvent(OrchestratorEvent):
    def __init__(self, message: str):
        self.message = message


class Orchestrator:
    def __init__(self, llm: LLMClient, cfg: dict, vector_store=None):
        self.llm = llm
        self.max_steps: int = cfg.get("max_steps", 10)
        self.max_tool_calls: int = cfg.get("max_tool_calls", 20)
        self.parallel: bool = cfg.get("parallel_tools", True)
        self.vector_store = vector_store

    async def run(
        self,
        user_message: str,
        session_history: list[dict],
        confirm_fn: Callable[[str], Awaitable[bool]] | None = None,
    ) -> AsyncIterator[OrchestratorEvent]:
        """
        Async generator that yields OrchestratorEvents as the agent works.
        The UI consumes these to show thinking indicators, tool activity, and final answer.

        confirm_fn: optional async callback used for needs_confirmation tool results.
          Receives the human-readable summary string, returns True (proceed) or
          False (cancel). The orchestrator pauses the loop until it resolves.
        """
        # Proactive context: semantic search over past logs before the first LLM call
        proactive_context: str | None = None
        if self.vector_store is not None:
            matches = await self.vector_store.search(user_message, top_k=5)
            if matches:
                lines = [
                    f"- [{m.metadata.get('source', '?')}] {m.text}" for m in matches
                ]
                proactive_context = "\n".join(lines)

        messages = _build_messages(
            session_history, user_message, proactive_context=proactive_context
        )
        call_log: list[tuple[str, str]] = []
        total_tool_calls = 0

        for _ in range(self.max_steps):
            yield ThinkingEvent()

            # Inject budget hint when getting close
            remaining = self.max_tool_calls - total_tool_calls
            if 0 < remaining <= 3:
                messages[-1][
                    "content"
                ] += f"\n[Note: you have {remaining} tool call(s) remaining. Synthesize if possible.]"

            response = await self.llm.complete(messages, tools=registry.schemas)

            # ── Stopping condition 1: model is done ──
            if response.finish_reason == "stop" or not response.tool_calls:
                content = response.content or "(no response)"
                yield AnswerEvent(content=content, usage=response.usage)
                return

            tool_calls = response.tool_calls

            # ── Stopping condition 3: cycle detection ──
            new_calls = [tc for tc in tool_calls if not _is_cycle(tc, call_log)]
            cycled = [tc for tc in tool_calls if _is_cycle(tc, call_log)]
            if cycled:
                log.warning(f"Cycle detected for: {[tc.name for tc in cycled]}")
            if not new_calls:
                # All calls are cycles — force synthesis
                force_response = await self.llm.complete(messages, tools=None)
                yield AnswerEvent(
                    content=force_response.content or "(no response)",
                    usage=force_response.usage,
                )
                return

            # ── Stopping condition 4: budget check ──
            if total_tool_calls + len(new_calls) > self.max_tool_calls:
                force_response = await self.llm.complete(messages, tools=None)
                yield AnswerEvent(
                    content=force_response.content or "(no response)",
                    usage=force_response.usage,
                )
                return

            yield ToolStartEvent(calls=new_calls)

            # ── Execute tools: parallel or sequential ──
            if self.parallel and len(new_calls) > 1:
                results = list(
                    await asyncio.gather(
                        *[registry.dispatch(tc.name, tc.arguments) for tc in new_calls]
                    )
                )
            else:
                results = []
                for tc in new_calls:
                    results.append(await registry.dispatch(tc.name, tc.arguments))

            # ── Handle needs_confirmation ──
            for i, (tc, result) in enumerate(zip(new_calls, results)):
                if result.status == "needs_confirmation":
                    if confirm_fn is not None:
                        confirmed = await confirm_fn(
                            result.message or "Confirm action?"
                        )
                        if confirmed:
                            results[i] = await registry.commit(tc.name, result.data)
                        else:
                            results[i] = ToolResult(
                                data=None,
                                status="error",
                                message="Action cancelled by user.",
                            )
                    # if no confirm_fn, pass through as-is so the LLM sees the summary

            total_tool_calls += len(new_calls)
            for tc in new_calls:
                call_log.append((tc.name, json.dumps(tc.arguments, sort_keys=True)))

            yield ToolDoneEvent(calls=new_calls, results=list(results))

            # ── Stopping condition 2: terminal tool result ──
            terminal = next((r for r in results if r.terminal), None)
            if terminal:
                yield AnswerEvent(
                    content=terminal.message or str(terminal.data), usage={}
                )
                return

            # Append to message history for next step
            messages.append(_tool_call_to_message(response))
            for tc, result in zip(new_calls, results):
                messages.append(_tool_result_to_message(tc, result))

        # Exhausted max_steps — force final synthesis
        force_response = await self.llm.complete(messages, tools=None)
        yield AnswerEvent(
            content=force_response.content or "(no response)",
            usage=force_response.usage,
        )
