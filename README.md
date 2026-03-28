# DebateItOut

A self-hosted multi-model AI debate engine. Set a proposition, pick two factions of models and a round count, then step through the debate one turn at a time as Claude, GPT, Gemini or local Ollama models argue both sides.

## What it does

- Each model gets isolated context. It sees its own history, teammates' arguments and coordination messages. It only sees the public arguments from opponents (no opponent thinking, no opponent team messages).
- Models respond using XML blocks: `<thinking>` (private), `<team_msg>` (faction-only) and `<argument>` (public).
- The moderator handles turn order, assembles context per-model and applies token budgeting when context gets too long.
- Everything persists in Postgres so you can pause and resume any debate.

## Architecture

```text
frontend/          Vanilla JS + CSS (faction columns, turn cards, moderator log)
backend/
  main.py          FastAPI app (debate CRUD, /turn, /retry-turn, /turn-preview)
  moderator.py     Turn order, context isolation, token budget and XML parsing
  handlers.py      Model dispatch (Anthropic and OpenAI-compatible endpoints)
  db.py            asyncpg pool, debates and messages schema
  prompts/
    system_prompt.py  Per-turn system prompt template
```

## Setup

**Requirements:** Docker and Docker Compose

```bash
cp backend/.env.example backend/.env
# Edit backend/.env to add your API keys and model endpoints
docker compose up --build
```

Open `http://localhost:3002`.

## Model configuration

Models are configured via environment variables using the pattern `MODEL_<ID>_<FIELD>`:

```env
# Anthropic
MODEL_CLAUDE_NAME=Claude
MODEL_CLAUDE_TYPE=anthropic
MODEL_CLAUDE_API_URL=https://api.anthropic.com/v1/messages
MODEL_CLAUDE_API_KEY=sk-ant-...
MODEL_CLAUDE_ANTHROPIC_VERSION=2023-06-01
MODEL_CLAUDE_MODEL=claude-opus-4-5

# OpenAI-compatible (including Ollama)
MODEL_DEEPSEEK_NAME=DeepSeek
MODEL_DEEPSEEK_TYPE=openai
MODEL_DEEPSEEK_API_URL=http://host.docker.internal:11434/v1/chat/completions
MODEL_DEEPSEEK_API_KEY=ollama
MODEL_DEEPSEEK_MODEL=deepseek-r1:14b
```

Add as many models as you need. They all appear in the faction builder.

## Key endpoints

| Method | Path | Description |
| :---: | :---: | :---: |
| `GET` | `/models` | Available models |
| `POST` | `/debates` | Create a debate |
| `GET` | `/debates` | List all debates |
| `GET` | `/debates/:id` | Full debate with public transcript and per-faction private data |
| `POST` | `/debates/:id/turn` | Advance one turn |
| `POST` | `/debates/:id/retry-turn` | Retry from error state |
| `GET` | `/debates/:id/turn-preview` | Inspect the next speaker's assembled context without dispatching |

The `/turn-preview` endpoint is handy for verifying isolation. You can see exactly what system prompt and message history each model gets before it speaks.

## Debate settings

| Variable | Default | Description |
| :---: | :---: | :---: |
| `DEFAULT_MAX_ROUNDS` | `6` | Rounds per debate |
| `MAX_CONTEXT_TOKENS` | `8000` | Context window budget per turn |
| `MAX_CONTEXT_TOKENS_<MODEL_ID>` | unset | Per-model override |
| `REVEAL_OPPONENT_IDENTITY` | `false` | Whether to tell models who they are debating against |

## Turn order

- Odd rounds: Faction A opens and Faction B responds.
- Even rounds: Faction B opens and Faction A responds.
- Within each faction, models speak in the order they were listed at creation.
- All models in the opening faction speak before any model in the responding faction.

## Context isolation

Each model sees:

- **Own history** (all its prior arguments, team messages and thinking)
- **Teammate history** (teammates' arguments and team messages but no thinking)
- **Opponent history** (only the public `<argument>` content from opponents)

Token budget eviction removes the oldest same-faction rounds first. Opponent history from the current round is never evicted since that is what is being actively rebutted.

## Exporting debates

You can export debates as JSON or Markdown files using the export button in the top right of the screen. A modal will prompt you to choose whether to include private data like thinking blocks and team messages. This makes it easy to save transcripts or share them cleanly.
