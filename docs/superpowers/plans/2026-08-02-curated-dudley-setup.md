# Curated Dudley Setup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the legacy Dudley setup wrappers with one curated default/AI dispatcher, disable Homebrew ask mode, and repair update routing on systems without rpm-ostreed.conf.

**Architecture:** `dsb-common` ships two explicit Brewfiles and one `ujust dudley` dispatcher. A small non-user-facing helper owns idempotent Homebrew environment configuration so its file behavior can be tested directly. Existing payload contract tests verify manifests, routing, and the update guard.

**Tech Stack:** Just, Bash, Homebrew Brewfiles, Python unittest, JSON payload contract

## Global Constraints

- Expose only `ujust dudley`, `ujust dudley ai`, and `ujust dudley info` as Dudley setup recipes.
- Use `brunoborges/tap/ghx`; do not install `gh`, `podman`, or `podman-compose`.
- Use `kubernetes-cli` as the sole provider of `kubectl`.
- Preserve all unrelated `~/.homebrew/brew.env` settings while enforcing `HOMEBREW_NO_ASK=1`.
- Keep Docker engine and group policy out of `dsb-common`.

---

### Task 1: Encode the curated payload contract

**Files:**
- Modify: `tests/test_payload_contract.py`
- Create: `system_files/dudley/usr/share/ublue-os/homebrew/dudley-default.Brewfile`
- Modify: `system_files/dudley/usr/share/ublue-os/homebrew/dudley-ai.Brewfile`
- Delete: `system_files/dudley/usr/share/ublue-os/homebrew/dudley-cli.Brewfile`
- Delete: `system_files/dudley/usr/share/ublue-os/homebrew/dudley-dev.Brewfile`
- Delete: `system_files/dudley/usr/share/ublue-os/homebrew/dudley-fonts.Brewfile`
- Delete: `system_files/dudley/usr/share/ublue-os/homebrew/dudley-ide.Brewfile`
- Delete: `system_files/dudley/usr/share/ublue-os/homebrew/dudley-k8s.Brewfile`
- Modify: `contract/dudley-payload.v1.json`
- Create: `system_files/dudley/usr/share/dudley/homebrew-profiles.json`

**Interfaces:**
- Consumes: Homebrew Brewfile syntax and the existing payload contract schema.
- Produces: `/usr/share/ublue-os/homebrew/dudley-default.Brewfile` and `dudley-ai.Brewfile`.

- [ ] **Step 1: Write failing contract tests** asserting the two-file manifest set, required tools, forbidden tools, unique Kubernetes CLI provider, and loading the `joshyorko/tools` classifications from the shipped profile-policy config.
- [ ] **Step 2: Run `python3 -m unittest tests.test_payload_contract -v`** and verify the new assertions fail because the legacy manifests and missing tap packages remain.
- [ ] **Step 3: Create the two curated Brewfiles and update the JSON contract** with the exact package classifications from the approved design.
- [ ] **Step 4: Re-run `python3 -m unittest tests.test_payload_contract -v`** and verify the manifest tests pass.
- [ ] **Step 5: Commit** with `feat: curate Dudley Homebrew profiles`.

### Task 2: Collapse the command surface and configure Homebrew

**Files:**
- Modify: `tests/test_payload_contract.py`
- Modify: `system_files/dudley/usr/share/ublue-os/just/60-dudley.just`
- Create: `system_files/dudley/usr/libexec/dudley/configure-homebrew-no-ask`
- Modify: `contract/dudley-payload.v1.json`
- Modify: `README.md`

**Interfaces:**
- Consumes: the two curated Brewfiles and `/usr/bin/dudley-build-info`.
- Produces: `ujust dudley [ai|info]` and an idempotent helper that updates `${HOME}/.homebrew/brew.env`.

- [ ] **Step 1: Write failing tests** for the visible recipe set, profile routing, rejected targets, and helper preservation/idempotence.
- [ ] **Step 2: Run `python3 -m unittest tests.test_payload_contract -v`** and verify failures identify the legacy wrappers and missing helper.
- [ ] **Step 3: Implement the helper and minimal dispatcher**; initialize `ujust bluefin-cli` only if `brew` is absent, run `dudley-default.Brewfile` plus the VS Code hook for default, run `dudley-ai.Brewfile` for AI, and show manifests for info.
- [ ] **Step 4: Update README and payload contract, then re-run tests** until the complete suite passes.
- [ ] **Step 5: Commit** with `feat: simplify Dudley setup command`.

### Task 3: Guard rpm-ostree configuration lookup

**Files:**
- Modify: `tests/test_payload_contract.py`
- Modify: `system_files/dudley/usr/share/ublue-os/just/update.just`

**Interfaces:**
- Consumes: `/etc/rpm-ostreed.conf` only when present.
- Produces: Fedora unlocked-layering routing to `rpm-ostree upgrade`; all other systems route to `sudo bootc upgrade` without grep errors.

- [ ] **Step 1: Write a failing structural regression test** requiring `[[ -f /etc/rpm-ostreed.conf ]]` before the grep expression.
- [ ] **Step 2: Run the targeted unittest** and verify it fails on the unconditional grep.
- [ ] **Step 3: Add the file-existence guard** to the update recipe.
- [ ] **Step 4: Run the full unittest suite and repository validation commands** from `AGENTS.md`, plus `git diff --check`.
- [ ] **Step 5: Commit** with `fix: guard rpm-ostree update detection`.

### Task 4: Publish and merge

**Files:**
- No source changes expected.

**Interfaces:**
- Consumes: a green feature branch and GitHub checks.
- Produces: a merged `dsb-common` PR and a published `ghcr.io/joshyorko/dsb-common:latest` image.

- [ ] **Step 1: Push `patchraptor/curate-dudley-setup` and open a PR against `main`.**
- [ ] **Step 2: Monitor all required checks to terminal success.**
- [ ] **Step 3: Merge the PR using the repository-supported merge method.**
- [ ] **Step 4: Verify the main publish workflow completes successfully.**
- [ ] **Step 5: Stop before changing the `dudley-os` dsb-common digest; Patchraptor owns that update.**
