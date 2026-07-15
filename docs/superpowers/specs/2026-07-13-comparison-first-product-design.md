# Comparison-First LLM Harness Product Design

**Date:** 2026-07-13

## Product decision

LLM Harness becomes a local workbench for running compatible, freely downloadable Hugging Face chat models side by side. Comparison is the default workflow and the durable unit of history; general-purpose agent chat is retained only as legacy functionality during migration.

The initial product remains Apple-Silicon-first and uses the existing MLX and Hugging Face Transformers runtimes. It supports compatible text-generation repositories rather than claiming universal Hugging Face compatibility.

## Current-state evaluation

### Reusable product and technical foundations

- The React/Tauri desktop shell, navigation, theming, and local FastAPI sidecar are a credible base for a focused local-model product.
- The single-model runtime manager already provides the correct resource constraint for local comparison: unload one model, load the next, and execute sequentially.
- MLX and Transformers loaders, Hugging Face cache integration, token settings, and progress WebSockets are reusable infrastructure once model identity includes backend plus immutable revision.
- SQLite sessions/messages are a useful compatibility layer for durable comparison threads; they can be extended rather than replaced.
- Streaming response rendering, model cards, hardware inspection, and the installed-model cache are reusable UI components after being made comparison-aware.
- The legacy CLI and tool loop are useful implementation references and compatibility surfaces, but they should no longer determine the desktop information architecture.

### Baseline product problems the pivot must remove

- The product previously presented general agent chat, tool permissions, model management, and comparison as peers, so no single job was legible as the reason to use it.
- Downloading and loading were one operation. A model card could evict the active runtime merely to make a repository available locally.
- Hub search metadata was treated as proof of compatibility; gated access, wrong weight formats, mutable revisions, and unsupported architectures failed late.
- Model selection was transient and model-ID-only, so reopening a comparison could not guarantee the same weights or runtime.
- History was a flat mix of chats and comparisons, with no project ownership or reusable comparison context.
- The recommended catalog emphasized tool-agent behavior and included models the actual text-only loaders could not run.

### Explicitly out of scope for the focused product

- Tool-enabled agent workflows, iMessage/calendar actions, broad macOS permission management, and autonomous multi-step execution.
- A first-class single-model chat product; legacy chats remain readable but do not receive new product investment.
- Universal execution of every Hub repository, including training checkpoints, arbitrary remote code, unsupported multimodal architectures, and GGUF-only repositories.
- Cloud inference providers, hosted model APIs, fine-tuning, training, and benchmark orchestration.
- Marketplace/social features, team collaboration, and public sharing in the initial local-first product.
- Automatic quality claims based on a model card. The harness records observed runs and user judgments rather than declaring a winner globally.

## Product hierarchy

```text
Harness
├── Projects
│   └── Project
│       ├── Comparison threads
│       │   └── Turns
│       │       └── One response per model
│       ├── Saved lineups
│       └── Project defaults
├── Model Library
│   ├── Installed
│   ├── Recent
│   ├── Pinned
│   └── Recommended for this Mac
└── Settings
```

- A project owns comparison history and, later, reusable lineups and prompt defaults.
- A comparison thread owns an ordered model lineup and a multi-turn conversation.
- Each user turn is shared across the lineup; each model receives its own prior assistant responses.
- A response is durable even when it represents an error, cancellation, or incompatibility.
- Adding or removing models after the first completed turn will eventually fork the comparison so earlier results remain reproducible.

## Core workflow

1. Create or select a project.
2. Start a new comparison.
3. Add two or three models from recent, installed, recommended, or Hugging Face search results.
4. Preflight each model for access, format, runtime compatibility, download size, and memory fit.
5. Install missing models and add them to the lineup.
6. Send one prompt to every model.
7. Run models sequentially on the local accelerator and stream results into aligned columns.
8. Persist the prompt, lineup, settings, model outcomes, metrics, and errors before declaring the run complete.
9. Reopen the comparison in the same side-by-side layout, continue it, retry one response, or fork it.

## Opinionated future-state experience

- **Home is Compare.** A new task opens an empty two-slot lineup, a shared prompt composer, and one primary action: add models.
- **Hub discovery is an in-context picker.** Search opens from a lineup slot, retains the draft lineup, defaults to public models that can run on this Mac, and returns explicitly to the comparison.
- **Preflight precedes commitment.** A model drawer resolves the requested branch/tag to a commit and shows access, selected runtime, exact weight family, download size, memory/disk fit, and local-cache state before installation.
- **Install is not load.** Installation downloads and verifies pinned artifacts in the background; runtime memory is allocated only when a comparison turn reaches that model.
- **Lineups are ordered experimental inputs.** The first completed turn locks model order and revisions. Changing the lineup creates a fork so prior results stay reproducible.
- **Comparison threads are the main history object.** Sidebar history is project-scoped and shows the prompt-derived title, model lineup, status, and recency. Reopening restores aligned turns and per-model histories.
- **Saved lineups reduce repeated setup.** A user can name a verified two- or three-model lineup, reuse it in a project, and see when a newer Hub revision is available without silently adopting it.
- **Fairness is visible.** Shared generation settings, runtime deviations, load time, generation time, token count, and failures are attached to each run. Models execute sequentially under the same prompt and supported parameters.
- **Partial outcomes remain useful.** A failed or cancelled model column is persisted beside successful responses, with a targeted retry action that does not erase the original attempt.
- **Evaluation is lightweight and human-centered.** Users can mark a preferred response, add notes/tags, and export a comparison; heavyweight benchmark suites remain outside the core workflow.

## Fair comparison defaults

- Models run sequentially because only one large model can reliably occupy local accelerator memory.
- Model load time and generation time are measured separately.
- Generation parameters are shared and locked where runtimes support equivalent behavior.
- Runtime deviations are recorded rather than silently approximated.
- Tools are disabled in the normal comparison path; tool-use evaluation can return later as an explicit capability test.
- Partial success is first-class: one model failing does not discard other results.

## First implementation slice

The first slice establishes the product skeleton without replacing every existing subsystem:

- Add a backward-compatible `projects` table and assign all existing sessions to a default imported project.
- Add project filtering to session APIs.
- Persist the ordered model lineup for every comparison session.
- Preserve each selected model's runtime backend instead of redetecting it at execution time.
- Persist model-load and generation failures as model-attributed messages.
- Restore saved comparison sessions into the side-by-side view.
- Preserve multi-turn, per-model conversation context.
- Use a shared tool-free comparison prompt so every run is a bounded model response rather than an agent workflow.
- Make Compare the default new-session destination while keeping legacy chat sessions readable.

This slice deliberately did not implement Hub preflight, exact revision pinning, saved reusable lineups, verdicts, or the full project-management UI. Those build on the durable comparison thread introduced here.

## Second implementation slice: Hub-to-lineup

The second slice completes the safe path from Hugging Face discovery into a comparison:

- Add deterministic model preflight for proven Hub access, task/architecture/weight compatibility, local runtime availability, preferred-format size, post-unload memory fit, free-disk fit, and exact-revision cache coverage.
- Resolve `main` or a release tag to an immutable Hub commit and carry that SHA through installation, loading, comparison persistence, and restored execution.
- Treat gated access, unsupported repositories, unavailable runtimes, and insufficient memory as actionable product states rather than late string failures.
- Install only the selected runnable weight family plus small runtime support files; do not allocate a model just to make it available in the library.
- Open the model browser directly in Hub selection mode from Compare, preserve the draft lineup across navigation, and keep installation progress visible in both surfaces.
- Require preflight for Hub cards and quick-add library models so search metadata is never treated as an executability guarantee.
- Distinguish metadata-only or partial Hub cache entries from complete installations.
- Restrict the localhost API to the desktop app's trusted development and Tauri origins.
- Replace incompatible tool-agent recommendations with public, loader-compatible MLX starters that run in the packaged desktop app.

Saved lineups, shared generation controls, run-level load timing, retry-one-model, verdicts/annotations, and comparison export remain subsequent slices.

## Delivery roadmap

1. **Foundation — delivered:** projects, comparison-first routing, fixed ordered lineups, durable per-model outcomes, multi-turn restore, and legacy-chat compatibility.
2. **Hub-to-lineup — delivered:** revision-resolving preflight, install-only downloads, direct selection mode, cache truth, runtime propagation, and actionable incompatibility states.
3. **Reusable experiments — next:** saved lineups, shared generation controls, explicit load-versus-generation timing, per-model retry, and comparison forking when inputs change.
4. **Evaluation layer:** preference/verdict capture, annotations, tags, search/filtering, and Markdown/JSON export with full run metadata.
5. **Model lifecycle:** pinned/recent library views, update availability without auto-upgrade, cache storage controls, disk planning, and clearer runtime installation guidance.

## Compatibility and migration

- Existing SQLite databases migrate in place; no current session or message is deleted.
- Existing sessions are assigned to a stable default project named `Imported conversations`.
- Existing comparison sessions derive their lineup from stored assistant `model_id` values when no explicit lineup exists.
- Existing prompt-only comparisons remain visible and are treated as incomplete rather than successful.
- Legacy chat remains routable during the transition but is no longer the default surface.

## Success criteria for the first slice

- Creating a comparison stores its project and ordered model lineup before model generation starts.
- A model-load failure is visible immediately and after an app restart.
- Selecting a comparison in history opens Compare, not Chat.
- A restored comparison shows its prior shared prompts and per-model responses in the correct columns.
- Continuing a restored comparison sends each model its own prior assistant history.
- Existing chat sessions still open and retain their messages.
- Backend tests, frontend build, and targeted lint checks pass.
