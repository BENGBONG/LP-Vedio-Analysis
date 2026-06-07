# Evaluation Fixtures

This directory contains golden evaluation cases for the deterministic parts of the video understanding workflow.

Each case should include:

- `manifest.json`: paths and minimum expectations for the case.
- `metadata.json`: stable ffprobe-style metadata used by `build-segments`.
- `transcript.json`: timestamped ASR output.
- `frame_observations.json`: timestamped visual captions, OCR, and object observations.
- `expected_video_analysis.json`: human-reviewed analysis used as the golden target.

Run all fixtures:

```bash
python3 scripts/evaluate_fixtures.py
```

The evaluator intentionally avoids calling ASR, OCR, VLMs, `ffmpeg`, or `ffprobe`. It validates stable contracts first. Add model-backed quality checks after a case has a reliable expected analysis.
