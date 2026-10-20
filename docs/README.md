# Documentation

The documents of `better-ssh`, a command-line tool that stores SSH servers
and drives the system `ssh`, `sftp` and `scp` binaries.

| Document | What it covers |
| --- | --- |
| [architecture.md](architecture.md) | How the package is put together, the modules, the data flow and the boundaries. |
| [screenshots/README.md](screenshots/README.md) | Whether the repository carries images, and which ones. |
| [../README.md](../README.md) | The front door: what the tool does, every command, every flag and every exit code. |
| [../AGENTS.md](../AGENTS.md) | The traps, the commands and the rules of the project. |
| [../PRODUCT.md](../PRODUCT.md) | The product truth: who it is for, and what it promises. |
| [../DESIGN.md](../DESIGN.md) | The colors, the type and the components, as the code has them. |

The `docs/` folder also holds the landing page: `index.html`, `style.css`
and `site.js`. It is published to GitHub Pages on every push that touches
it, and it lives at <https://aa-blinov.github.io/better-ssh/>.

## Reading order

New here: [../README.md](../README.md), then
[architecture.md](architecture.md). The README is the manual, and it is long
because the command surface is long.

Changing the code: [architecture.md](architecture.md) first, to see which
module owns what, then [../AGENTS.md](../AGENTS.md) for the traps that cost
a rebuild to learn.

Looking for the reason a change was made: [../PRODUCT.md](../PRODUCT.md).
