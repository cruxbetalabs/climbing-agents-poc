# climbing-agents-poc

A proof-of-concept for agent orchestration in a personal climbing training app.
The core idea: a terminal chatbot backed by a ReAct agent loop that routes user
questions to the right tools — structured SQLite queries, keyword search over
chat history, user profile reads/writes, and external web scraping — running
them sequentially or in parallel as needed, then synthesizing a response.

Built to explore how agent orchestration patterns (tool routing, parallel dispatch,
cycle detection, budget control) work in a domain-specific context before building
a full backend.

---

## Project structure

```shell
main.py              — entry point, prompt-toolkit chat UI
config.yaml          — LLM provider, model, and app settings
agent/
  config.py          — config loader
  llm_client.py      — provider-agnostic LLM adapter (OpenAI / Ollama / Anthropic stub)
  orchestrator.py    — ReAct loop with parallel tool dispatch and stopping conditions
tools/
  registry.py        — tool registry and ToolResult type
  db_tools.py        — count_climb_logs, query_climb_logs, search_chat_history
  profile_tools.py   — get_user_profile, update_user_profile
  web_tools.py       — get_climber_info (climbing-history.org, no-op stub)
db/
  schema.py          — SQLite schema init and migration helpers
  seed.py            — example climb logs and user profile
data/
  climbing.db        — SQLite database (created on first run)
```

---

## Setup

**1. Clone and create a virtual environment**

```bash
git clone <repo-url>
cd climbing-agents-poc
python -m venv .venv
source .venv/bin/activate
```

**2. Install dependencies**

```bash
pip install -r requirements.txt
```

**3. Add your OpenAI API key**

Copy `.env` and fill in your key:

```bash
# .env
OPENAI_API_KEY=sk-your-key-here
```

**4. (Optional) Adjust model settings**

Edit `config.yaml` to change the model, temperature, or switch provider:

```yaml
llm:
  provider: openai    # openai | ollama
  model: gpt-4o
  temperature: 0.3
```

For Ollama, set `provider: ollama` and `base_url: http://localhost:11434/v1`.

**5. Seed the database**

The database is seeded automatically on first launch with 10 example climb logs
and a user profile. To reseed from scratch at any time:

```bash
python -m db.seed --force
```

**6. Run**

```bash
python main.py
```

---

## Example questions to try

**Querying climb logs**
```
how many V6 climbs did I do?
show me my recent sends at Movement
how many attempts did I have on my V8 project?
```

**Searching across sources** *(hits climb log notes + chat history in parallel)*
```
did I mention anything about a heel hook?
have I logged anything involving a dyno?
did I ever note anything about being underrecovered?
```

**Profile**
```
what does my profile look like?
update my peak boulder grade to V9
```

**External climber lookup** *(mock data until scraping is wired)*
```
how much does Colin Duffy span?
look up Adam Ondra on climbing history
```

---

## How the agent works

Each message goes through a ReAct loop:

1. **Think** — the LLM reasons about what tools to call
2. **Act** — tools are dispatched (in parallel if independent)
3. **Observe** — results are appended to the message context
4. Repeat until a stopping condition is met:
   - Model produces a final answer with no tool calls
   - A tool returns a terminal signal
   - A cycle is detected (same tool + args called twice)
   - Step or token budget is exhausted → forced synthesis

---

## Adding a new tool

1. Create the function in `tools/` and decorate it with `@registry.register(schema={...})`
2. Import the module in `tools/__init__.py` so the decorator fires on startup
3. Call `init_your_tools(db_path)` from `init_all_tools()` if it needs the DB path

The orchestrator picks up new tools automatically via `registry.schemas`.
