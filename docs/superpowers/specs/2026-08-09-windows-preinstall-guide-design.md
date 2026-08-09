# Windows native-lite Pre-Extraction Guide Design

## Goal

Provide a Chinese plain-text operations guide that can be opened from the
mobile disk before the deployment ZIP is extracted. The guide must take an
operator from media receipt through checksum verification, LM Studio
preparation, extraction, installation, startup, and first diagnostics without
requiring access to files inside the ZIP.

## Deliverables

- Source document: `deploy/windows-standalone/PRE_INSTALL_GUIDE.txt`.
- Generated handoff document:
  `deploy/windows-standalone/out/GIS-Data-Agent-Windows-native-lite-PRE-INSTALL.txt`.
- The mobile-disk handoff becomes exactly three files: the ZIP, its `.sha256`,
  and the external pre-install guide.
- The generated `out` document remains ignored by Git, while the source
  document, builder behavior, tests, and updated README are committed.

## Build Behavior

After a bundle build reaches `ready`, the builder copies the source guide next
to the ZIP. The output filename is derived from the ZIP stem by appending
`-PRE-INSTALL.txt`. The generated text uses UTF-8 with BOM so Windows
PowerShell 5.1 and older Notepad versions display Chinese correctly.

The guide is generated only for a successful build. A blocked build must not
create or refresh a handoff guide that could be mistaken for a valid release.
The guide does not hard-code the ZIP hash; it instructs the operator to compare
the ZIP against the accompanying `.sha256`, which is generated after the ZIP.

## Guide Contents

The document contains these sections in operational order:

1. The exact three files that must be present on the mobile disk.
2. Supported host assumptions, administrator PowerShell, disk-space and path
   preparation, and the no-Docker boundary.
3. LM Studio prerequisites: `/v1` base URL, exact Qwen model ID, exact
   embedding model ID, optional API key, host reachability, and mandatory
   768-dimensional embeddings.
4. A fail-closed external SHA-256 verification command. A mismatch instructs
   the operator to stop without extracting.
5. Exact extraction and `Set-Location` commands for bundle version
   `23.0.0-windows-standalone.2-native-lite`.
6. The complete `install_offline_bundle.ps1` command using environment-based
   API-key handling.
7. Task registration, startup, URLs, database password locations, and
   diagnostics paths.
8. Explicit statements that no external
   `natural_resource_standard_contracts.json`, Ollama, Gemma4, or text
   embedding weights are required.
9. Stop conditions for checksum mismatch, unreachable LM Studio, wrong model
   IDs, non-768 embeddings, insufficient disk, or an unsupported host.

## Error Handling

- Hash mismatch: do not extract; recopy both ZIP and `.sha256` from the
  approved media source.
- Missing or unreachable LM Studio dependency: do not start installation.
- Existing non-empty install or staging path: use a new directory unless an
  approved upgrade procedure supplies the existing PostgreSQL password.
- Installer exit code `2`: inspect the generated preflight and bundle
  verification reports before attempting startup.

## Verification

- A regression test first proves that the builder does not yet expose the
  pre-install guide helper/output.
- Tests verify the generated filename, UTF-8 BOM, and required operational
  phrases and commands.
- The existing Windows bundle regression tests and PowerShell 5.1 parser checks
  remain green.
- Rebuild the full native-lite ZIP, confirm the external guide exists beside
  it, recompute the ZIP `.sha256`, extract the ZIP, and rerun artifact
  verification.

## Scope Boundary

This change does not add middleware, alter the ZIP payload profile, or claim
support for an unverified Windows version. It only makes the already-defined
native-lite deployment workflow available before extraction and keeps that
handoff document synchronized with future builds.
