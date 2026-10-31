# /// script
# requires-python = ">=3.12"
# dependencies = ["anthropic", "httpx", "python-dotenv"]
# ///
"""Spike: what does the per-source LLM pipeline (analyze + primer) cost per hour of content, and how good is it?

Runs the latest full episode with a published transcript from each test show through:
  - analyze: summary (with timestamps), domain/topic, tags, concepts, and 3-5 review cards, on Haiku and on Sonnet
  - primer: the background the episode assumes, on Sonnet and on Opus
Every output is written to outputs/<show>.md for reading, and costs are printed per step and per hour of audio.
Run: uv run spikes/llm_processing/process_sources.py
"""

import concurrent.futures
import enum
import html
import json
import pathlib
import re
import xml.etree.ElementTree
from dataclasses import dataclass
from decimal import Decimal

import anthropic
import dotenv
import httpx

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SPIKE_DIR = pathlib.Path(__file__).resolve().parent
CACHE_DIR = SPIKE_DIR / ".cache"
OUTPUT_DIR = SPIKE_DIR / "outputs"
PODCAST_NAMESPACE = "https://podcastindex.org/namespace/1.0"
REQUEST_TIMEOUT_SECONDS = 120
# Timestamped lines every ~30s are enough for summaries to cite where an idea came from
TIMESTAMP_INTERVAL_SECONDS = 30
PARALLEL_CALLS = 6
# Monthly listening volume assumed in the findings doc's cost table
MONTHLY_AUDIO_HOURS = Decimal("43")
# Measured by the name-correction spike: Haiku at $0.005 per 15-minute clip
CORRECTION_USD_PER_AUDIO_HOUR = Decimal("0.02")
TRANSCRIPTION_USD_PER_AUDIO_HOUR = Decimal("0.04")


@dataclass(frozen=True)
class Show:
    slug: str
    feed_url: str
    description: str


SHOWS = [
    Show(
        slug="bankless",
        feed_url="https://feeds.flightcast.com/p83fuj0y0u58o82l41xei7zo.xml",
        description="Bankless (Ryan Sean Adams, David Hoffman): crypto, Ethereum, DeFi",
    ),
    Show(
        slug="money-stuff",
        feed_url="https://www.omnycontent.com/d/playlist/e73c998e-6e60-432f-8610-ae210140c5b1/ee4336cb-155f-4488-90e0-b1400134e40e/77e6a3a7-290d-4a82-8164-b14001353ef2/podcast.rss",
        description="Money Stuff (Matt Levine, Katie Greifeld): finance and markets",
    ),
    Show(
        slug="darknet-diaries",
        feed_url="https://podcast.darknetdiaries.com",
        description="Darknet Diaries (Jack Rhysider): true stories of hacking and cybercrime",
    ),
    Show(
        slug="bussin",
        feed_url="https://www.omnycontent.com/d/playlist/e73c998e-6e60-432f-8610-ae210140c5b1/f7d20af0-ea4d-48fc-bc4c-b2920123b22a/95b710b5-a45b-4abe-a98a-b2920123b23f/podcast.rss",
        description="Bussin' With The Boys (Will Compton, Taylor Lewan): NFL and college football",
    ),
    Show(
        slug="acquired",
        feed_url="https://feeds.transistor.fm/acquired",
        description="Acquired (Ben Gilbert, David Rosenthal): company histories",
    ),
]


@dataclass(frozen=True)
class Model:
    name: str
    model_id: str
    usd_per_million_input: Decimal
    usd_per_million_output: Decimal


HAIKU = Model(
    name="haiku-5.5",
    model_id="claude-haiku-5-5",
    usd_per_million_input=Decimal("0.10"),
    usd_per_million_output=Decimal("0.50"),
)
SONNET = Model(
    name="sonnet-5.5",
    model_id="claude-sonnet-5-5",
    usd_per_million_input=Decimal("2"),
    usd_per_million_output=Decimal("10"),
)
OPUS = Model(
    name="opus-5.5",
    model_id="claude-opus-5-5",
    usd_per_million_input=Decimal("4"),
    usd_per_million_output=Decimal("20"),
)


class Step(enum.StrEnum):
    ANALYZE = "analyze"
    PRIMER = "primer"


STEP_MODELS = {Step.ANALYZE: [HAIKU, SONNET], Step.PRIMER: [SONNET, OPUS]}
MAX_OUTPUT_TOKENS = {Step.ANALYZE: 8000, Step.PRIMER: 6000}

DOMAINS = [
    "AI",
    "Macro",
    "Crypto",
    "Startups",
    "Finance",
    "Tech",
    "History",
    "Security",
    "Sports",
    "Other",
]

# The reading voice is still to be designed, so this is a neutral stand-in shared by every step
READING_VOICE = """Write in plain, conversational English for a smart reader who is new to the subject. Short sentences. \
Define any jargon the first time it appears. Prefer concrete examples and rough numbers ("~1 GW", not "1.07 GW")."""

ANALYZE_SYSTEM_PROMPT = f"""You process podcast episodes for a personal learning app. The user listened to this episode and \
wants "level 2" knowledge of its subject: enough to hold a real conversation about it, including the vocabulary, how things \
work, the key players, rough numbers, and the current debates.

From the transcript, produce:
- summary: the gist in 2-3 sentences, the key ideas, and the numbers worth remembering. Cite the [mm:ss] or [h:mm:ss] \
timestamp where each idea or number comes up. Skip ads and sponsor reads.
- domain: the one broad domain the episode belongs to.
- topic: a short, reusable topic name under that domain (e.g. "Stablecoins", "Fed policy", "NFL quarterbacks").
- tags: 3-8 short tags.
- concepts: the key concepts the episode relies on or teaches, as short noun phrases.
- cards: 3-5 open-recall review cards on concepts, mechanisms ("why does X cause Y"), and rough numbers. Each answer is what \
a good response would cover in 1-3 sentences. Avoid trivia that only matters to this one episode.

{READING_VOICE}"""

PRIMER_SYSTEM_PROMPT = f"""You write primers for a personal learning app. A primer gives the background an episode assumes \
its listener already has, so the episode is easy to follow. It is not a summary of the episode.

Read the transcript, work out which concepts, players, history, and numbers the hosts take for granted, and explain those. \
Write for a smart beginner: friendly, no assumed jargon, a 5-8 minute read (roughly 900-1400 words). Use markdown with short \
sections and a title. Don't reveal the episode's own conclusions or story beats.

{READING_VOICE}"""

ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {
            "type": "object",
            "properties": {
                "gist": {"type": "string"},
                "key_ideas": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "timestamp": {"type": "string"},
                            "idea": {"type": "string"},
                        },
                        "required": ["timestamp", "idea"],
                        "additionalProperties": False,
                    },
                },
                "numbers": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "timestamp": {"type": "string"},
                            "fact": {"type": "string"},
                        },
                        "required": ["timestamp", "fact"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["gist", "key_ideas", "numbers"],
            "additionalProperties": False,
        },
        "domain": {"type": "string", "enum": DOMAINS},
        "topic": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "concepts": {"type": "array", "items": {"type": "string"}},
        "cards": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": ["concept", "mechanism", "number"],
                    },
                    "question": {"type": "string"},
                    "answer": {"type": "string"},
                },
                "required": ["kind", "question", "answer"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["summary", "domain", "topic", "tags", "concepts", "cards"],
    "additionalProperties": False,
}


@dataclass
class Episode:
    show: Show
    title: str
    description: str
    audio_hours: Decimal
    transcript: str


@dataclass
class StepResult:
    show_slug: str
    step: Step
    model: Model
    input_tokens: int
    output_tokens: int
    output: str

    @property
    def usd(self) -> Decimal:
        return (
            self.input_tokens * self.model.usd_per_million_input
            + self.output_tokens * self.model.usd_per_million_output
        ) / 1_000_000


def main() -> None:
    dotenv.load_dotenv(REPO_ROOT / ".env")
    client = anthropic.Anthropic()
    episodes = [_load_episode(show=show) for show in SHOWS]
    for episode in episodes:
        words = len(episode.transcript.split())
        print(
            f"{episode.show.slug:16} {episode.audio_hours:.2f} h · {words:,} words · {episode.title}"
        )

    # Every (episode, step, model) call is independent, so run them side by side
    jobs = [
        (episode, step, model)
        for episode in episodes
        for step, models in STEP_MODELS.items()
        for model in models
    ]
    with concurrent.futures.ThreadPoolExecutor(max_workers=PARALLEL_CALLS) as executor:
        results = list(
            executor.map(
                lambda job: _run_step(
                    client=client, episode=job[0], step=job[1], model=job[2]
                ),
                jobs,
            )
        )

    _write_outputs(episodes=episodes, results=results)
    _print_costs(episodes=episodes, results=results)


# --- Loading episodes ---


def _load_episode(show: Show) -> Episode:
    feed = httpx.get(
        show.feed_url, follow_redirects=True, timeout=REQUEST_TIMEOUT_SECONDS
    ).content
    items = xml.etree.ElementTree.fromstring(feed).find("channel").findall("item")
    item = next(item for item in items if _vtt_url(item=item))
    title = item.findtext("title", default="").strip()

    # Published VTT stands in for the Groq transcript: same length, so the same token cost
    cache_path = CACHE_DIR / f"{show.slug}.vtt"
    if not cache_path.exists():
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        vtt_text = httpx.get(
            _vtt_url(item=item), follow_redirects=True, timeout=REQUEST_TIMEOUT_SECONDS
        ).text
        cache_path.write_text(vtt_text)
    transcript, last_second = _timestamped_transcript(vtt=cache_path.read_text())

    description = html.unescape(
        re.sub(r"<[^>]+>", " ", item.findtext("description", default=""))
    )
    return Episode(
        show=show,
        title=title,
        description=re.sub(r"\s+", " ", description).strip(),
        audio_hours=Decimal(last_second) / 3600,
        transcript=transcript,
    )


def _vtt_url(item: xml.etree.ElementTree.Element) -> str | None:
    tags = item.findall(f"{{{PODCAST_NAMESPACE}}}transcript")
    return next((tag.get("url") for tag in tags if "vtt" in tag.get("type", "")), None)


def _timestamped_transcript(vtt: str) -> tuple[str, int]:
    # Group cues into lines that each start with a timestamp, like Groq's segments would give the real pipeline
    lines: list[str] = []
    current_start = -TIMESTAMP_INTERVAL_SECONDS
    start = 0
    for cue in re.split(r"\n\s*\n", vtt):
        timing = re.search(r"(?:(\d+):)?(\d\d):(\d\d)[.,]\d+\s*-->", cue)
        if not timing:
            continue

        hours, minutes, seconds = timing.groups()
        start = int(hours or 0) * 3600 + int(minutes) * 60 + int(seconds)
        text = re.sub(
            r"<[^>]+>",
            "",
            " ".join(line for line in cue.splitlines() if "-->" not in line),
        ).strip()
        if start - current_start >= TIMESTAMP_INTERVAL_SECONDS:
            current_start = start
            lines.append(f"[{_format_timestamp(seconds=start)}] {text}")
        else:
            lines[-1] += f" {text}"
    return "\n".join(lines), start


def _format_timestamp(seconds: int) -> str:
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours}:{minutes:02}:{seconds:02}" if hours else f"{minutes}:{seconds:02}"


# --- Running the pipeline ---


def _run_step(
    client: anthropic.Anthropic, episode: Episode, step: Step, model: Model
) -> StepResult:
    user_message = (
        f"Show: {episode.show.description}\n"
        f"Episode: {episode.title}\n"
        f"Episode description: {episode.description}\n\n"
        f"<transcript>\n{episode.transcript}\n</transcript>"
    )
    extra = (
        {
            "output_config": {
                "format": {"type": "json_schema", "schema": ANALYSIS_SCHEMA}
            }
        }
        if step == Step.ANALYZE
        else {}
    )

    # Long transcripts plus long outputs can run past the non-streaming timeout, so stream and collect
    with client.messages.stream(
        model=model.model_id,
        max_tokens=MAX_OUTPUT_TOKENS[step],
        system=ANALYZE_SYSTEM_PROMPT if step == Step.ANALYZE else PRIMER_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
        **extra,
    ) as stream:
        response = stream.get_final_message()

    print(f"  done {episode.show.slug} {step} {model.name} ({response.stop_reason})")
    text = "".join(block.text for block in response.content if block.type == "text")
    return StepResult(
        show_slug=episode.show.slug,
        step=step,
        model=model,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
        output=text,
    )


# --- Output ---


def _write_outputs(episodes: list[Episode], results: list[StepResult]) -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    for episode in episodes:
        sections = [
            f"# {episode.title}\n\n{episode.show.description} · {episode.audio_hours:.2f} h of audio\n"
        ]
        for result in (
            result for result in results if result.show_slug == episode.show.slug
        ):
            body = (
                _analysis_markdown(text=result.output)
                if result.step == Step.ANALYZE
                else result.output
            )
            sections.append(
                f"---\n\n## {result.step} · {result.model.name} (${result.usd:.3f})\n\n{body}\n"
            )
        (OUTPUT_DIR / f"{episode.show.slug}.md").write_text("\n".join(sections))


def _analysis_markdown(text: str) -> str:
    analysis = json.loads(text)
    summary = analysis["summary"]
    ideas = "\n".join(
        f"- **[{entry['timestamp'].strip("[]")}]** {entry['idea']}"
        for entry in summary["key_ideas"]
    )
    numbers = "\n".join(
        f"- **[{entry['timestamp'].strip("[]")}]** {entry['fact']}" for entry in summary["numbers"]
    )
    cards = "\n\n".join(
        f"**Q ({card['kind']}):** {card['question']}\n\n**A:** {card['answer']}"
        for card in analysis["cards"]
    )
    return (
        f"**{analysis['domain']} → {analysis['topic']}** · tags: {', '.join(analysis['tags'])}\n\n"
        f"**Concepts:** {', '.join(analysis['concepts'])}\n\n"
        f"### Gist\n\n{summary['gist']}\n\n### Key ideas\n\n{ideas}\n\n### Numbers\n\n{numbers}\n\n### Cards\n\n{cards}"
    )


def _print_costs(episodes: list[Episode], results: list[StepResult]) -> None:
    total_hours = sum(episode.audio_hours for episode in episodes)
    print(
        f"\n=== Cost per step ({total_hours:.2f} h of audio over {len(episodes)} episodes) ==="
    )
    print(
        f"  {'step':8} {'model':11} {'input tok':>10} {'output tok':>10} {'total $':>8} {'$/audio h':>10} {'$/mo @43h':>10}"
    )
    per_hour: dict[tuple[Step, str], Decimal] = {}
    for step, models in STEP_MODELS.items():
        for model in models:
            matching = [
                result
                for result in results
                if result.step == step and result.model == model
            ]
            usd = sum(result.usd for result in matching)
            per_hour[(step, model.name)] = usd / total_hours
            print(
                f"  {step:8} {model.name:11} {sum(result.input_tokens for result in matching):>10,}"
                f" {sum(result.output_tokens for result in matching):>10,} {usd:>8.3f}"
                f" {usd / total_hours:>10.3f} {usd / total_hours * MONTHLY_AUDIO_HOURS:>10.2f}"
            )

    # Whole pipeline per audio hour, including the transcription and name-correction costs measured earlier
    print(
        "\n=== Pipeline per month @ 43 h (transcription + corrections + analyze + primer), list / Batch API ==="
    )
    fixed = TRANSCRIPTION_USD_PER_AUDIO_HOUR + CORRECTION_USD_PER_AUDIO_HOUR
    for analyze_model in STEP_MODELS[Step.ANALYZE]:
        for primer_model in STEP_MODELS[Step.PRIMER]:
            llm = (
                per_hour[(Step.ANALYZE, analyze_model.name)]
                + per_hour[(Step.PRIMER, primer_model.name)]
            )
            print(
                f"  analyze {analyze_model.name:11} + primer {primer_model.name:11}"
                f" ${(fixed + llm) * MONTHLY_AUDIO_HOURS:>6.2f} / ${(fixed + llm / 2) * MONTHLY_AUDIO_HOURS:>6.2f}"
            )


if __name__ == "__main__":
    main()
