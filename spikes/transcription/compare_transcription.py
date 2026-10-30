# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx", "jiwer", "python-dotenv"]
# ///
"""Spike: compare speech-to-text providers on jargon-heavy podcast clips.

Episodes whose feed publishes a transcript are scored against it (word error rate, skipped passages).
Runs every provider whose API key is present in the repo-root .env; a provider that errors is reported and skipped.
Run: uv run spikes/transcription/compare_transcription.py
"""

import concurrent.futures
import enum
import html
import itertools
import math
import os
import pathlib
import re
import statistics
import subprocess
import time
import xml.etree.ElementTree
from dataclasses import dataclass, field

import dotenv
import httpx
import jiwer

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
CACHE_DIR = pathlib.Path(__file__).resolve().parent / ".cache"
PODCAST_NAMESPACE = "https://podcastindex.org/namespace/1.0"

# Only the opening minutes of each episode are transcribed, to keep cost and rate limits small
CLIP_SECONDS = 900
# Dynamic ad insertion can shift the audio relative to the published transcript, so take extra reference
REFERENCE_SLACK_SECONDS = 300
CHUNK_SECONDS = 600
CHUNK_BITRATE = "48k"
REQUEST_TIMEOUT_SECONDS = 300
# Groq's free tier caps audio seconds per hour, so a 5-hour run has to sit out long limits
MAX_RATE_LIMIT_WAIT_SECONDS = 1800
RICH_HINT_MAX_CHARS = 700
# Unmatched alignment runs at least this long are ads or skipped passages rather than mishearings
BLOCK_WORDS = 15
# A matching run this long can't be coincidence, so it marks where the clip and reference truly overlap
ANCHOR_WORDS = 8
PARALLEL_EPISODES = 4


@dataclass(frozen=True)
class Show:
    slug: str
    feed_url: str
    # Vocabulary hint, the way production would build one from show metadata
    prompt_hint: str
    # How many of the most recent episodes with a published VTT transcript to test
    episode_count: int
    use_published_transcript: bool = True
    # Correct spellings of jargon to count; only scored in episodes whose reference mentions them
    jargon_terms: tuple[str, ...] = ()


SHOWS = [
    Show(
        slug="bankless",
        feed_url="https://feeds.flightcast.com/p83fuj0y0u58o82l41xei7zo.xml",
        prompt_hint="Bankless podcast with Ryan Sean Adams and David Hoffman. Crypto, Ethereum, DeFi, stablecoins.",
        episode_count=5,
        jargon_terms=(
            "Ripio",
            "Morpho",
            "Uniswap",
            "Aave",
            "Hyperliquid",
            "stablecoin",
        ),
    ),
    Show(
        slug="money-stuff",
        feed_url="https://www.omnycontent.com/d/playlist/e73c998e-6e60-432f-8610-ae210140c5b1/ee4336cb-155f-4488-90e0-b1400134e40e/77e6a3a7-290d-4a82-8164-b14001353ef2/podcast.rss",
        prompt_hint="Money Stuff podcast with Matt Levine and Katie Greifeld. Finance, markets, Wall Street.",
        episode_count=5,
        jargon_terms=("Tice", "mNAV", "Levine", "Greifeld"),
    ),
    Show(
        slug="darknet-diaries",
        feed_url="https://podcast.darknetdiaries.com",
        prompt_hint="Darknet Diaries with Jack Rhysider. Hacking, cybersecurity, malware.",
        episode_count=5,
        jargon_terms=("Dyre", "Conti", "Europol", "Rhysider"),
    ),
    Show(
        slug="bussin",
        feed_url="https://www.omnycontent.com/d/playlist/e73c998e-6e60-432f-8610-ae210140c5b1/f7d20af0-ea4d-48fc-bc4c-b2920123b22a/95b710b5-a45b-4abe-a98a-b2920123b23f/podcast.rss",
        prompt_hint="Bussin' With The Boys with Will Compton and Taylor Lewan. NFL, college football.",
        episode_count=4,
        jargon_terms=("Lewan", "Compton", "Mahomes"),
    ),
    # Acquired only publishes a transcript for one recent episode
    Show(
        slug="acquired",
        feed_url="https://feeds.transistor.fm/acquired",
        prompt_hint="Acquired podcast with Ben Gilbert and David Rosenthal. Company histories, technology, business.",
        episode_count=1,
        jargon_terms=("Arthur Blank", "Bernie Marcus", "Handy Dan"),
    ),
]


@dataclass(frozen=True)
class Provider:
    name: str
    env_key: str
    url: str
    model: str
    usd_per_audio_hour: float  # Unverified list prices as of 2026-10
    # Whisper derails on long prompts (skips and garbage in the first spike), so it only gets the basic hint
    handles_long_prompts: bool


PROVIDERS = [
    Provider(
        name="groq-whisper-large-v3-turbo",
        env_key="GROQ_API_KEY",
        url="https://api.groq.com/openai/v1/audio/transcriptions",
        model="whisper-large-v3-turbo",
        usd_per_audio_hour=0.04,
        handles_long_prompts=False,
    ),
    Provider(
        name="openai-gpt-4o-mini-transcribe",
        env_key="OPENAI_API_KEY",
        url="https://api.openai.com/v1/audio/transcriptions",
        model="gpt-4o-mini-transcribe",
        usd_per_audio_hour=0.18,
        handles_long_prompts=True,
    ),
    Provider(
        name="openai-gpt-4o-transcribe",
        env_key="OPENAI_API_KEY",
        url="https://api.openai.com/v1/audio/transcriptions",
        model="gpt-4o-transcribe",
        usd_per_audio_hour=0.36,
        handles_long_prompts=True,
    ),
]


class HintStyle(enum.StrEnum):
    BASIC = "basic"  # Show name and hosts only
    RICH = "rich"  # Plus the episode title and description from the feed


@dataclass
class PreparedEpisode:
    show: Show
    slug: str
    title: str
    rich_hint: str
    chunks: list[pathlib.Path]
    chunk_seconds: list[float]
    reference_text: str | None


@dataclass
class Score:
    word_error_rate: float
    skipped_words: int


@dataclass
class EpisodeTranscript:
    chunk_texts: list[str]
    score: Score | None

    @property
    def text(self) -> str:
        return " ".join(self.chunk_texts)


@dataclass
class ProviderRun:
    provider: Provider
    hint_style: HintStyle
    seconds_elapsed: float = 0.0
    error: str | None = None
    episodes: dict[str, EpisodeTranscript] = field(default_factory=dict)

    @property
    def label(self) -> str:
        return f"{self.provider.name.replace('groq-whisper-large-v3-', '').replace('openai-gpt-4o-', '4o-')}/{self.hint_style}"


def main() -> None:
    dotenv.load_dotenv(REPO_ROOT / ".env")
    CACHE_DIR.mkdir(exist_ok=True)
    available = [provider for provider in PROVIDERS if os.environ.get(provider.env_key)]
    print(f"Providers with keys: {[provider.name for provider in available]}\n")

    prepared = _prepare_all()
    runs = [
        _run_provider(provider=provider, hint_style=hint_style, prepared=prepared)
        for provider in available
        for hint_style in HintStyle
        if hint_style == HintStyle.BASIC or provider.handles_long_prompts
    ]

    _print_episode_table(prepared=prepared, runs=runs)
    _print_skips(prepared=prepared, runs=runs)
    _print_summary(prepared=prepared, runs=runs)
    _print_pairwise(prepared=prepared, runs=runs)
    _print_jargon(prepared=prepared, runs=runs)


# --- Inputs: clip each episode's audio and pull the matching slice of its published transcript ---


def _prepare_all() -> list[PreparedEpisode]:
    feed_items = [
        (show, index, item)
        for show in SHOWS
        for index, item in enumerate(_pick_feed_items(show=show))
    ]
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=PARALLEL_EPISODES
    ) as executor:
        return list(
            executor.map(
                lambda entry: _prepare_episode(
                    show=entry[0], index=entry[1], item=entry[2]
                ),
                feed_items,
            )
        )


def _pick_feed_items(show: Show) -> list[xml.etree.ElementTree.Element]:
    feed = httpx.get(
        show.feed_url, follow_redirects=True, timeout=REQUEST_TIMEOUT_SECONDS
    ).content
    items = xml.etree.ElementTree.fromstring(feed).find("channel").findall("item")
    if not show.use_published_transcript:
        return items[: show.episode_count]

    # The most recent episodes that publish a VTT transcript
    return [item for item in items if _vtt_url(item=item)][: show.episode_count]


def _prepare_episode(
    show: Show, index: int, item: xml.etree.ElementTree.Element
) -> PreparedEpisode:
    title = item.findtext("title", default="").strip()

    # Key the cache by title, since a new release shifts every episode's position in the feed
    slug = f"{show.slug}-{index + 1}"
    episode_dir = (
        CACHE_DIR
        / show.slug
        / re.sub(r"[^a-z0-9]+", "-", title.lower())[:50].strip("-")
    )
    episode_dir.mkdir(parents=True, exist_ok=True)

    chunks = _clip_and_chunk(
        audio_url=item.find("enclosure").get("url"), episode_dir=episode_dir
    )
    reference_text = (
        _reference_text(item=item) if show.use_published_transcript else None
    )
    if reference_text:
        (episode_dir / "reference.txt").write_text(reference_text)

    print(
        f"[{slug}] {title} · {len(chunks)} chunks · reference words: {len((reference_text or '').split())}"
    )
    return PreparedEpisode(
        show=show,
        slug=slug,
        title=title,
        rich_hint=_rich_hint(show=show, title=title, item=item),
        chunks=chunks,
        chunk_seconds=[_duration_seconds(chunk=chunk) for chunk in chunks],
        reference_text=reference_text,
    )


def _rich_hint(show: Show, title: str, item: xml.etree.ElementTree.Element) -> str:
    # Whisper only reads the last ~224 tokens of a prompt, so keep the title and the description's opening
    description = item.findtext("description", default="")
    plain_description = html.unescape(re.sub(r"<[^>]+>", " ", description))
    plain_description = re.sub(r"\s+", " ", plain_description).strip()
    return f"{show.prompt_hint} Episode: {title}. {plain_description}"[
        :RICH_HINT_MAX_CHARS
    ]


def _vtt_url(item: xml.etree.ElementTree.Element) -> str | None:
    tags = item.findall(f"{{{PODCAST_NAMESPACE}}}transcript")
    return next((tag.get("url") for tag in tags if "vtt" in tag.get("type", "")), None)


def _clip_and_chunk(audio_url: str, episode_dir: pathlib.Path) -> list[pathlib.Path]:
    chunk_dir = episode_dir / "chunks"
    if chunk_dir.exists() and any(chunk_dir.iterdir()):
        return sorted(chunk_dir.glob("*.mp3"))

    # ffmpeg streams just the opening minutes, re-encoded to small mono chunks under upload limits
    chunk_dir.mkdir(exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-loglevel",
            "error",
            "-user_agent",
            "second-brain-spike/0.1",
            "-i",
            audio_url,
            "-t",
            str(CLIP_SECONDS),
            "-ac",
            "1",
            "-ar",
            "16000",
            "-b:a",
            CHUNK_BITRATE,
            "-f",
            "segment",
            "-segment_time",
            str(CHUNK_SECONDS),
            str(chunk_dir / "chunk_%03d.mp3"),
        ],
        check=True,
    )
    return sorted(chunk_dir.glob("*.mp3"))


def _reference_text(item: xml.etree.ElementTree.Element) -> str:
    vtt = httpx.get(
        _vtt_url(item=item), follow_redirects=True, timeout=REQUEST_TIMEOUT_SECONDS
    ).text
    window_end = CLIP_SECONDS + REFERENCE_SLACK_SECONDS

    # Keep the cue text whose start time falls inside the clip window (plus slack for inserted ads)
    cues = re.split(r"\n\s*\n", vtt)
    kept = []
    for cue in cues:
        timing = re.search(
            r"(\d+):(\d\d):(\d\d)[.,]\d+\s*-->|(\d+):(\d\d)[.,]\d+\s*-->", cue
        )
        if not timing:
            continue

        hours, minutes, seconds, short_minutes, short_seconds = timing.groups()
        start = (
            int(hours) * 3600 + int(minutes) * 60 + int(seconds)
            if hours
            else int(short_minutes) * 60 + int(short_seconds)
        )
        if start > window_end:
            break

        text_lines = [
            line
            for line in cue.splitlines()
            if "-->" not in line and not line.strip().isdigit()
        ]
        kept.append(re.sub(r"<[^>]+>", "", " ".join(text_lines)).strip())
    return " ".join(kept)


def _duration_seconds(chunk: pathlib.Path) -> float:
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
            str(chunk),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(probe.stdout)


# --- Providers: transcribe every clip, then score against references ---


def _run_provider(
    provider: Provider, hint_style: HintStyle, prepared: list[PreparedEpisode]
) -> ProviderRun:
    run = ProviderRun(provider=provider, hint_style=hint_style)
    print(f"\nTranscribing with {run.label}…")
    started = time.monotonic()
    try:
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=PARALLEL_EPISODES
        ) as executor:
            transcripts = executor.map(
                lambda item: _transcribe_episode(
                    provider=provider, hint_style=hint_style, item=item
                ),
                prepared,
            )
            run.episodes = {
                item.slug: transcript for item, transcript in zip(prepared, transcripts)
            }
    except (
        httpx.HTTPStatusError
    ) as error:  # Spike: one provider failing shouldn't stop the others
        run.error = f"{error.response.status_code}: {error.response.text[:160]}"
        print(f"  FAILED {run.error}")

    run.seconds_elapsed = time.monotonic() - started
    return run


def _transcribe_episode(
    provider: Provider, hint_style: HintStyle, item: PreparedEpisode
) -> EpisodeTranscript:
    cache_file = (
        item.chunks[0].parent.parent / f"{provider.name}.{hint_style}.chunks.txt"
    )
    if cache_file.exists():
        chunk_texts = cache_file.read_text().split("\n\n")
    else:
        prompt = (
            item.rich_hint if hint_style == HintStyle.RICH else item.show.prompt_hint
        )
        chunk_texts = [
            _transcribe_chunk(provider=provider, chunk=chunk, prompt=prompt)
            for chunk in item.chunks
        ]
        cache_file.write_text("\n\n".join(chunk_texts))

    transcript = EpisodeTranscript(chunk_texts=chunk_texts, score=None)
    if item.reference_text:
        transcript.score = _score(
            reference_text=item.reference_text, hypothesis_text=transcript.text
        )
    print(f"  done {item.slug}")
    return transcript


def _transcribe_chunk(provider: Provider, chunk: pathlib.Path, prompt: str) -> str:
    while True:
        response = httpx.post(
            provider.url,
            headers={"Authorization": f"Bearer {os.environ[provider.env_key]}"},
            data={"model": provider.model, "prompt": prompt, "response_format": "json"},
            files={"file": (chunk.name, chunk.read_bytes(), "audio/mpeg")},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

        # Free tiers rate-limit audio seconds; wait out limits instead of failing the run
        retry_after = float(response.headers.get("retry-after", "0") or 0)
        if (
            response.status_code == 429
            and 0 < retry_after <= MAX_RATE_LIMIT_WAIT_SECONDS
        ):
            print(f"  rate limited, waiting {retry_after:.0f}s")
            time.sleep(retry_after)
            continue

        # Text without spaces after newlines keeps the chunk cache's blank-line separator unambiguous
        response.raise_for_status()
        return re.sub(r"\s+", " ", response.json()["text"]).strip()


def _score(reference_text: str, hypothesis_text: str) -> Score:
    # The reference window is deliberately longer than the clip, and ads may differ at the edges, so
    # score only between the first and last solid matching runs. Trimming at any match isn't enough:
    # a stray common word aligned inside the reference's extra tail would count the whole tail as skipped
    output = jiwer.process_words(
        _normalize(text=reference_text), _normalize(text=hypothesis_text)
    )
    alignment = output.alignments[0]
    anchors = [
        index
        for index, chunk in enumerate(alignment)
        if chunk.type == "equal" and chunk.ref_end_idx - chunk.ref_start_idx >= ANCHOR_WORDS
    ]
    alignment = alignment[anchors[0] : anchors[-1] + 1] if anchors else []

    # Long unmatched blocks are ads (inserted) or passages the model skipped (deleted); score them
    # separately so word-level accuracy isn't swamped by ad reads that the reference omits
    def block_size(chunk: jiwer.AlignmentChunk) -> int:
        return max(
            chunk.ref_end_idx - chunk.ref_start_idx,
            chunk.hyp_end_idx - chunk.hyp_start_idx,
        )

    word_errors = sum(
        block_size(chunk)
        for chunk in alignment
        if chunk.type != "equal" and block_size(chunk) < BLOCK_WORDS
    )
    skipped_words = sum(
        block_size(chunk)
        for chunk in alignment
        if chunk.type == "delete" and block_size(chunk) >= BLOCK_WORDS
    )
    reference_words = sum(
        chunk.ref_end_idx - chunk.ref_start_idx for chunk in alignment
    )
    return Score(
        word_error_rate=word_errors / reference_words if reference_words else 1.0,
        skipped_words=skipped_words,
    )


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9' ]", " ", text.lower())).strip()


# --- Skip detection: what a provider skipped beyond what every provider "skipped" ---


def _excess_skips(
    prepared: list[PreparedEpisode], runs: list[ProviderRun]
) -> dict[tuple[str, str], int]:
    # A passage every provider misses is reference text that isn't in our audio (ads, intros), so the
    # smallest skip count on an episode is its baseline and only the excess is the model's fault
    finished = [run for run in runs if not run.error]
    excess = {}
    for item in prepared:
        if not item.reference_text:
            continue
        baseline = min(run.episodes[item.slug].score.skipped_words for run in finished)
        for run in finished:
            excess[(run.label, item.slug)] = (
                run.episodes[item.slug].score.skipped_words - baseline
            )
    return excess


def _words_per_minute(
    item: PreparedEpisode, transcript: EpisodeTranscript
) -> list[float]:
    return [
        len(text.split()) / (seconds / 60)
        for text, seconds in zip(transcript.chunk_texts, item.chunk_seconds)
        if seconds >= 60
    ]


# --- Output ---


def _print_episode_table(
    prepared: list[PreparedEpisode], runs: list[ProviderRun]
) -> None:
    finished = [run for run in runs if not run.error]
    excess = _excess_skips(prepared=prepared, runs=runs)
    print(
        "\n=== Per episode: word-level error (excl. ads) · words skipped beyond the episode's baseline ==="
    )
    print(f"{'episode':22}" + "".join(f"{run.label:>22}" for run in finished))
    for item in prepared:
        if not item.reference_text:
            continue
        cells = [
            f"{run.episodes[item.slug].score.word_error_rate:>5.1%} · {excess[(run.label, item.slug)]:>4}"
            for run in finished
        ]
        print(f"{item.slug:22}" + "".join(f"{cell:>22}" for cell in cells))
    for run in runs:
        if run.error:
            print(f"{run.label}: ERROR {run.error}")


def _print_skips(prepared: list[PreparedEpisode], runs: list[ProviderRun]) -> None:
    # Each real skip with the transcript's slowest chunk, to judge whether a words-per-minute check would catch it
    excess = _excess_skips(prepared=prepared, runs=runs)
    by_slug = {item.slug: item for item in prepared}
    print(
        f"\n=== Real skips (≥{BLOCK_WORDS} words beyond baseline) and the slowest chunk's words/min ==="
    )
    for (label, slug), words in sorted(excess.items()):
        if words < BLOCK_WORDS:
            continue
        run = next(run for run in runs if run.label == label)
        rates = _words_per_minute(item=by_slug[slug], transcript=run.episodes[slug])
        print(
            f"  {label:22} {slug:22} skipped {words:>4} words · slowest chunk {min(rates):.0f} wpm"
        )


def _print_summary(prepared: list[PreparedEpisode], runs: list[ProviderRun]) -> None:
    excess = _excess_skips(prepared=prepared, runs=runs)
    scored = [item for item in prepared if item.reference_text]
    audio_hours = sum(sum(item.chunk_seconds) for item in prepared) / 3600
    print(
        f"\n=== Summary over {len(scored)} scored episodes ({audio_hours:.1f} h of audio) ==="
    )
    print(
        f"{'provider/hint':22}{'median err':>11}{'mean err':>10}{'eps w/ skip':>13}{'words skipped':>15}"
        f"{'min wpm':>9}{'time':>8}{'cost':>8}"
    )
    for run in runs:
        if run.error:
            continue
        error_rates = [run.episodes[item.slug].score.word_error_rate for item in scored]
        skips = [excess[(run.label, item.slug)] for item in scored]
        rates = [
            rate
            for item in prepared
            for rate in _words_per_minute(item=item, transcript=run.episodes[item.slug])
        ]
        print(
            f"{run.label:22}{statistics.median(error_rates):>11.1%}{statistics.mean(error_rates):>10.1%}"
            f"{sum(1 for words in skips if words >= BLOCK_WORDS):>13}{sum(words for words in skips if words >= BLOCK_WORDS):>15}"
            f"{min(rates):>9.0f}{run.seconds_elapsed:>7.0f}s{audio_hours * run.provider.usd_per_audio_hour:>7.2f}$"
        )

    # Speaking-rate floor across every chunk, for sizing an "unusually short chunk" check
    all_rates = sorted(
        rate
        for run in runs
        if not run.error
        for item in prepared
        for rate in _words_per_minute(item=item, transcript=run.episodes[item.slug])
    )
    print(
        f"Chunk words/min across all runs: min {all_rates[0]:.0f} · p10 {all_rates[len(all_rates) // 10]:.0f} · "
        f"median {statistics.median(all_rates):.0f}"
    )
    print(
        "Note: published transcripts may themselves be machine-generated, so error here measures disagreement, not truth."
    )


def _print_pairwise(prepared: list[PreparedEpisode], runs: list[ProviderRun]) -> None:
    # Paired sign test: on how many episodes did each model beat the other? A lopsided split that a coin
    # flip would rarely produce (p < 0.05) is a real quality difference; anything else is noise
    finished = [run for run in runs if not run.error]
    scored = [item for item in prepared if item.reference_text]
    excess = _excess_skips(prepared=prepared, runs=runs)
    print("\n=== Pairwise sign tests (episodes where A beat B / B beat A, two-sided p) ===")
    for first, second in itertools.combinations(finished, 2):
        error_wins, error_losses = _wins_and_losses(
            first=[first.episodes[item.slug].score.word_error_rate for item in scored],
            second=[second.episodes[item.slug].score.word_error_rate for item in scored],
        )
        skip_wins, skip_losses = _wins_and_losses(
            first=[excess[(first.label, item.slug)] for item in scored],
            second=[excess[(second.label, item.slug)] for item in scored],
        )
        print(
            f"  {first.label:22} vs {second.label:22} "
            f"error {error_wins:>2}/{error_losses:<2} p={_sign_test_p(wins=error_wins, losses=error_losses):.3f}   "
            f"skips {skip_wins:>2}/{skip_losses:<2} p={_sign_test_p(wins=skip_wins, losses=skip_losses):.3f}"
        )


def _wins_and_losses(first: list[float], second: list[float]) -> tuple[int, int]:
    # Lower is better for both error rate and skipped words; ties carry no information and are dropped
    return (
        sum(1 for first_value, second_value in zip(first, second) if first_value < second_value),
        sum(1 for first_value, second_value in zip(first, second) if first_value > second_value),
    )


def _sign_test_p(wins: int, losses: int) -> float:
    trials = wins + losses
    if trials == 0:
        return 1.0
    tail = sum(math.comb(trials, count) for count in range(0, min(wins, losses) + 1)) / 2**trials
    return min(1.0, 2 * tail)


def _print_jargon(prepared: list[PreparedEpisode], runs: list[ProviderRun]) -> None:
    # Correct spellings summed over the episodes whose reference actually mentions the term
    finished = [run for run in runs if not run.error]
    print(
        "\n=== Known jargon spelled correctly (summed over episodes where the reference mentions it) ==="
    )
    for show in SHOWS:
        items = [item for item in prepared if item.show == show and item.reference_text]
        for term in show.jargon_terms:
            relevant = [
                item for item in items if _count(term=term, text=item.reference_text)
            ]
            if not relevant:
                continue
            reference_count = sum(
                _count(term=term, text=item.reference_text) for item in relevant
            )
            counts = "  ".join(
                f"{run.label}={sum(_count(term=term, text=run.episodes[item.slug].text) for item in relevant)}"
                for run in finished
            )
            print(f"  {show.slug:16} {term:14} ref={reference_count:<3} {counts}")


def _count(term: str, text: str) -> int:
    return len(re.findall(re.escape(term), text, flags=re.IGNORECASE))


if __name__ == "__main__":
    main()
