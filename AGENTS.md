# Repository Guide

This package supplies an AHUI Connector through `a13n_harness_ui.connectors`.

- Use Python 3.13 and uv. Keep `uv.lock` synchronized with `pyproject.toml`.
- Write canonical code and documentation in English. Use readable names and focused modules.
- Follow the public AHUI Connector SDK and preserve its account, configuration-version and lifecycle boundaries.
- Use async external I/O with explicit timeouts. Keep network work outside Host transactions.
- Keep credentials in private Host storage. Keep credentials out of declarations, captures, model context and logs.
- Reuse AHUI account management and structured setup rendering.
- Keep changes focused and validate changed behavior through `make check` and relevant integration checks.
- Report validation accurately. GitHub account authorization and live writes require explicit authorization.
- Commit, push, remote repository creation and release actions require user authorization covering that action.
