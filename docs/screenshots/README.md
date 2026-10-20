# Screenshots

`better-ssh` has no screenshots in this folder, and there are no images
anywhere in the repository.

The reason is the interface. The product is a terminal: a Rich table, a
picker, and the line the tool prints before it runs `ssh`. A picture of a
terminal in a repository is a picture of one person's theme, one window
size and one store of servers, and it goes stale the moment the tool
changes a column.

What the repository does carry instead:

- The landing page under `docs/`, which renders the command surface as
  text: the install command, the before-and-after transcripts and the
  capability cards. It is published to
  <https://aa-blinov.github.io/better-ssh/>.
- The command reference in the [README](../../README.md), where every
  command, every flag and every exit code is written out.

If a screenshot is added later, it goes in this folder and is referenced
from the README by a relative path, so it resolves on GitHub and in a local
checkout. The house-style checker verifies that every image reference points
at a file that exists, so a renamed screenshot cannot quietly break the
README.
