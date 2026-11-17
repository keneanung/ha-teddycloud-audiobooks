# Publish as a standalone Marketplace repository

This is a standalone Git repository at `~/git/teddycloud-audiobooks`.
The household deployment configuration remains in the separate `homeDeployment`
repository.
The public repository is `keneanung/ha-teddycloud-audiobooks`. The manifest URLs
and codeowner target that location. Releases and catalog submission are separate
steps.

1. Publish **only this directory's contents at repository root** to a public
   GitHub repository. Do not publish household configuration, backups or media.
   Set a description and topics (for example home-assistant, marketplace,
   teddycloud, audiobook), enable issues, and retain the MIT license.
2. Ensure `.github/workflows/validate.yml` runs from that repository root.
   HACS validation and hassfest must pass without ignored checks. The first published run identified missing repository description/topics and
   unsorted manifest keys; ensure the corrected revision passes. Local/runtime
   tests are a separate check.
3. Resolve any upstream-validator findings, then make a GitHub release matching
   `manifest.json` version `0.1.0`. A tag alone is not sufficient for catalog
   inclusion. The normal repository layout does not require a release ZIP.
4. Install via Marketplace's custom repository URL and verify download/update
   on a disposable HA installation before inviting wider use. Installation
   still requires YAML configuration; there is no configuration-flow UI.
5. Catalog listing is optional. After checks and a full release pass, the owner
   can submit the repository to the `integration` list in `hacs/default`.
   This is separate from custom-repository installability.

The tree includes one `custom_components/<domain>` directory, README,
`hacs.json`, versioned manifest with documentation/issues/codeowners, local
`brand/icon.png`, license and validation workflow, matching the documented
Marketplace/HACS integration repository structure.

Official references checked 2026-11-17:

- [Repository structure](https://contributors.home-assistant.io/marketplace/reference/repository-structure/)
- [Catalog requirements](https://contributors.home-assistant.io/marketplace/guides/catalog/)

Marketplace replaces HACS in HA 2026.11. The compatible `hacs.json` name and
`hacs/action` validator remain part of the publishing format.
