# Spike: podcast show → RSS (2026-10-26)

`python3 -I spikes/podcast_resolve/resolve_shows.py`

The 28 shows I actually listen to were resolved through the iTunes Search API to their public RSS feeds, then the 10 most recent episodes of each were checked for Podcasting 2.0 `<podcast:transcript>` tags.

## Results

- **28/28 shows have a public RSS feed with audio.** None of them are Spotify-exclusive, including Joe Rogan.
- **5/28 publish transcripts in RSS:** Bussin' With The Boys, Bankless, Darknet Diaries (about half of recent episodes), Acquired (about half), and Money Stuff.
- **The other 23 need transcription.** Many of them are long (Rogan ~3h, Acquired up to ~4h, Lex ~3.5h, Huberman ~2.5h), so transcription is a real but small cost (see the findings doc).

## Lessons

- **Matching by name is brittle.** Taking the top search hit picked a spin-off (*Inside the Bus* instead of *Bussin' With The Boys*), a stale listing with a dead feed (*Invest Like the Best*), and an unrelated show. Preferring an exact title match fixed those, but then picked a *different* show that shares the exact name (*When Shift Happens*).
- **Design implication:** keep a **show registry**. The first time a show appears, match it using the show name **and** the publisher (both visible on the Spotify page), save the mapping, and let me correct it in the app. My show list is small and stable, so it can be pre-loaded with these 28.

## Still untested

- **Episode-level matching** from a real Spotify episode link: read the episode title and show from the Spotify page, then find the same episode in the RSS feed by title and date. This needs real `open.spotify.com/episode/...` links.
- Transcript quality and cost on a real episode (needs a transcription API key).
- Whether shows like Dwarkesh publish transcripts on their own sites (not in RSS), which would avoid transcription for those shows.
