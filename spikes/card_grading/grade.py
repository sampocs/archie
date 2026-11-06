"""Grade the dataset's typed answers with Claude models (JSON-schema structured output) and measure accuracy, latency and cost.

Run: uv run --package archie-worker python spikes/card_grading/grade.py <variant> [<variant> ...]
Variants: haiku, sonnet, opus, haiku_1shot. `opus` runs only on the ids where haiku and sonnet disagree with the label.
"""

import concurrent.futures
import json
import os
import pathlib
import sys
import time
from decimal import Decimal

import anthropic

HERE = pathlib.Path(__file__).parent
MODELS = {"haiku": "claude-haiku-5-5", "sonnet": "claude-sonnet-5-5", "opus": "claude-opus-5-5", "haiku_1shot": "claude-haiku-5-5"}
# USD per million tokens (input, output), as in services/worker/archie_worker/llm.py.
PRICES = {"claude-haiku-5-5": (Decimal("0.10"), Decimal("0.50")), "claude-sonnet-5-5": (Decimal(2), Decimal(10)), "claude-opus-5-5": (Decimal(4), Decimal(20))}

# Sonnet thinks by default (slow, and it ate a small token budget); grading needs none. Each model spells "off" differently.
# Opus accepts neither spelling, so it runs with its default and a roomy max_tokens.
THINKING_OFF = {
    "claude-haiku-5-5": {"thinking": {"type": "disabled"}},
    "claude-sonnet-5-5": {"thinking": {"type": "between_tools"}},
}

SYSTEM = """You grade a typed or dictated recall answer to a spaced-repetition flashcard.

Judge the IDEA, not the wording. Be lenient on phrasing, word order, typos, missing punctuation, dictation errors and terseness. Be strict on the core idea: the answer must contain the essential point(s) of the accepted answer and must not contradict them.

Grades:
- got_it: the answer carries the core idea of the accepted answer, in any words. Minor omitted detail is fine.
- partly: the answer is correct as far as it goes but misses an essential part of the idea (for example gives what but not why, or only one of several required parts), or is too vague to show real understanding.
- missed: the answer is wrong, contradicts the accepted answer, is off-topic, or is blank / "I don't know".

Numbers: right if within roughly the precision of the accepted answer (about 5% unless the card says "roughly"/"about", then about 15%). A wrong order of magnitude is missed.

`missing`: for partly and missed, ONE short sentence (under 20 words) saying what the answer lacked or got wrong, addressed to the learner without quoting the whole accepted answer. Empty string for got_it.

`confident`: false only if you genuinely cannot tell whether the answer matches the idea (ambiguous wording, answer might be right under another reading, or the accepted answer itself is unclear). Otherwise true. Do not mark a clear miss or a clear match as not confident."""

ONE_SHOT = """

Example
Question: Why does a regular fridge stay cold when the door is closed?
Accepted answer: The insulated door seal traps cold air, and the compressor only runs to remove the small amount of heat that leaks in.
Answer: "cuz the seal keeps the cold in and the motor kicks on once in a while"
Grade: got_it (the seal and the intermittent compressor are the core idea; wording is casual).
Answer: "The compressor keeps running."
Grade: partly, missing "It doesn't say the insulated seal is what keeps heat out."
"""

# Structured output via output_config, the same mechanism the worker's `complete` uses.
SCHEMA = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "grade": {"type": "string", "enum": ["got_it", "partly", "missed"]},
            "missing": {"type": "string"},
            "confident": {"type": "boolean"},
        },
        "required": ["grade", "missing", "confident"],
}


def grade_one(client: anthropic.Anthropic, variant: str, row: dict) -> dict:
    """Grade one answer; returns the verdict, wall-clock seconds and USD cost."""
    system = SYSTEM + (ONE_SHOT if variant == "haiku_1shot" else "")
    user = f"Question: {row['card']['question']}\nAccepted answer: {row['card']['answer']}\nAnswer: {row['answer']!r}"
    model = MODELS[variant]
    started = time.perf_counter()
    response = client.messages.create(
        model=model,
        max_tokens=1500,
        **THINKING_OFF.get(model, {}),
        system=system,
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": user}],
    )
    seconds = time.perf_counter() - started
    text = "".join(block.text for block in response.content if block.type == "text")
    if not text:
        raise SystemExit(f"no text for id {row['id']}: stop_reason={response.stop_reason} content={response.content}")
    verdict = json.loads(text)
    input_price, output_price = PRICES[model]
    cost = (Decimal(response.usage.input_tokens) * input_price + Decimal(response.usage.output_tokens) * output_price) / 1_000_000
    return {"id": row["id"], **verdict, "seconds": seconds, "cost": float(cost), "in": response.usage.input_tokens, "out": response.usage.output_tokens}


def load_api_key() -> str:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return os.environ["ANTHROPIC_API_KEY"]
    for line in (HERE.parents[1] / ".env").read_text().splitlines():
        if line.startswith("ANTHROPIC_API_KEY="):
            return line.split("=", 1)[1].strip().strip("\"'")
    raise SystemExit("ANTHROPIC_API_KEY not found")


def main() -> None:
    client = anthropic.Anthropic(api_key=load_api_key())
    dataset = json.loads((HERE / "dataset.json").read_text())
    for variant in sys.argv[1:]:
        rows = dataset
        if variant == "opus":
            wrong = set()
            for other in ("haiku", "sonnet"):
                for result in json.loads((HERE / "results_haiku.json" if other == "haiku" else HERE / "results_sonnet.json").read_text()):
                    expected = dataset[result["id"]]["expected"]
                    if result["grade"] != expected:
                        wrong.add(result["id"])
            rows = [row for row in dataset if row["id"] in wrong]
        # Sequential runs would take minutes; 4 workers keeps per-call latency honest (no rate-limit queueing).
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda row: grade_one(client, variant, row), rows))
        (HERE / f"results_{variant}.json").write_text(json.dumps(results, indent=1))
        print(variant, len(results), "calls, $", round(sum(r["cost"] for r in results), 4))


main()
