# UWM Customer Demand Phase 0 Integration

Date: 2026-07-10

## Source Branches

- Integration branch: `feat/v12-extensible-platform`
- Requirement worktree: `.worktrees/uwm-livability-requirement-split`
- Requirement branch head before integration: `e1ea8c9`
- Mobility-aware UWM head before design commit: `1d5e924`

## Preservation

- Status: `/private/tmp/uwm-livability-requirement-split-2026-07-10-status.txt`
  - SHA-256: `6b12d3a240b1a8b898a33dee4bfd044e79dd01d40602f1b55c6af7f611c6cce7`
- Patch: `/private/tmp/uwm-livability-requirement-split-2026-07-10.patch`
  - SHA-256: `a32454aa569c37aa93316b7cc6e7c5ccece2ee30158936e25c54e8b47f9fe186`
- Source archive: `/private/tmp/uwm-livability-requirement-split-2026-07-10-files.tar.gz`
  - SHA-256: `c38927bbc20c99d2d23c8aacf4328e721f674425db3f044f3024a49f67b917d9`

`/private/tmp` is non-persistent temporary storage. The operating system or a
cleanup process may remove these files without notice. Copy all three
preservation artifacts to durable storage before relying on them for recovery.

## Source Archive Manifest

The source archive contains exactly these eight files:

```text
data_agent/uwm/livability_requirement_registry.py
data_agent/test_uwm_livability_requirement_registry.py
data_agent/test_uwm_ai_demand_readiness_routes.py
data_agent/test_uwm_ai_demand_readiness_frontend_contract.py
frontend/src/components/datapanel/AiDemandReadinessTab.tsx
frontend/src/components/datapanel/LivabilityWorldModelTab.tsx
frontend/src/components/datapanel/TraditionalLivabilityTab.tsx
frontend/src/styles/layout.css
```

The binary-safe patch records all tracked modifications reported by the saved
status, including tracked files not present in the eight-file source archive.
Untracked entries shown in the saved status are not represented by `git diff`
and are not recoverable from the patch. Only the eight files listed above are
recoverable from the source archive.

## Verification Commands

Run these commands before using any preservation artifact:

```bash
printf '%s  %s\n' \
  '6b12d3a240b1a8b898a33dee4bfd044e79dd01d40602f1b55c6af7f611c6cce7' \
  '/private/tmp/uwm-livability-requirement-split-2026-07-10-status.txt' \
  'a32454aa569c37aa93316b7cc6e7c5ccece2ee30158936e25c54e8b47f9fe186' \
  '/private/tmp/uwm-livability-requirement-split-2026-07-10.patch' \
  'c38927bbc20c99d2d23c8aacf4328e721f674425db3f044f3024a49f67b917d9' \
  '/private/tmp/uwm-livability-requirement-split-2026-07-10-files.tar.gz' \
  | shasum -a 256 -c -

tar -tzf /private/tmp/uwm-livability-requirement-split-2026-07-10-files.tar.gz
```

The checksum command must report `OK` for all three artifacts. The archive
listing must match the eight-file manifest exactly.

## Safe Patch Recovery

Do not apply the patch to the integration branch or to the existing dirty
requirement worktree. Recover into a new detached worktree based on the saved
requirement branch head, verify the patch first, and only then apply it:

```bash
recovery_dir=/private/tmp/uwm-livability-requirement-split-recovery

git worktree add --detach "$recovery_dir" e1ea8c9
git -C "$recovery_dir" status --short
git -C "$recovery_dir" apply --check --binary \
  /private/tmp/uwm-livability-requirement-split-2026-07-10.patch
git -C "$recovery_dir" apply --binary \
  /private/tmp/uwm-livability-requirement-split-2026-07-10.patch
git -C "$recovery_dir" status --short
```

The first status command must be empty. Stop without applying if checksum
verification or `git apply --check` fails. These commands are recovery
instructions only; no recovery was performed while preparing this report.

## Integration Rule

The requirement branch is implementation input, not a blind merge. The
canonical registry follows the confirmed one-primary-route design and retains
the mobility-aware UWM exports already present on the integration branch.
