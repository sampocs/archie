"""Real public media the M3 tests and Maestro flows share, chosen once so every cassette uses the same links.

Everything here was found on 2026-11-03 with iTunes Search / Lookup, the shows' RSS feeds and the public Spotify pages.
"""

from __future__ import annotations

# A short Spotify episode with no published transcript: UPI Odd News Minute (daily, ~2 min of speech). The feed is
# 716 KB with 300 episodes back to 2023, so the item stays put for the Maestro flow. Found through iTunes Search
# (collection 1680976721, feedUrl https://feeds.libsyn.com/464601/rss); the Spotify show page
# https://open.spotify.com/show/0nmTbPwLNx8Ah2BRfMuOqe lists the episode, whose ld+json name and datePublished
# (2026-11-03) match the RSS item "Alligator in a bagel shop, largest rubber band ball" (pubDate 2026-11-03 20:00 UTC).
SPOTIFY_EPISODE_URL = "https://open.spotify.com/episode/4G2R6Ii1bIj7uLShXTqpCS"
SPOTIFY_EPISODE_TITLE = "Alligator in a bagel shop, largest rubber band ball"
SPOTIFY_SHOW_NAME = "UPI Odd News Minute"

# That episode's RSS enclosure: 2,636,530 bytes (Content-Length matches), 128 s by ffprobe.
EPISODE_AUDIO_URL = (
    "https://traffic.libsyn.com/secure/e59433fc-5e10-4942-80dd-917c5571638a/oddpod_11.3.26.mp3?dest-id=3923703"
)
EPISODE_FEED_URL = "https://feeds.libsyn.com/464601/rss"

# An Apple episode with a published transcript: Darknet Diaries "182: Blackshades". The feed (1.06 MB) carries a
# `<podcast:transcript type="text/vtt">` of 77 KB / ~10,600 words. iTunes Lookup (id 1296350485, podcastEpisode,
# limit 200) returns it as trackId 1000798773721 (newest episode); the link resolves (HTTP 200). The lookup's
# episodeGuid differs from the feed's guid ("prx_7057_..."), so the feed item matches by title ("Blackshades" vs
# "182: Blackshades", ratio ~0.85) and date.
APPLE_TRANSCRIPT_EPISODE_URL = "https://podcasts.apple.com/us/podcast/blackshades/id1296350485?i=1000798773721"
APPLE_TRANSCRIPT_EPISODE_TITLE = "Blackshades"

# "Powell and the Fed in 60 s" from the YouTube spike: English auto captions, re-checked on 2026-11-03 (28 snippets).
YOUTUBE_VIDEO_URL = "https://www.youtube.com/watch?v=e0gVE3YxZs8"

# A Spotify show page with a known id, for show-link (non-episode) rejection tests.
SPOTIFY_SHOW_URL = "https://open.spotify.com/show/4rOoJ6Egrf8K2IrywzwOMk"

# A Spotify-exclusive episode: "The Dark Side Of" (Parcast / Spotify original). iTunes Search finds a show of that name
# with no feedUrl, so no RSS can contain the episode. Found by searching `"The Dark Side Of" site:open.spotify.com`;
# the episode is the season-trailer "New Season! Introducing The Dark Side Of: The 90s!" (2020-06-14).
SPOTIFY_EXCLUSIVE_EPISODE_URL: str | None = "https://open.spotify.com/episode/0inIb18yUwTeNb1FVRqwIH"

# A public X post with a native video, for `fetch_collection_item`'s preview test (cassette `collection_x_video.yaml`).
# Found on 2026-11-05 from @NFL's timeline; fxtwitter returned a video thumbnail and length for it.
X_VIDEO_POST_URL = "https://x.com/NFL/status/2118529649387225218"
