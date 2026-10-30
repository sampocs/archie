# Archie: UX & Brand Design (v1)

> Status: approved design, 2026-10-29. Covers roadmap step 3 ("finalize the product: the exact interface, down to styling") for visual design, interaction, and brand. The reading voice is a separate track.
> Companion to [product scope](2026-10-26-product-scope.md). **Visual reference:** [2026-10-29-ux-and-brand-reference.html](2026-10-29-ux-and-brand-reference.html), a single page with every token and the final interactive mockups. When this doc and the reference disagree, this doc wins.

## Goal

The app should feel good enough that you'd rather consume everything inside it. In practice: crisp type, calm color, instant feedback, native-feeling motion, and haptics on every meaningful moment. Nothing should feel like homework.

## Brand

- **Name: Archie.** (This replaces "Carl" in the product scope.)
- **Where the name appears:** the home-screen label, the notification title, the share-sheet target ("Add to Archie"), the wordmark, and conversation. **It never appears in UI copy.** The chat tab is labeled **Ask**, the bar reads "Ask about this episode," and Review shows "Answer," not "Archie's answer."
- **Wordmark:** "Archie." in Geist Bold, tracking −0.06em, with a forest period (mint `#79B39E` in dark mode). Used on the launch screen and outside the app.
- **App icon:** a top-down brain in thick white line art on brand forest `#3F7262`, with a scalloped outline, a center line, and C-shaped curls in each hemisphere. The current art is a programmatic draft. It needs a proper vector pass (hand-drawn or careful Figma work) before shipping, keeping the same composition and stroke weight.

## Visual system

### Direction

Precision-tool type (Geist, heavy tight headings) on soft white cards with a little depth, over a warm off-white page. **Graphite is the chrome; color is a signal.** Navigation, back, the active tab, primary buttons, + and the Ask bar are graphite. Color appears only where it carries meaning: domain labels, verdicts, and the review card.

### Color tokens

| Token | Light | Dark (warm charcoal) | Use |
|---|---|---|---|
| bg | `#F4F2EC` | `#151412` | Page |
| surface | `#FFFFFF` | `#201F1C` | Cards |
| ink | `#0E0E0C` | `#F1EFE9` | Primary text |
| ink-2 | `#55534D` | `#B3AFA5` | Secondary text |
| ink-3 | `#9A978F` | `#7E7A70` | Tertiary text, mono labels |
| line | `#E8E6DF` | `#2D2B27` | Hairlines |
| press | `#EFEDE6` | `#2A2824` | Chips, pressed rows, inputs |
| chrome | `#1C1B18` | `#F1EFE9` | Nav, primary buttons, active tab. **Inverts in dark**, with text on chrome flipping to `#141311` |

**Domains (muted, one color per domain):**

| Domain | Light | Dark |
|---|---|---|
| Macro | `#3F7262` | `#79B39E` |
| AI | `#6A5A9C` | `#A898DE` |
| Crypto | `#A8613A` | `#DC9867` |
| Startups | `#3D6690` | `#7FA7D9` |
| Finance | `#8A7533` | `#CDB46A` |
| History | `#8E5468` | `#C98BA0` |

New domains get a new muted hue at the same saturation and lightness as the others. Dark versions are lifted, never neon.

**Signals:**
- Got it: `#3F7262` / `#79B39E`
- Partly: `#A97F22` / `#D6AC4E`
- Missed and "Parts lost me": `#B04A3C` / `#E3806F`
- Review card on Today: `#3F7262` / `#2F5A4C`

**Depth:** in light mode, cards have a 1px hairline plus a 2px soft shadow. In dark mode, the shadow is dropped and cards get a faint hairline border instead.

### Type

- **Geist** is used everywhere, including long-form reading. **Geist Mono** is used for section labels, timestamps, counts, and rough numbers.
- **Scale** (size / weight / tracking):
  - Large title: 32 / 700 / −0.04em
  - Article title: 28 / 700 / −0.04em
  - Review question: 27, shrinking to 21 / 650 when the keyboard is up or the grade shows
  - Headline: 16 / 600 / −0.018em
  - Reading body: 16, line height 1.62
  - UI body: 15
  - Secondary: 13–13.5
  - Kicker: 10.5 / 600 / +0.06em / uppercase, in the domain color, as colored text (no pill or dot)
  - Mono label: 11 / 500 / uppercase

### Shape and layout

- **Radii:**
  - Grouped cards: 18
  - Review answer card and text box: 22
  - Primary buttons: 16, at a height of 50–54
  - Chips: 8–12
- **Gutters:** 16 for card groups, 22–24 for text. Sections are spaced 22–24 apart.
- **Tab bar:** Today · Library · ＋ · Review · **Ask**. Standard iOS style with labels and a translucent blur. The active tab is chrome. It slides away on pushed reading screens.
- **Artwork:** shown everywhere a source has it. Missing art falls back to a **monogram tile in the domain color**: a letter, or ◆ for primers. Fetching it is cheap, because every source already returns an image URL from the lookup the pipeline makes: the iTunes API for podcasts, Open Library for books, YouTube thumbnail URLs, `og:image` for articles, and fxtwitter avatars, which render as circles because they're people.

### Motion

- **Curve:** `cubic-bezier(.32,.72,0,1)`, an iOS spring feel.
- **Push and pop:** about 0.5s. The previous screen shifts −28% and dims.
- **Press states:** scale to .96–.975 over 0.18s.
- **Keyboard and layout reflow:** 0.42s.
- **Chat answers:** stream word by word, about 28ms per word.

### Haptics

| Event | Feedback |
|---|---|
| Tab switch, segmented toggle, chip select | selection |
| Push / pop, send, open source peek | light |
| Start recording, Drop | medium |
| Grade: got it / partly / missed | notification success / warning / error |
| Saved (share sheet), card added, session done, undo | notification success |
| Drag past the Drop threshold | selection (once) |
| Submit with an empty answer | rigid, plus a shake animation |

## Screens

### Today
- Large "Today" title with a mono date.
- **Pulse:** one card group of stories. Each story has a domain kicker, a headline and a 2-line snippet, followed by "Also happening ›."
- **Review card:** "12 cards · about 4 minutes · 3 foundations first" in the review-card color.
- **Primer ready**, then **Up next.** Up next rows carry a "Prep me" chip.

### Review
The layout is a hybrid of the two explored options: a question on the page that turns into an answer card.

- **Answering:**
  - The question sits on the page in large type, with the domain kicker and card kind (Foundation / Mechanism / Rough number) above it.
  - Below it is a **large writing area**: a white card with a toolbar holding **Drop** (bottom-left), mic and ↑.
  - When the keyboard rises, the question shrinks and the box fills the space between.
- **Voice:** tapping the mic shows a waveform while recording. When you stop, the transcription types itself into the box.
- **Grade:**
  - On submit, the ↑ button breathes while grading.
  - The text box then **becomes the card**, with "You said," the verdict chip (it pops in), "what was missing" for partly or missed, and "Answer."
  - Under that sit "I actually knew it" (overrides to Got it) and "What I care about…" (inline input, rewrites the card).
  - The question stays visible above the card. There's no bottom sheet.
- **Next:** the card flicks left and the next question fades up.
- **Drop:**
  - It's a neutral grey chip, not red and not an X. Red is the "missed" color, and dropping a card isn't a failure.
  - It shows an undo toast: "Dropped. Fewer cards like this · Undo."
- **Shake to undo:** shaking always reverses the last Drop, Next or override. A native alert asks "Undo Drop?" or "Undo Answer?"
- **Done screen:** "Done.", a summary line, then the got it / partly / missed / dropped tally and "Back to Today."

### Library
- Large title, a **List / Domains** segmented control, a search field ("Search everything, or ask…"), and status chips (All · Queued · Done · Inbox · Primers · Books).
- **List:** grouped by time ("This week" / "Earlier"). Each row has artwork, a domain kicker, a 2-line title, meta, and a status tag. Unread inbox items get a blue dot.
- **Domains:**
  - One row per domain, with a colored square, a count, and a thin bar showing done / queued / inbox.
  - Topic chips sit under each domain. Topics you added have an outline instead of a fill.
  - Ends with "＋ Add a topic you want to understand."

### Item page
- **Header: cover beside title.** The cover is 92px next to the kicker, by-line and reaction chip, with the full-width title below. There's no color wash.
- **Sections, in order:**
  1. Gist
  2. Key ideas (numbered)
  3. Rough numbers, in mono, with **timestamp chips** that open the source app at that moment
  4. Background you might need (the primer, collapsed and expandable)
  5. Your note
  6. Cards from this, each with a status dot and when it's due
  7. Related (a horizontal row of artwork cards)
- A floating "Ask about this episode" bar sits at the bottom.

### Ask (chat)
- **Document style:**
  - Your messages are graphite bubbles on the right.
  - Answers are full-width text.
  - Big numbers get a **"For scale" block** with comparison bars.
- **Inline [1] citations:** tapping one opens a **source peek sheet** with the artwork, title, timestamp, the exact quote, and "Play from …" or "Open."
- **Sources:**
  - The latest answer shows source chips with artwork, plus "＋ Make a card" and Copy.
  - **Earlier turns collapse their sources** into one stacked chip ("2 sources"), which expands when tapped.
- **Follow-ups:** suggestions (↳) appear under the latest answer.
- **Make a card:** shows the generated card inline ("due tomorrow · Edit"). A badge appears on the Review tab.
- **Context:** opened from an item page, the top bar shows a "Looking at: <item>" context chip.
- **Empty state:** suggested questions, including one from today's Pulse.

### Share sheet and ＋
- The iOS share sheet shows the Archie icon. Tapping it opens Archie's sheet, and the app behind scales back.
- The item **matches on its own.** It shows a shimmer, then the artwork, title and domain fade in.
- **Finished** reveals "How'd it go?" (Easy / Mostly followed / Parts lost me, each in its verdict color) and "Anything confusing?" with a mic.
- **Queue it** reveals the **Prep me** toggle.
- **Save** draws a check with a context-aware message, then the sheet auto-dismisses. The shortest path is two taps: Finished, then Save.
- The ＋ tab uses the same sheet.

### Dark mode
The dark mode uses the warm charcoal base. All tokens are above. It follows the system setting.

## Out of scope here
- Reading voice and style guide (separate track).
- Onboarding, settings and notification copy beyond the daily review line.
- Final icon artwork (needs the vector pass described above).

## Build plan (Medium)

The plan assumes the Expo app shell exists, which comes from roadmap step 4 (technical spec). This spec only defines the design-system layer the screens are built on.

### Chunk 1: Theme tokens, type, and primitives
- **Files:**
  - `app/theme/tokens.ts`: color (light/dark), domain and signal colors, radii, spacing
  - `app/theme/type.ts`: the scale above, with Geist and Geist Mono loaded via `expo-font`
  - `app/theme/ThemeProvider.tsx`: follows `useColorScheme`
- **Primitives:** `Card`, `GroupedList`, `Kicker`, `MonoLabel`, `Chip`, `PrimaryButton`, `ArtworkTile` (image plus monogram fallback).
- **Interfaces:** `useTheme()` returns the tokens. Screens import primitives only, never raw hex values.
- **Tests:** snapshot each primitive in light and dark. Unit-test that `ArtworkTile` falls back to the monogram when the URL is missing or fails to load.
- **Depends on:** none.

### Chunk 2: Motion and haptics
- **Files:**
  - `app/theme/motion.ts`: the spring config for `react-native-reanimated`, press-scale hook, push/pop transition preset for the navigator
  - `app/theme/haptics.ts`: named events mapped to `expo-haptics`, per the table above
  - `app/hooks/useShakeToUndo.ts`: `expo-sensors` accelerometer, threshold-tuned, plus an undo stack interface
- **Interfaces:** `haptic('grade.partly')`, `usePressScale()`, and `useShakeToUndo(stack)`, where the stack has `push`, `pop` and a label.
- **Tests:** unit-test the event-to-haptic mapping and the undo stack (push / pop / label). Test the shake threshold on a device.
- **Depends on:** none (parallel with chunk 1).

### Chunk 3: Brand assets
- **Files:**
  - `assets/icon.png` (1024): vector-pass brain on forest
  - `assets/splash.png`: wordmark on bg, plus a dark variant
  - `app.json` icon and splash config
- **Key decision:** keep the draft composition and stroke weight.
- **Tests:** check the icon at 1024, 180, 120, 87, 58 and 40px on a light and a dark wallpaper.
- **Depends on:** none.
