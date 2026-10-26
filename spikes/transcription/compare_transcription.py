# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx", "jiwer", "python-dotenv"]
# ///
"""Spike: compare speech-to-text providers on jargon-heavy podcast clips.

Episodes whose feed publishes a transcript are scored against it (word error rate, name recall).
Episodes without one are compared provider-vs-provider, listing the names they disagree on.
Runs every provider whose API key is present in the repo-root .env; a provider that errors is reported and skipped.
Run: uv run spikes/transcription/compare_transcription.py
"""

import enum
import html
import os
import pathlib
import re
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
MAX_RATE_LIMIT_WAIT_SECONDS = 180
RICH_HINT_MAX_CHARS = 700
# Unmatched alignment runs at least this long are ads or skipped passages rather than mishearings
BLOCK_WORDS = 15


@dataclass(frozen=True)
class Episode:
    slug: str
    show: str
    feed_url: str
    jargon: str
    # Vocabulary hint, the way production would build one from show and episode metadata
    prompt_hint: str
    use_published_transcript: bool
    # Correct spellings of jargon known to appear in the clip, counted in every transcript
    jargon_terms: tuple[str, ...]


EPISODES = [
    Episode(
        slug="bankless",
        show="Bankless",
        feed_url="https://feeds.flightcast.com/p83fuj0y0u58o82l41xei7zo.xml",
        jargon="crypto news, tokens, protocols",
        prompt_hint="Bankless podcast with Ryan Sean Adams and David Hoffman. Crypto, Ethereum, DeFi, stablecoins.",
        use_published_transcript=True,
        jargon_terms=("Ripio", "Morpho", "Uniswap"),
    ),
    Episode(
        slug="money-stuff",
        show="Money Stuff: The Podcast",
        feed_url="https://www.omnycontent.com/d/playlist/e73c998e-6e60-432f-8610-ae210140c5b1/ee4336cb-155f-4488-90e0-b1400134e40e/77e6a3a7-290d-4a82-8164-b14001353ef2/podcast.rss",
        jargon="markets, finance, legal",
        prompt_hint="Money Stuff podcast with Matt Levine and Katie Greifeld. Finance, markets, Wall Street.",
        use_published_transcript=True,
        jargon_terms=("Tyce", "mNAV"),
    ),
    Episode(
        slug="darknet-diaries",
        show="Darknet Diaries",
        feed_url="https://podcast.darknetdiaries.com",
        jargon="hacking, security",
        prompt_hint="Darknet Diaries with Jack Rhysider. Hacking, cybersecurity, malware.",
        use_published_transcript=True,
        jargon_terms=("Dyre", "Conti", "Europol"),
    ),
    Episode(
        slug="acquired",
        show="Acquired",
        feed_url="https://feeds.transistor.fm/acquired",
        jargon="company history, business",
        prompt_hint="Acquired podcast with Ben Gilbert and David Rosenthal. Company histories, technology, business.",
        use_published_transcript=True,
        jargon_terms=("Arthur Blank", "Bernie Marcus", "Handy Dan"),
    ),
    Episode(
        slug="0xresearch",
        show="0xResearch",
        feed_url="https://feeds.megaphone.fm/0xresearch",
        jargon="niche crypto research (MEV, L2s, tokens)",
        prompt_hint="0xResearch podcast by Blockworks. Crypto research, MEV, rollups, Solana, Ethereum, Hyperliquid.",
        use_published_transcript=False,
        jargon_terms=("Citrini", "Aerodrome", "Uniswap", "Hyperliquid"),
    ),
]


@dataclass(frozen=True)
class Provider:
    name: str
    env_key: str
    url: str
    model: str
    usd_per_audio_hour: float  # Unverified list prices as of 2026-10
    returns_timestamps: bool


PROVIDERS = [
    Provider(
        name="groq-whisper-large-v3-turbo",
        env_key="GROQ_API_KEY",
        url="https://api.groq.com/openai/v1/audio/transcriptions",
        model="whisper-large-v3-turbo",
        usd_per_audio_hour=0.04,
        returns_timestamps=True,
    ),
    Provider(
        name="openai-gpt-4o-mini-transcribe",
        env_key="OPENAI_API_KEY",
        url="https://api.openai.com/v1/audio/transcriptions",
        model="gpt-4o-mini-transcribe",
        usd_per_audio_hour=0.18,
        returns_timestamps=False,
    ),
    Provider(
        name="openai-gpt-4o-transcribe",
        env_key="OPENAI_API_KEY",
        url="https://api.openai.com/v1/audio/transcriptions",
        model="gpt-4o-transcribe",
        usd_per_audio_hour=0.36,
        returns_timestamps=False,
    ),
]


class HintStyle(enum.StrEnum):
    BASIC = "basic"  # Show name and hosts only
    RICH = "rich"  # Plus the episode title and description from the feed


@dataclass
class PreparedEpisode:
    episode: Episode
    title: str
    rich_hint: str
    chunks: list[pathlib.Path]
    reference_text: str | None


@dataclass
class Score:
    word_error_rate: float | None
    skipped_words: int | None
    name_recall: float | None


@dataclass
class ProviderRun:
    provider: Provider
    hint_style: HintStyle
    seconds_elapsed: float = 0.0
    audio_seconds: float = 0.0
    error: str | None = None
    transcripts: dict[str, str] = field(default_factory=dict)
    scores: dict[str, Score] = field(default_factory=dict)

    @property
    def label(self) -> str:
        return f"{self.provider.name}/{self.hint_style}"


def main() -> None:
    dotenv.load_dotenv(REPO_ROOT / ".env")
    CACHE_DIR.mkdir(exist_ok=True)
    available = [provider for provider in PROVIDERS if os.environ.get(provider.env_key)]
    print(f"Providers with keys: {[provider.name for provider in available]}\n")

    prepared = [_prepare_episode(episode=episode) for episode in EPISODES]
    runs = [
        _run_provider(provider=provider, hint_style=hint_style, prepared=prepared)
        for provider in available
        for hint_style in HintStyle
    ]

    _print_scores(prepared=prepared, runs=runs)
    _print_jargon(prepared=prepared, runs=runs)
    _print_disagreements(prepared=prepared, runs=runs)


# --- Inputs: clip each episode's audio and pull the matching slice of its published transcript ---


def _prepare_episode(episode: Episode) -> PreparedEpisode:
    episode_dir = CACHE_DIR / episode.slug
    episode_dir.mkdir(exist_ok=True)

    item = _pick_feed_item(episode=episode)
    title = item.findtext("title", default="").strip()
    chunks = _clip_and_chunk(
        audio_url=item.find("enclosure").get("url"), episode_dir=episode_dir
    )
    reference_text = (
        _reference_text(item=item) if episode.use_published_transcript else None
    )
    if reference_text:
        (episode_dir / "reference.txt").write_text(reference_text)

    print(
        f"[{episode.slug}] {title} · {len(chunks)} chunks · reference words: {len((reference_text or '').split())}"
    )
    return PreparedEpisode(
        episode=episode,
        title=title,
        rich_hint=_rich_hint(episode=episode, title=title, item=item),
        chunks=chunks,
        reference_text=reference_text,
    )


def _rich_hint(episode: Episode, title: str, item: xml.etree.ElementTree.Element) -> str:
    # Whisper only reads the last ~224 tokens of a prompt, so keep the title and the description's opening
    description = item.findtext("description", default="")
    plain_description = html.unescape(re.sub(r"<[^>]+>", " ", description))
    plain_description = re.sub(r"\s+", " ", plain_description).strip()
    return f"{episode.prompt_hint} Episode: {title}. {plain_description}"[:RICH_HINT_MAX_CHARS]


def _pick_feed_item(episode: Episode) -> xml.etree.ElementTree.Element:
    feed = httpx.get(
        episode.feed_url, follow_redirects=True, timeout=REQUEST_TIMEOUT_SECONDS
    ).content
    items = xml.etree.ElementTree.fromstring(feed).find("channel").findall("item")
    if not episode.use_published_transcript:
        return items[0]

    # The most recent episode that publishes a VTT transcript
    return next(item for item in items if _vtt_url(item=item))


def _vtt_url(item: xml.etree.ElementTree.Element) -> str | None:
    tags = item.findall(f"{{{PODCAST_NAMESPACE}}}transcript")
    return next((tag.get("url") for tag in tags if "vtt" in tag.get("type", "")), None)


def _clip_and_chunk(audio_url: str, episode_dir: pathlib.Path) -> list[pathlib.Path]:
    chunk_dir = episode_dir / "chunks"
    if chunk_dir.exists() and any(chunk_dir.iterdir()):
        return sorted(chunk_dir.glob("*.mp3"))

    # ffmpeg streams just the opening minutes, re-encoded to small mono chunks under upload limits
    chunk_dir.mkdir()
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


# --- Providers: transcribe every clip, then score against references ---


def _run_provider(
    provider: Provider, hint_style: HintStyle, prepared: list[PreparedEpisode]
) -> ProviderRun:
    run = ProviderRun(provider=provider, hint_style=hint_style)
    print(f"\nTranscribing with {run.label}…")
    started = time.monotonic()
    try:
        for item in prepared:
            text = " ".join(
                _transcribe_chunk(
                    provider=provider,
                    chunk=chunk,
                    prompt=item.rich_hint if hint_style == HintStyle.RICH else item.episode.prompt_hint,
                )
                for chunk in item.chunks
            )
            run.transcripts[item.episode.slug] = text
            run.audio_seconds += sum(
                _duration_seconds(chunk=chunk) for chunk in item.chunks
            )
            (CACHE_DIR / item.episode.slug / f"{provider.name}.{hint_style}.txt").write_text(text)
            run.scores[item.episode.slug] = _score(
                reference_text=item.reference_text, hypothesis_text=text
            )
            print(f"  done {item.episode.slug}")
    except (
        httpx.HTTPStatusError
    ) as error:  # Spike: one provider failing shouldn't stop the others
        run.error = f"{error.response.status_code}: {error.response.text[:160]}"
        print(f"  FAILED {run.error}")

    run.seconds_elapsed = time.monotonic() - started
    return run


def _transcribe_chunk(provider: Provider, chunk: pathlib.Path, prompt: str) -> str:
    while True:
        response = httpx.post(
            provider.url,
            headers={"Authorization": f"Bearer {os.environ[provider.env_key]}"},
            data={"model": provider.model, "prompt": prompt, "response_format": "json"},
            files={"file": (chunk.name, chunk.read_bytes(), "audio/mpeg")},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

        # Free tiers rate-limit audio seconds; wait out short limits instead of failing the run
        retry_after = float(response.headers.get("retry-after", "0") or 0)
        if (
            response.status_code == 429
            and 0 < retry_after <= MAX_RATE_LIMIT_WAIT_SECONDS
        ):
            print(f"  rate limited, waiting {retry_after:.0f}s")
            time.sleep(retry_after)
            continue

        response.raise_for_status()
        return response.json()["text"]


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


def _score(reference_text: str | None, hypothesis_text: str) -> Score:
    if not reference_text:
        return Score(word_error_rate=None, skipped_words=None, name_recall=None)

    word_error_rate, skipped_words = _word_error_rate_and_skips(
        reference_text=reference_text, hypothesis_text=hypothesis_text
    )
    return Score(
        word_error_rate=word_error_rate,
        skipped_words=skipped_words,
        name_recall=_name_recall(
            reference_text=reference_text, hypothesis_text=hypothesis_text
        ),
    )


def _word_error_rate_and_skips(reference_text: str, hypothesis_text: str) -> tuple[float, int]:
    # The reference window is deliberately longer than the clip, and ads may differ at the edges,
    # so ignore unmatched runs at the start and end of the alignment and score only the overlap
    output = jiwer.process_words(
        _normalize(text=reference_text), _normalize(text=hypothesis_text)
    )
    alignment = output.alignments[0]
    while alignment and alignment[0].type in ("delete", "insert"):
        alignment = alignment[1:]
    while alignment and alignment[-1].type in ("delete", "insert"):
        alignment = alignment[:-1]

    # Long unmatched blocks are ads (inserted) or passages the model skipped (deleted); score them
    # separately so word-level accuracy isn't swamped by ad reads that the reference omits
    def block_size(chunk: jiwer.AlignmentChunk) -> int:
        return max(chunk.ref_end_idx - chunk.ref_start_idx, chunk.hyp_end_idx - chunk.hyp_start_idx)

    word_errors = sum(
        block_size(chunk) for chunk in alignment if chunk.type != "equal" and block_size(chunk) < BLOCK_WORDS
    )
    skipped_words = sum(
        block_size(chunk) for chunk in alignment if chunk.type == "delete" and block_size(chunk) >= BLOCK_WORDS
    )
    reference_words = sum(chunk.ref_end_idx - chunk.ref_start_idx for chunk in alignment)
    return (word_errors / reference_words if reference_words else 1.0), skipped_words


def _name_recall(reference_text: str, hypothesis_text: str) -> float:
    # Restrict to names inside the overlap: those the hypothesis plausibly covers
    names = _names(text=reference_text)
    hypothesis_words = set(_normalize(text=hypothesis_text).split())
    reference_tail = set(_normalize(text=reference_text[-2000:]).split())
    candidates = {
        name
        for name in names
        if name.lower() not in reference_tail or name.lower() in hypothesis_words
    }
    found = [name for name in candidates if name.lower() in hypothesis_words]
    return len(found) / len(candidates) if candidates else 0.0


def _names(text: str) -> set[str]:
    # Capitalized words that don't start a sentence approximate people, companies, and projects
    return set(re.findall(r"(?<![.!?\"]\s)(?<!^)\b([A-Z][a-zA-Z0-9]{2,})\b", text))


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9' ]", " ", text.lower())).strip()


# --- Output ---


def _print_scores(prepared: list[PreparedEpisode], runs: list[ProviderRun]) -> None:
    print(
        "\n=== Vs published transcript: word-level error (excl. ads) and words in skipped passages ==="
    )
    header = f"{'provider/hint':40}" + "".join(
        f"{item.episode.slug:>24}" for item in prepared if item.reference_text
    )
    print(header + f"{'time':>8}{'cost':>9}")
    for run in runs:
        cells = []
        for item in prepared:
            if not item.reference_text:
                continue
            score = run.scores.get(item.episode.slug)
            cells.append(
                f"{score.word_error_rate:>5.1%} skip {score.skipped_words:>3}".rjust(24)
                if score
                else "—".rjust(24)
            )
        cost = run.audio_seconds / 3600 * run.provider.usd_per_audio_hour
        print(
            f"{run.label:40}"
            + "".join(cells)
            + f"{run.seconds_elapsed:>7.0f}s{cost:>8.3f}$"
            + (f"  ERROR {run.error}" if run.error else "")
        )
    print(
        "Note: published transcripts may themselves be machine-generated, so WER here measures disagreement, not truth."
    )


def _print_disagreements(
    prepared: list[PreparedEpisode], runs: list[ProviderRun]
) -> None:
    finished = [run for run in runs if not run.error]
    if len(finished) < 2:
        return

    # For each episode, list names that only some providers produced: these are the spellings to eyeball
    print("\n=== Names the providers disagree on (eyeball which spelling is right) ===")
    for item in prepared:
        names_by_provider = {
            run.label: _names(text=run.transcripts[item.episode.slug])
            for run in finished
            if run.hint_style == HintStyle.RICH
        }
        everyone = set.intersection(*names_by_provider.values())
        print(f"\n[{item.episode.slug}] {item.title}  ({item.episode.jargon})")
        for provider_name, names in names_by_provider.items():
            unique = sorted(names - everyone)[:40]
            print(f"  {provider_name:40} {', '.join(unique) or '-'}")


def _print_jargon(prepared: list[PreparedEpisode], runs: list[ProviderRun]) -> None:
    # How often each run spelled known jargon correctly, against the published transcript's count
    print("\n=== Known jargon spelled correctly (count in transcript; ref = published transcript) ===")
    finished = [run for run in runs if not run.error]
    for item in prepared:
        print(f"\n[{item.episode.slug}]")
        for term in item.episode.jargon_terms:
            reference_count = _count(term=term, text=item.reference_text) if item.reference_text else None
            counts = "  ".join(
                f"{run.label.replace('groq-whisper-large-v3-', '').replace('openai-gpt-4o-', '4o-')}={_count(term=term, text=run.transcripts[item.episode.slug])}"
                for run in finished
            )
            print(f"  {term:14} ref={reference_count if reference_count is not None else '-':<3} {counts}")


def _count(term: str, text: str) -> int:
    return len(re.findall(re.escape(term), text, flags=re.IGNORECASE))


if __name__ == "__main__":
    main()
