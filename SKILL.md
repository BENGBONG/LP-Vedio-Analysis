---
name: video-understanding-skill
description: General video understanding workflow for agents. Use when Codex is asked to analyze, summarize, index, search, answer questions about, report on, or cut clips from videos, meeting recordings, course videos, livestreams, product demos, talks, sports or esports replays, and screen recordings.
---

# Video Understanding Skill

Use this skill to turn a video into structured understanding artifacts: metadata, transcript, frame observations, semantic segments, summaries, reports, search indexes, Q&A context, and optional selected-moment clips.

## Core Workflow

Before running commands, locate the skill directory that contains this `SKILL.md`. Call that path `<skill_dir>`. The helper script must exist at `<skill_dir>/scripts/video_understanding.py`. The older `<skill_dir>/scripts/video_highlight.py` entrypoint remains as a compatibility wrapper.

1. Create a work directory.
   - Run `python3 <skill_dir>/scripts/video_understanding.py init-analysis --output <workdir> --scenario <summary|meeting|course|live|report|search|qa>`.
   - Keep generated files in that work directory.

2. Inspect the source video.
   - Run `python3 <skill_dir>/scripts/video_understanding.py probe <video> --output <workdir>/metadata.json`.
   - Use duration, dimensions, streams, and frame rate to choose ASR and frame sampling settings.

3. Extract analysis inputs.
   - Run `python3 <skill_dir>/scripts/video_understanding.py extract-audio <video> --output <workdir>/audio.wav` when audio exists.
   - Run `python3 <skill_dir>/scripts/video_understanding.py sample-frames <video> --output-dir <workdir>/frames --interval 30`.
   - Lower `--interval` to 5-15 seconds for product demos, UI walkthroughs, sports, games, or visually dense videos.

4. Build `video_analysis.json`.
   - Transcribe audio with available ASR or multimodal model support.
   - Caption sampled frames and collect OCR when useful.
   - Merge transcript, visual observations, and metadata into `references/video-analysis-schema.md`.
   - Save the result to `<workdir>/video_analysis.json`.

5. Validate analysis.
   - Run `python3 <skill_dir>/scripts/video_understanding.py validate-analysis <workdir>/video_analysis.json`.
   - Fix invalid timestamps, overlapping segments, missing titles, missing summaries, and malformed lists.

6. Produce task-specific outputs.
   - Summary: `python3 <skill_dir>/scripts/video_understanding.py summary --analysis <workdir>/video_analysis.json --output <workdir>/summary.md`
   - Search index: `python3 <skill_dir>/scripts/video_understanding.py search-index --analysis <workdir>/video_analysis.json --output <workdir>/search_index.jsonl`
   - Optional clip plan: `python3 <skill_dir>/scripts/video_understanding.py derive-clips --analysis <workdir>/video_analysis.json --output <workdir>/clip_plan.json`

7. Cut optional selected moments and generate a review page.
   - Validate clips: `python3 <skill_dir>/scripts/video_understanding.py validate-plan <workdir>/clip_plan.json`.
   - Cut clips: `python3 <skill_dir>/scripts/video_understanding.py cut <video> --plan <workdir>/clip_plan.json --output-dir <workdir>/clips`.
   - Generate page: `python3 <skill_dir>/scripts/video_understanding.py page --plan <workdir>/clip_plan.json --clips-dir <workdir>/clips --source-video <video> --copy-media --output <workdir>/site/index.html`.

## Model Responsibilities

The script performs deterministic media work. The agent or connected model must provide video understanding:

- ASR or audio transcription with timestamps.
- Frame captioning or multimodal visual review.
- OCR when slides, UI, or text overlays matter.
- Segment summaries and topic labels.
- Scenario-specific extraction such as decisions, action items, claims, questions, chapters, and selected moments.

## Scenario Routing

- `summary`: whole-video summary plus timestamped timeline.
- `meeting`: decisions, owners, action items, blockers, risks, deadlines, and open questions.
- `course`: chapters, concepts, demos, examples, prerequisites, and practice prompts.
- `live`: event spikes, turning points, reactions, score changes, and replay-worthy moments.
- `report`: claims, evidence timestamps, risks, contradictions, and facts to verify.
- `search`: segment-level JSONL for Video RAG or media asset search.
- `qa`: timestamped context that supports cited answers.

## Cost Controls

- Short videos under 5 minutes: dense frame sampling and direct multimodal review are acceptable.
- Medium videos from 5 to 30 minutes: use ASR first and sample frames every 10-30 seconds.
- Long videos over 30 minutes: use ASR and segment summaries first; run multimodal review only on candidate windows.
- For talks, meetings, and courses, transcript is the primary signal.
- For sports, games, demos, UI walkthroughs, and silent videos, increase visual sampling and frame captioning.

## Output Contracts

Read `references/video-analysis-schema.md` before generating or validating `video_analysis.json`.

For optional clip output, read `references/analysis-schema.md`; it remains the clip plan contract used by `cut` and `page`.

Required primary artifact:

- `<workdir>/video_analysis.json`

Common derived artifacts:

- `<workdir>/summary.md`
- `<workdir>/search_index.jsonl`
- Optional: `<workdir>/clip_plan.json`
- Optional: `<workdir>/clips/*.mp4`
- Optional: `<workdir>/site/index.html`

## Quality Checks

Before final delivery:

- Confirm `video_analysis.json` validates.
- Confirm segment timestamps are ordered and non-overlapping.
- Confirm summary text cites meaningful timestamps when useful.
- Confirm optional clips exist and have non-zero size.
- Confirm generated recap pages use relative media paths under `site/`.
- Mention when subtitles are sidecar SRT files rather than burned into video.
