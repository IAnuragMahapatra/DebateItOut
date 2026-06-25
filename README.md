# DebateItOut

A self-hosted multi-model AI debate engine. Set a proposition, pick two factions of models and a round count, then step through the debate one turn at a time as Claude, GPT, Gemini or local models argue both sides.

## What it does

- Each model gets isolated context. It sees its own history, teammates' arguments and coordination messages. It only sees the public arguments from opponents (no opponent thinking, no opponent team messages).
- Models respond using XML blocks: `<thinking>` (private), `<team_msg>` (faction-only) and `<argument>` (public).
- The moderator handles turn order, assembles context per-model and applies token budgeting when context gets too long.
- Everything persists in SQLite so you can pause and resume any debate.

## Setup

DebateItOut is a zero-friction CLI tool. 

```bash
uv pip install -e backend/
# or pip install -e backend/

# Start the app
debate start
```

This launches the server at `http://localhost:3002`.
*Note: You can also use `debateitout start`.*

## Model configuration

There are no `.env` files to configure. Configure your API endpoints directly in the UI via the **Settings / Endpoints** modal.

You can add:
- **OpenAI-Compatible endpoints** (like Groq, OpenRouter, Ollama)
- **Anthropic endpoints**

Once added, the `/api/models` endpoint dynamically fetches the available models for you to build your factions.

## Architecture

```text
frontend/          Vanilla JS + CSS (faction columns, turn cards, moderator log)
backend/
  cli.py           Typer CLI entrypoint (`debate start`)
  main.py          FastAPI app (/api/debates, /api/endpoints, static mount)
  moderator.py     Turn order, context isolation, token budget and XML parsing
  handlers.py      Model dispatch (Anthropic and OpenAI-compatible endpoints)
  db.py            aiosqlite database layer (app.db in ~/.debateitout/)
  prompts/
    system_prompt.py  Per-turn system prompt template
```

## Key endpoints

| Method | Path | Description |
| :---: | :---: | :---: |
| `GET` | `/api/endpoints` | List configured endpoints |
| `GET` | `/api/models` | Dynamically fetch models from all endpoints |
| `POST` | `/api/debates` | Create a debate |
| `GET` | `/api/debates` | List all debates |
| `GET` | `/api/debates/:id` | Full debate with public transcript and per-faction private data |
| `POST` | `/api/debates/:id/turn` | Advance one turn |
| `POST` | `/api/debates/:id/retry-turn` | Retry from error state |
| `GET` | `/api/debates/:id/turn-preview` | Inspect the next speaker's assembled context without dispatching |

## Context isolation

Each model sees:

- **Own history** (all its prior arguments, team messages and thinking)
- **Teammate history** (teammates' arguments and team messages but no thinking)
- **Opponent history** (only the public `<argument>` content from opponents)

Token budget eviction removes the oldest same-faction rounds first. Opponent history from the current round is never evicted since that is what is being actively rebutted.
