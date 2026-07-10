# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

Prior history (before this changelog was introduced) is summarized in the
`git log` — each keyword conversion and bug fix landed as its own commit / PR.

## [Unreleased]

### Added

- `pyproject.toml` with a `k2rad` console entry point and optional
  `[modal]` / `[viz]` extras.
- Contributor scaffolding (LICENSE, CONTRIBUTING, CHANGELOG, PR/issue templates).

### Changed

### Fixed

- `*LOAD_SEGMENT_SET` pressure loads were silently dropped; now converted to
  `/PLOAD`.
