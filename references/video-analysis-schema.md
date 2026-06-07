# Video Analysis Schema

Use this schema as the primary output contract for general video understanding. A downstream task can derive selected-moment clips, meeting notes, course chapters, reports, Q&A context, or a search index from this file.

## Strict JSON Shape

```json
{
  "scenario": "summary",
  "source": {
    "title": "Video title",
    "duration": 3600.0,
    "width": 1920,
    "height": 1080,
    "fps": "30/1",
    "has_audio": true,
    "metadata_path": "metadata.json"
  },
  "summary": "One paragraph summary of the whole video.",
  "transcript": [
    {
      "start": 0.0,
      "end": 8.4,
      "speaker": "Speaker 1",
      "text": "Timestamped transcript text."
    }
  ],
  "frames": [
    {
      "timestamp": 30.0,
      "path": "frames/frame_00001.jpg",
      "caption": "Speaker shows a product dashboard.",
      "ocr": ["Revenue", "Activation"],
      "objects": ["speaker", "screen", "chart"]
    }
  ],
  "segments": [
    {
      "id": "seg_0001",
      "start": 0.0,
      "end": 65.2,
      "title": "Opening context",
      "summary": "The speaker frames the problem and the desired outcome.",
      "topics": ["context", "problem"],
      "visuals": ["talking head", "title slide"],
      "importance": 3
    }
  ],
  "highlights": [
    {
      "start": 305.2,
      "end": 365.8,
      "title": "End-to-end demo result",
      "summary": "A concrete demo reaches a visible result.",
      "reason": "Strong standalone proof point.",
      "score": 92,
      "tags": ["demo"],
      "quote": "Here is the completed result.",
      "takeaways": ["The workflow completes successfully."],
      "subtitles": [
        {
          "start": 305.2,
          "end": 309.7,
          "text": "Here is the completed result."
        }
      ]
    }
  ],
  "entities": [
    {
      "name": "Product name",
      "type": "product",
      "timestamps": [120.0, 305.2]
    }
  ],
  "claims": [
    {
      "claim": "Specific factual claim made in the video.",
      "timestamp": 425.0,
      "verification_status": "not_checked"
    }
  ],
  "actions": [
    {
      "task": "Follow-up task",
      "owner": "Unknown",
      "due": ""
    }
  ],
  "questions": [
    {
      "question": "Open question raised by the speaker.",
      "timestamp": 900.0,
      "status": "open"
    }
  ]
}
```

## Segment Rules

- Use seconds for `start`, `end`, and `timestamp` when possible.
- Segments should be semantically coherent. Avoid making every fixed interval a segment unless no better boundary is available.
- Keep segment boundaries non-overlapping and ordered.
- Use `importance` from 0 to 5.
- Prefer transcript-aligned timestamps over frame-only guesses.

## Scenario Guidance

- `summary`: concise whole-video summary plus timeline segments.
- `meeting`: decisions, action items, blockers, owners, deadlines, and unresolved questions.
- `course`: chapters, concepts, examples, prerequisites, and practice prompts.
- `highlight`: reusable moments with standalone value.
- `live`: event spikes, turning points, reactions, and major state changes.
- `report`: claims, evidence, risk, contradictions, and facts to verify.
- `search`: segment-level documents for Video RAG or asset search.
- `qa`: answerable context with timestamp citations.

## Cost Controls

- Short videos under 5 minutes: dense frame sampling and direct multimodal review are acceptable.
- Medium videos from 5 to 30 minutes: ASR first, frame sampling every 10-30 seconds.
- Long videos over 30 minutes: ASR plus segment summaries first, multimodal review only on candidate windows.
- Fast visual content such as sports, games, and UI walkthroughs needs denser frame sampling than talks or meetings.
