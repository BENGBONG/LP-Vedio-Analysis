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
   - Optionally generate the recommended processing strategy:
     `python3 <skill_dir>/scripts/video_understanding.py plan-analysis --metadata <workdir>/metadata.json --scenario <scenario> --budget standard --output <workdir>/analysis_strategy.json`.

3. Extract analysis inputs.
   - Run `python3 <skill_dir>/scripts/video_understanding.py extract-audio <video> --output <workdir>/audio.wav` when audio exists.
   - Run `python3 <skill_dir>/scripts/video_understanding.py sample-frames <video> --output-dir <workdir>/frames --interval 30`.
   - Lower `--interval` to 5-15 seconds for product demos, UI walkthroughs, sports, games, or visually dense videos.

4. Prepare model observation files.
   - Transcribe audio with available ASR or multimodal model support.
   - Prepare sampled frames for VLM/OCR review:
     `python3 <skill_dir>/scripts/video_understanding.py prepare-frame-review --frames-dir <workdir>/frames --interval 30 --output <workdir>/frame_review_manifest.json --prompt-output <workdir>/frame_review_prompt.md --language Chinese`
   - Send `<workdir>/frame_review_manifest.json` and `<workdir>/frame_review_prompt.md` to the available multimodal model or OCR workflow.
   - Save the model response as `<workdir>/frame_review_output.json`.
   - Normalize model output:
     `python3 <skill_dir>/scripts/video_understanding.py ingest-frame-review --manifest <workdir>/frame_review_manifest.json --review <workdir>/frame_review_output.json --output <workdir>/frame_observations.json`
   - Save transcript to `<workdir>/transcript.json`.
   - Validate them with `validate-transcript` and `validate-frames`.

5. Build `video_analysis.json`.
   - Run `python3 <skill_dir>/scripts/video_understanding.py build-segments --transcript <workdir>/transcript.json --frames <workdir>/frame_observations.json --metadata <workdir>/metadata.json --output <workdir>/video_analysis.json --scenario <scenario>`.
   - Use this script-generated analysis as the first pass, then let the agent refine titles, summaries, topics, claims, actions, questions, and optional moments when needed.

6. Validate analysis.
   - Run `python3 <skill_dir>/scripts/video_understanding.py validate-analysis <workdir>/video_analysis.json`.
   - Fix invalid timestamps, overlapping segments, missing titles, missing summaries, and malformed lists.

7. Produce task-specific outputs.
   - Second-pass plan: `python3 <skill_dir>/scripts/video_understanding.py refine-plan --analysis <workdir>/video_analysis.json --output <workdir>/refine_plan.json`
   - Use `refine_plan.json` to decide which windows need denser frame sampling, local ASR, VLM review, or OCR. P0 means prioritize, P1 means review when budget allows, P2 means optional.
   - Prepare selected refine windows:
     `python3 <skill_dir>/scripts/video_understanding.py execute-refine-plan <video> --plan <workdir>/refine_plan.json --output-dir <workdir>/refine --priorities P0,P1`
   - Run ASR and VLM/OCR outside this script for each refine window, saving `transcript.json` and/or `frame_review_output.json` in the window directory.
   - Merge refine outputs:
     `python3 <skill_dir>/scripts/video_understanding.py merge-refine-results --analysis <workdir>/video_analysis.json --execution-manifest <workdir>/refine/refine_execution_manifest.json --normalize-outputs --output <workdir>/video_analysis.refined.json`
   - Summary: `python3 <skill_dir>/scripts/video_understanding.py summary --analysis <workdir>/video_analysis.json --output <workdir>/summary.md`
   - Search index: `python3 <skill_dir>/scripts/video_understanding.py search-index --analysis <workdir>/video_analysis.json --output <workdir>/search_index.jsonl`
   - Optional clip plan: `python3 <skill_dir>/scripts/video_understanding.py derive-clips --analysis <workdir>/video_analysis.json --output <workdir>/clip_plan.json`

8. Cut optional selected moments and generate a review page.
   - Validate clips: `python3 <skill_dir>/scripts/video_understanding.py validate-plan <workdir>/clip_plan.json`.
   - Cut clips: `python3 <skill_dir>/scripts/video_understanding.py cut <video> --plan <workdir>/clip_plan.json --output-dir <workdir>/clips`.
   - Generate page: `python3 <skill_dir>/scripts/video_understanding.py page --plan <workdir>/clip_plan.json --clips-dir <workdir>/clips --source-video <video> --copy-media --output <workdir>/site/index.html`.

## Model Responsibilities

The script performs deterministic media work. The agent or connected model must provide video understanding:

- ASR or audio transcription with timestamps.
- Frame captioning or multimodal visual review saved as frame observations.
- OCR when slides, UI, or text overlays matter.
- Refinement of script-generated segment summaries and topic labels.
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
- Use `refine-plan` after the first `video_analysis.json` to avoid spending multimodal budget on every segment.

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
