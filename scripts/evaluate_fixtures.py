#!/usr/bin/env python3
import argparse
import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
VIDEO_UNDERSTANDING_PATH = ROOT / "scripts" / "video_understanding.py"
SPEC = importlib.util.spec_from_file_location("video_understanding", VIDEO_UNDERSTANDING_PATH)
video_understanding = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(video_understanding)


def load_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def resolve_case_path(case_dir, value):
    if not value:
        return None
    path = Path(value)
    if path.is_absolute():
        return path
    return case_dir / path


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def validate_json_payloads(case_id, transcript_path, frames_path, analysis_path):
    transcript = video_understanding.load_list_payload(transcript_path, "transcript")
    frame_items = video_understanding.load_list_payload(frames_path, "frames")
    analysis = load_json(analysis_path)

    errors = []
    errors.extend(video_understanding.validate_transcript_items(transcript))
    errors.extend(video_understanding.validate_frame_items(frame_items))
    errors.extend(video_understanding.validate_analysis_data(analysis))
    require(not errors, f"{case_id}: validation failed: {'; '.join(errors)}")
    return transcript, frame_items, analysis


def collect_topics(analysis):
    topics = set()
    for segment in analysis.get("segments") or []:
        topics.update(str(topic) for topic in segment.get("topics") or [])
    return topics


def collect_ocr(frame_items):
    return {str(item) for frame in frame_items for item in frame.get("ocr", [])}


def collect_entity_names(analysis):
    return {str(entity.get("name", "")) for entity in analysis.get("entities") or []}


def collect_claim_text(analysis):
    return " ".join(str(claim.get("claim", "")) for claim in analysis.get("claims") or []).lower()


def read_jsonl(path):
    rows = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def run_derived_outputs(case_id, scenario, transcript_path, frames_path, metadata_path, analysis_path, expectations):
    with tempfile.TemporaryDirectory(prefix=f"{case_id}-eval-") as tmp:
        tmpdir = Path(tmp)
        built_analysis = tmpdir / "built_video_analysis.json"
        summary_path = tmpdir / "summary.md"
        search_path = tmpdir / "search_index.jsonl"

        video_understanding.cmd_build_segments(SimpleNamespace(
            transcript=str(transcript_path),
            frames=str(frames_path),
            metadata=str(metadata_path) if metadata_path else None,
            output=str(built_analysis),
            scenario=scenario,
            title="",
            summary="",
            max_segment_duration=90.0,
            gap=8.0,
        ))
        require(built_analysis.exists(), f"{case_id}: build-segments did not write analysis")

        built = load_json(built_analysis)
        require(not video_understanding.validate_analysis_data(built), f"{case_id}: built analysis is invalid")

        video_understanding.cmd_summary(SimpleNamespace(
            analysis=str(analysis_path),
            output=str(summary_path),
        ))
        summary_text = summary_path.read_text(encoding="utf-8")
        require("## Timeline" in summary_text, f"{case_id}: summary is missing timeline")

        video_understanding.cmd_search_index(SimpleNamespace(
            analysis=str(analysis_path),
            output=str(search_path),
        ))
        rows = read_jsonl(search_path)
        min_search_rows = expectations.get("min_search_rows", len(load_json(analysis_path).get("segments") or []))
        require(len(rows) >= min_search_rows, f"{case_id}: expected at least {min_search_rows} search rows")
        require(all(row.get("text") for row in rows), f"{case_id}: every search row must have text")
        require(all("transcript_text" in row and "visual_text" in row and "ocr_text" in row for row in rows),
                f"{case_id}: search rows must expose transcript, visual, and OCR text")

        search_text = "\n".join(str(row.get("text", "")) for row in rows).lower()
        for needle in expectations.get("required_search_text", []):
            require(str(needle).lower() in search_text, f"{case_id}: search index missing {needle!r}")


def evaluate_case(case_dir):
    manifest_path = case_dir / "manifest.json"
    manifest = load_json(manifest_path)
    case_id = manifest.get("id") or case_dir.name
    scenario = manifest.get("scenario") or "summary"
    expectations = manifest.get("expectations") or {}

    source_video = resolve_case_path(case_dir, manifest.get("source_video"))
    transcript_path = resolve_case_path(case_dir, manifest.get("transcript"))
    frames_path = resolve_case_path(case_dir, manifest.get("frame_observations"))
    metadata_path = resolve_case_path(case_dir, manifest.get("metadata"))
    analysis_path = resolve_case_path(case_dir, manifest.get("expected_analysis"))

    for label, path in [
        ("source_video", source_video),
        ("transcript", transcript_path),
        ("frame_observations", frames_path),
        ("metadata", metadata_path),
        ("expected_analysis", analysis_path),
    ]:
        require(path and path.exists(), f"{case_id}: missing {label}: {path}")

    transcript, frame_items, analysis = validate_json_payloads(case_id, transcript_path, frames_path, analysis_path)

    require(analysis.get("scenario") == scenario, f"{case_id}: expected scenario {scenario}")
    require(len(transcript) >= expectations.get("min_transcript_items", 1), f"{case_id}: too few transcript items")
    require(len(frame_items) >= expectations.get("min_frame_observations", 1), f"{case_id}: too few frame observations")
    require(len(analysis.get("segments") or []) >= expectations.get("min_segments", 1), f"{case_id}: too few segments")

    topics = collect_topics(analysis)
    for topic in expectations.get("required_topics", []):
        require(topic in topics, f"{case_id}: missing topic {topic!r}")

    entity_names = collect_entity_names(analysis)
    for entity in expectations.get("required_entities", []):
        require(entity in entity_names, f"{case_id}: missing entity {entity!r}")

    claim_text = collect_claim_text(analysis)
    for claim in expectations.get("required_claim_text", []):
        require(str(claim).lower() in claim_text, f"{case_id}: missing claim text {claim!r}")

    ocr_items = collect_ocr(frame_items)
    for ocr in expectations.get("required_ocr", []):
        require(ocr in ocr_items, f"{case_id}: missing OCR text {ocr!r}")

    summary = str(analysis.get("summary", "")).lower()
    for needle in expectations.get("summary_contains", []):
        require(str(needle).lower() in summary, f"{case_id}: summary missing {needle!r}")

    run_derived_outputs(case_id, scenario, transcript_path, frames_path, metadata_path, analysis_path, expectations)
    return {"id": case_id, "segments": len(analysis.get("segments") or [])}


def evaluate_all(eval_dir):
    root = Path(eval_dir)
    case_dirs = sorted(path for path in root.iterdir() if (path / "manifest.json").exists())
    require(case_dirs, f"no eval cases found in {root}")
    return [evaluate_case(case_dir) for case_dir in case_dirs]


def main(argv=None):
    parser = argparse.ArgumentParser(description="Evaluate golden video analysis fixtures.")
    parser.add_argument("--eval-dir", default=str(ROOT / "examples" / "eval"), help="Directory containing eval case folders.")
    args = parser.parse_args(argv)
    try:
        results = evaluate_all(args.eval_dir)
    except AssertionError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    for result in results:
        print(f"OK {result['id']} segments={result['segments']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
