# Hugging Face Preflight and Direct Selection Plan

**Goal:** Make adding a freely available Hugging Face model to a comparison safe, direct, reproducible, and understandable.

**Architecture:** A deterministic backend preflight service resolves Hub metadata to an immutable commit and returns an executability verdict. A separate pinned installer downloads only the selected runtime artifact family without allocating it. React preserves full model specifications through the Hub browser and comparison draft, while the existing comparison store persists the resolved revision.

**Tech stack:** Python, FastAPI, huggingface_hub, MLX, Transformers, React, TypeScript, WebSockets, pytest, Vite

## 1. Preflight contract

- [x] Resolve requested revisions to immutable Hub commit SHAs.
- [x] Classify public, authorized, token-required, and denied access by probing a pinned artifact when a token is configured.
- [x] Check text-generation task, causal architecture, custom-code requirements, supported weight family, and local runtime availability.
- [x] Select one runnable weight family and avoid double-counting alternate formats.
- [x] Estimate peak memory against the post-unload sequential runtime budget and return `fits`, `tight`, `too_large`, or `unknown`.
- [x] Measure missing pinned artifacts against free disk with download headroom before installation.
- [x] Classify the exact revision cache as `missing`, `partial`, or `complete`.
- [x] Expose structured actionable errors and retryability through `POST /models/preflight`.

## 2. Revision-aware runtime

- [x] Add revision identity to `ModelInfo` and the already-loaded check.
- [x] Forward revision through REST loading and progress WebSockets.
- [x] Forward revision to MLX cache lookup/load and Transformers processor/model loading.
- [x] Execute restored comparisons with the revision persisted in their ordered lineup.
- [x] Include revision in current-model and terminal progress payloads.

## 3. Pinned installation

- [x] Build an exact install artifact plan from preflight metadata.
- [x] Add `/ws/models/install` for cache installation without runtime allocation.
- [x] Require the submitted revision to match the immutable preflight result.
- [x] Verify exact-revision cache completeness after download.
- [x] Verify the same exact artifact plan used for installation, including sharded-weight indexes.
- [x] Keep install progress durable across frontend navigation.
- [x] Key every transfer by model, backend, and revision; retain a blocking state when the user stops watching uncancellable backend work.

## 4. Direct comparison selection

- [x] Preserve `{model_id, backend, revision}` in the draft lineup.
- [x] Open Hub directly in an explicit add-to-comparison mode.
- [x] Show a persistent selected-lineup tray and return-to-comparison action.
- [x] Run preflight in model details with an editable branch/tag/commit field.
- [x] Show access, runtime, weights, memory fit, cache status, and pinned commit before action.
- [x] Add or remove a model without losing the rest of the draft lineup.
- [x] Disable comparison execution while a selected install is pending or failed.
- [x] Route Hub card actions through preflight instead of direct loading.
- [x] Ignore stale preflight and search responses when newer requests have superseded them.
- [x] Make model drawers and Hub disclosure dialogs keyboard-modal with focus restoration.

## 5. Cache and credential correctness

- [x] Exclude metadata-only Hub entries from the downloaded library.
- [x] Fetch model cards without creating false local installations.
- [x] Stop details size from summing duplicate weight formats.
- [x] Prevent masked API-token placeholders from overwriting real secrets.
- [x] Correct the Hub trending sort key.
- [x] Restrict browser REST and WebSocket access to trusted Vite and Tauri origins.
- [x] Replace the incompatible legacy recommendations with live-verified, public MLX text-generation models.

## 6. Verification

- [x] Add preflight, cache, installer, revision propagation, endpoint, and settings regression tests.
- [x] Pass the complete Python test suite.
- [x] Pass full frontend ESLint.
- [x] Pass the TypeScript and Vite production build.
- [x] Exercise the complete Hub selection flow in the running desktop UI.

### Live QA record

- Installed `HuggingFaceTB/SmolLM2-135M-Instruct` from Hub after preflight resolved `main` to commit `12fd25f77366fa6b3b4b768ec3050bf629380bac`.
- Added cached `Qwen/Qwen2.5-0.5B-Instruct` after preflight resolved it to commit `7ae557604adf67be50417f59c2c2f167def9a775`.
- Executed one shared prompt against both pinned models and received independent responses with timing and token metadata.
- Repeated the full setup as a brand-new comparison after immutable-revision enforcement and confirmed creation, execution, and restoration still succeed.
- Started a new comparison, reopened the saved comparison from project history, and verified both exact revisions and responses were restored.
- Confirmed an incompatible GGUF-only repository is blocked with an actionable explanation and no install action.
- Confirmed a configured token without accepted Llama terms reports `denied`, shows disk and memory estimates, and exposes no install action.
- Confirmed the three packaged MLX recommendations render as runnable catalog defaults.
- Confirmed Escape closes the model dialog and restores focus to its triggering card action.
- Confirmed the browser console contained no warnings or errors after the flow.

### Automated verification record

- `python3.11 -m pytest -q`: 293 passed, 2 dependency deprecation warnings.
- `npm run lint`: passed with zero ESLint findings.
- `npm run build`: TypeScript and Vite production build passed.
