# /// script
# requires-python = ">=3.12"
# dependencies = ["anthropic", "httpx", "jiwer", "python-dotenv"]
# ///
"""Spike: can Claude fix misheard names in a Groq transcript using episode context and web search?

Claude returns a list of corrections (heard -> correct) that code applies; it never rewrites the transcript.
Each correction is checked against the published transcript, and jargon counts are compared before and after.
Run after compare_transcription.py has cached Groq transcripts: uv run spikes/transcription/correct_names.py
"""

import concurrent.futures
import enum
import json
import pathlib
import re
import statistics
from dataclasses import dataclass
from decimal import Decimal

import anthropic
import dotenv

import compare_transcription

SOURCE_TRANSCRIPT = "groq-whisper-large-v3-turbo.basic.chunks.txt"
MAX_WEB_SEARCHES = 5
MAX_OUTPUT_TOKENS = 16000
PARALLEL_EPISODES = 4

SYSTEM_PROMPT = """You fix misheard names and jargon in automatic podcast transcripts.

Speech-to-text gets ordinary words right but mangles rare proper nouns: people, companies, crypto protocols and tokens, malware and hacking groups, products, places, and technical terms. Your job is to find those and give the correct spelling.

Use the episode title and description first, since they usually spell the guests and topics correctly. Search the web when a term looks misheard and the context doesn't settle it.

Rules:
- Only fix proper nouns and jargon. Never fix grammar, filler words, punctuation, or phrasing.
- "heard" must be copied exactly from the transcript, and should be as short as possible while still unambiguous: just the misheard word or phrase.
- Only include a correction you're confident in. A wrong "fix" is worse than leaving a mishearing alone.
- If the transcript already spells something correctly, leave it out.
- Return an empty list if nothing needs fixing."""

CORRECTIONS_SCHEMA = {
    "type": "object",
    "properties": {
        "corrections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "heard": {"type": "string"},
                    "correct": {"type": "string"},
                    "evidence": {
                        "type": "string",
                        "enum": ["description", "web_search", "context"],
                    },
                },
                "required": ["heard", "correct", "evidence"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["corrections"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class Model:
    name: str
    model_id: str
    # Haiku isn't on the dynamic-filtering web search version, so it gets the basic one
    web_search_type: str
    usd_per_million_input: Decimal
    usd_per_million_output: Decimal


MODELS = [
    Model(
        name="haiku-5.5",
        model_id="claude-haiku-5-5",
        web_search_type="web_search_20250305",
        usd_per_million_input=Decimal("0.10"),
        usd_per_million_output=Decimal("0.50"),
    ),
    Model(
        name="sonnet-5.5",
        model_id="claude-sonnet-5-5",
        web_search_type="web_search_20260209",
        usd_per_million_input=Decimal("2"),
        usd_per_million_output=Decimal("10"),
    ),
]
# Unverified list price for the web search server tool
USD_PER_WEB_SEARCH = Decimal("0.01")


class Verdict(enum.StrEnum):
    CONFIRMED = "confirmed"  # The published transcript uses the corrected spelling
    WRONG = (
        "wrong"  # The published transcript uses what was heard, so the "fix" broke it
    )
    UNVERIFIABLE = "unverifiable"  # The published transcript uses neither spelling


@dataclass
class Correction:
    heard: str
    correct: str
    evidence: str
    replacements: int
    verdict: Verdict | None


@dataclass
class EpisodeResult:
    slug: str
    corrections: list[Correction]
    error_before: float
    error_after: float
    usd: Decimal
    web_searches: int


def main() -> None:
    dotenv.load_dotenv(compare_transcription.REPO_ROOT / ".env")
    client = anthropic.Anthropic()
    prepared = [
        item for item in compare_transcription.prepare_all() if item.reference_text
    ]

    for model in MODELS:
        print(f"\n##### {model.name}")
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=PARALLEL_EPISODES
        ) as executor:
            results = list(
                executor.map(
                    lambda item: _correct_episode(
                        client=client, model=model, item=item
                    ),
                    prepared,
                )
            )
        _print_corrections(results=results)
        _print_summary(model=model, results=results)
        _print_jargon(prepared=prepared, model=model)


def _correct_episode(
    client: anthropic.Anthropic,
    model: Model,
    item: compare_transcription.PreparedEpisode,
) -> EpisodeResult:
    episode_dir = item.chunks[0].parent.parent
    transcript = " ".join((episode_dir / SOURCE_TRANSCRIPT).read_text().split("\n\n"))

    # Ask Claude for corrections, then apply them in code so it can't drop or rewrite anything else
    response, web_searches = _request_corrections(
        client=client, model=model, item=item, transcript=transcript
    )
    corrections = _parse_corrections(response=response)
    corrected = _apply_corrections(transcript=transcript, corrections=corrections)
    (episode_dir / f"corrected.{model.name}.txt").write_text(corrected)

    # Judge each fix against the published transcript, and check the overall error didn't get worse
    for correction in corrections:
        correction.verdict = _verdict(
            correction=correction, reference_text=item.reference_text
        )
    usage = response.usage
    return EpisodeResult(
        slug=item.slug,
        corrections=corrections,
        error_before=compare_transcription.score_transcript(
            reference_text=item.reference_text, hypothesis_text=transcript
        ).word_error_rate,
        error_after=compare_transcription.score_transcript(
            reference_text=item.reference_text, hypothesis_text=corrected
        ).word_error_rate,
        usd=(
            usage.input_tokens * model.usd_per_million_input
            + usage.output_tokens * model.usd_per_million_output
        )
        / 1_000_000
        + web_searches * USD_PER_WEB_SEARCH,
        web_searches=web_searches,
    )


def _request_corrections(
    client: anthropic.Anthropic,
    model: Model,
    item: compare_transcription.PreparedEpisode,
    transcript: str,
) -> tuple[anthropic.types.Message, int]:
    messages = [
        {
            "role": "user",
            "content": (
                f"Show: {item.show.prompt_hint}\n"
                f"Episode title: {item.title}\n"
                f"Episode description: {item.description}\n\n"
                f"<transcript>\n{transcript}\n</transcript>"
            ),
        }
    ]

    # Web search runs server-side; a long search loop pauses and is resumed by resending the turn
    web_searches = 0
    while True:
        response = client.messages.create(
            model=model.model_id,
            max_tokens=MAX_OUTPUT_TOKENS,
            system=SYSTEM_PROMPT,
            messages=messages,
            tools=[
                {
                    "type": model.web_search_type,
                    "name": "web_search",
                    "max_uses": MAX_WEB_SEARCHES,
                }
            ],
            output_config={
                "format": {"type": "json_schema", "schema": CORRECTIONS_SCHEMA}
            },
        )
        server_tool_use = response.usage.server_tool_use
        web_searches += server_tool_use.web_search_requests if server_tool_use else 0
        if response.stop_reason != "pause_turn":
            print(
                f"  done {item.slug} ({response.stop_reason}, {web_searches} searches)"
            )
            return response, web_searches
        messages = [messages[0], {"role": "assistant", "content": response.content}]


def _parse_corrections(response: anthropic.types.Message) -> list[Correction]:
    # With web search, text blocks can precede the answer, so the JSON is the last text block
    text = [block.text for block in response.content if block.type == "text"][-1]
    return [
        Correction(
            heard=entry["heard"],
            correct=entry["correct"],
            evidence=entry["evidence"],
            replacements=0,
            verdict=None,
        )
        for entry in json.loads(text)["corrections"]
        if entry["heard"].strip() and entry["heard"] != entry["correct"]
    ]


def _apply_corrections(transcript: str, corrections: list[Correction]) -> str:
    # Whole-word, case-insensitive replacement, so "Ty" can't rewrite the middle of "Tyler"
    result = transcript
    for correction in corrections:
        pattern = re.compile(
            rf"(?<!\w){re.escape(correction.heard)}(?!\w)", flags=re.IGNORECASE
        )
        result, correction.replacements = pattern.subn(correction.correct, result)
    return result


def _verdict(correction: Correction, reference_text: str) -> Verdict:
    reference = f" {compare_transcription.normalize(text=reference_text)} "
    correct_in_reference = (
        f" {compare_transcription.normalize(text=correction.correct)} " in reference
    )
    heard_in_reference = (
        f" {compare_transcription.normalize(text=correction.heard)} " in reference
    )
    if correct_in_reference:
        return Verdict.CONFIRMED
    return Verdict.WRONG if heard_in_reference else Verdict.UNVERIFIABLE


# --- Output ---


def _print_corrections(results: list[EpisodeResult]) -> None:
    for result in results:
        print(f"\n[{result.slug}]")
        for correction in result.corrections:
            print(
                f"  {correction.verdict:<13} {correction.heard!r} -> {correction.correct!r}"
                f" ×{correction.replacements} ({correction.evidence})"
            )


def _print_summary(model: Model, results: list[EpisodeResult]) -> None:
    corrections = [
        correction for result in results for correction in result.corrections
    ]
    counts = {
        verdict: sum(1 for correction in corrections if correction.verdict == verdict)
        for verdict in Verdict
    }
    total_usd = sum(result.usd for result in results)
    print(
        f"\n=== {model.name}: {len(corrections)} corrections over {len(results)} episodes ==="
    )
    print("  " + " · ".join(f"{verdict}: {count}" for verdict, count in counts.items()))
    print(
        f"  never matched the transcript: {sum(1 for correction in corrections if not correction.replacements)}"
    )
    print(
        f"  mean error before {statistics.mean(result.error_before for result in results):.2%}"
        f" -> after {statistics.mean(result.error_after for result in results):.2%}"
    )
    print(
        f"  web searches: {sum(result.web_searches for result in results)} · cost ${total_usd:.2f}"
        f" (${total_usd / len(results):.3f} per 15-min clip)"
    )


def _print_jargon(
    prepared: list[compare_transcription.PreparedEpisode], model: Model
) -> None:
    # The same known-term counts as the transcription spike, before and after correction
    print(
        f"\n=== {model.name}: known jargon spelled correctly (ref / groq before / after) ==="
    )
    for show in compare_transcription.SHOWS:
        items = [item for item in prepared if item.show == show]
        for term in show.jargon_terms:
            relevant = [
                item
                for item in items
                if compare_transcription.count_term(term=term, text=item.reference_text)
            ]
            if not relevant:
                continue
            reference_count, before, after = (
                sum(
                    compare_transcription.count_term(term=term, text=read(item))
                    for item in relevant
                )
                for read in (
                    lambda item: item.reference_text,
                    lambda item: (
                        item.chunks[0].parent.parent / SOURCE_TRANSCRIPT
                    ).read_text(),
                    lambda item: (
                        item.chunks[0].parent.parent / f"corrected.{model.name}.txt"
                    ).read_text(),
                )
            )
            print(
                f"  {show.slug:16} {term:14} {reference_count:>3} / {before:>3} / {after:>3}"
            )


if __name__ == "__main__":
    main()
