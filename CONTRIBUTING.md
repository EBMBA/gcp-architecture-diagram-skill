# Contributing

Thanks for helping improve the skill. Issues and pull requests are welcome.

## Setup

```bash
git clone https://github.com/EBMBA/gcp-architecture-diagram-skill
cd gcp-architecture-diagram-skill
python3 skills/gcp-architecture-diagram/scripts/gcp_drawio.py fetch      # downloads Google's icon packs to ~/.cache
python3 -m unittest discover -s tests
```

No dependencies beyond the Python 3.9+ standard library.

The installable skill is **`skills/gcp-architecture-diagram/`** only (that folder is what users get). Keep repo-only files
(docs, tests, CI, images) outside it; CI fails if anything else appears there. Paths below are relative
to the skill folder unless they start with the repo root. Exports need
[draw.io desktop](https://github.com/jgraph/drawio-desktop/releases).

## Common contributions

### Add or fix a product in the icon map

1. Find the product's category in Google's icon guide
   (https://services.google.com/fh/files/misc/google-cloud-product-icons.pdf). Products marked with `*`
   are core products with their own icon.
2. Edit `references/icon-map.json`: `label`, `category`, `"core": true` if it has a core icon,
   `legacy` = file stem in the legacy pack (e.g. `cloud_run` for `cloud_run.svg`), optional `aliases`.
3. Run `python3 scripts/gcp_drawio.py fetch` (reports any file it cannot find) and
   `python3 scripts/gcp_drawio.py docs` to regenerate `references/icons.md`.
4. Check the rendering:
   `python3 scripts/gcp_drawio.py sheet -o sheet.drawio && python3 scripts/gcp_drawio.py export sheet.drawio`.

### Improve layout rules or the validator

- Rules the agent must follow live in `SKILL.md`; keep it concise and concrete (checkable rules, not
  "make it look nice").
- Whatever can be checked mechanically belongs in `validate_tree()` in `scripts/gcp_drawio.py`, with a
  unit test in `tests/`.
- Validate a change against real output: build and export the examples, and attach before/after PNGs to
  the PR.

### Add an example

Add the **source** diagram (`name.src.drawio`, placeholders, before `build`) and its companion `.md` to
`examples/`, and its rendering to the repo's `docs/images/name.png`. Examples must build with zero
warnings (a test enforces it).

## Rules

- **Never commit Google Cloud icon files** (SVG/PNG from the official packs). They are downloaded by
  `fetch`. Rendered diagrams (PNG) in `docs/images/` are fine.
- Keep the script dependency-free (standard library only).
- Update `CHANGELOG.md` under *Unreleased*.
