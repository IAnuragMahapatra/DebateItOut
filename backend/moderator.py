from __future__ import annotations

import os
import re
from prompts.system_prompt import build_system_prompt

# --- turn order ---

def determine_next_speaker(
    debate: dict,
    messages: list[dict],
) -> dict:
    current_round = debate["currentRound"]
    a_models = debate["factionA"]["models"]
    b_models = debate["factionB"]["models"]

    if current_round % 2 == 1:
        ordered = [("A", mid) for mid in a_models] + [("B", mid) for mid in b_models]
    else:
        ordered = [("B", mid) for mid in b_models] + [("A", mid) for mid in a_models]

    spoke = {
        (m["faction"], m["modelId"]) for m in messages if m["round"] == current_round
    }

    for faction, model_id in ordered:
        if (faction, model_id) not in spoke:
            return {"faction": faction, "model_id": model_id, "model_name": _model_name(model_id)}

    raise ValueError(f"All models have already spoken in round {current_round}")


def determine_next_status(
    debate: dict, all_messages: list[dict]
) -> tuple[str, int | None]:
    current_round = debate["currentRound"]
    max_rounds = debate["maxRounds"]
    total = len(debate["factionA"]["models"]) + len(debate["factionB"]["models"])

    current_msgs = [m for m in all_messages if m["round"] == current_round]

    if len(current_msgs) < total:
        return "active", None

    if current_round >= max_rounds:
        return "concluded", None

    return "active", current_round + 1


# --- context assembly ---

def _model_name(model_id: str) -> str:
    # model_id is "endpoint_id|model_slug", we just return the slug
    if "|" in model_id:
        return model_id.split("|", 1)[1]
    return model_id

def assemble_context(
    debate: dict,
    messages: list[dict],
    speaker: dict,
) -> dict:
    faction = speaker["faction"]
    model_id = speaker["model_id"]
    name = _model_name(model_id)

    if faction == "A":
        teammate_ids = [mid for mid in debate["factionA"]["models"] if mid != model_id]
        opponent_ids = debate["factionB"]["models"]
        stance = debate["factionA"]["stance"]
    else:
        teammate_ids = [mid for mid in debate["factionB"]["models"] if mid != model_id]
        opponent_ids = debate["factionA"]["models"]
        stance = debate["factionB"]["stance"]

    reveal = False # Not currently exposed in UI, default False
    teammate_names = [_model_name(mid) for mid in teammate_ids]
    opponent_names = [_model_name(mid) for mid in opponent_ids] if reveal else None

    current_round = debate["currentRound"]
    max_rounds = debate["maxRounds"]

    is_opening_faction = (faction == "A" and current_round % 2 == 1) or (
        faction == "B" and current_round % 2 == 0
    )
    is_first_round = current_round == 1
    is_final_round = current_round == max_rounds

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
            parts = []
            if msg.get("thinking"):
                parts.append(f"<thinking>\n{msg['thinking']}\n</thinking>")
            if msg.get("teamMsg"):
                parts.append(f"<team_msg>\n{msg['teamMsg']}\n</team_msg>")
            parts.append(f"<argument>\n{msg['argument']}\n</argument>")
            raw.append({"role": "assistant", "content": "\n\n".join(parts)})

        elif mf == faction:
            tname = _model_name(mid)
            parts = [f"[Teammate: {tname}]"]
            if msg.get("teamMsg"):
                parts.append(msg["teamMsg"])
            parts.append(msg["argument"])
            raw.append({"role": "user", "content": "\n".join(parts)})

        else:
            prefix = f"[Opponent: {_model_name(mid)}]" if reveal else "[Opponent]"
            raw.append({"role": "user", "content": f"{prefix}\n{msg['argument']}"})

    merged = _merge_roles(raw)

    if not merged or merged[0]["role"] == "assistant":
        merged.insert(
            0,
            {"role": "user", "content": "[Debate started. Make your opening argument.]"},
        )

    if merged and merged[-1]["role"] == "assistant":
        merged.append({"role": "user", "content": "[Please continue the debate.]"})

    all_text = system + "".join(m["content"] for m in merged)
    token_estimate = len(all_text) // 4

    return {
        "system": system,
        "messages": merged,
        "token_estimate": token_estimate,
        "evicted_rounds": [],
        "_raw_messages": messages,
        "_speaker": speaker,
        "_debate": debate,
    }


def _merge_roles(messages: list[dict]) -> list[dict]:
    if not messages:
        return []
    merged = [dict(messages[0])]
    for msg in messages[1:]:
        if msg["role"] == merged[-1]["role"]:
            merged[-1]["content"] += f"\n\n{msg['content']}"
        else:
            merged.append(dict(msg))
    return merged


def apply_token_budget(context: dict, model_id: str) -> dict:
    # 8000 default context size
    max_tokens = 8000

    if context["token_estimate"] <= max_tokens:
        return context

    speaker = context["_speaker"]
    debate = context["_debate"]
    current_round = debate["currentRound"]
    faction = speaker["faction"]
    evicted: list[int] = list(context["evicted_rounds"])

    evictable = sorted(
        {
            m["round"]
            for m in context["_raw_messages"]
            if m["faction"] == faction and m["round"] < current_round - 1
        }
    )

    for evict_round in evictable:
        if context["token_estimate"] <= max_tokens:
            break
        before = context["token_estimate"]
        evicted.append(evict_round)
        filtered = [
            m for m in context["_raw_messages"]
            if not (m["faction"] == faction and m["round"] == evict_round)
        ]
        context = assemble_context(debate, filtered, speaker)
        context["evicted_rounds"] = list(evicted)
        print(f"[token-budget] {model_id} — evicted round {evict_round}: {before} → {context['token_estimate']} tokens")

    return context


def parse_xml_response(raw_text: str) -> dict:
    thinking = _extract_tag(raw_text, "thinking")
    team_msg = _extract_tag(raw_text, "team_msg")
    argument = _extract_tag(raw_text, "argument")

    if argument is None:
        argument = _extract_unclosed_tag(raw_text, "argument")

    if argument is not None:
        return {
            "argument": argument.strip(),
            "team_msg": team_msg.strip() if team_msg else None,
            "thinking": thinking.strip() if thinking else None,
            "parse_ok": True,
        }

    cleaned = raw_text
    if thinking is not None:
        cleaned = re.sub(r"<thinking>.*?</thinking>", "", cleaned, count=1, flags=re.DOTALL)
    if team_msg is not None:
        cleaned = re.sub(r"<team_msg>.*?</team_msg>", "", cleaned, count=1, flags=re.DOTALL)
    cleaned = cleaned.strip()

    if not cleaned:
        cleaned = raw_text.strip()
    
    return {
        "argument": cleaned,
        "team_msg": team_msg.strip() if team_msg else None,
        "thinking": thinking.strip() if thinking else None,
        "parse_ok": False,
    }

def _extract_tag(text: str, tag: str) -> str | None:
    match = re.search(rf"<{tag}>(.*?)</{tag}>", text, re.DOTALL)
    return match.group(1) if match else None

def _extract_unclosed_tag(text: str, tag: str) -> str | None:
    match = re.search(rf"<{tag}>(.*)", text, re.DOTALL)
    return match.group(1) if match else None
