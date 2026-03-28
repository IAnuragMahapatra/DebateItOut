from __future__ import annotations

import os
import re

from prompts.system_prompt import build_system_prompt


# --- turn order ---

def determine_next_speaker(
    debate: dict,
    messages: list[dict],
    all_models: list[dict] | None = None,
) -> dict:
    """Returns the next model that should speak, in faction-block order."""
    current_round = debate["currentRound"]
    a_models = debate["factionA"]["models"]
    b_models = debate["factionB"]["models"]

    # odd rounds: A opens, even rounds: B opens
    if current_round % 2 == 1:
        ordered = [("A", mid) for mid in a_models] + [("B", mid) for mid in b_models]
    else:
        ordered = [("B", mid) for mid in b_models] + [("A", mid) for mid in a_models]

    spoke = {(m["faction"], m["modelId"]) for m in messages if m["round"] == current_round}

    for faction, model_id in ordered:
        if (faction, model_id) not in spoke:
            result: dict = {"faction": faction, "model_id": model_id}
            if all_models:
                m = next((x for x in all_models if x["id"] == model_id), None)
                result["model_name"] = m["name"] if m else model_id
            return result

    raise ValueError(f"All models have already spoken in round {current_round}")


def determine_next_status(debate: dict, all_messages: list[dict]) -> tuple[str, int | None]:
    """Returns (next_status, next_round). next_round is None when the round doesn't change."""
    current_round = debate["currentRound"]
    max_rounds = debate["maxRounds"]
    total = len(debate["factionA"]["models"]) + len(debate["factionB"]["models"])

    current_msgs = [m for m in all_messages if m["round"] == current_round]

    if len(current_msgs) < total:
        # still speakers left this round
        return "active", None

    if current_round >= max_rounds:
        return "concluded", None

    return "active", current_round + 1


# --- context assembly ---

def _model_name(model_id: str, all_models: list[dict]) -> str:
    m = next((x for x in all_models if x["id"] == model_id), None)
    return m["name"] if m else model_id


def assemble_context(
    debate: dict,
    messages: list[dict],
    speaker: dict,
    all_models: list[dict],
) -> dict:
    """
    Assembles the per-model conversation context with 4-tier visibility:
      own messages     → assistant role (includes thinking + team_msg + argument)
      teammate messages → user role (team_msg + argument, no thinking)
      opponent messages → user role (argument only)
    Messages already arrive ordered by round ASC, created_at ASC from the DB.
    """
    faction = speaker["faction"]
    model_id = speaker["model_id"]
    name = _model_name(model_id, all_models)

    if faction == "A":
        teammate_ids = [mid for mid in debate["factionA"]["models"] if mid != model_id]
        opponent_ids = debate["factionB"]["models"]
        stance = debate["factionA"]["stance"]
    else:
        teammate_ids = [mid for mid in debate["factionB"]["models"] if mid != model_id]
        opponent_ids = debate["factionA"]["models"]
        stance = debate["factionB"]["stance"]

    reveal = os.getenv("REVEAL_OPPONENT_IDENTITY", "false").lower() == "true"
    teammate_names = [_model_name(mid, all_models) for mid in teammate_ids]
    opponent_names = [_model_name(mid, all_models) for mid in opponent_ids] if reveal else None

    current_round = debate["currentRound"]
    max_rounds = debate["maxRounds"]

    # Faction A opens odd rounds, Faction B opens even rounds
    is_opening_faction = (faction == "A" and current_round % 2 == 1) or \
                         (faction == "B" and current_round % 2 == 0)
    is_first_round = current_round == 1
    is_final_round = current_round == max_rounds

    # Check if this model is the first one in its faction's model list
    faction_key = "factionA" if faction == "A" else "factionB"
    is_faction_lead = debate[faction_key]["models"][0] == model_id

    system = build_system_prompt(
        proposition=debate["proposition"],
        stance=stance,
        model_name=name,
        teammates=teammate_names,
        opponents=opponent_names,
        reveal_opponents=reveal,
        is_opening_faction=is_opening_faction,
        is_first_round=is_first_round,
        is_final_round=is_final_round,
        is_faction_lead=is_faction_lead,
    )

    raw: list[dict] = []

    for msg in messages:
        mid = msg["modelId"]
        mf = msg["faction"]

        if mid == model_id:
            # own turn — assistant, include thinking + team_msg + argument
            parts = []
            if msg.get("thinking"):
                parts.append(f"<thinking>\n{msg['thinking']}\n</thinking>")
            if msg.get("teamMsg"):
                parts.append(f"<team_msg>\n{msg['teamMsg']}\n</team_msg>")
            parts.append(f"<argument>\n{msg['argument']}\n</argument>")
            raw.append({"role": "assistant", "content": "\n\n".join(parts)})

        elif mf == faction:
            # teammate — user, team_msg + argument, no thinking
            tname = _model_name(mid, all_models)
            parts = [f"[Teammate: {tname}]"]
            if msg.get("teamMsg"):
                parts.append(msg["teamMsg"])
            parts.append(msg["argument"])
            raw.append({"role": "user", "content": "\n".join(parts)})

        else:
            # opponent — user, argument only
            prefix = f"[Opponent: {_model_name(mid, all_models)}]" if reveal else "[Opponent]"
            raw.append({"role": "user", "content": f"{prefix}\n{msg['argument']}"})

    # merge consecutive same-role entries (required for Anthropic)
    merged = _merge_roles(raw)

    # Anthropic requires the conversation to start with a user message;
    # also inject one when there's no history at all (first turn)
    if not merged or merged[0]["role"] == "assistant":
        merged.insert(0, {"role": "user", "content": "[Debate started. Make your opening argument.]"})

    all_text = system + "".join(m["content"] for m in merged)
    token_estimate = len(all_text) // 4

    return {
        "system": system,
        "messages": merged,
        "token_estimate": token_estimate,
        "evicted_rounds": [],
        # metadata kept for apply_token_budget to rebuild if needed
        "_raw_messages": messages,
        "_speaker": speaker,
        "_debate": debate,
        "_all_models": all_models,
    }


def _merge_roles(messages: list[dict]) -> list[dict]:
    """Merge consecutive messages of the same role into one."""
    if not messages:
        return []
    merged = [dict(messages[0])]
    for msg in messages[1:]:
        if msg["role"] == merged[-1]["role"]:
            merged[-1]["content"] += f"\n\n{msg['content']}"
        else:
            merged.append(dict(msg))
    return merged


# --- token budget ---

def apply_token_budget(context: dict, model_id: str) -> dict:
    """
    Evicts oldest same-faction rounds until under budget.
    Never removes the current or previous round, never touches opponent history.
    """
    env_key = f"MAX_CONTEXT_TOKENS_{model_id.upper()}"
    max_tokens = int(os.getenv(env_key) or os.getenv("MAX_CONTEXT_TOKENS", "8000"))

    if context["token_estimate"] <= max_tokens:
        return context

    speaker = context["_speaker"]
    debate = context["_debate"]
    all_models = context["_all_models"]
    current_round = debate["currentRound"]
    faction = speaker["faction"]
    evicted: list[int] = list(context["evicted_rounds"])

    # rounds eligible for eviction: same faction, older than (current - 1)
    evictable = sorted({
        m["round"] for m in context["_raw_messages"]
        if m["faction"] == faction and m["round"] < current_round - 1
    })

    for evict_round in evictable:
        if context["token_estimate"] <= max_tokens:
            break

        before = context["token_estimate"]
        evicted.append(evict_round)

        filtered = [
            m for m in context["_raw_messages"]
            if not (m["faction"] == faction and m["round"] == evict_round)
        ]

        context = assemble_context(debate, filtered, speaker, all_models)
        context["evicted_rounds"] = list(evicted)

        print(
            f"[token-budget] {model_id} — evicted round {evict_round}: "
            f"{before} → {context['token_estimate']} tokens"
        )

    return context


# --- XML parsing ---

def parse_xml_response(raw_text: str) -> dict:
    """
    Extracts <thinking>, <team_msg>, <argument> from model output.
    If <argument> is missing, the whole response becomes the argument (parse_ok=False).
    """
    thinking = _extract_tag(raw_text, "thinking")
    team_msg = _extract_tag(raw_text, "team_msg")
    argument = _extract_tag(raw_text, "argument")

    if argument is not None:
        return {
            "argument": argument.strip(),
            "team_msg": team_msg.strip() if team_msg else None,
            "thinking": thinking.strip() if thinking else None,
            "parse_ok": True,
        }

    # fallback — whole response is treated as the public argument
    return {
        "argument": raw_text.strip(),
        "team_msg": None,
        "thinking": thinking.strip() if thinking else None,
        "parse_ok": False,
    }


def _extract_tag(text: str, tag: str) -> str | None:
    match = re.search(rf"<{tag}>(.*?)</{tag}>", text, re.DOTALL)
    return match.group(1) if match else None
