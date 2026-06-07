<div align="center">
  <img src="examples/lp-video-analysis-cover.svg" alt="LP Video Analysis Skill cover" width="900" />
  <h1>LP Video Analysis Skill</h1>
  <p><strong>General video understanding skill for agents: inspect media, extract audio and frames, build structured video analysis, derive summaries, reports, Q&A context, search indexes, and optional clips.</strong></p>
  <p>
    <code>Codex</code> · <code>Claude Code</code> · <code>OpenClaw</code> · <code>Agent Skill</code> · <code>Video RAG</code>
  </p>
</div>

[中文说明](README.zh-CN.md)

## What It Does

- Probes video metadata with `ffprobe`
- Extracts audio for ASR
- Samples frames for visual review
- Validates external ASR transcripts and frame observation files
- Builds semantic segments from transcript, frame observations, and metadata
- Defines a general `video_analysis.json` schema
- Validates semantic segments, transcript entries, and optional key moments
- Derives Markdown summaries, reports, and JSONL search indexes
- Derives optional clip plans from analysis
- Cuts optional clips with `ffmpeg`
- Exports sidecar SRT subtitles
- Generates a static review page for selected moments

The repository does not include an embedded video foundation model. Your Agent or model stack provides ASR, frame captioning, OCR, multimodal review, and structured JSON generation.

## Quick Start

Install or clone the complete repository, including `SKILL.md`, `scripts/`, `references/`, `assets/`, `agents/`, and `examples/`.

Then give your Agent a video and ask:

```text
Use video-understanding-skill to analyze this video, create video_analysis.json, produce a summary, and build a search index.
```

## Commands

Create an analysis workspace:

```bash
python3 scripts/video_understanding.py init-analysis --output work/demo --scenario summary
```

Inspect media:

```bash
python3 scripts/video_understanding.py probe examples/demo-input/original-product-video.mp4 --output work/demo/metadata.json
```

Choose a cost-aware processing strategy from metadata:

```bash
python3 scripts/video_understanding.py plan-analysis \
  --metadata work/demo/metadata.json \
  --scenario report \
  --budget standard \
  --output work/demo/analysis_strategy.json
```

Extract audio and frames:

```bash
python3 scripts/video_understanding.py extract-audio input.mp4 --output work/demo/audio.wav
python3 scripts/video_understanding.py sample-frames input.mp4 --output-dir work/demo/frames --interval 30
```

Validate model-produced transcript and frame observations:

```bash
python3 scripts/video_understanding.py validate-transcript assets/sample_transcript.json
python3 scripts/video_understanding.py validate-frames assets/sample_frame_observations.json
```

Prepare sampled frames for multimodal review, then ingest the model output:

```bash
python3 scripts/video_understanding.py prepare-frame-review \
  --frames-dir work/demo/frames \
  --interval 30 \
  --output work/demo/frame_review_manifest.json \
  --prompt-output work/demo/frame_review_prompt.md \
  --language Chinese

# After your VLM writes work/demo/frame_review_output.json:
python3 scripts/video_understanding.py ingest-frame-review \
  --manifest work/demo/frame_review_manifest.json \
  --review work/demo/frame_review_output.json \
  --output work/demo/frame_observations.json
```

Build `video_analysis.json` from the model outputs:

```bash
python3 scripts/video_understanding.py build-segments \
  --transcript assets/sample_transcript.json \
  --frames assets/sample_frame_observations.json \
  --metadata work/demo/metadata.json \
  --output work/demo/video_analysis.json \
  --scenario summary
```

Validate a general video analysis artifact:

```bash
python3 scripts/video_understanding.py validate-analysis assets/sample_video_analysis.json
```

Select candidate windows for second-pass review:

```bash
python3 scripts/video_understanding.py refine-plan \
  --analysis work/demo/video_analysis.json \
  --output work/demo/refine_plan.json
```

The refine plan marks windows as `P0`, `P1`, or `P2` based on rules such as high segment importance, high moment score, visual or uncertainty keywords, missing transcript despite audio, and open questions. Use those windows for denser frame sampling and local ASR/VLM/OCR review.

Prepare dense second-pass materials from the refine plan:

```bash
python3 scripts/video_understanding.py execute-refine-plan input.mp4 \
  --plan work/demo/refine_plan.json \
  --output-dir work/demo/refine \
  --priorities P0,P1
```

For each selected window this writes dense `frames/`, `audio.wav` when ASR is needed, `frame_review_manifest.json`, `frame_review_prompt.md`, and `window.json`. After ASR and VLM/OCR outputs are saved in those window folders, merge them back:

```bash
python3 scripts/video_understanding.py merge-refine-results \
  --analysis work/demo/video_analysis.json \
  --execution-manifest work/demo/refine/refine_execution_manifest.json \
  --normalize-outputs \
  --output work/demo/video_analysis.refined.json
```

Derive outputs:

```bash
python3 scripts/video_understanding.py summary --analysis assets/sample_video_analysis.json --output work/demo/summary.md
python3 scripts/video_understanding.py search-index --analysis assets/sample_video_analysis.json --output work/demo/search_index.jsonl
python3 scripts/video_understanding.py derive-clips --analysis assets/sample_video_analysis.json --output work/demo/clip_plan.json
```

Optionally cut selected moments and generate a review page:

```bash
python3 scripts/video_understanding.py cut examples/demo-input/original-product-video.mp4 --plan work/demo/clip_plan.json --output-dir work/demo/clips
python3 scripts/video_understanding.py page --plan work/demo/clip_plan.json --clips-dir work/demo/clips --source-video examples/demo-input/original-product-video.mp4 --copy-media --output work/demo/site/index.html
```

The legacy `scripts/video_highlight.py` entrypoint still works and forwards to `video_understanding.py`.

## Output Model

Primary artifact:

```text
video_analysis.json
```

Derived artifacts:

```text
summary.md
search_index.jsonl
optional: clip_plan.json
optional: clips/*.mp4
optional: clips/*.srt
optional: site/index.html
```

Read:

- [references/video-analysis-schema.md](references/video-analysis-schema.md) for general analysis.
- [references/analysis-schema.md](references/analysis-schema.md) for optional clip plans.

## Recommended Architecture

```text
video
 -> ffprobe metadata
 -> plan-analysis
 -> ASR transcript with timestamps
 -> sampled frames
 -> VLM frame review + OCR
 -> build-segments
 -> video_analysis.json
 -> refine-plan
 -> dense candidate-window review
 -> refined video_analysis.json
 -> summary / search index / report / Q&A
 -> optional selected moments and ffmpeg clips
```

For long videos, avoid sending the whole video to a strong multimodal model at once. Use ASR and low-frequency frame sampling first, then run multimodal review only on candidate windows.

The model handoff layer is explicit:

```text
frames/*.jpg
 -> prepare-frame-review
 -> frame_review_manifest.json + frame_review_prompt.md
 -> external VLM/OCR model
 -> frame_review_output.json
 -> ingest-frame-review
 -> frame_observations.json
```

Second-pass review is also explicit:

```text
video_analysis.json
 -> refine-plan
 -> refine_plan.json
 -> execute-refine-plan
 -> per-window dense frames + local audio + frame review prompts
 -> external ASR/VLM/OCR outputs
 -> merge-refine-results
 -> refined video_analysis.json
```

## Evaluation

Golden fixtures live in `examples/eval/`. They validate the stable parts of the workflow without calling ASR, OCR, VLMs, `ffmpeg`, or `ffprobe`:

```bash
python3 scripts/evaluate_fixtures.py
```

Each fixture contains a `manifest.json`, stable metadata, transcript, frame observations, and a human-reviewed `expected_video_analysis.json`. Add real project videos as new fixture folders once you have representative examples.

## Requirements

- Python 3.9+
- `ffmpeg`
- `ffprobe`
- An Agent/model stack that can provide ASR and multimodal understanding

## License

MIT. See [LICENSE](LICENSE).

## Attribution

This repository is adapted from [inhai-wiki/video-highlight-skill](https://github.com/inhai-wiki/video-highlight-skill), which is published under the MIT License.

What we referenced from the original project:

- The Agent Skill packaging pattern: `SKILL.md`, `scripts/`, `references/`, `assets/`, `agents/`, and examples.
- The deterministic media helper workflow using `ffprobe`, `ffmpeg`, audio extraction, frame sampling, clip cutting, SRT sidecars, and a static review page.
- The original optional clip-plan schema and demo media flow.

What we changed:

- Repositioned the project from highlight-first clipping to general video understanding.
- Added `video_analysis.json` as the primary analysis artifact.
- Added `references/video-analysis-schema.md`.
- Added `scripts/video_understanding.py` with `init-analysis`, `validate-analysis`, `summary`, `search-index`, and `derive-clips`.
- Added explicit transcript/frame-observation validation, VLM frame-review handoff commands, `build-segments`, `moments`, and richer Video RAG JSONL output.
- Kept `scripts/video_highlight.py` only as a backward-compatible wrapper.
- Replaced the old highlight-first branding with LP Video Analysis branding.
- Added `assets/sample_video_analysis.json` and unit tests.
