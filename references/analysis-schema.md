# Optional Clip Plan Schema

Use this reference when preparing or validating `clip_plan.json` for optional selected-moment clipping and review page generation.

For general video understanding, first produce `video_analysis.json` using `references/video-analysis-schema.md`, then derive a clip plan only when selected moments need to be cut or reviewed.

## Strict JSON Shape

```json
{
  "scenario": "clips",
  "source_title": "Talk or video title",
  "summary": "One paragraph summary of the whole source video.",
  "segments": [
    {
      "start": 0,
      "end": 120,
      "title": "Opening and context",
      "summary": "What happens in this time range.",
      "visuals": ["speaker on stage", "architecture diagram"],
      "topics": ["agent workflow", "video analysis"],
      "importance": 3
    }
  ],
  "moments": [
    {
      "start": 305.2,
      "end": 365.8,
      "title": "Agent completes the first end-to-end cut",
      "summary": "The speaker shows the long-video workflow completing analysis, clipping, subtitles, and recap page generation.",
      "reason": "Clear end-to-end proof point with visible output.",
      "score": 92,
      "tags": ["demo", "workflow"],
      "quote": "The agent has now generated the first selected moment.",
      "takeaways": ["The workflow can run end to end.", "The result is ready for a recap page."],
      "subtitles": [
        {
          "start": 305.2,
          "end": 309.7,
          "text": "The agent has now generated the first selected moment."
        }
      ]
    }
  ],
  "report": {
    "key_points": ["Main conclusion"],
    "claims_to_verify": [
      {
        "claim": "Specific factual claim made in the video.",
        "timestamp": 425.0,
        "verification_status": "not_checked"
      }
    ],
    "action_items": [
      {
        "task": "Follow-up task",
        "owner": "Unknown",
        "due": ""
      }
    ]
  }
}
```

## Prompt Pattern

Ask the model to produce only JSON:

```text
Analyze this long video using the transcript, frame observations, and metadata below.
Return strict JSON matching the schema. Do not include markdown.

Scenario: <clips|meeting|course|live|report>
Target clips: <number>
Clip duration: <min>-<max> seconds

Selection rules:
- Prefer moments with clear standalone value.
- Use exact timestamps from transcript alignment.
- Include subtitle entries when transcript timing is available.
- Include `quote` and `takeaways` when a review page needs richer moment breakdowns.
- Avoid overlapping moments unless the user asked for a montage.

Metadata:
<metadata>

Transcript:
<timestamped transcript>

Visual observations:
<frame observations>
```

## Scenario Scoring

`clips` scoring:

- 90-100: strong standalone demo, major reveal, memorable conclusion, or audience reaction
- 75-89: useful explanation, concrete example, crisp technical point
- 60-74: context that supports a stronger nearby clip
- below 60: keep in segments, skip as a selected moment

`meeting` scoring:

- Decisions and owner-bound action items score highest.
- Risks, blockers, deadlines, and unresolved questions are useful.
- Casual discussion without a decision should stay in segments.

`course` scoring:

- Each segment should represent one teachable unit.
- Prefer clean boundaries around topic changes.
- Use `moments` for must-watch moments or examples.

`live` scoring:

- Score visual action, commentary intensity, crowd reaction, score changes, and replay-worthy turning points.
- Sample frames more frequently than speech-heavy videos.

`report` scoring:

- Prioritize claims, evidence, data points, conclusions, and contradictions.
- Add factual claims to `report.claims_to_verify`.

## Validation Rules

- `end` must be greater than `start`.
- Clip duration should be at least 3 seconds.
- `score` should be 0-100.
- Timestamps must be within the source video duration when metadata is available.
- Titles should be concise and specific.
- Summaries should explain what the viewer will see or learn.
