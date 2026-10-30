from __future__ import annotations

import textwrap

import pytest

from messages_api_lint.python_engine import PythonLinter

HEADER = "import anthropic\nclient = anthropic.Anthropic()\n"


def lint(code: str, assume_model: str | None = None, header: str = HEADER):
    return PythonLinter("app.py", header + textwrap.dedent(code), assume_model).run()


def rules_of(findings) -> dict[str, str]:
    return {f.rule_id: f.severity for f in findings}


def call(args: str) -> str:
    return f"r = client.messages.create(max_tokens=9, messages=[], {args})\nprint(r)\n"


def test_clean_call_has_no_findings():
    code = """
    r = client.messages.create(model="claude-opus-5-5", max_tokens=9,
        messages=[{"role": "user", "content": "hi"}])
    if r.stop_reason == "refusal":
        raise SystemExit
    print(r.content)
    """
    assert lint(code) == []


@pytest.mark.parametrize(
    ("model", "severity"),
    [
        ("claude-opus-5-5", "error"),
        ("claude-sonnet-5", "error"),
        ("claude-haiku-5-5", "error"),
        ("claude-fable-5-1", "error"),
        ("claude-opus-4-6", "warning"),
        ("claude-sonnet-4-6", "warning"),
        ("claude-haiku-4-5", "info"),
        ("claude-opus-4-5-20251101", "info"),
        ("anthropic.claude-opus-5-5", "error"),
    ],
)
def test_ma001_severity_follows_the_model(model, severity):
    code = call(f'model="{model}", thinking={{"type": "enabled", "budget_tokens": 5}}')
    assert rules_of(lint(code))["MA001"] == severity


def test_ma001_unresolved_model_is_a_warning_and_assume_model_decides():
    code = call('model=pick(), thinking={"type": "enabled", "budget_tokens": 5}')
    assert rules_of(lint(code))["MA001"] == "warning"
    assert rules_of(lint(code, assume_model="claude-opus-5-5"))["MA001"] == "error"


def test_ma001_through_variable_and_typed_config():
    code = """
    t = {"type": "enabled", "budget_tokens": 5}
    r = client.messages.create(model="claude-opus-5", thinking=t, max_tokens=9, messages=[])
    print(r)
    """
    assert rules_of(lint(code))["MA001"] == "error"
    code = call('model="claude-opus-5", thinking=ThinkingConfigEnabled(budget_tokens=5)')
    assert rules_of(lint(code))["MA001"] == "error"


def test_ma001_stray_config_without_a_call():
    assert "MA001" in rules_of(lint('T = {"type": "enabled", "budget_tokens": 5}\n'))


def test_adaptive_thinking_is_fine():
    assert "MA001" not in rules_of(
        lint(call('model="claude-opus-5-5", thinking={"type": "adaptive"}'))
    )


@pytest.mark.parametrize(
    ("args", "severity"),
    [
        ('model="claude-opus-5-5", temperature=0.2', "error"),
        ('model="claude-opus-5-5", top_k=5', "error"),
        ('model="claude-opus-5-5", temperature=1', "warning"),  # the default, on API 2023-06-01
        ('model="claude-haiku-5-5", top_p=0.99', "warning"),
        ('model="claude-opus-4-6", temperature=0.2', "warning"),  # 2026-10-21 removes it
        ("model=pick(), temperature=0.2", "warning"),
    ],
)
def test_ma002_severity(args, severity):
    assert rules_of(lint(call(args)))["MA002"] == severity


def test_ma002_inside_extra_body():
    code = call('model="claude-opus-5-5", extra_body={"temperature": 0.5}')
    assert rules_of(lint(code))["MA002"] == "error"


def test_ma003_pair():
    assert rules_of(lint(call('model="claude-opus-4-5", temperature=0.2, top_p=0.9')))["MA003"] == (
        "error"
    )
    assert rules_of(lint(call("model=pick(), temperature=0.2, top_p=0.9")))["MA003"] == "warning"
    assert "MA003" not in rules_of(lint(call('model="claude-opus-4-5", temperature=0.2')))


@pytest.mark.parametrize(
    ("model", "severity"),
    [
        ("claude-opus-5-5", "error"),
        ("claude-opus-4-6", "error"),
        ("claude-sonnet-4-6", "error"),
        ("claude-haiku-5-5", "error"),
        ("claude-haiku-4-5", "info"),
        ("claude-sonnet-4-5", "info"),
    ],
)
def test_ma004_prefill(model, severity):
    code = f"""
    r = client.messages.create(model="{model}", max_tokens=9, messages=[
        {{"role": "user", "content": "hi"}},
        {{"role": "assistant", "content": "{{"}},
    ])
    print(r)
    """
    assert rules_of(lint(code))["MA004"] == severity


def test_ma004_text_block_and_named_list():
    code = """
    msgs = [{"role": "assistant", "content": [{"type": "text", "text": "x"}]}]
    r = client.messages.create(model="claude-opus-5", max_tokens=9, messages=msgs)
    print(r)
    """
    assert rules_of(lint(code))["MA004"] == "error"


def test_ma004_not_for_earlier_assistant_turns_or_resumes():
    few_shot = """
    r = client.messages.create(model="claude-opus-5", max_tokens=9, messages=[
        {"role": "assistant", "content": "example"},
        {"role": "user", "content": "hi"},
    ])
    print(r)
    """
    assert "MA004" not in rules_of(lint(few_shot))
    resume = """
    r = client.messages.create(model="claude-opus-5", max_tokens=9, messages=[
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": previous.content},
    ])
    print(r)
    """
    assert "MA004" not in rules_of(lint(resume))


@pytest.mark.parametrize(
    ("model", "severity"),
    [
        ("claude-opus-5-5", "error"),
        ("claude-sonnet-5-5", "error"),
        ("claude-fable-5-1", "error"),
        ("claude-mythos-5-1", "error"),
        ("claude-opus-5", "info"),
        ("claude-fable-5", "info"),
        ("claude-haiku-5-5", "info"),
    ],
)
def test_ma005_forced_tool_choice(model, severity):
    code = call(f'model="{model}", tool_choice={{"type": "any"}}')
    assert rules_of(lint(code))["MA005"] == severity


def test_ma005_auto_and_none_are_fine():
    for kind in ("auto", "none"):
        code = call(f'model="claude-opus-5-5", tool_choice={{"type": "{kind}"}}')
        assert "MA005" not in rules_of(lint(code))


def test_ma006_output_format_but_not_on_parse():
    assert rules_of(lint(call('model="claude-opus-5-5", output_format=S')))["MA006"] == "warning"
    code = 'r = client.messages.parse(model="claude-opus-5-5", max_tokens=9, messages=[], output_format=S)\nprint(r)\n'  # noqa: E501
    assert "MA006" not in rules_of(lint(code))


@pytest.mark.parametrize(
    ("model", "severity"),
    [
        ("claude-3-5-sonnet-20241022", "error"),
        ("claude-3-opus-20240229", "error"),
        ("claude-2.1", "error"),
        ("claude-3-haiku-20240307", "warning"),
        ("claude-opus-4-20250514", "warning"),
        ("claude-sonnet-4-5-20250929", "info"),
        ("claude-sonnet-9-20990101", "warning"),
    ],
)
def test_ma007_model_ids(model, severity):
    assert rules_of(lint(f'M = "{model}"\n'))["MA007"] == severity


def test_ma007_finds_prefixed_ids_but_not_docstrings_or_comments():
    assert "MA007" in rules_of(lint('M = "us.anthropic.claude-3-opus-20240229-v1:0"\n'))
    code = '''
    def f():
        """Migrated off claude-3-opus-20240229."""
        # also claude-3-opus-20240229 here
    '''
    assert "MA007" not in rules_of(lint(code))


def test_ma007_alias_is_fine():
    assert lint('M = "claude-opus-5-5"\n') == []


def test_ma008_tool_versions():
    assert "MA008" in rules_of(lint('T = {"type": "web_search_20250305", "name": "web_search"}\n'))
    assert "MA008" in rules_of(lint('T = "text_editor_20250124"\n'))
    assert "MA008" in rules_of(lint('T = "str_replace_editor"\n'))
    assert "MA008" not in rules_of(lint('T = "web_search_20260209"\n'))
    assert "MA008" not in rules_of(lint('T = "web_fetch_20260318"\n'))


def test_ma009_content_read_without_stop_reason():
    code = 'r = client.messages.create(model="claude-opus-5-5", max_tokens=9, messages=[])\nprint(r.content)\n'  # noqa: E501
    assert rules_of(lint(code))["MA009"] == "warning"


def test_ma009_quiet_when_the_response_escapes():
    for tail in ("return r", "handle(r)", "print(r.content); log(r)", "print(r.model_dump())"):
        code = f"""
        def f():
            r = client.messages.create(model="claude-opus-5-5", max_tokens=9, messages=[])
            print(r.content)
            {tail}
        """
        assert "MA009" not in rules_of(lint(code)), tail


def test_ma009_covers_await_and_chained_calls():
    code = """
    async def f():
        r = await client.messages.create(model="claude-opus-5-5", max_tokens=9, messages=[])
        print(r.content)
    """
    assert "MA009" in rules_of(lint(code))
    chained = 'print(client.messages.create(model="claude-opus-5-5", max_tokens=9, messages=[]).content)\n'  # noqa: E501
    assert "MA009" in rules_of(lint(chained))


def test_ma009_covers_final_message_from_a_stream():
    code = """
    with client.messages.stream(model="claude-opus-5-5", max_tokens=9, messages=[]) as stream:
        final = stream.get_final_message()
    print(final.content)
    """
    assert "MA009" in rules_of(lint(code))


def test_ma010_branches_without_refusal():
    code = """
    r = client.messages.create(model="claude-opus-5-5", max_tokens=9, messages=[])
    if r.stop_reason in ("end_turn", "max_tokens"):
        print(r.content)
    """
    assert rules_of(lint(code)) == {"MA010": "info"}


def test_ma010_match_statement_and_refusal_present():
    code = """
    r = client.messages.create(model="claude-opus-5-5", max_tokens=9, messages=[])
    match r.stop_reason:
        case "end_turn":
            print(r.content)
        case "refusal":
            pass
    """
    assert lint(code) == []


def test_ma010_quiet_when_stop_reason_is_passed_along():
    code = """
    r = client.messages.create(model="claude-opus-5-5", max_tokens=9, messages=[])
    log(r.stop_reason)
    if r.stop_reason == "tool_use":
        print(r.content)
    """
    assert "MA010" not in rules_of(lint(code))


def test_request_built_as_a_spread_dict():
    code = """
    params = {"model": "claude-opus-5-5", "temperature": 0.3, "max_tokens": 9, "messages": []}
    r = client.messages.create(**params)
    print(r)
    """
    assert rules_of(lint(code))["MA002"] == "error"


def test_raw_http_payload_dict():
    code = """
    requests.post(URL, json={"model": "claude-opus-5-5", "messages": [], "top_k": 3})
    """
    assert rules_of(lint(code))["MA002"] == "error"


def test_scopes_do_not_leak_between_functions():
    code = """
    def a():
        MODEL = "claude-opus-4-5"
        r = client.messages.create(model=MODEL, temperature=0.2, max_tokens=9, messages=[])
        return r

    def b(MODEL):
        r = client.messages.create(model=MODEL, temperature=0.2, max_tokens=9, messages=[])
        return r
    """
    assert all(f.severity == "warning" for f in lint(code) if f.rule_id == "MA002")


def test_module_constant_visible_in_functions():
    code = """
    MODEL = "claude-opus-5-5"
    def f():
        r = client.messages.create(model=MODEL, temperature=0.2, max_tokens=9, messages=[])
        return r
    """
    assert rules_of(lint(code))["MA002"] == "error"


def test_other_messages_apis_are_left_alone():
    code = "client.messages.create(to='+10000000000', temperature=0.5, top_p=0.1)\n"
    assert lint(code, header="import smsclient\nclient = smsclient.Client()\n") == []


def test_other_providers_model_is_left_alone():
    code = 'client.messages.create(model="some-other-model", temperature=0.5, messages=[])\n'
    assert lint(code) == []
