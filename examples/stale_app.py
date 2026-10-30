"""Deliberately stale API usage, for the linter to find. Do not copy; it is never run."""

import anthropic

client = anthropic.Anthropic()
MODEL = "claude-opus-5-5"


def summarise(text: str) -> str:
    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        temperature=0.2,
        top_p=0.9,
        thinking={"type": "enabled", "budget_tokens": 8000},
        messages=[
            {"role": "user", "content": text},
            {"role": "assistant", "content": "Summary:"},
        ],
    )
    return response.content[0].text


def extract_order(text: str, schema: dict) -> str:
    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        tool_choice={"type": "tool", "name": "record_order"},
        output_format={"type": "json_schema", "schema": schema},
        messages=[{"role": "user", "content": text}],
    )
    if response.stop_reason == "tool_use":
        return "called"
    return "done"


def legacy_call(text: str) -> None:
    params = {
        "model": "claude-3-5-sonnet-20241022",
        "max_tokens": 256,
        "messages": [{"role": "user", "content": text}],
    }
    reply = client.messages.create(**params)
    print(reply.content)


PINNED = "claude-haiku-4-5-20251001"
