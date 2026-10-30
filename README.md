# messages-api-lint

Code written against last year's Claude API keeps compiling and then returns a 400. This finds it before the request does.

Parameters such as `budget_tokens`, `temperature` and a forced `tool_choice` are fine on some models and rejected on others, so the same line can be correct or broken depending on the model string beside it. This reads your source with the Python AST, plus a best-effort regex pass for TypeScript, and judges each call against the model it names. It never calls the API.

No dependencies, no API key, no network. Not affiliated with Anthropic.

## Rules have a date

**Rules written: 2026-10-30.** Source: the `claude-api` skill bundled with Claude Code 2.1.309. The API changes, so a clean run means "clean against that snapshot". The date appears in `--version`, in every text summary and in the JSON output, and the CLI prints a note once the rules pass 180 days old.

## Quickstart

```sh
pip install -e .
messages-api-lint path/to/your/code
```

```text
$ messages-api-lint examples/stale_app.py
examples/stale_app.py:10: MA003 error: `temperature` and `top_p` together return a 400 on claude-opus-5-5
examples/stale_app.py:10: MA009 warning: `response.content` is read but `response.stop_reason` never is; a `refusal` is an HTTP 200, and `max_tokens` means a cut-off reply
examples/stale_app.py:13: MA002 error: `temperature=0.2` returns a 400 on claude-opus-5-5; omit it and steer in the prompt
examples/stale_app.py:14: MA002 error: `top_p=0.9` returns a 400 on claude-opus-5-5; omit it and steer in the prompt
examples/stale_app.py:15: MA001 error: `budget_tokens` returns a 400 on claude-opus-5-5; use `thinking={'type': 'adaptive'}` and `output_config.effort`
examples/stale_app.py:18: MA004 error: a final assistant turn returns a 400 on claude-opus-5-5; use `output_config.format` or a system prompt instruction
examples/stale_app.py:25: MA010 info: `response.stop_reason` is compared, but never against 'refusal'
examples/stale_app.py:28: MA008 warning: web_search_20250305 still works but has no dynamic filtering; web_search_20260209 does
examples/stale_app.py:29: MA005 error: `tool_choice` type 'tool' returns a 400 on claude-opus-5-5; use `auto`, name the tool in the prompt, set `strict: true`, and check that a call was made
examples/stale_app.py:30: MA006 warning: top-level `output_format` is deprecated; use `output_config.format`
examples/stale_app.py:40: MA007 error: claude-3-5-sonnet-20241022 was retired on 2025-10-28 and returns a 404; use claude-sonnet-5-5
examples/stale_app.py:44: MA009 warning: `reply.content` is read but `reply.stop_reason` never is; a `refusal` is an HTTP 200, and `max_tokens` means a cut-off reply
examples/stale_app.py:48: MA007 info: dated snapshot claude-haiku-4-5-20251001; the alias is claude-haiku-4-5
1 files: 7 error, 4 warning, 2 info (rules written 2026-10-30)
```

The same mistakes in TypeScript. Findings from this pass are marked `(regex)`:

```text
$ messages-api-lint examples/stale_app.ts
examples/stale_app.ts:8: MA009 warning: `response.content` is read but `response.stop_reason` never is; a `refusal` is an HTTP 200, and `max_tokens` means a cut-off reply (regex)
examples/stale_app.ts:11: MA002 error: `temperature=0.2` returns a 400 on claude-opus-5-5; omit it and steer in the prompt (regex)
examples/stale_app.ts:12: MA001 error: `budget_tokens` returns a 400 on claude-opus-5-5; use `thinking={'type': 'adaptive'}` and `output_config.effort` (regex)
examples/stale_app.ts:13: MA005 error: `tool_choice` type 'any' returns a 400 on claude-opus-5-5; use `auto`, name the tool in the prompt, set `strict: true`, and check that a call was made (regex)
examples/stale_app.ts:16: MA004 error: a final assistant turn returns a 400 on claude-opus-5-5; use `output_config.format` or a system prompt instruction (regex)
examples/stale_app.ts:24: MA007 error: claude-3-opus-20240229 was retired on 2026-01-05 and returns a 404; use claude-opus-4-8 (regex)
1 files: 5 error, 1 warning, 0 info (rules written 2026-10-30)
```

Current code passes:

```text
$ messages-api-lint examples/current_app.py --fail-on info
1 files: 0 error, 0 warning, 0 info (rules written 2026-10-30)
```

Both examples are fixtures for the linter and are never run.

## How severity works

Severity follows the model the call names, resolved through local and module-level constants and `**params` dicts.

- `error`: the reference documents a 400 or 404 for this model. For example, `budget_tokens` on `claude-opus-5-5`.
- `warning`: deprecated, or the model could not be resolved. Pass `--assume-model` when it comes from an environment variable.
- `info`: accepted today, rejected by the model's successors. For example, forced `tool_choice` on `claude-opus-5`.

Exit code is 0 when clean, 1 when a finding reaches `--fail-on` (default `error`), 2 for bad input. Silence one line with `# messages-api-lint: ignore[MA002]`, or `//` in TypeScript.

```text
$ messages-api-lint examples/stale_app.py --select MA005 --format json --fail-on never
{
  "version": 1,
  "rules_written": "2026-10-30",
  "rules_source": "claude-api skill bundled with Claude Code 2.1.309",
  "files": 1,
  "summary": {
    "error": 1
  },
  "findings": [
    {
      "rule": "MA005",
      "severity": "error",
      "title": "forced `tool_choice`",
      "path": "examples/stale_app.py",
      "line": 29,
      "message": "`tool_choice` type 'tool' returns a 400 on claude-opus-5-5; use `auto`, name the tool in the prompt, set `strict: true`, and check that a call was made",
      "engine": "ast",
      "citations": [
        "shared/model-migration.md § Breaking change 2: forced tool use is rejected",
        "shared/model-migration.md § Breaking change 1: forced tool use is rejected"
      ]
    }
  ]
}
```

## Every rule cites its source

Each citation is a section heading in a file of the reference. `SKILL.md`, the reference's index, was not present in the copy I read, so nothing cites it; the facts come from the files under `shared/` and `python/`.

```text
$ messages-api-lint --list-rules
Rules written 2026-10-30 from: claude-api skill bundled with Claude Code 2.1.309
MA001  `budget_tokens` in a thinking config
       shared/model-migration.md § `thinking` - `budget_tokens` -> adaptive
       shared/model-migration.md § Breaking changes (will 400 on Opus 4.7)
       shared/model-migration.md § Breaking change 1: thinking can't be disabled
MA002  sampling parameter on a model or API version that rejects it
       shared/model-migration.md § Sampling parameters - `temperature` / `top_p` / `top_k`
       shared/model-migration.md § Breaking change 2: non-default sampling parameters return a 400
       shared/api-version-migration.md § 1. Sampling parameters are removed
MA003  `temperature` and `top_p` sent together
       shared/model-migration.md § Additional Changes When Coming from 3.x / 4.0 / 4.1 -> 4.6
MA004  assistant prefill as the last message
       shared/model-migration.md § Migrating to the 4.6 family (Opus 4.6 and Sonnet 4.6)
       shared/model-migration.md § Prefill replacement - structured outputs via `output_config.format`
       shared/model-migration.md § Breaking change 3: assistant prefill returns a 400
MA005  forced `tool_choice`
       shared/model-migration.md § Breaking change 2: forced tool use is rejected
       shared/model-migration.md § Breaking change 1: forced tool use is rejected
MA006  deprecated top-level `output_format`
       shared/model-migration.md § All models
       shared/tool-use-concepts.md § Structured Outputs
MA007  dated, deprecated or retired model ID
       shared/model-migration.md § Retired Model Replacements
       shared/model-migration.md § Deprecated Models (retiring soon)
       shared/models.md § Retired Models (no longer available)
       shared/models.md § Legacy Models (still active)
MA008  old server or client tool version
       shared/tool-use-concepts.md § Dynamic Filtering (Claude Opus 5.5 / Claude Opus 5 / Fable 5 / Opus 4.8 / Opus 4.7 / Opus 4.6 / Claude Sonnet 5.5 / Sonnet 5 / Sonnet 4.6)
       shared/model-migration.md § Additional Changes When Coming from 3.x / 4.0 / 4.1 -> 4.6
MA009  response content read without checking `stop_reason`
       python/claude-api/README.md § Stop Reasons
       shared/model-migration.md § `refusal` stop reason - handle before reading content
MA010  `stop_reason` branches never handle `refusal`
       shared/model-migration.md § Additional Changes When Coming from 3.x / 4.0 / 4.1 -> 4.6
       python/claude-api/README.md § Stop Reasons
```

`--check-citations` re-checks those headings against a copy of the reference, which is a cheap way to notice when a newer version has moved something. It checks that the heading exists, not that the fact under it is unchanged.

```text
$ messages-api-lint --check-citations .   # run from the skill directory
24 of 24 citations found in .
```

## Limits

- Nothing has been checked against the live API. The severity table is transcribed from documentation and could contain my own transcription errors.
- The reference disagrees with itself on some retirement dates (a date in one file, "TBD" in another), and several listed dates have already passed without the model moving to the retired table. Those IDs stay at `warning`, and the message says so.
- Model resolution is simple. A model chosen by a function, a config object or a conditional is "unresolved". Last assignment in a scope wins, with no flow analysis.
- Prefill detection needs a literal last message. `messages.append(...)` followed by a call is not seen, because agent loops do that legitimately. Echoing `response.content` is treated as a `pause_turn` resume, not a prefill.
- MA009 stays quiet when the response is returned or passed on, since the receiver may check. It only follows one scope.
- It stays quiet on files with no sign of this SDK (no `anthropic` import and no `claude-` string), because other SDKs also have `client.messages.create`.
- The TypeScript pass is regexes and a bracket matcher. It sees object literals at the call site or in a `const` in the same file. Spreads, imports and helpers are invisible, regex literals can confuse it, and MA009 and MA010 work per file rather than per function.
- Not covered: `thinking: disabled`, computer-use tool changes, beta headers, the `preserved thinking` history checks, and languages other than Python and TypeScript.
- Tests are self-written fixtures: `97 passed in 0.07s`. About 1224 lines of source.

## License

MIT
