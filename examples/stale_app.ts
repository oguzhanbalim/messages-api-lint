// Deliberately stale API usage, for the linter to find. Do not copy; it is never run.
import Anthropic from "@anthropic-ai/sdk";

const client = new Anthropic();
const MODEL = "claude-opus-5-5";

export async function summarise(text: string): Promise<string> {
  const response = await client.messages.create({
    model: MODEL,
    max_tokens: 1024,
    temperature: 0.2,
    thinking: { type: "enabled", budget_tokens: 8000 },
    tool_choice: { type: "any" },
    messages: [
      { role: "user", content: text },
      { role: "assistant", content: "Summary:" },
    ],
  });
  const first = response.content[0];
  return first.type === "text" ? first.text : "";
}

// A comment naming claude-3-opus-20240229 is not a finding.
export const fallbackModel = "claude-3-opus-20240229";
