---
name: better-ssh
description: The terminal is the product. Colors are Rich's semantic names, resolved by the terminal's own theme; the landing page uses the house tokens.
colors:
  primary: "#ebdbb2"
  neutral-bg: "#1d2021"
  surface: "#282828"
  muted: "#a89984"
  rule: "#504945"
  success: "#b8bb26"
  danger: "#ff8a7a"
  info: "#83a598"
typography:
  body:
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.6
  title:
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif"
    fontSize: "clamp(1.9rem, 1.2rem + 2.4vw, 3rem)"
    fontWeight: 700
    lineHeight: 1.15
    letterSpacing: "-0.02em"
  code:
    fontFamily: "JetBrains Mono, ui-monospace, SFMono-Regular, Menlo, monospace"
    fontSize: "0.85rem"
    lineHeight: 1.55
rounded:
  md: "6px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "16px"
  lg: "24px"
  xl: "40px"
---

# Design system: better-ssh

## Overview

**Creative North Star: "the terminal owns the interface"**

better-ssh is a command-line tool. Its interface is a table, a prompt, and
the line the tool prints before it runs `ssh`. There is no brand palette, no
logo, and no typeface decision: the terminal's own theme decides the color,
and the tool only decides which semantic name to ask for. Rich's named styles
are used, never a hex value, so the output follows the user's terminal
palette on every platform.

The one rule the interface holds to is that a color means one thing. Green is
a success, yellow is a warning, red is a failure, cyan marks a command the
tool is about to run or a value the reader is expected to type, and dim is
context rather than content. Nothing is colored for decoration.

Two surfaces exist. The terminal is the product. The landing page under
`docs/` is a rendering of the same argument, and it uses the house stylesheet
that every repository in this collection shares. That stylesheet is not a
better-ssh palette. Its rules live in `docs/style.css` above the block marked
as the site's own rules.

Key characteristics:

- Semantic color names only in the terminal, so the output follows the
  terminal theme.
- One table shape. A column appears only when at least one row has a value
  for it.
- The command line is printed before it runs, in cyan.
- The landing page adds its rules at the end of the house stylesheet, and
  nowhere else.

## Colors

### Terminal

The terminal names below are Rich's style names. The hex value behind each
one belongs to the user's terminal theme, and the tool does not choose it.

- **cyan**: the command that is about to run, the label of a shell hook, and
  the values a reader is expected to type, such as a file name in an export
  hint.
- **green**: an outcome that succeeded. A reachable server, an exported
  store, a pinned server, an enabled X11 flag.
- **yellow**: an outcome that needs attention but did not fail. A cancelled
  import, a missing key, a non-zero post-connect hook.
- **red**: an outcome that failed. A missing binary, a refused command line,
  a broken jump-host reference.
- **bold**: the value that the row is about. The server name, the count in a
  confirmation prompt.
- **dim**: context. The id column, the last-used column, the notes column,
  the paths in parentheses.
- **blue**: counts and specifications. The number of port forwards, the
  environment pairs, the forward list on a card.
- **magenta**: tags, and nothing else.

### Landing page

The house tokens, from `docs/style.css`. The dark set is the primary one,
because a reader who lands on the page is usually next to a terminal.

- **Warm ground** (`#1d2021`, `#fbf1c7` in light): the page.
- **Warm ink** (`#ebdbb2`, `#3c3836` in light): the text.
- **Surface** (`#282828`, `#f2e5bc` in light): code blocks, cards, table
  cells.
- **Muted** (`#a89984`, `#665c54` in light): body copy inside a section and
  the small print.
- **Rule** (`#504945`, `#d5c4a1` in light): every border, the one pixel
  under the header and above the footer.
- **Ok** (`#b8bb26`, `#5f5f0e` in light): a status that passed.
- **Danger** (`#ff8a7a`, `#cc241d` in light): a status that failed.
- **Info** (`#83a598`, `#076678` in light): the prompt in a terminal
  transcript.

### Rules

**The meaning of a color is fixed.** A green that means "success" in the
table cannot mean "the next server in the list" in the card. When a new
output path needs a color, it picks the existing name whose meaning already
matches, and a new name is introduced only with a reason.

**A color never carries information on its own.** Every colored line also
says what it means in words, so a reader who cannot distinguish the hues
loses nothing.

## Typography

**Display Font:** system-ui, -apple-system, Segoe UI, Roboto, sans-serif
**Body Font:** system-ui, -apple-system, Segoe UI, Roboto, sans-serif
**Code Font:** JetBrains Mono, ui-monospace, SFMono-Regular, Menlo, monospace

In the terminal there is no type system to speak of. Rich renders in the
terminal's monospace face, and the tool sets weight, color and case, never a
font.

On the landing page:

- **Title**: `clamp(1.9rem, 1.2rem + 2.4vw, 3rem)`, weight 700, line height
  1.15, letter spacing -0.02em. One per page, inside the hero.
- **Section heading**: 1.4rem, weight 700 by default, line height 1.3,
  letter spacing -0.01em.
- **Subheading**: 1.05rem, weight 700, used for a card title and for a third
  level heading.
- **Body**: 16px, weight 400, line height 1.6. A paragraph in a section is
  capped at 70 characters; the hero lede at 60.
- **Label**: 0.78rem, uppercase, letter spacing 0.1em, weight 600. Table
  headers and the small caps labels in the comparison transcripts.
- **Code**: 0.85rem inside a `pre`, line height 1.55, and 0.9em inline.

The two families are the only ones. A third face is a sign that a component
has grown an identity of its own.

## Layout

The landing page is a single column of 1080px with 24px of padding on each
side. The hero is one column, not the two the house stylesheet defines,
because the repository has no screenshot to put in the second column. Every
section after it is separated from the previous one by a one pixel rule and
padded by 24px.

The capability cards are a grid of three columns, two below 900px and one
below 620px. The house `.rail` is an auto-fit grid, which would leave a
single card alone on the last row, so the site sets three columns of its
own. The site navigation disappears below 720px, and the before-and-after
transcripts stack into one column below 860px.

In the terminal the layout belongs to Rich. The server table is a `Table`
with a box, the detail card is a `Panel` around a boxless table, and the
pickers are InquirerPy lists.

## Elevation & Depth

Nothing is lifted. There is no shadow in `docs/style.css`, and the house
stylesheet says so on purpose: on a page read next to a terminal, a shadow
reads as a rendering artifact rather than as depth. Depth comes from tone.
The surface color sits above the ground color, and a one pixel rule carries
the edge.

The terminal has the same rule in a different form. A `Panel` draws a border
around the server card and around the encryption status, and the border
color is the one the content deserves: cyan for a server, green for an
enabled encryption, yellow for a disabled one, red for a warning.

## Shapes

One radius, 6px, for everything: buttons, code blocks, keyboard hints, status
tags, table wrappers, cards, images and the focus ring. There is no second
radius and no pill.

Borders are one pixel and always use the rule color. The focus ring is a
2px outline in the ink color with a 2px offset, so it is visible on both the
ground and the surface.

The terminal has no shapes of its own. Rich's box characters are the
terminal's, not the tool's.

## Components

### The server table

The main view, printed by `_print_servers` in `app/cli/_shared.py`.

- **Shape:** a Rich table with a box and a title. No outer radius, because
  there is none.
- **Columns:** ID (dim, first 8 characters), Pin (centred), Name (bold),
  Connection, Auth (centred). Then Via (cyan), Alive (green, right
  aligned), Fwd (blue, right aligned), Last used (dim), Tags (magenta,
  capped at 30 characters) and Notes (dim, capped at 40).
- **Conditional columns:** Via, Alive, Fwd, Last used, Tags and Notes each
  appear only when at least one server has a value for them. A store of four
  plain servers prints four columns.
- **Order:** pinned first, then most recently used, then most used, then
  name. `bssh recent` turns the sort off, so a pinned server keeps its real
  position in time.

### The server card

`bssh view` prints one server in full.

- **Shape:** a Rich `Panel` with a cyan border, `expand=False`, holding a
  table with no header, no box and one column of padding.
- **Fields:** the left column is dim and holds the field name; the right
  column holds the value. The name is bold, the jump chain is cyan, the
  keep-alive and X11 values are green, the environment and the forwards are
  blue, the tags are magenta.
- **Failure:** a broken jump-host reference is printed in red as
  `broken: <reason>` in place of the chain, rather than the row being left
  out.

### The picker

The interactive server list, and the jump-host list inside `bssh add` and
`bssh edit`.

- **Style:** an InquirerPy select with `cycle=True` and `vi_mode=False`, so
  the arrow keys wrap and the type-ahead filter is available.
- **Labels:** each choice shows the server's own display string, name,
  credentials and pin marker. A jump-host choice adds the count of the
  servers that already use it, and the current choice is marked.
- **Escape:** every user string in a label goes through Rich's `escape()`
  first, so a server named `[red]x[/red]` is text and not markup.

### Buttons

On the landing page only. The terminal has no buttons; it has prompts.

- **Shape:** 6px radius, one pixel border, minimum height 38px.
- **Primary:** the ink color as background and the ground color as text, so
  the button reads as an inverted cut-out of the page.
- **Ghost:** transparent background, a rule-colored border, used for the
  secondary action next to the install command.
- **Hover:** the primary button moves to the surface color; the ghost button
  moves its border to the ink color. Both transitions run for 200ms.
- **Focus:** a 2px outline in the ink color with a 2px offset, and the
  radius follows.

### The command block

The install command in the hero.

- **Style:** a `pre` in the code font at 0.85rem, with a surface background,
  a one pixel rule, a 6px radius and 16px of padding. The site's own rule
  makes it an inline-flex row of at least 38px so that the copy control
  beside it lines up with the button.
- **Focus:** the copy control is a real button, so it takes the house font
  and shows a pointer.

### Status tags

Used on the landing page, not in the terminal.

- **Style:** inline-flex, 1px 8px padding, a 1px border in the rule color,
  the code font at 0.72rem, uppercase, letter spacing 0.08em, in the muted
  color.
- **Variants:** `tag-ok` in the ok color, `tag-warn` in the info color,
  `tag-bad` in the danger color. The border takes the same color as the
  text.

## Do's and Don'ts

### Do:

- **Do** pick the Rich style name that already means what the line means.
  Green for an outcome that worked, red for one that did not.
- **Do** escape every user-provided string before it reaches Rich. Names,
  hosts, notes, tags and the printed command line all go through
  `escape()`.
- **Do** hide a column when no row has a value for it.
- **Do** put the site's own rules at the end of `docs/style.css`, under a
  comment saying what they are for.
- **Do** use the token names in the stylesheet. A literal hex inside a rule
  is a second source of truth.

### Don't:

- **Don't** introduce a hex value into the terminal output. The terminal
  theme decides the color.
- **Don't** use a color to decorate a value that has no state attached to
  it.
- **Don't** add a second radius, a second spacing step or a third typeface
  to the landing page.
- **Don't** add a shadow. Depth is tone.
- **Don't** change the shared house rules in `docs/style.css`. A site that
  edits them cannot be restyled by the next person.
