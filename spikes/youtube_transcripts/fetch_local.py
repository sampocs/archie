# /// script
# requires-python = ">=3.12"
# dependencies = ["youtube-transcript-api>=1.0", "yt-dlp"]
# ///
"""Baseline: fetch YouTube transcripts from this Mac (residential IP) with two methods.

Run: uv run fetch_local.py
"""

import json
import pathlib
import tempfile
import time
from dataclasses import dataclass
from enum import StrEnum

import yt_dlp
from youtube_transcript_api import YouTubeTranscriptApi


class Method(StrEnum):
    TRANSCRIPT_API = "youtube-transcript-api"
    YT_DLP = "yt-dlp"


@dataclass(frozen=True)
class Video:
    video_id: str
    label: str


@dataclass
class Result:
    video: Video
    method: Method
    ok: bool
    words: int
    seconds: float
    error: str


VIDEOS = [
    Video("ugvHCXCOmm4", "Lex Fridman x Dario Amodei, 5.2h, human captions"),
    Video("y0YkGWKT0gI", "Odd Lots, 40m, human captions"),
    Video("LPZh9BOjkQs", "3Blue1Brown LLMs explained, 8m, human captions"),
    Video("0lJKucu6HJc", "Sam Altman startup talk, 16m, auto captions only"),
    Video("iClsnZ1KYSk", "Bankless Tom Lee, 63m, auto captions only"),
    Video("e0gVE3YxZs8", "Powell and the Fed in 60s, short, auto captions only"),
    Video("SlpcNYFuuWw", "Bitcoin live stream, captions disabled"),
]


def fetch_with_transcript_api(video_id: str) -> int:
    fetched = YouTubeTranscriptApi().fetch(video_id, languages=["en"])
    return sum(len(snippet.text.split()) for snippet in fetched)


def fetch_with_yt_dlp(video_id: str) -> int:
    with tempfile.TemporaryDirectory() as tmp_dir:
        options = {
            "skip_download": True,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": ["en"],
            "subtitlesformat": "json3",
            "outtmpl": str(pathlib.Path(tmp_dir) / "%(id)s"),
            "quiet": True,
            "noprogress": True,
            "no_warnings": True,
        }
        with yt_dlp.YoutubeDL(options) as downloader:
            downloader.download([f"https://www.youtube.com/watch?v={video_id}"])

        subtitle_files = list(pathlib.Path(tmp_dir).glob("*.json3"))
        if not subtitle_files:
            raise RuntimeError("no subtitle file produced")

        events = json.loads(subtitle_files[0].read_text())["events"]
        return sum(len(segment.get("utf8", "").split()) for event in events for segment in event.get("segs", []))


FETCHERS = {Method.TRANSCRIPT_API: fetch_with_transcript_api, Method.YT_DLP: fetch_with_yt_dlp}


def run_one(video: Video, method: Method) -> Result:
    started = time.monotonic()
    try:
        words = FETCHERS[method](video.video_id)
    except Exception as error:  # noqa: BLE001 - a spike records every failure mode instead of crashing
        return Result(video, method, False, 0, time.monotonic() - started, f"{type(error).__name__}: {str(error)[:80]}")
    return Result(video, method, words > 0, words, time.monotonic() - started, "")


def main() -> None:
    print("| video | method | ok | words | seconds | error |")
    print("|---|---|---|---|---|---|")
    for video in VIDEOS:
        for method in Method:
            result = run_one(video=video, method=method)
            error = result.error.replace("\n", " ").replace("|", "/")
            print(f"| {video.video_id} ({video.label}) | {method} | {result.ok} | {result.words} | {result.seconds:.1f} | {error} |")


if __name__ == "__main__":
    main()
