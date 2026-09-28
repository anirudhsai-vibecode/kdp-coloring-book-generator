# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0.0] - 2026-09-28

### Added
- Initial release of KDP Coloring Book Generator
- CLI tool for generating print-ready KDP coloring books
- Cloudflare Workers AI (FLUX.1-schnell) integration with multi-account rotation
- Theme system with theme-lock enforcement (pets, garden, animals, etc.)
- Hard QA gates: canvas 2550×3300, pure B&W, 0.5" margins, no solid fills
- PDF interior and full-wrap cover generation with KDP-compliant spine calculation
- User review gate (`--require-user-review`) for manual approval before packaging
- Failed_dump archiving for QA failures with manifest tracking

### Changed
- N/A (initial release)

### Fixed
- N/A (initial release)

### Security
- Multi-account Cloudflare credential rotation on quota exhaustion (HTTP 429/4006)
- No API tokens committed to repository (environment variables only)