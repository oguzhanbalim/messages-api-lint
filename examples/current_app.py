"""Current API usage, which the linter should pass. Not run by the tests or by CI."""

import anthropic

client = anthropic.Anthropic()


def classify(text: str, schema: dict) -> str | None:
    response = client.messages.create(
        model="claude-opus-5-5",
        max_tokens=4096,
        thinking={"type": "adaptive"},
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
        tools=[{"type": "web_search_20260209", "name": "web_search"}],
        messages=[{"role": "user", "content": text}],
    )
    if response.stop_reason == "refusal":
        return None
    if response.stop_reason == "max_tokens":
        raise RuntimeError("reply was cut off")
    return next(block.text for block in response.content if block.type == "text")
