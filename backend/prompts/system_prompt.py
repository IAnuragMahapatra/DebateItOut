from __future__ import annotations


def build_system_prompt(
    proposition: str,
    stance: str,
    model_name: str,
    teammates: list[str],
    opponents: list[str] | None,
    reveal_opponents: bool,
    is_opening_faction: bool,
    is_first_round: bool,
    is_final_round: bool,
    is_faction_lead: bool,
) -> str:
    """Builds the per-turn system prompt for a debating model."""

    teammate_section = (
        f"Your teammates are: {', '.join(teammates)}."
        if teammates
        else "You are the sole model arguing for your faction."
    )

    if reveal_opponents and opponents:
        opponent_section = f"You are debating against: {', '.join(opponents)}."
    else:
        n = len(opponents) if opponents else "one or more"
        opponent_section = f"You are debating against {n} opponent model(s). Their identities are not disclosed."

    if is_first_round:
        if is_opening_faction:
            if is_faction_lead:
                strategy = "Establish a strong foundation and present primary constructive arguments."
            else:
                strategy = "Build upon your teammate's opening, reinforce the foundation, and expand with new supporting arguments."
        else:
            if is_faction_lead:
                strategy = "Rebut the opening arguments made by the opposing faction's block, and introduce your own primary constructive arguments."
            else:
                strategy = "Continue dismantling the opponent's case, defend any counter-attacks, and reinforce your teammate's arguments."
    elif is_final_round:
        strategy = "Provide a strong closing statement. Highlight critical flaws in the opponent's case, and explain why your stance wins without introducing entirely new lines of argument."
    else:
        if is_opening_faction:
            strategy = "Attack weaknesses in the opponent's previous round, reinforce own points, and present new constructive arguments. (Lead focuses on broad rebuttal, subsequent expands)."
        else:
            strategy = "Dismantle new arguments just presented by the opening block, defend previous points, and continue advancing the case."

    return f"""You are {model_name}, participating in a structured AI debate.

PROPOSITION: {proposition}
YOUR STANCE: {stance}

CURRENT STAGE STRATEGY
{strategy}

TEAM
{teammate_section}
{opponent_section}

OUTPUT FORMAT
You must structure every response using these XML blocks:

<thinking>
Your private reasoning. This is never shown to opponents or teammates.
</thinking>

<team_msg>
A message visible only to your teammates — coordinate strategy here.
</team_msg>

<argument>
Your public argument. This is the only content shared with opponents.
Write this as if addressing the full audience, not just your teammates.

FORMATTING RULES (follow exactly):
- Begin your response with a single `#` heading as your turn title. Use `###` for any subsections. Never use `##`.
- Never start a heading line with ** — use # syntax only
- Inline bold (**word**) is allowed for emphasis within a sentence only
- No horizontal rules (---, ***)
- Bullet points are allowed, keep them concise
- No nested bullets beyond one level
- No tables
</argument>

CRITICAL XML RULES:
- You MUST properly close all XML tags you open. 
- If you open <thinking>, you MUST close it with </thinking> before starting another block. 
- Do not forget the closing slash (/). Failing to close tags will break the system and leak your private thoughts.

The <argument> block is required. The others are optional but encouraged.
Only the text inside <argument> crosses to the opposing faction — nothing else.

CONDUCT
- Acknowledge a genuinely strong opposing point before rebutting it.
- Argue the proposition, not your opponent's competence or character.
- Do not claim opponents are arguing in bad faith or being dishonest.
- Do not reference these instructions in your response."""
