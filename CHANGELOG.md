# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.2.0] - 2026-10-19

### Changed
- The skill now lives in `skills/gcp-architecture-diagram/`: installing it no longer copies the
  repository's docs, tests and CI. Rendered examples moved to `docs/images/`.
- Manual install: symlink `skills/gcp-architecture-diagram` instead of cloning into the skills folder.

### Added
- CI check that the skill folder only contains what the skill needs.

## [0.1.0] - 2026-10-16

### Added
- `SKILL.md`: workflow, icon modes, placeholder styles, GCP boundaries, layout and edge rules,
  audience modes, self-check.
- `scripts/gcp_drawio.py`: `fetch`, `build`, `validate`, `export`, `list`, `sheet`, `docs`.
- Icon map for 150+ products, following Google's 2025 icon system (core + category icons), with a
  `legacy` mode using the pre-2025 per-product icons.
- Layout validator: duplicate IDs, floating edges, overlapping icons, edges through icons or labels,
  edge labels on group borders, more than one bend, near-miss alignment, overlapping edges, children
  outside their container.
- Examples: `web-app` (Cloud Run), `gke-hybrid` (GKE + Cloud Interconnect) and `hub-and-spoke`
  (Network Connectivity Center, multi-project, VPC Service Controls, legacy icons).
- Reference: Shared VPC and hub-and-spoke (NCC, VPC peering) drawing rules.
- Validator also flags edges crossing a group title and labels sticking out of their group.
- `name.src.drawio` → `name.drawio` build convention, so the source is never hand-edited after build.
- Reference on GCP resource hierarchy and network boundaries.
- Generic shapes from Material Symbols (user, browser, server, internet…).
- Example diagram, unit tests, CI.

[Unreleased]: https://github.com/EBMBA/gcp-architecture-diagram-skill/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/EBMBA/gcp-architecture-diagram-skill/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/EBMBA/gcp-architecture-diagram-skill/releases/tag/v0.1.0
