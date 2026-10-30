from __future__ import annotations

from pathlib import Path

from messages_api_lint.ts_engine import (
    TypeScriptLinter,
    match_bracket,
    object_fields,
    split_top_level,
    strip_comments,
)

HEADER = 'import Anthropic from "@anthropic-ai/sdk";\nconst client = new Anthropic();\n'
EXAMPLE = Path(__file__).parent.parent / "examples" / "stale_app.ts"


def lint(code: str, assume_model: str | None = None):
    return TypeScriptLinter("app.ts", HEADER + code, assume_model).run()


def rules_of(findings) -> dict[str, str]:
    return {f.rule_id: f.severity for f in findings}


def call(fields: str) -> str:
    return f"await client.messages.create({{ max_tokens: 9, messages: [], {fields} }});\n"


def test_strip_comments_keeps_offsets_and_strings():
    source = 'a // x\nb /* y\nz */ c "// not a comment"'
    out = strip_comments(source)
    assert len(out) == len(source)
    assert "x" not in out
    assert "y" not in out
    assert '"// not a comment"' in out
    assert out.count("\n") == source.count("\n")


def test_strip_comments_handles_stray_apostrophe_on_a_line():
    out = strip_comments("const a = <p>don't</p>;\nb // gone\n")
    assert "gone" not in out


def test_match_bracket_skips_strings():
    text = '{ a: "}", b: [1, {c: 2}] } tail'
    assert text[match_bracket(text, 0)] == "}"
    assert text[match_bracket(text, 0) + 1 :] == " tail"


def test_split_top_level():
    assert [c.strip() for _, c in split_top_level('a: 1, b: [1, 2], c: "x,y"')] == [
        "a: 1",
        "b: [1, 2]",
        'c: "x,y"',
    ]


def test_object_fields():
    text = "{ model: 'm', 'quoted-key': 2, ...rest, tool_choice }"
    fields = object_fields(text, 0)
    assert fields["model"][1] == "'m'"
    assert fields["quoted-key"][1] == "2"
    assert fields["tool_choice"][1] == "tool_choice"
    assert "rest" not in fields


def test_clean_call():
    code = """
const r = await client.messages.create({
  model: "claude-opus-5-5",
  max_tokens: 9,
  messages: [{ role: "user", content: "hi" }],
});
if (r.stop_reason === "refusal") throw new Error("declined");
console.log(r.content);
"""
    assert lint(code) == []


def test_each_request_rule_fires():
    found = rules_of(
        lint(
            call(
                """model: "claude-opus-5-5", temperature: 0.2, top_p: 0.5,
                thinking: { type: "enabled", budget_tokens: 5 },
                tool_choice: { type: "tool", name: "x" },
                output_format: S"""
            )
        )
    )
    assert found == {
        "MA001": "error",
        "MA002": "error",
        "MA003": "error",
        "MA005": "error",
        "MA006": "warning",
    }


def test_severity_follows_the_model():
    assert rules_of(lint(call('model: "claude-haiku-4-5", tool_choice: { type: "any" }'))) == {
        "MA005": "info"
    }


def test_default_sampling_value_is_a_warning():
    assert rules_of(lint(call('model: "claude-opus-5-5", temperature: 1')))["MA002"] == "warning"


def test_unresolved_model_and_assume_model():
    code = call("model: pickModel(), temperature: 0.2")
    assert rules_of(lint(code))["MA002"] == "warning"
    assert rules_of(lint(code, assume_model="claude-opus-5-5"))["MA002"] == "error"


def test_model_and_params_through_consts():
    code = """
const MODEL = "claude-opus-5-5";
const params = { model: MODEL, temperature: 0.2, max_tokens: 9, messages: [] };
await client.messages.create(params);
"""
    assert rules_of(lint(code))["MA002"] == "error"


def test_prefill_line_number_points_at_the_turn():
    code = """await client.messages.create({
  model: "claude-opus-5-5",
  max_tokens: 9,
  messages: [
    { role: "user", content: "hi" },
    { role: "assistant", content: "{" },
  ],
});
"""
    prefill = [f for f in lint(code) if f.rule_id == "MA004"]
    assert prefill[0].severity == "error"
    assert prefill[0].line == 8  # two header lines, then the sixth line of the call


def test_resume_is_not_a_prefill():
    code = call(
        'model: "claude-opus-5-5", messages: [{ role: "assistant", content: previous.content }]'
    ).replace("messages: [], ", "")
    assert "MA004" not in rules_of(lint(code))


def test_output_format_allowed_on_parse():
    code = 'await client.messages.parse({ model: "claude-opus-5-5", output_format: S });\n'
    assert "MA006" not in rules_of(lint(code))


def test_model_ids_and_tool_versions_in_strings_only():
    code = """
// claude-3-opus-20240229 in a comment
const a = "claude-3-opus-20240229";
const b = { type: "web_search_20250305", name: "web_search" };
"""
    found = lint(code)
    assert [(f.rule_id, f.line) for f in found] == [("MA007", 5), ("MA008", 6)]


def test_stop_reason_rules():
    missing = """
const r = await client.messages.create({ model: "claude-opus-5-5", max_tokens: 9, messages: [] });
console.log(r.content);
"""
    assert rules_of(lint(missing)) == {"MA009": "warning"}
    no_refusal = """
const r = await client.messages.create({ model: "claude-opus-5-5", max_tokens: 9, messages: [] });
if (r.stop_reason === "tool_use") console.log(r.content);
"""
    assert rules_of(lint(no_refusal)) == {"MA010": "info"}
    escapes = """
const r = await client.messages.create({ model: "claude-opus-5-5", max_tokens: 9, messages: [] });
console.log(r.content);
return r;
"""
    assert lint(escapes) == []


def test_final_message_counts_as_a_response():
    code = """
const m = await stream.finalMessage();
console.log(m.content);
"""
    assert rules_of(lint(code)) == {"MA009": "warning"}


def test_unrelated_file_is_left_alone():
    code = "await client.messages.create({ to: '+10000000000', temperature: 0.5 });\n"
    assert TypeScriptLinter("sms.ts", code).run() == []


def test_example_file():
    found = TypeScriptLinter(str(EXAMPLE), EXAMPLE.read_text()).run()
    assert {f.rule_id for f in found} == {"MA001", "MA002", "MA004", "MA005", "MA007", "MA009"}
    assert all(f.engine == "regex" for f in found)
