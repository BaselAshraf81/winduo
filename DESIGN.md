# Design

<!-- impeccable:design-schema 1 -->

Recorded from the built surfaces, not from intent. Two surfaces share this
system: the project site in `docs/` (Persuade) and the desktop app's windows in
`winduo/ui/` (Operate). The app carries the world in material and detail only;
nothing there is allowed to make a slider harder to find.

Seed key `a822940d`. Direction: scene painter's anamorphic stage flat, candidate
6 of 7 on the grounded list.

## The world

A painted flat is an image constructed to read correctly from one seat while the
surface it sits on is angled away from the audience. That is what this app does
to a screen, so the world is the scene shop rather than a metaphor about
laptops: stretched cloth, chalk snap-lines struck across it, distemper paint,
everything squared up to a marked sightline.

What this refuses, deliberately: the open-source landing page arrangement of dark
hero, gradient headline, three feature cards, badge row. There are no cards
anywhere in `docs/style.css`. Sections are separated by struck lines, and content
is grouped by measure and rhythm instead of by boxes.

## Colour

**Drenched.** Prussian blue owns the whole surface at page scale; it is the
ground, not an accent on a neutral. Oxide red is the only saturated mark and is
reserved for things that are active or being operated: the primary action, the
hinge line, the step numerals, the direction arrow, the dashed line marking what
has left the frame. Chalk carries all text.

Dark, and not by category habit. The app runs on a laptop in an ordinary lit
room, and the effect it advertises is a screen going dark as it leans away. A
light ground would fight its own demonstration.

### Site (`docs/style.css`)

| Token | Value | Role |
|---|---|---|
| `--blue-deep` | `#0d2135` | Recessed bays, the quiet passage, the footer |
| `--blue` | `#123049` | Page ground |
| `--blue-lift` | `#1a3d59` | The lit corner of the flat, top left |
| `--blue-line` | `#2d5875` | Snap lines, rules, borders |
| `--chalk` | `#f4f0e6` | Headings and body. 12.4:1 on `--blue` |
| `--chalk-soft` | `#c6cdd2` | Secondary prose. 7.8:1 |
| `--chalk-faint` | `#93a3af` | Captions and fine print. 4.6:1 |
| `--oxide` | `#d2542c` | The working mark |
| `--oxide-lift` | `#ea6c3f` | Hover, focus ring, live readout |
| `--linen` | `#d9cdb4` | Raw cloth, used for code and one diagram line |

Every text pair meets WCAG 2.2 AA on its own ground. Secondary text is tinted
from the blue rather than greyed.

### App (`winduo/ui/theme.py`)

The app windows sit on oiled canvas rather than distemper blue, because a
settings window should recede next to the effect it configures. `CANVAS`
`#1c1a17`, `CHALK` `#f2ede4` at 13.9:1, `OXIDE` `#c1502e` for active controls,
and `PRUSSIAN` `#4a7fa5` for anything measured rather than chosen. That split is
load-bearing: in the calibration wizard, blue means the machine is reporting and
red means the user is setting.

## Type

- **Display: Big Shoulders Display**, 700/800. Condensed wood type, the register
  a scene shop paints in. Carries the wordmark, all headings, the step numerals,
  and the live readout.
- **Text: Archivo**, 400/500/600. A workhorse grotesk that stays legible at 0.86
  rem for captions.
- **App windows: the platform text face** (`Segoe UI Variable Text`, falling back
  through `Segoe UI`). Operate surfaces are well served by it, and a settings
  panel is not where a display voice belongs.

Headings run `line-height: 0.94` with `letter-spacing: -0.01em` and
`text-wrap: balance`. Body is 1.62 with a 34 rem measure. Small labels are 0.7
rem uppercase at `0.14em` tracking, which is how a flat gets stencilled.

## Composition

- One `--measure` for prose, one `--gap`, one `--bay-y` for vertical rhythm.
  Space above a heading always exceeds space below it.
- `.bay` is the section primitive: a two-column grid above 62 rem that collapses
  to one, with variants that force a single column when the content is a
  sequence, a statement, or a list.
- Density is paced rather than uniform. The mechanism passage is dense two-column
  prose beside a diagram; the passage after it is a single wide column on a
  recessed ground with one large statement; then a three-part sequence; then a
  definition list; then the close. A dense passage earns a quiet one.
- **The `.snap` rule is the only divider on either surface.** A 1px line with a
  single oxide dot where the chalk was pinned.
- Numbers appear on the calibration steps only, because that sequence is a real
  order the user performs. Nothing else is numbered.

## The demonstration

The first viewport performs the effect on the page's own content, using the same
three operations as the shader:

1. **Perspective.** `rotateX(var(--lean))` on the screen with
   `transform-origin: 50% 100%` inside a `perspective: 1500px` room, so the hinge
   edge stays pinned and the far edge recedes and converges. Positive rotation:
   negative would lean the top toward the viewer, which is a lid opening.
2. **Progressive blur.** Three `backdrop-filter` layers at 4px, 12px, and 28px,
   each masked to a band further from the hinge. The same idea as sampling a mip
   pyramid at a level chosen by height.
3. **Dimming.** A gradient from the hinge upward, held to roughly two thirds of
   the app's own depth. The app takes the far edge to black, which is right when
   the lid is nearly shut and nobody is looking, but a demonstration that goes
   black has hidden the blur and the perspective it exists to show.

`--travel` is a registered `@property`, so it animates and interpolates as a
number.

## Motion

One authored moment, the lid closing, on `cubic-bezier(0.16, 1, 0.3, 1)`
throughout.

Driven by `animation-timeline: scroll(root block)` over `0 70vh`, so the page
demonstrates itself with scripting off. Root scroll rather than `view()`: a view
timeline is already partway through when the element loads mid-viewport, which
would show a leaning screen beside a readout claiming nothing had moved.

`docs/demo.js` is enhancement only. It mirrors the scroll-driven value into the
readout and the slider thumb, and hands the warp to the slider permanently once
touched. Handing it back and forth would mean fighting the reader for the same
element.

The diagram's scene slides as one rigid piece, because that is what pitch does to
an image; nothing inside it moves relative to anything else.

`prefers-reduced-motion: reduce` stops both animations and shows a part-closed
still, which still makes the point.

## Icons

Drawn, never borrowed and never a glyph. One stroke weight per icon. The app icon
and the site favicon are the same mark: a flat hinged at its foot and leaning
back, narrower at the top, with one chalk snap-line across it. The product's own
geometry as its identity.

## Accessibility

- Skip link, one `h1`, headings in order, `dl` for the limits, `ol` for the
  sequence.
- `:focus-visible` is a 2px oxide outline at 3px offset. The wizard's sightline
  dial is keyboard operable with arrows, Shift for fine steps, Home and End, and
  draws its own focus ring.
- The range input keeps its native semantics with `aria-describedby` pointing at
  the live `output`.
- The diagram carries a full `role="img"` label describing what it shows.
- Colour never carries meaning alone: the tray reports status as text, the wizard
  states what to do in words, and confidence has a numeric readout beside its
  meter.
- No horizontal overflow at 390px. Verified in-browser at 1440 and 390.

## Copy

Plain, specific, and it names failure. Controls name their action ("Run the
effect", "This is my usual angle", "It is shut"). Errors name the problem and the
recovery ("The camera view went dark. Make sure nothing is covering it."), never
a code. Measurements appear as measurements: degrees, pixels per degree, pixels
of movement seen so far. The site's limits section states what the app will not
do, in the same voice as the rest, because trust in a measurement comes from
knowing where it breaks.
