# Changelog

All notable changes to **video-studio** are documented here
(format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), versions: [SemVer](https://semver.org/)).

## [Unreleased]

### Added
- feat(api): add FastAPI HTTP API, MCP server, Web UI, and tool configs (TASK-008) (`TASK-008`, by `@antigravity`)
- feat(render): integrate edge-tts dual TTS and pnpm HyperFrames HTML rendering (TASK-009) (`TASK-009`, by `@antigravity`)
- feat(web): add notebooklm-batch-studio style Web UI, full settings, and agy chat planner (TASK-010) (`TASK-010`, by `@antigravity`)
- feat(ui): add voice language settings, toast stack, collapsible dock, and WYSIWYG layout guides (by `@Antigravity`)
- feat(studio): add AI script drafting, bilingual subtitles, and dual-engine Avatar presenter (Route A & B) (by `@Antigravity`)
- feat(studio): add 10s Avatar A/B preview, 10s prosody A/B/C preview, and word-level prosody tags (by `@Antigravity`)
- feat(studio): add visual prosody highlight editor, immutable original script preservation, and agy-cli model selection (by `@Antigravity`)
- feat(ui): expose OLLAMA_MODEL and SADTALKER_DIR in Web UI env settings (by `@Antigravity`)
- feat(ai): make agy-cli primary brain for script drafting and bilingual translation with Ollama fallback (by `@Antigravity`)
- feat(ui): support batch multi-file upload to job input/ (by `@Antigravity`)
- feat(ui): add drag-drop multi-file upload queue and prominent input file chips (by `@Antigravity`)
- feat(script): include input/ directory and uploaded files in agy script draft prompt (by `@Antigravity`)

### Changed
- refactor(adapters): migrate and conform openwebui tool and runner (TASK-001) (`TASK-001`, by `@antigravity`)
- refactor(services): conform services layer to architecture and typing standards (TASK-002) (`TASK-002`, by `@antigravity`)
- refactor(templates): move templates and configs, remove legacy directory and starter greeting (TASK-004) (`TASK-004`, by `@antigravity`)
- ci: install ffmpeg in GitHub Actions runner for video workflows (by `@antigravity`)
- refactor(quality): resolve Code Review Guard warnings and ignore graphify-out (TASK-007) (`TASK-007`, by `@antigravity`)

### Fixed
- fix(overlay): fallback to load_default font and install fonts-noto-cjk in CI (by `@antigravity`)
- fix(studio): ignore empty-workspace hint in job dropdown and return 404 on missing job (by `@Antigravity`)

### Documentation
- docs: migrate design specs and update project architecture documentation (TASK-003) (`TASK-003`, by `@antigravity`)
- docs: update and synchronize all project markdown documentation, adrs, and known issues (TASK-006) (`TASK-006`, by `@antigravity`)
- docs(standards): sync web app and architecture rules from template (by `@antigravity`)

### Testing
- test: add comprehensive end-to-end workflow tests for all services (TASK-005) (`TASK-005`, by `@antigravity`)

### Chore
- chore(migration): finalize migration and complete verification (by `@antigravity`)
- chore: update framework to v3.4.0 (by `@antigravity`)
- chore(framework): sync framework updates and add project-auditor skill (by `@antigravity`)
- chore(framework): sync framework updates and pass agentctl check (by `@antigravity`)

## [0.1.0] - 2026-10-22
### Added
- Initial project scaffold (framework v3.3.0).
