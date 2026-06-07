<div align="center">
  <img src="examples/video-highlight-skill-cover.jpg" alt="Video Understanding Skill cover" width="900" />
  <h1>LP Video Analysis Skill</h1>
  <p><strong>General video understanding skill for agents: inspect media, extract audio and frames, build structured video analysis, derive summaries/search indexes/highlights, cut clips with FFmpeg, and generate recap pages.</strong></p>
  <p>
    <code>Codex</code> · <code>Claude Code</code> · <code>OpenClaw</code> · <code>Agent Skill</code> · <code>Video RAG</code>
  </p>
</div>

## What It Does

- Probes video metadata with `ffprobe`
- Extracts audio for ASR
- Samples frames for visual review
- Defines a general `video_analysis.json` schema
- Validates semantic segments, transcript entries, and optional highlights
- Derives Markdown summaries and JSONL search indexes
- Derives highlight clip plans from analysis
- Cuts clips with `ffmpeg`
- Exports sidecar SRT subtitles
- Generates a YouTube-style static recap page

The repository does not include an embedded video foundation model. Your Agent or model stack provides ASR, frame captioning, OCR, multimodal review, and structured JSON generation.

## Quick Start

Install or clone the complete repository, including `SKILL.md`, `scripts/`, `references/`, `assets/`, `agents/`, and `examples/`.

Then give your Agent a video and ask:

```text
Use video-understanding-skill to analyze this video, create video_analysis.json, produce a summary, build a search index, and cut highlights if useful.
```

## Commands

Create an analysis workspace:

```bash
python3 scripts/video_understanding.py init-analysis --output work/demo --scenario highlight
```

Inspect media:

```bash
python3 scripts/video_understanding.py probe examples/demo-input/original-product-video.mp4 --output work/demo/metadata.json
```

Extract audio and frames:

```bash
python3 scripts/video_understanding.py extract-audio input.mp4 --output work/demo/audio.wav
python3 scripts/video_understanding.py sample-frames input.mp4 --output-dir work/demo/frames --interval 30
```

Validate a general video analysis artifact:

```bash
python3 scripts/video_understanding.py validate-analysis assets/sample_video_analysis.json
```

Derive outputs:

```bash
python3 scripts/video_understanding.py summary --analysis assets/sample_video_analysis.json --output work/demo/summary.md
python3 scripts/video_understanding.py search-index --analysis assets/sample_video_analysis.json --output work/demo/search_index.jsonl
python3 scripts/video_understanding.py derive-highlight --analysis assets/sample_video_analysis.json --output work/demo/clip_plan.json
```

Cut clips and generate the recap page:

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
clip_plan.json
clips/*.mp4
clips/*.srt
site/index.html
```

Read:

- [references/video-analysis-schema.md](references/video-analysis-schema.md) for general analysis.
- [references/analysis-schema.md](references/analysis-schema.md) for highlight clip plans.

## Recommended Architecture

```text
video
 -> ffprobe metadata
 -> ASR transcript with timestamps
 -> sampled frames + captions + OCR
 -> semantic segments
 -> video_analysis.json
 -> summary / search index / highlights / report / Q&A
 -> optional ffmpeg clips and recap page
```

For long videos, avoid sending the whole video to a strong multimodal model at once. Use ASR and low-frequency frame sampling first, then run multimodal review only on candidate windows.

## Requirements

- Python 3.9+
- `ffmpeg`
- `ffprobe`
- An Agent/model stack that can provide ASR and multimodal understanding

## License

MIT
