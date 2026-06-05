# Flowz Brand Kit

Flowz is a free, open voice dictation app for Windows. The brand should feel fast,
fluid, clear, and quietly premium. It should not feel like a generic AI assistant,
enterprise recorder, or noisy productivity hack.

## Brand Idea

**Voice becomes text without friction.**

Flowz is built around one physical action: hold, speak, release. The identity
should communicate that same movement: a continuous line, a soft acceleration,
and a clean landing point.

## Positioning

Flowz is the lightweight, free alternative to premium dictation tools like Wispr
Flow for people who want fast voice typing without a heavy subscription product.

Core promise:

> Speak naturally. Flowz turns it into text.

Short variants:

- Voice to text, instantly.
- Dictation that stays out of your way.
- Hold. Speak. Release.
- Type at the speed of thought.

## Personality

Flowz should feel:

- Fluid, not flashy.
- Fast, not frantic.
- Human, not robotic.
- Polished, not corporate.
- Open, not hobbyist.

Avoid:

- Generic purple AI gradients.
- Overly technical hacker styling.
- Loud neon/glass UI.
- Fake enterprise dashboards.
- Dense marketing language.

## Logo System

Primary asset:

```text
assets/flowz-logo.svg
```

The logo is a blue handwritten wordmark. It should be used as the primary brand
signal. The curves imply speech, flow, and text being drawn in real time.

Usage rules:

- Use the full wordmark in primary surfaces: README, website hero, installer,
  settings window, and release pages.
- Keep generous whitespace around it. Minimum clear space equals the height of
  the lowercase `o`.
- Do not place the wordmark inside a pill, badge, or decorative sticker.
- Do not add shadows stronger than the supplied soft shadow.
- Do not recolor it outside the approved palette unless using monochrome.

Preferred lockups:

- Wordmark alone.
- Wordmark above the line "Fast voice dictation for Windows."
- Wordmark with a small circular waveform mark only in tight UI surfaces.

## Color Tokens

Flowz uses a light, airy surface with precise blue accents and a dark ink system
for product UI.

| Token | Hex | Use |
| --- | --- | --- |
| Flow Blue 500 | `#1C9CEB` | Primary brand blue |
| Flow Blue 600 | `#1289DB` | Buttons, links, active states |
| Flow Blue 700 | `#0871C1` | Pressed states, deep accents |
| Sky 100 | `#EAF7FF` | Light background wash |
| Mist 050 | `#F8FCFF` | Page surface |
| Ink 950 | `#071521` | Primary text |
| Ink 800 | `#163044` | Secondary text |
| Steel 400 | `#7B94A8` | Muted copy, borders |
| Cloud 000 | `#FFFFFF` | Cards, high contrast surfaces |
| Signal Green | `#2CD889` | Success and ready states |
| Warm Amber | `#E6A93A` | Paused, warning, waiting states |
| Error Red | `#FF4D5E` | Recording/error state |

Gradients:

```css
--flowz-logo: linear-gradient(135deg, #45BDFF 0%, #1C9CEB 38%, #1289DB 72%, #0871C1 100%);
--flowz-surface: radial-gradient(circle at 50% 24%, #ffffff 0%, #f8fcff 55%, #eaf7ff 100%);
--flowz-ink: linear-gradient(180deg, #071521 0%, #10283b 100%);
```

## Typography

Primary UI and web typography:

- **Cabinet Grotesk** for headlines, navigation, marketing pages, and launch
  materials.
- **Geist** for app UI, README screenshots, settings, and body copy.
- **JetBrains Mono** for command snippets and technical diagnostics.

Fallback stack:

```css
--font-display: "Cabinet Grotesk", "Satoshi", "Outfit", system-ui, sans-serif;
--font-body: "Geist", "Segoe UI", system-ui, sans-serif;
--font-mono: "JetBrains Mono", "Cascadia Code", monospace;
```

Type scale:

| Role | Size |
| --- | --- |
| Hero | `clamp(3rem, 5.6vw, 6.25rem)` |
| Page title | `clamp(2.4rem, 4vw, 4.5rem)` |
| Section title | `clamp(2rem, 3vw, 3.25rem)` |
| Card title | `1.35rem` |
| Body | `1rem` to `1.125rem` |
| Caption | `0.8125rem` |

Headline rule:

Keep launch-page hero headlines to 2-3 lines using `max-w-6xl w-full`. Never
force Flowz into narrow centered columns that create 5-6 line wraps.

## Voice and Copy

Flowz copy should be short and operational. It should sound like a useful tool,
not a motivational coach.

Good:

- "Hold. Speak. Release."
- "Flowz listens only when you ask."
- "Fast dictation for any text field."
- "Warm capture keeps the first word intact."
- "Your voice lands where your cursor is."

Avoid:

- "Unleash your productivity."
- "AI-powered revolutionary workflow."
- "Magical voice intelligence."
- "Speak your dreams into existence."

## UI Direction

Visual mode:

Light editorial product with precise blue motion accents.

Surfaces:

- Mist-white backgrounds.
- Fine blue radial glow behind the wordmark.
- Dark ink panels for terminal/app screenshots.
- Thin borders using `rgba(28, 156, 235, 0.16)`.
- Rounded corners from `8px` to `14px`, not oversized bubbles.

Buttons:

Primary:

```css
background: #071521;
color: #ffffff;
border: 1px solid rgba(255, 255, 255, 0.12);
```

Secondary:

```css
background: #ffffff;
color: #071521;
border: 1px solid rgba(22, 48, 68, 0.14);
```

Active/ready state:

```css
background: #2CD889;
color: #071521;
```

Recording state:

```css
background: #FF4D5E;
color: #ffffff;
```

## Website System

Navigation:

Use a minimal split nav. Wordmark left, core links center, GitHub/download action
right. Keep the nav quiet and do not put the hero in a card.

Attention:

Editorial split hero. Left side contains a wide headline:

> Type at the speed of thought.

Right side contains a clean app-state visual: hotkey, waveform, transcript
landing in a text field. No fake dashboard overload.

Interest:

Use a gapless 12-column bento grid with `grid-flow-dense`.

Grid proof:

- 12 columns x 6 rows = 72 cells.
- Card A: 4 columns x 3 rows = 12 cells.
- Card B: 4 columns x 3 rows = 12 cells.
- Card C: 4 columns x 3 rows = 12 cells.
- Card D: 6 columns x 3 rows = 18 cells.
- Card E: 6 columns x 3 rows = 18 cells.
- Total = 72 cells, no gaps.

Cards:

- Ready sound and hotkey.
- Warm capture and pre-roll.
- Silence trim.
- Open settings.
- Free alternative positioning.

Desire:

Use pinned scroll: left title stays fixed while right panels move through
"Hold", "Speak", "Release", "Paste". Use scrubbing text reveal for one concise
paragraph, not long copy.

Action:

High-contrast footer CTA:

> Download Flowz and start speaking into any text field.

Use exactly two actions: "Download for Windows" and "View on GitHub".

## Motion System

Motion should feel like ink becoming text.

Principles:

- Smooth, low-amplitude, precise.
- 220-420ms for UI response.
- 700-1100ms for hero and scroll reveal.
- Easing: `power3.out`, `expo.out`, or CSS `cubic-bezier(.16, 1, .3, 1)`.

GSAP direction:

- Scroll pinning for workflow chapters.
- Scrubbing text reveals for product promise.
- Image scale/fade for brand panels.

Hover physics:

```css
transform: translateY(-2px) scale(1.01);
transition: transform 700ms cubic-bezier(.16, 1, .3, 1), border-color 300ms ease;
```

Do not bounce, wobble, or use playful spring effects. Flowz is fluid but calm.

## Sound Identity

Ready sound:

Use a short "point" chime as the ready-to-speak cue. In the app this is
configured through `ready_sound_path`, so packaged builds can ship a branded
sound while local builds can point to any user-provided file.

Sound should be:

- Short.
- Soft.
- Confirming, not alerting.
- Different from Windows error sounds.

Use it only for "ready to speak." Do not reuse it for error or completion states.

## Product Icon Direction

If a square app icon is needed, use:

- White or mist background.
- A single lowercase flowing `f` stroke or abstract waveform path.
- Flow Blue gradient.
- No microphone icon unless extremely simplified.

The app icon should not be a tiny version of the full wordmark; it will not
remain readable at tray size.

## Brand Applications

README:

- Logo centered, 520-620px wide.
- Short one-line promise.
- No badges above the fold except essential build/license badges if added later.

Settings GUI:

- Use "Flowz Settings" title.
- Keep the controls functional and restrained.
- Primary action should be "Save and close".

Tray:

- Use product behavior labels: "Settings", "Pause Dictation", "Release Warm
  Capture", "Open Config Folder", "Exit".

Installer:

- Install path: `%LOCALAPPDATA%\Flowz\Flowz.exe`.
- Start Menu folder: `Flowz`.
- Startup registry key name: `Flowz`.

## Brand Board

Presentation board:

```text
assets/flowz-brandkit-board.svg
```

Use this board in launch posts, GitHub discussions, release notes, and investor
or contributor context when explaining the product visually.

## Do Not Do

- Do not use generic purple-blue "AI SaaS" backgrounds.
- Do not add floating sparkles or random stickers.
- Do not use cheap section labels.
- Do not make the logo black unless the surface requires monochrome.
- Do not set copy in Inter.
- Do not put UI cards inside other cards.
- Do not place the wordmark over busy photos.
