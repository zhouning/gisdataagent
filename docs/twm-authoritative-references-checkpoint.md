# TWM authoritative references checkpoint

Date: 2026-06-19

## What is done

- Read `docs/twm-authoritative-references.md`.
- Extracted 46 reference items from the table.
- Confirmed the task is a literature collection / Zotero-attachment workflow, not a pure citation formatting task.
- Checked local repo for existing reference files and verified there are already several partial BibTeX sources we can reuse.

## Verified access

- `pubmed.ncbi.nlm.nih.gov` reachable.
- `api.crossref.org` reachable at the HTTP level.
- `arxiv.org/pdf/...` reachable.
- `proceedings.mlr.press/...pdf` reachable.
- `openreview.net/pdf?id=...` reachable.
- `openaccess.thecvf.com/...pdf` reachable.
- `nature.com` article pages reachable, but PDF access varies by article and redirect chain.

## Known blockers

- `api.openalex.org` DNS resolution failed in the current shell.
- `api.unpaywall.org` DNS resolution failed in the current shell.
- Some references are books / standards / paywalled journal articles, so not every item will have a legal public PDF.

## Reusable local sources already found

- `arcgis-farmland-mpc/paper/references_v6.bib`
- `arcgis-farmland-mpc/paper/references_v6_codex.bib`
- `alphaearth-training-system/submission/paper12_isprs_jprs_20260606/02_latex_source/references.bib`
- `paper10-geojepa-mpc-farmland-layout/references/paper10_verified_references_2026-06-09.bib`
- `paper10-geojepa-mpc-farmland-layout/references/paper10_local_sources_2026-06-09.bib`
- `farmland-drl-optimization/manuscript/references.bib`

## Best next step

1. Normalize the 46 items into a machine-readable list of titles / DOIs / arXiv IDs.
2. Batch-download all openly accessible PDFs.
3. Save citation files (`.ris` and/or `.bib`) beside the PDFs for Zotero import.
4. Separate out non-downloadable items into a metadata-only list.

## Handoff note

Continue from this checkpoint and treat `docs/twm-authoritative-references.md` as the source of truth for scope. The current workspace is already dirty from other user work; do not revert unrelated changes.

## Resume instructions for the next window

Use this file as the restart point.

- Source of truth: `docs/twm-authoritative-references.md`
- Saved progress: 46 reference items have already been extracted from the table.
- Verified access so far: PubMed, CrossRef, arXiv PDFs, PMLR PDFs, OpenReview PDFs, CVF Open Access PDFs, and some Nature article pages.
- Known blockers: OpenAlex and Unpaywall DNS resolution failed in the current shell.
- Local reuse sources already identified: the BibTeX files listed above.
- Zotero target root already available: `/Users/zhouning/Zotero/`

Continue with this sequence:

1. Normalize the 46 references into a machine-readable list with title, year, venue, DOI, arXiv ID, and best access URL.
2. Download all legally accessible PDFs into the Zotero attachment area.
3. Generate `.ris` and/or `.bib` sidecar files for Zotero import.
4. Split out items that are books, standards, or paywalled into a metadata-only list.
5. Verify counts and attachment placement before finishing.

Working rules:

- Do not touch unrelated dirty changes in the repo.
- Prefer existing local BibTeX sources before searching externally.
- Use `curl`/direct source checks when Python fetches or DNS lookups are unreliable.
