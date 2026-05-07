# Cross-Repo Development Workflow Guideline

## Background

As part of the CI consolidation effort, all CI validation and merge gating have been migrated from the `potpie` repository into the `pydantic-deepagents` repository.

Going forward:

* The `potpie` repository CI is no longer used as the primary PR merge gate.
* All PR validation is enforced through the `merge-gate-tests` workflow in `pydantic-deepagents`.
* The `merge-gate-tests` workflow validates whether `pydantic-deepagents` is using the latest commit from `potpie/main`.

Because of this dependency relationship, contributors must ensure that changes across both repositories remain properly aligned.

---

# Repository Relationship

```text
pydantic-deepagents
└── code-graph-providers/potpie
```

The `pydantic-deepagents` repository is now the source of truth for integration validation and PR merge gating.

---

# Development Workflow

## Scenario 1 — Changes Only Affect pydantic-deepagents

If your changes do not require modifications in `potpie`:

1. Create a PR in `pydantic-deepagents`
2. Run the normal CI flow
3. Merge after all required checks pass

No additional synchronization is required.

---

# Scenario 2 — Changes Affect Both Repositories

If your feature or fix requires changes in both:

* `potpie`
* `pydantic-deepagents`

then the following workflow MUST be followed.

---

## Step 1 — Create the potpie PR

Create a PR in `potpie` containing the required changes.

At this stage:

* The PR does NOT need to be merged yet.
* The PR branch may still be under development.

---

## Step 2 — Create the pydantic-deepagents PR

Create a PR in `pydantic-deepagents` that references the corresponding `potpie` PR.

The PR description should clearly indicate:

* which `potpie` PR it depends on
* why the dependency exists
* whether any temporary CI failures are expected

Example:

```text
Depends on potpie PR #123
```

---

## Step 3 — Run merge-gate-tests

Run the normal `merge-gate-tests` workflow in `pydantic-deepagents`.

At this stage, the workflow is expected to validate:

* integration behavior
* end-to-end compatibility
* CI correctness
* graph provider functionality
* vector/logging infrastructure
* ports allocation behavior

---

## Step 4 — Merge the potpie PR

If all checks pass EXCEPT:

```text
Check / Potpie submodule SHA matches remote main HEAD
```

then:

1. Merge the `potpie` PR into `main`
2. Wait until the new commit is available on `origin/main`

This failure is expected before the `potpie` PR is merged.

---

## Step 5 — Update the potpie Reference in pydantic-deepagents

Inside `pydantic-deepagents`:

```bash
cd code-graph-providers/potpie
git fetch origin
git checkout main
git pull
```

Then update the parent repository reference:

```bash
cd ../../
git add code-graph-providers/potpie
git commit -m "Update potpie dependency"
```

Push the updated commit to the `pydantic-deepagents` PR branch.

At this point:

```text
Check / Potpie submodule SHA matches remote main HEAD
```

should pass.

---

## Step 6 — Merge the pydantic-deepagents PR

After all checks pass:

1. Merge the `pydantic-deepagents` PR
2. Verify that the final merge gate workflow succeeds

---

# Recommended Commit Order

```text
1. Create potpie PR
2. Create pydantic-deepagents PR and reference the potpie PR
3. Run merge-gate-tests
4. If merge-gate-tests pass and only fail in:
   "Check / Potpie submodule SHA matches remote main HEAD"
   merge the potpie PR
5. Update the potpie reference in pydantic-deepagents and ensure:
   "Check / Potpie submodule SHA matches remote main HEAD"
   passes
6. Merge the pydantic-deepagents PR
```

---

# Important Notes

## The Latest potpie Main Commit Is Required

The merge gate workflow validates whether `pydantic-deepagents` references the latest commit from `potpie/main`.

If the PR references an older `potpie` commit, CI will fail.

---

## Temporary SHA Mismatch Failure Is Expected

Before the `potpie` PR is merged, the following check is expected to fail:

```text
Check / Potpie submodule SHA matches remote main HEAD
```

This is normal behavior during cross-repo development.

---

## Keep Changes Logically Separated

Recommended separation:

### potpie PR

* provider logic
* infrastructure changes
* graph generation
* vector integration
* low-level functionality

### pydantic-deepagents PR

* orchestration
* integration logic
* tests
* workflow wiring
* merge gate updates

This separation improves:

* review clarity
* debugging
* rollback safety
* CI reproducibility

---

# Summary

The `pydantic-deepagents` repository is now the authoritative CI gate for cross-repository validation.

To ensure stable integration behavior:

* create both PRs in parallel when needed
* use `merge-gate-tests` for integration validation
* merge `potpie` only after all other checks pass
* update the `potpie` reference afterward
* ensure both repositories remain synchronized at all times

Failure to follow this workflow may result in:

* merge gate failures
* inconsistent integration behavior
