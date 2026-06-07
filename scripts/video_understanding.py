#!/usr/bin/env python3
import argparse
import html
import json
import shutil
import subprocess
import sys
from pathlib import Path


SCENARIOS = {"clips", "highlight", "meeting", "course", "live", "report", "summary", "search", "qa"}


def run_command(args):
    try:
        subprocess.run(args, check=True)
    except FileNotFoundError as exc:
        raise SystemExit(f"Missing executable: {args[0]}") from exc
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"Command failed with exit code {exc.returncode}: {' '.join(args)}") from exc


def parse_time(value):
    if isinstance(value, (int, float)):
        return float(value)
    if value is None:
        raise ValueError("missing timestamp")
    text = str(value).strip()
    if not text:
        raise ValueError("empty timestamp")
    if ":" not in text:
        return float(text)
    parts = [float(part) for part in text.split(":")]
    if len(parts) == 3:
        hours, minutes, seconds = parts
    elif len(parts) == 2:
        hours = 0
        minutes, seconds = parts
    else:
        raise ValueError(f"invalid timestamp: {value}")
    return hours * 3600 + minutes * 60 + seconds


def format_timestamp(seconds):
    seconds = max(0.0, float(seconds))
    whole = int(seconds)
    millis = int(round((seconds - whole) * 1000))
    if millis == 1000:
        whole += 1
        millis = 0
    hours = whole // 3600
    minutes = (whole % 3600) // 60
    secs = whole % 60
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def safe_slug(text, fallback):
    allowed = []
    for char in str(text).lower():
        if char.isalnum():
            allowed.append(char)
        elif char in {" ", "-", "_"}:
            allowed.append("-")
    slug = "".join(allowed).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or fallback


def load_plan(path):
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if isinstance(data, list):
        data = {"scenario": "clips", "source_title": "", "summary": "", "segments": [], "moments": data}
    return data


def get_moments(plan):
    items = plan.get("moments") or plan.get("highlights") or plan.get("clips") or []
    if not isinstance(items, list):
        raise ValueError("moments must be a list")
    return items


def get_highlights(plan):
    return get_moments(plan)


def get_segments(analysis):
    items = analysis.get("segments") or []
    if not isinstance(items, list):
        raise ValueError("segments must be a list")
    return items


def normalize_list_payload(data, key):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        value = data.get(key) or data.get(f"{key}_items") or []
        if isinstance(value, list):
            return value
    raise ValueError(f"{key} payload must be a list or an object containing a {key} list")


def load_list_payload(path, key):
    return normalize_list_payload(load_plan(path), key)


def ensure_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def relative_url(path, base_dir):
    try:
        return Path(path).resolve().relative_to(Path(base_dir).resolve()).as_posix()
    except ValueError:
        return Path(path).as_posix()


def copy_media_file(src, media_dir, prefix=""):
    source = Path(src)
    if not source.exists():
        return source
    media_dir.mkdir(parents=True, exist_ok=True)
    target_name = f"{prefix}{source.name}" if prefix else source.name
    target = media_dir / target_name
    if source.resolve() != target.resolve():
        shutil.copy2(source, target)
    return target


def list_frame_files(frames_dir):
    root = Path(frames_dir)
    patterns = ["*.jpg", "*.jpeg", "*.png", "*.webp"]
    files = []
    for pattern in patterns:
        files.extend(root.glob(pattern))
    return sorted(path for path in files if path.is_file())


def trailing_number(text, fallback):
    digits = []
    for char in reversed(str(text)):
        if char.isdigit():
            digits.append(char)
        elif digits:
            break
    if not digits:
        return fallback
    return int("".join(reversed(digits)))


def build_frame_review_manifest(frames_dir, interval, start_time=0.0, relative_to=None):
    root = Path(frames_dir)
    base = Path(relative_to) if relative_to else root.parent
    frames = []
    for fallback_index, path in enumerate(list_frame_files(root), start=1):
        index = trailing_number(path.stem, fallback_index)
        timestamp = float(start_time) + max(0, index - 1) * float(interval)
        frames.append({
            "id": path.stem,
            "index": index,
            "timestamp": timestamp,
            "path": relative_url(path, base),
            "absolute_path": str(path.resolve()),
        })
    return {
        "schema": "frame_review_manifest.v1",
        "frames_dir": str(root),
        "frame_interval": float(interval),
        "start_time": float(start_time),
        "instructions": {
            "task": "Review each sampled video frame with a multimodal model and return frame observations.",
            "output_schema": "frame_observations.v1",
            "required_fields": ["timestamp", "path", "caption", "ocr", "objects"],
        },
        "frames": frames,
    }


def frame_review_prompt(manifest, language):
    frame_rows = "\n".join(
        f"- {item['id']} @ {format_seconds(item['timestamp'])}: {item['path']}"
        for item in manifest.get("frames", [])
    )
    return f"""# Frame Review Task

Review the sampled video frames listed below and return strict JSON.

Language for `caption`, `objects`, and `notes`: {language}

Return this shape:

```json
{{
  "frames": [
    {{
      "timestamp": 0,
      "path": "frames/frame_00001.jpg",
      "caption": "Describe the visible scene, action, setting, mood, and any relevant uncertainty.",
      "ocr": ["visible text, signs, subtitles, labels"],
      "objects": ["important objects, people, places, visual elements"],
      "confidence": 0.0,
      "notes": "Optional uncertainty, location clues, or follow-up needs."
    }}
  ]
}}
```

Rules:

- Keep `timestamp` and `path` exactly aligned with the manifest.
- Put all visible text in `ocr`; use an empty list when there is none.
- Use `caption` for visual facts and careful uncertainty, not creative copy.
- Use `objects` for searchable nouns such as people, roads, mountains, food stalls, UI screens, products, animals, signs, and vehicles.
- Do not invent exact place names, identities, brands, or claims unless visible in the frame or provided by OCR.

Frames:

{frame_rows}
"""


def normalize_frame_review_payload(data, manifest=None):
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = (
            data.get("frames")
            or data.get("frame_observations")
            or data.get("observations")
            or []
        )
    else:
        raise ValueError("frame review payload must be a JSON object or list")
    if not isinstance(items, list):
        raise ValueError("frame review items must be a list")
    manifest_frames = {}
    if manifest:
        for frame in manifest.get("frames") or []:
            for key in [frame.get("id"), frame.get("path"), Path(str(frame.get("path", ""))).name]:
                if key:
                    manifest_frames[str(key)] = frame
    normalized = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"frame review item {index} must be an object")
        lookup_keys = [
            item.get("id"),
            item.get("path"),
            item.get("frame_path"),
            Path(str(item.get("path", ""))).name if item.get("path") else "",
        ]
        manifest_item = {}
        for key in lookup_keys:
            if key and str(key) in manifest_frames:
                manifest_item = manifest_frames[str(key)]
                break
        timestamp = item.get("timestamp", item.get("time", manifest_item.get("timestamp")))
        path = item.get("path") or item.get("frame_path") or manifest_item.get("path") or ""
        if timestamp is None:
            raise ValueError(f"frame review item {index} is missing timestamp")
        if not path:
            raise ValueError(f"frame review item {index} is missing path")
        normalized.append({
            "timestamp": parse_time(timestamp),
            "path": str(path),
            "caption": str(
                item.get("caption")
                or item.get("description")
                or item.get("visual_description")
                or ""
            ).strip(),
            "ocr": [str(value) for value in ensure_list(item.get("ocr", item.get("text_overlays", []))) if str(value).strip()],
            "objects": [str(value) for value in ensure_list(item.get("objects", item.get("visual_elements", []))) if str(value).strip()],
            **({"confidence": item.get("confidence")} if item.get("confidence") is not None else {}),
            **({"notes": item.get("notes")} if item.get("notes") else {}),
        })
    normalized.sort(key=lambda item: parse_time(item.get("timestamp")))
    return normalized


def render_tags(tags):
    if not tags:
        return ""
    items = "\n".join(f"<span>{html.escape(str(tag))}</span>" for tag in tags)
    return f'<div class="tags">{items}</div>'


def render_takeaways(takeaways):
    if not takeaways:
        return ""
    items = "\n".join(f"<li>{html.escape(str(item))}</li>" for item in takeaways)
    return f'<ul class="takeaways">{items}</ul>'


def render_active_details(item, start, end, clip_src):
    tags = render_tags(item.get("tags") or [])
    takeaways = render_takeaways(item.get("takeaways") or [])
    quote = item.get("quote")
    quote_markup = f"<blockquote>{html.escape(str(quote))}</blockquote>" if quote else ""
    return f"""
      <div class="active-meta">
        <span>{html.escape(format_seconds(start))} - {html.escape(format_seconds(end))}</span>
        <span>Score {html.escape(str(item.get('score', '')))}</span>
      </div>
      {quote_markup}
      <p class="reason">{html.escape(str(item.get('reason', '')))}</p>
      {takeaways}
      {tags}
      <div class="active-actions">
        <a href="{html.escape(clip_src, quote=True)}" download>Download clip</a>
        <button class="source-jump-button" type="button" data-start="{html.escape(str(start), quote=True)}">Play in original</button>
      </div>
    """


def render_report(plan):
    report = plan.get("report") or {}
    key_points = report.get("key_points") or []
    claims = report.get("claims_to_verify") or []
    actions = report.get("action_items") or []
    blocks = []
    if key_points:
        items = "\n".join(f"<li>{html.escape(str(item))}</li>" for item in key_points)
        blocks.append(f"<section class=\"notes\"><h2>Key Points</h2><ul>{items}</ul></section>")
    if claims:
        items = []
        for claim in claims:
            timestamp = claim.get("timestamp", "")
            status = claim.get("verification_status", "")
            items.append(
                "<li>"
                f"{html.escape(str(claim.get('claim', '')))}"
                f"<span>{html.escape(str(timestamp))} · {html.escape(str(status))}</span>"
                "</li>"
            )
        blocks.append(f"<section class=\"notes\"><h2>Claims</h2><ul>{''.join(items)}</ul></section>")
    if actions:
        items = []
        for action in actions:
            owner = action.get("owner", "")
            due = action.get("due", "")
            items.append(
                "<li>"
                f"{html.escape(str(action.get('task', '')))}"
                f"<span>{html.escape(str(owner))} {html.escape(str(due))}</span>"
                "</li>"
            )
        blocks.append(f"<section class=\"notes\"><h2>Action Items</h2><ul>{''.join(items)}</ul></section>")
    if not blocks:
        return ""
    return f"<div class=\"notes-grid\">{''.join(blocks)}</div>"


def validate_plan_data(plan, duration=None):
    errors = []
    scenario = plan.get("scenario")
    if scenario and scenario not in SCENARIOS:
        errors.append(f"scenario must be one of {sorted(SCENARIOS)}")
    moments = get_moments(plan)
    if not moments:
        errors.append("moments is empty")
    last_end = -1.0
    for index, item in enumerate(moments, start=1):
        prefix = f"moment {index}"
        try:
            start = parse_time(item.get("start"))
            end = parse_time(item.get("end"))
        except Exception as exc:
            errors.append(f"{prefix}: invalid start/end: {exc}")
            continue
        if end <= start:
            errors.append(f"{prefix}: end must be greater than start")
        if end - start < 3:
            errors.append(f"{prefix}: duration is shorter than 3 seconds")
        if duration is not None and end > duration:
            errors.append(f"{prefix}: end exceeds video duration")
        if start < last_end:
            errors.append(f"{prefix}: overlaps previous moment")
        last_end = max(last_end, end)
        if not str(item.get("title", "")).strip():
            errors.append(f"{prefix}: missing title")
        if not str(item.get("summary", "")).strip():
            errors.append(f"{prefix}: missing summary")
        score = item.get("score", 0)
        try:
            score = float(score)
            if score < 0 or score > 100:
                errors.append(f"{prefix}: score must be 0-100")
        except Exception:
            errors.append(f"{prefix}: score must be numeric")
    return errors


def validate_analysis_data(analysis):
    errors = []
    if not isinstance(analysis, dict):
        return ["analysis must be a JSON object"]
    source = analysis.get("source") or {}
    if not isinstance(source, dict):
        errors.append("source must be an object")
        source = {}
    duration = None
    if source.get("duration") not in (None, ""):
        try:
            parsed_duration = parse_time(source.get("duration"))
            if parsed_duration < 0:
                errors.append("source.duration must be non-negative")
            elif parsed_duration > 0:
                duration = parsed_duration
        except Exception as exc:
            errors.append(f"source.duration is invalid: {exc}")
    for field in ["transcript", "frames", "segments", "moments", "entities", "claims", "actions", "questions"]:
        value = analysis.get(field, [])
        if not isinstance(value, list):
            errors.append(f"{field} must be a list")
    if "highlights" in analysis and not isinstance(analysis.get("highlights"), list):
        errors.append("highlights must be a list when provided")
    last_end = -1.0
    for index, item in enumerate(analysis.get("segments") or [], start=1):
        prefix = f"segment {index}"
        if not isinstance(item, dict):
            errors.append(f"{prefix}: must be an object")
            continue
        try:
            start = parse_time(item.get("start"))
            end = parse_time(item.get("end"))
        except Exception as exc:
            errors.append(f"{prefix}: invalid start/end: {exc}")
            continue
        if end <= start:
            errors.append(f"{prefix}: end must be greater than start")
        if duration is not None and end > duration:
            errors.append(f"{prefix}: end exceeds source duration")
        if start < last_end:
            errors.append(f"{prefix}: overlaps previous segment")
        last_end = max(last_end, end)
        if not str(item.get("title", "")).strip():
            errors.append(f"{prefix}: missing title")
        if not str(item.get("summary", "")).strip():
            errors.append(f"{prefix}: missing summary")
        if item.get("importance") not in (None, ""):
            try:
                importance = float(item.get("importance"))
                if importance < 0 or importance > 5:
                    errors.append(f"{prefix}: importance must be 0-5")
            except Exception:
                errors.append(f"{prefix}: importance must be numeric")
    for index, item in enumerate(analysis.get("transcript") or [], start=1):
        prefix = f"transcript {index}"
        if not isinstance(item, dict):
            errors.append(f"{prefix}: must be an object")
            continue
        try:
            start = parse_time(item.get("start"))
            end = parse_time(item.get("end"))
        except Exception as exc:
            errors.append(f"{prefix}: invalid start/end: {exc}")
            continue
        if end <= start:
            errors.append(f"{prefix}: end must be greater than start")
        if not str(item.get("text", "")).strip():
            errors.append(f"{prefix}: missing text")
    moments = analysis.get("moments") or analysis.get("highlights") or []
    if moments:
        errors.extend(validate_plan_data({
            "scenario": "clips",
            "moments": moments,
        }, duration=duration))
    return errors


def validate_transcript_items(items):
    errors = []
    if not isinstance(items, list):
        return ["transcript must be a list"]
    last_end = -1.0
    for index, item in enumerate(items, start=1):
        prefix = f"transcript {index}"
        if not isinstance(item, dict):
            errors.append(f"{prefix}: must be an object")
            continue
        try:
            start = parse_time(item.get("start"))
            end = parse_time(item.get("end"))
        except Exception as exc:
            errors.append(f"{prefix}: invalid start/end: {exc}")
            continue
        if end <= start:
            errors.append(f"{prefix}: end must be greater than start")
        if start < last_end:
            errors.append(f"{prefix}: overlaps previous transcript item")
        last_end = max(last_end, end)
        if not str(item.get("text", "")).strip():
            errors.append(f"{prefix}: missing text")
    return errors


def validate_frame_items(items):
    errors = []
    if not isinstance(items, list):
        return ["frames must be a list"]
    for index, item in enumerate(items, start=1):
        prefix = f"frame {index}"
        if not isinstance(item, dict):
            errors.append(f"{prefix}: must be an object")
            continue
        try:
            parse_time(item.get("timestamp"))
        except Exception as exc:
            errors.append(f"{prefix}: invalid timestamp: {exc}")
        for field in ["ocr", "objects"]:
            value = item.get(field, [])
            if not isinstance(value, list):
                errors.append(f"{prefix}: {field} must be a list")
    return errors


def metadata_source(metadata):
    source = {
        "title": "",
        "duration": 0,
        "width": 0,
        "height": 0,
        "fps": "",
        "has_audio": False,
        "metadata_path": "",
    }
    if not metadata:
        return source
    fmt = metadata.get("format") or {}
    source["title"] = fmt.get("tags", {}).get("title", "") if isinstance(fmt.get("tags"), dict) else ""
    if fmt.get("duration") not in (None, ""):
        source["duration"] = parse_time(fmt.get("duration"))
    for stream in metadata.get("streams") or []:
        if stream.get("codec_type") == "video" and not source["width"]:
            source["width"] = int(stream.get("width") or 0)
            source["height"] = int(stream.get("height") or 0)
            source["fps"] = stream.get("avg_frame_rate") or stream.get("r_frame_rate") or ""
        if stream.get("codec_type") == "audio":
                source["has_audio"] = True
    return source


def analysis_duration(analysis):
    source = analysis.get("source") or {}
    if source.get("duration") not in (None, ""):
        try:
            return parse_time(source.get("duration"))
        except Exception:
            return 0.0
    ends = []
    for field in ["segments", "moments", "transcript"]:
        for item in analysis.get(field) or []:
            if isinstance(item, dict) and item.get("end") not in (None, ""):
                try:
                    ends.append(parse_time(item.get("end")))
                except Exception:
                    pass
    return max(ends) if ends else 0.0


def clamp_window(start, end, duration=0.0, padding=0.0):
    start = max(0.0, parse_time(start) - float(padding))
    end = parse_time(end) + float(padding)
    if duration:
        end = min(float(duration), end)
    return start, max(start, end)


def frame_count_for_interval(duration, interval, max_frames=0):
    if not duration or not interval:
        return 0
    count = int(duration // interval) + 1
    if max_frames:
        count = min(count, int(max_frames))
    return count


def classify_content_type(scenario, content_type):
    if content_type and content_type != "auto":
        return content_type
    if scenario in {"meeting", "course", "qa"}:
        return "transcript_primary"
    if scenario in {"live"}:
        return "visual_dense"
    return "balanced"


def build_analysis_strategy(metadata, scenario="summary", content_type="auto", budget="standard"):
    source = metadata_source(metadata)
    duration = float(source.get("duration") or 0)
    minutes = duration / 60 if duration else 0
    has_audio = bool(source.get("has_audio"))
    classified = classify_content_type(scenario, content_type)

    if minutes and minutes <= 5:
        intervals = {"quick": 30, "standard": 10, "deep": 5}
    elif minutes <= 15:
        intervals = {"quick": 60, "standard": 30, "deep": 10}
    elif minutes <= 30:
        intervals = {"quick": 90, "standard": 60, "deep": 30}
    elif minutes <= 60:
        intervals = {"quick": 180, "standard": 120, "deep": 60}
    else:
        intervals = {"quick": 300, "standard": 180, "deep": 120}

    if classified == "visual_dense":
        intervals = {key: max(5, value / 2) for key, value in intervals.items()}
    elif classified == "transcript_primary":
        intervals = {key: value * 2 for key, value in intervals.items()}

    max_frames_by_budget = {"quick": 40, "standard": 80, "deep": 160}
    refine_interval_by_budget = {"quick": 10, "standard": 5, "deep": 3}
    budget = budget if budget in max_frames_by_budget else "standard"
    coarse_interval = float(intervals[budget])
    max_frames = max_frames_by_budget[budget]
    estimated_frames = frame_count_for_interval(duration, coarse_interval, max_frames=max_frames)
    if estimated_frames >= max_frames and duration:
        coarse_interval = max(coarse_interval, duration / max_frames)
        estimated_frames = frame_count_for_interval(duration, coarse_interval, max_frames=max_frames)

    return {
        "schema": "analysis_strategy.v1",
        "scenario": scenario,
        "content_type": classified,
        "budget": budget,
        "source": source,
        "duration_seconds": duration,
        "duration_minutes": round(minutes, 2),
        "recommended": {
            "asr_scope": "full" if has_audio else "none",
            "coarse_frame_interval": round(coarse_interval, 2),
            "coarse_max_frames": max_frames,
            "estimated_coarse_frames": estimated_frames,
            "vlm_scope": "coarse_frames_then_refine_windows",
            "refine_frame_interval": refine_interval_by_budget[budget],
            "refine_window_padding": 5,
        },
        "rationale": [
            "Use ASR as the low-cost full-video signal when audio exists." if has_audio else "No audio stream detected; visual review is the primary signal.",
            "Use low-frequency frame review for whole-video structure.",
            "Run multimodal review only on candidate windows selected by refine-plan.",
        ],
        "commands": [
            "python3 scripts/video_understanding.py extract-audio <video> --output <workdir>/audio.wav" if has_audio else "",
            f"python3 scripts/video_understanding.py sample-frames <video> --output-dir <workdir>/frames --interval {round(coarse_interval, 2)} --max-frames {max_frames}",
            f"python3 scripts/video_understanding.py prepare-frame-review --frames-dir <workdir>/frames --interval {round(coarse_interval, 2)} --output <workdir>/frame_review_manifest.json --prompt-output <workdir>/frame_review_prompt.md",
            "python3 scripts/video_understanding.py refine-plan --analysis <workdir>/video_analysis.json --output <workdir>/refine_plan.json",
        ],
    }


REFINE_REASON_KEYWORDS = [
    "封面",
    "预告",
    "片尾",
    "视觉冲击",
    "人物关系",
    "地点不确定",
    "不确定",
    "核验",
    "OCR",
    "字幕",
    "招牌",
    "路牌",
]


def text_contains_any(text, keywords):
    haystack = str(text or "").lower()
    return [keyword for keyword in keywords if str(keyword).lower() in haystack]


def time_overlap(a_start, a_end, b_start, b_end):
    return parse_time(a_start) < parse_time(b_end) and parse_time(a_end) > parse_time(b_start)


def questions_for_window(questions, start, end):
    hits = []
    for question in questions or []:
        if not isinstance(question, dict):
            continue
        if question.get("timestamp") in (None, ""):
            hits.append(question)
            continue
        try:
            ts = parse_time(question.get("timestamp"))
        except Exception:
            continue
        if parse_time(start) <= ts <= parse_time(end):
            hits.append(question)
    return hits


def moments_for_segment(moments, segment):
    start = parse_time(segment.get("start"))
    end = parse_time(segment.get("end"))
    hits = []
    for moment in moments or []:
        if not isinstance(moment, dict):
            continue
        if moment.get("start") in (None, "") or moment.get("end") in (None, ""):
            continue
        try:
            if time_overlap(start, end, moment.get("start"), moment.get("end")):
                hits.append(moment)
        except Exception:
            pass
    return hits


def refine_priority(condition_count):
    if condition_count >= 3:
        return "P0"
    if condition_count >= 2:
        return "P1"
    if condition_count >= 1:
        return "P2"
    return "skip"


def recommended_refine_interval(priority, default_interval=5):
    if priority == "P0":
        return min(float(default_interval), 3.0)
    if priority == "P1":
        return float(default_interval)
    if priority == "P2":
        return max(float(default_interval), 10.0)
    return float(default_interval)


def segment_needs_refine(analysis, segment, args=None):
    source = analysis.get("source") or {}
    observations = analysis.get("observations") or {}
    moments = analysis.get("moments") or analysis.get("highlights") or []
    questions = analysis.get("questions") or []
    has_audio = bool(source.get("has_audio"))
    transcript_count = int(observations.get("transcript_count") or len(analysis.get("transcript") or []))
    start = parse_time(segment.get("start"))
    end = parse_time(segment.get("end"))
    matched_moments = moments_for_segment(moments, segment)
    matched_questions = questions_for_window(questions, start, end)
    conditions = []

    try:
        importance = float(segment.get("importance", 0) or 0)
    except Exception:
        importance = 0
    if importance >= 5:
        conditions.append("importance >= 5")

    high_score_moments = []
    for moment in matched_moments:
        try:
            if float(moment.get("score", 0) or 0) >= 90:
                high_score_moments.append(moment)
        except Exception:
            pass
    if high_score_moments:
        conditions.append("overlapping moment score >= 90")

    text_parts = [
        segment.get("title", ""),
        segment.get("summary", ""),
        " ".join(str(value) for value in segment.get("topics", []) or []),
        " ".join(str(value) for value in segment.get("visuals", []) or []),
    ]
    for moment in matched_moments:
        text_parts.extend([
            moment.get("title", ""),
            moment.get("summary", ""),
            moment.get("reason", ""),
            " ".join(str(value) for value in moment.get("tags", []) or []),
            " ".join(str(value) for value in moment.get("takeaways", []) or []),
        ])
    keyword_hits = text_contains_any(" ".join(text_parts), REFINE_REASON_KEYWORDS)
    if keyword_hits:
        conditions.append("reason/title/summary contains: " + ", ".join(keyword_hits[:5]))

    if has_audio and transcript_count == 0:
        conditions.append("has_audio = true and transcript_count = 0")

    if matched_questions:
        conditions.append("questions present for window")

    priority = refine_priority(len(conditions))
    default_interval = getattr(args, "refine_interval", 5) if args else 5
    padding = getattr(args, "padding", 5) if args else 5
    duration = analysis_duration(analysis)
    win_start, win_end = clamp_window(start, end, duration=duration, padding=padding)
    needs_ocr = bool(keyword_hits) and any(word in " ".join(keyword_hits) for word in ["OCR", "字幕", "招牌", "路牌", "地点不确定", "不确定"])
    needs_asr = bool(has_audio and (transcript_count == 0 or matched_questions or high_score_moments))
    return {
        "segment_id": segment.get("id", ""),
        "segment_title": segment.get("title", ""),
        "start": win_start,
        "end": win_end,
        "source_start": start,
        "source_end": end,
        "priority": priority,
        "condition_count": len(conditions),
        "conditions": conditions,
        "matched_moments": [
            {
                "title": moment.get("title", ""),
                "start": moment.get("start"),
                "end": moment.get("end"),
                "score": moment.get("score"),
            }
            for moment in matched_moments
        ],
        "recommended_frame_interval": recommended_refine_interval(priority, default_interval=default_interval),
        "needs_vlm": priority != "skip",
        "needs_ocr": needs_ocr,
        "needs_asr": needs_asr,
        "questions": matched_questions,
    }


def build_refine_plan(analysis, min_conditions=1, args=None):
    errors = validate_analysis_data(analysis)
    if errors:
        raise ValueError("; ".join(errors))
    windows = []
    for segment in get_segments(analysis):
        decision = segment_needs_refine(analysis, segment, args=args)
        if decision["condition_count"] >= min_conditions:
            windows.append(decision)
    priority_rank = {"P0": 0, "P1": 1, "P2": 2, "skip": 3}
    windows.sort(key=lambda item: (priority_rank.get(item["priority"], 9), parse_time(item["start"])))
    return {
        "schema": "refine_plan.v1",
        "source_title": (analysis.get("source") or {}).get("title", ""),
        "rules": [
            "importance >= 5",
            "overlapping moment score >= 90",
            "reason/title/summary contains high-value or uncertainty keywords",
            "has_audio = true and transcript_count = 0",
            "questions present for the window",
        ],
        "priority_rules": {
            "P0": "3 or more conditions",
            "P1": "2 conditions",
            "P2": "1 condition",
        },
        "windows": windows,
    }


def parse_priority_filter(value):
    if not value:
        return {"P0", "P1"}
    return {item.strip().upper() for item in str(value).split(",") if item.strip()}


def refine_window_dir_name(window, index):
    label = window.get("segment_title") or window.get("segment_id") or f"window-{index}"
    return f"{index:02d}-{window.get('priority', 'P')}-{safe_slug(label, f'window-{index:02d}')}"


def run_sample_window_frames(video, window, frames_dir, interval, width):
    frames_dir.mkdir(parents=True, exist_ok=True)
    vf = f"fps=1/{interval},scale='min({width},iw)':-2"
    run_command([
        "ffmpeg",
        "-y",
        "-ss",
        str(window["start"]),
        "-to",
        str(window["end"]),
        "-i",
        video,
        "-vf",
        vf,
        "-q:v",
        "3",
        str(frames_dir / "frame_%05d.jpg"),
    ])


def run_extract_window_audio(video, window, output):
    output.parent.mkdir(parents=True, exist_ok=True)
    run_command([
        "ffmpeg",
        "-y",
        "-ss",
        str(window["start"]),
        "-to",
        str(window["end"]),
        "-i",
        video,
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        str(output),
    ])


def execute_refine_plan(refine_plan, video, output_dir, priorities=None, language="Chinese", width=960, skip_audio=False):
    priority_filter = parse_priority_filter(priorities)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    execution_windows = []
    for index, window in enumerate(refine_plan.get("windows") or [], start=1):
        if window.get("priority") not in priority_filter:
            continue
        interval = float(window.get("recommended_frame_interval") or 5)
        window_dir = out / refine_window_dir_name(window, len(execution_windows) + 1)
        frames_dir = window_dir / "frames"
        window_dir.mkdir(parents=True, exist_ok=True)
        window_record = {
            "window": window,
            "directory": str(window_dir),
            "frames_dir": str(frames_dir),
            "frame_interval": interval,
            "frame_review_manifest": str(window_dir / "frame_review_manifest.json"),
            "frame_review_prompt": str(window_dir / "frame_review_prompt.md"),
            "frame_review_output": str(window_dir / "frame_review_output.json"),
            "frame_observations": str(window_dir / "frame_observations.json"),
            "transcript": str(window_dir / "transcript.json"),
            "audio": str(window_dir / "audio.wav") if window.get("needs_asr") and not skip_audio else "",
        }
        run_sample_window_frames(video, window, frames_dir, interval=interval, width=width)
        manifest = build_frame_review_manifest(
            frames_dir,
            interval=interval,
            start_time=parse_time(window["start"]),
            relative_to=window_dir,
        )
        Path(window_record["frame_review_manifest"]).write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        Path(window_record["frame_review_prompt"]).write_text(frame_review_prompt(manifest, language), encoding="utf-8")
        if window_record["audio"]:
            run_extract_window_audio(video, window, Path(window_record["audio"]))
        (window_dir / "window.json").write_text(json.dumps(window_record, ensure_ascii=False, indent=2), encoding="utf-8")
        execution_windows.append(window_record)
    return {
        "schema": "refine_execution.v1",
        "source_video": video,
        "priorities": sorted(priority_filter),
        "language": language,
        "windows": execution_windows,
    }


def unique_time_path_items(items):
    seen = set()
    output = []
    for item in sorted(items, key=lambda value: parse_time(value.get("timestamp", value.get("start", 0)))):
        key = (
            round(parse_time(item.get("timestamp", item.get("start", 0))), 3),
            str(item.get("path", item.get("text", ""))),
        )
        if key in seen:
            continue
        seen.add(key)
        output.append(item)
    return output


def load_refine_execution(execution_manifest=None, refine_dir=None):
    if execution_manifest:
        return load_plan(execution_manifest)
    if not refine_dir:
        raise ValueError("merge requires --execution-manifest or --refine-dir")
    root = Path(refine_dir)
    windows = []
    for path in sorted(root.glob("*/window.json")):
        windows.append(load_plan(path))
    return {
        "schema": "refine_execution.v1",
        "source_video": "",
        "windows": windows,
    }


def load_window_frame_observations(window_record, normalize_outputs=False):
    observations_path = Path(window_record.get("frame_observations") or "")
    if observations_path.exists():
        return load_list_payload(observations_path, "frames")
    review_path = Path(window_record.get("frame_review_output") or "")
    manifest_path = Path(window_record.get("frame_review_manifest") or "")
    if review_path.exists():
        manifest = load_plan(manifest_path) if manifest_path.exists() else None
        frames = normalize_frame_review_payload(load_plan(review_path), manifest=manifest)
        if normalize_outputs and observations_path:
            observations_path.parent.mkdir(parents=True, exist_ok=True)
            observations_path.write_text(json.dumps({
                "schema": "frame_observations.v1",
                "source_review": str(review_path),
                "frames": frames,
            }, ensure_ascii=False, indent=2), encoding="utf-8")
        return frames
    return []


def merge_refine_results(analysis, execution, normalize_outputs=False):
    merged = json.loads(json.dumps(analysis, ensure_ascii=False))
    all_frames = list(merged.get("frames") or [])
    all_transcript = list(merged.get("transcript") or [])
    merged_frame_count = 0
    merged_transcript_count = 0
    windows_used = []
    for window_record in execution.get("windows") or []:
        frames = load_window_frame_observations(window_record, normalize_outputs=normalize_outputs)
        transcript_path = Path(window_record.get("transcript") or "")
        transcript = load_list_payload(transcript_path, "transcript") if transcript_path.exists() else []
        if frames or transcript:
            windows_used.append({
                "segment_id": (window_record.get("window") or {}).get("segment_id", ""),
                "priority": (window_record.get("window") or {}).get("priority", ""),
                "frames_added": len(frames),
                "transcript_items_added": len(transcript),
            })
        all_frames.extend(frames)
        all_transcript.extend(transcript)
        merged_frame_count += len(frames)
        merged_transcript_count += len(transcript)
    merged["frames"] = unique_time_path_items(all_frames)
    merged["transcript"] = sorted(all_transcript, key=lambda item: parse_time(item.get("start", 0)))
    observations = merged.get("observations") or {}
    observations["frame_count"] = len(merged["frames"])
    observations["transcript_count"] = len(merged["transcript"])
    observations["refined_frame_count"] = merged_frame_count
    observations["refined_transcript_count"] = merged_transcript_count
    merged["observations"] = observations
    merged["refinement"] = {
        "schema": "refinement_merge.v1",
        "source_video": execution.get("source_video", ""),
        "windows_used": windows_used,
    }
    errors = validate_analysis_data(merged)
    if errors:
        raise ValueError("; ".join(errors))
    return merged


def segment_summary(transcript_items, frame_items):
    text = " ".join(str(item.get("text", "")).strip() for item in transcript_items if item.get("text"))
    captions = [str(item.get("caption", "")).strip() for item in frame_items if item.get("caption")]
    if text and captions:
        return f"{text} Visual context: {'; '.join(captions[:2])}."
    if text:
        return text
    if captions:
        return "; ".join(captions[:3])
    return "Segment generated from available timestamped observations."


def build_segments_from_inputs(transcript, frames, max_duration=90.0, gap=8.0):
    timeline = sorted(transcript, key=lambda item: parse_time(item.get("start")))
    segments = []
    current = []
    for item in timeline:
        start = parse_time(item.get("start"))
        end = parse_time(item.get("end"))
        if not current:
            current = [item]
            continue
        current_start = parse_time(current[0].get("start"))
        current_end = parse_time(current[-1].get("end"))
        should_split = (start - current_end > gap) or (end - current_start > max_duration)
        if should_split:
            segments.append(current)
            current = [item]
        else:
            current.append(item)
    if current:
        segments.append(current)
    if not segments and frames:
        sorted_frames = sorted(frames, key=lambda item: parse_time(item.get("timestamp")))
        for frame in sorted_frames:
            ts = parse_time(frame.get("timestamp"))
            segments.append([{"start": ts, "end": ts + 5, "text": frame.get("caption", "")}])
    output = []
    for index, items in enumerate(segments, start=1):
        start = parse_time(items[0].get("start"))
        end = max(parse_time(item.get("end")) for item in items)
        frame_hits = [
            frame for frame in frames
            if frame.get("timestamp") is not None and start <= parse_time(frame.get("timestamp")) <= end
        ]
        visuals = [frame.get("caption") for frame in frame_hits if frame.get("caption")]
        topics = sorted({topic for item in items for topic in item.get("topics", [])}) if any(isinstance(item.get("topics"), list) for item in items) else []
        output.append({
            "id": f"seg_{index:04d}",
            "start": start,
            "end": end,
            "title": f"Segment {index}",
            "summary": segment_summary(items, frame_hits),
            "topics": topics,
            "visuals": visuals,
            "importance": 3,
            "evidence": [
                {"type": "transcript", "count": len(items)},
                {"type": "frame", "count": len(frame_hits)},
            ],
        })
    return output


def cmd_validate_transcript(args):
    items = load_list_payload(args.transcript, "transcript")
    errors = validate_transcript_items(items)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        raise SystemExit(1)
    print("Transcript is valid")


def cmd_validate_frames(args):
    items = load_list_payload(args.frames, "frames")
    errors = validate_frame_items(items)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        raise SystemExit(1)
    print("Frame observations are valid")


def cmd_build_segments(args):
    transcript = load_list_payload(args.transcript, "transcript") if args.transcript else []
    frames = load_list_payload(args.frames, "frames") if args.frames else []
    metadata = load_plan(args.metadata) if args.metadata else {}
    errors = validate_transcript_items(transcript) + validate_frame_items(frames)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        raise SystemExit(1)
    source = metadata_source(metadata)
    if args.title:
        source["title"] = args.title
    if args.metadata:
        source["metadata_path"] = args.metadata
    segments = build_segments_from_inputs(transcript, frames, max_duration=args.max_segment_duration, gap=args.gap)
    analysis = {
        "scenario": args.scenario,
        "source": source,
        "raw_inputs": {
            "metadata_path": args.metadata or "",
            "transcript_path": args.transcript or "",
            "frame_observations_path": args.frames or "",
        },
        "observations": {
            "transcript_count": len(transcript),
            "frame_count": len(frames),
        },
        "summary": args.summary or "",
        "transcript": transcript,
        "frames": frames,
        "segments": segments,
        "moments": [],
        "entities": [],
        "claims": [],
        "actions": [],
        "questions": [],
    }
    errors = validate_analysis_data(analysis)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        raise SystemExit(1)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote analysis to {args.output}")


def cmd_init_analysis(args):
    out = Path(args.output)
    for name in ["frames", "clips", "notes", "site"]:
        (out / name).mkdir(parents=True, exist_ok=True)
    analysis = {
        "scenario": args.scenario,
        "source": {
            "title": "",
            "duration": 0,
            "width": 0,
            "height": 0,
            "fps": "",
            "has_audio": False,
            "metadata_path": "metadata.json",
        },
        "raw_inputs": {
            "metadata_path": "metadata.json",
            "transcript_path": "transcript.json",
            "frame_observations_path": "frame_observations.json",
        },
        "observations": {
            "transcript_count": 0,
            "frame_count": 0,
        },
        "summary": "",
        "transcript": [],
        "frames": [],
        "segments": [],
        "moments": [],
        "entities": [],
        "claims": [],
        "actions": [],
        "questions": [],
    }
    (out / "video_analysis.json").write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")
    prompt = (
        "Analyze the video inputs and return strict JSON matching references/video-analysis-schema.md.\n"
        f"Scenario: {args.scenario}\n"
        "Use timestamped transcript, sampled frame observations, OCR, and metadata. "
        "Return segments first; derive selected moments only when they are useful for the requested task.\n"
    )
    (out / "model_prompt.txt").write_text(prompt, encoding="utf-8")
    print(f"Created analysis project at {out}")


def cmd_init_project(args):
    out = Path(args.output)
    for name in ["frames", "clips", "notes"]:
        (out / name).mkdir(parents=True, exist_ok=True)
    scenario = args.scenario
    skeleton = {
        "scenario": scenario,
        "source_title": "",
        "summary": "",
        "segments": [],
        "moments": [],
        "report": {"key_points": [], "claims_to_verify": [], "action_items": []},
    }
    (out / "clip_plan.json").write_text(json.dumps(skeleton, ensure_ascii=False, indent=2), encoding="utf-8")
    prompt = (
        "Analyze the video inputs and return strict JSON matching references/analysis-schema.md.\n"
        f"Scenario: {scenario}\n"
        "Use exact timestamps. Include moments with start, end, title, summary, reason, score, tags, and subtitles when available.\n"
    )
    (out / "model_prompt.txt").write_text(prompt, encoding="utf-8")
    print(f"Created project at {out}")


def cmd_probe(args):
    command = [
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        args.video,
    ]
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise SystemExit("Missing executable: ffprobe") from exc
    except subprocess.CalledProcessError as exc:
        raise SystemExit(exc.stderr or "ffprobe failed") from exc
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(result.stdout, encoding="utf-8")
    print(f"Wrote metadata to {args.output}")


def cmd_plan_analysis(args):
    metadata = load_plan(args.metadata) if args.metadata else {}
    strategy = build_analysis_strategy(
        metadata,
        scenario=args.scenario,
        content_type=args.content_type,
        budget=args.budget,
    )
    strategy["commands"] = [command for command in strategy.get("commands", []) if command]
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(strategy, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote analysis strategy to {args.output}")


def cmd_extract_audio(args):
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    run_command([
        "ffmpeg",
        "-y",
        "-i",
        args.video,
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        args.output,
    ])
    print(f"Wrote audio to {args.output}")


def cmd_sample_frames(args):
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    vf = f"fps=1/{args.interval},scale='min({args.width},iw)':-2"
    if args.max_frames:
        vf = f"{vf},trim=end_frame={args.max_frames}"
    run_command([
        "ffmpeg",
        "-y",
        "-i",
        args.video,
        "-vf",
        vf,
        "-q:v",
        "3",
        str(out / "frame_%05d.jpg"),
    ])
    print(f"Wrote frames to {out}")


def cmd_prepare_frame_review(args):
    manifest = build_frame_review_manifest(
        args.frames_dir,
        args.interval,
        start_time=args.start_time,
        relative_to=args.relative_to,
    )
    if not manifest["frames"]:
        raise SystemExit(f"No frame images found in {args.frames_dir}")
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.prompt_output:
        Path(args.prompt_output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.prompt_output).write_text(frame_review_prompt(manifest, args.language), encoding="utf-8")
    print(f"Wrote frame review manifest with {len(manifest['frames'])} frames to {args.output}")
    if args.prompt_output:
        print(f"Wrote frame review prompt to {args.prompt_output}")


def cmd_ingest_frame_review(args):
    review = load_plan(args.review)
    manifest = load_plan(args.manifest) if args.manifest else None
    frames = normalize_frame_review_payload(review, manifest=manifest)
    errors = validate_frame_items(frames)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        raise SystemExit(1)
    payload = {
        "schema": "frame_observations.v1",
        "source_review": args.review,
        "frames": frames,
    }
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(frames)} frame observations to {args.output}")


def cmd_refine_plan(args):
    analysis = load_plan(args.analysis)
    try:
        plan = build_refine_plan(analysis, min_conditions=args.min_conditions, args=args)
    except ValueError as exc:
        raise SystemExit(f"ERROR: {exc}") from exc
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote refine plan with {len(plan['windows'])} windows to {args.output}")


def cmd_execute_refine_plan(args):
    refine_plan = load_plan(args.plan)
    execution = execute_refine_plan(
        refine_plan,
        video=args.video,
        output_dir=args.output_dir,
        priorities=args.priorities,
        language=args.language,
        width=args.width,
        skip_audio=args.skip_audio,
    )
    manifest_path = Path(args.output_manifest or Path(args.output_dir) / "refine_execution_manifest.json")
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(execution, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote refine execution manifest with {len(execution['windows'])} windows to {manifest_path}")


def cmd_merge_refine_results(args):
    analysis = load_plan(args.analysis)
    try:
        execution = load_refine_execution(execution_manifest=args.execution_manifest, refine_dir=args.refine_dir)
        merged = merge_refine_results(analysis, execution, normalize_outputs=args.normalize_outputs)
    except ValueError as exc:
        raise SystemExit(f"ERROR: {exc}") from exc
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote merged refined analysis to {args.output}")


def write_srt(path, subtitles, clip_start):
    lines = []
    for index, sub in enumerate(subtitles, start=1):
        start = parse_time(sub.get("start")) - clip_start
        end = parse_time(sub.get("end")) - clip_start
        text = str(sub.get("text", "")).strip()
        if not text or end <= 0:
            continue
        lines.extend([
            str(index),
            f"{format_timestamp(max(0, start))} --> {format_timestamp(max(0, end))}",
            text,
            "",
        ])
    if lines:
        path.write_text("\n".join(lines), encoding="utf-8")


def cmd_validate_plan(args):
    plan = load_plan(args.plan)
    duration = parse_time(args.duration) if args.duration else None
    errors = validate_plan_data(plan, duration=duration)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        raise SystemExit(1)
    print("Plan is valid")


def cmd_validate_analysis(args):
    analysis = load_plan(args.analysis)
    errors = validate_analysis_data(analysis)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        raise SystemExit(1)
    print("Analysis is valid")


def segment_to_highlight(item, index):
    start = parse_time(item.get("start"))
    end = parse_time(item.get("end"))
    importance = item.get("importance", 3)
    try:
        score = min(95, max(60, 55 + float(importance) * 8))
    except Exception:
        score = 75
    topics = item.get("topics") or []
    visuals = item.get("visuals") or []
    takeaways = []
    if item.get("summary"):
        takeaways.append(str(item.get("summary")))
    if visuals:
        takeaways.append("Visual evidence: " + ", ".join(str(value) for value in visuals[:3]))
    return {
        "start": start,
        "end": end,
        "title": item.get("title") or f"Moment {index}",
        "summary": item.get("summary") or "",
        "reason": item.get("reason") or "Selected from the highest-importance video segments.",
        "score": round(score),
        "tags": topics,
        "quote": item.get("quote", ""),
        "takeaways": takeaways,
        "subtitles": item.get("subtitles") or [],
    }


def cmd_derive_highlight(args):
    analysis = load_plan(args.analysis)
    errors = validate_analysis_data(analysis)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        raise SystemExit(1)
    moments = analysis.get("moments") or analysis.get("highlights") or []
    if not moments:
        segments = sorted(
            get_segments(analysis),
            key=lambda item: (float(item.get("importance", 0) or 0), parse_time(item.get("end")) - parse_time(item.get("start"))),
            reverse=True,
        )
        moments = [segment_to_highlight(item, index) for index, item in enumerate(segments[:args.target_count], start=1)]
        moments.sort(key=lambda item: parse_time(item["start"]))
    plan = {
        "scenario": "clips",
        "source_title": (analysis.get("source") or {}).get("title") or analysis.get("source_title", ""),
        "summary": analysis.get("summary", ""),
        "segments": analysis.get("segments") or [],
        "moments": moments,
        "report": {
            "key_points": analysis.get("key_points") or [],
            "claims_to_verify": analysis.get("claims") or [],
            "action_items": analysis.get("actions") or [],
        },
    }
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote clip plan to {args.output}")


def cmd_summary(args):
    analysis = load_plan(args.analysis)
    errors = validate_analysis_data(analysis)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        raise SystemExit(1)
    source = analysis.get("source") or {}
    lines = [
        f"# {source.get('title') or 'Video Summary'}",
        "",
        analysis.get("summary") or "",
        "",
        "## Timeline",
        "",
    ]
    for item in get_segments(analysis):
        lines.extend([
            f"### {format_seconds(parse_time(item.get('start')))} - {format_seconds(parse_time(item.get('end')))} · {item.get('title', '')}",
            "",
            str(item.get("summary", "")),
            "",
        ])
    if analysis.get("actions"):
        lines.extend(["## Action Items", ""])
        for action in analysis.get("actions") or []:
            lines.append(f"- {action.get('task', '')} {action.get('owner', '')} {action.get('due', '')}".strip())
        lines.append("")
    if analysis.get("claims"):
        lines.extend(["## Claims To Verify", ""])
        for claim in analysis.get("claims") or []:
            timestamp = claim.get("timestamp", "")
            lines.append(f"- {claim.get('claim', '')} ({timestamp})")
        lines.append("")
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    print(f"Wrote summary to {args.output}")


def cmd_search_index(args):
    analysis = load_plan(args.analysis)
    errors = validate_analysis_data(analysis)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        raise SystemExit(1)
    transcript = analysis.get("transcript") or []
    frames = analysis.get("frames") or []
    source = analysis.get("source") or {}
    entities = analysis.get("entities") or []
    rows = []
    for index, segment in enumerate(get_segments(analysis), start=1):
        start = parse_time(segment.get("start"))
        end = parse_time(segment.get("end"))
        transcript_hits = [
            item for item in transcript
            if item.get("start") is not None and item.get("end") is not None
            and parse_time(item.get("start")) < end and parse_time(item.get("end")) > start
        ]
        transcript_text = " ".join(
            str(item.get("text", ""))
            for item in transcript_hits
        )
        frame_hits = [
            item for item in frames
            if item.get("timestamp") is not None and start <= parse_time(item.get("timestamp")) <= end
        ]
        ocr_items = [text for frame in frame_hits for text in frame.get("ocr", [])]
        visual_text = " ".join(str(item.get("caption", "")) for item in frame_hits if item.get("caption"))
        entity_hits = [
            item.get("name") for item in entities
            if any(start <= parse_time(ts) <= end for ts in item.get("timestamps", []) or [])
        ]
        row = {
            "segment_id": segment.get("id") or f"seg_{index:04d}",
            "source_title": source.get("title", ""),
            "source_video": source.get("path", ""),
            "start": start,
            "end": end,
            "title": segment.get("title", ""),
            "summary": segment.get("summary", ""),
            "topics": segment.get("topics") or [],
            "entities": entity_hits,
            "visuals": segment.get("visuals") or [],
            "ocr": ocr_items,
            "transcript_text": transcript_text,
            "visual_text": visual_text,
            "ocr_text": " ".join(str(item) for item in ocr_items),
            "text": " ".join(value for value in [segment.get("summary", ""), transcript_text, visual_text, " ".join(str(item) for item in ocr_items)] if value),
            "evidence": segment.get("evidence") or [
                {"type": "transcript", "count": len(transcript_hits)},
                {"type": "frame", "count": len(frame_hits)},
            ],
        }
        rows.append(row)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"Wrote {len(rows)} search rows to {args.output}")


def cmd_cut(args):
    plan = load_plan(args.plan)
    errors = validate_plan_data(plan)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        raise SystemExit(1)
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    generated = []
    for index, item in enumerate(get_highlights(plan), start=1):
        start = parse_time(item["start"])
        end = parse_time(item["end"])
        title = item.get("title", f"clip-{index}")
        slug = safe_slug(title, f"clip-{index:02}")
        clip_path = out / f"{index:02d}-{slug}.mp4"
        command = ["ffmpeg", "-y", "-ss", str(start), "-to", str(end), "-i", args.video]
        if args.copy:
            command.extend(["-map", "0", "-c", "copy"])
        else:
            command.extend(["-map", "0:v:0", "-map", "0:a?", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac"])
        command.append(str(clip_path))
        run_command(command)
        subtitles = item.get("subtitles") or []
        if subtitles:
            write_srt(clip_path.with_suffix(".srt"), subtitles, start)
        generated.append(str(clip_path))
    manifest = {"source": args.video, "clips": generated}
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(generated)} clips to {out}")


def cmd_page(args):
    plan = load_plan(args.plan)
    clips_dir = Path(args.clips_dir)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    media_dir = out.parent / args.media_dir
    title = plan.get("source_title") or "Video Recap"
    summary = plan.get("summary") or ""
    source_rel = ""
    if args.source_video:
        source_path = Path(args.source_video)
        if args.copy_media:
            source_path = copy_media_file(source_path, media_dir, prefix="source-")
        source_rel = relative_url(source_path, out.parent)
    playlist = []
    active_details = ""
    initial_src = source_rel
    initial_badge = "Original Video" if source_rel else "Selected Moment"
    initial_title = title
    initial_summary = summary
    if source_rel:
        active_details = '<p class="reason">Select a moment from the right playlist to load it in the main player.</p>'
    else:
        active_details = ""
    for index, item in enumerate(get_highlights(plan), start=1):
        start = parse_time(item.get("start"))
        end = parse_time(item.get("end"))
        slug = safe_slug(item.get("title", ""), f"clip-{index:02}")
        expected = clips_dir / f"{index:02d}-{slug}.mp4"
        if not expected.exists():
            matches = sorted(clips_dir.glob(f"{index:02d}-*.mp4"))
            expected = matches[0] if matches else expected
        if args.copy_media and expected.exists():
            expected = copy_media_file(expected, media_dir / "clips")
            srt = Path(expected).with_suffix(".srt")
            original_srt = (clips_dir / expected.name).with_suffix(".srt")
            if original_srt.exists() and not srt.exists():
                copy_media_file(original_srt, media_dir / "clips")
        rel = relative_url(expected, out.parent)
        if not initial_src:
            initial_src = rel
            initial_title = item.get("title", f"Clip {index}")
            initial_summary = item.get("summary", "")
        if not active_details:
            active_details = render_active_details(item, start, end, rel)
        duration = f"{format_seconds(start)} - {format_seconds(end)}"
        playlist.append(f"""
          <button class="playlist-item{' active' if not source_rel and index == 1 else ''}" type="button"
            data-src="{html.escape(rel, quote=True)}"
            data-title="{html.escape(str(item.get('title', f'Clip {index}')), quote=True)}"
            data-summary="{html.escape(str(item.get('summary', '')), quote=True)}"
            data-start="{html.escape(str(start), quote=True)}"
            data-end="{html.escape(str(end), quote=True)}"
            data-score="{html.escape(str(item.get('score', '')), quote=True)}"
            data-reason="{html.escape(str(item.get('reason', '')), quote=True)}"
            data-quote="{html.escape(str(item.get('quote', '')), quote=True)}"
            data-takeaways="{html.escape(json.dumps(item.get('takeaways') or [], ensure_ascii=False), quote=True)}"
            data-tags="{html.escape(json.dumps(item.get('tags') or [], ensure_ascii=False), quote=True)}">
            <span class="playlist-preview">
              <video muted playsinline preload="metadata" src="{html.escape(rel, quote=True)}"></video>
              <span class="playlist-index">{index:02d}</span>
            </span>
            <span class="playlist-copy">
              <strong>{html.escape(str(item.get('title', f'Clip {index}')))}</strong>
              <span>{html.escape(duration)} · Score {html.escape(str(item.get('score', '')))}</span>
              <small>{html.escape(str(item.get('summary', '')))}</small>
            </span>
          </button>
        """)
    report = render_report(plan)
    doc = PAGE_TEMPLATE.format(
        title=html.escape(str(title)),
        summary=html.escape(str(summary)),
        source_video=html.escape(source_rel, quote=True),
        initial_src=html.escape(initial_src, quote=True),
        initial_badge=html.escape(initial_badge),
        initial_title=html.escape(str(initial_title)),
        initial_summary=html.escape(str(initial_summary)),
        active_details=active_details,
        playlist="\n".join(playlist),
        highlight_count=len(get_highlights(plan)),
        scenario=html.escape(str(plan.get("scenario", "clips"))),
        report=report,
        github_url="https://github.com/BENGBONG/LP-Vedio-Analysis",
    )
    out.write_text(doc, encoding="utf-8")
    print(f"Wrote page to {out}")


def format_seconds(seconds):
    seconds = int(round(float(seconds)))
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours:
        return f"{hours:02}:{minutes:02}:{secs:02}"
    return f"{minutes:02}:{secs:02}"


PAGE_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #fafafa;
      --text: #0a0a0a;
      --muted: #666666;
      --soft: #8a8a8a;
      --line: #e5e5e5;
      --panel: #ffffff;
      --subtle: #f5f5f5;
      --inverse: #ffffff;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--text);
    }}
    a {{ color: inherit; text-decoration: none; }}
    header {{
      padding: 18px min(4vw, 52px);
      border-bottom: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.92);
      position: sticky;
      top: 0;
      z-index: 10;
      backdrop-filter: blur(12px);
    }}
    .nav {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
      color: var(--muted);
      font-size: 13px;
    }}
    .brand {{ color: var(--text); font-weight: 700; }}
    .nav-actions {{
      display: flex;
      align-items: center;
      gap: 14px;
    }}
    .github-link {{
      display: inline-flex;
      align-items: center;
      gap: 7px;
      padding: 7px 10px;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: var(--panel);
      color: var(--text);
      font-weight: 650;
    }}
    .github-link svg {{ width: 16px; height: 16px; }}
    main {{
      max-width: 1440px;
      margin: 0 auto;
      padding: 22px min(3vw, 36px) 48px;
    }}
    .page-title {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 20px;
      align-items: end;
      margin-bottom: 18px;
    }}
    h1 {{
      margin: 0 0 8px;
      max-width: 900px;
      font-size: clamp(28px, 4vw, 56px);
      line-height: 1;
      letter-spacing: 0;
    }}
    .summary {{
      margin: 0;
      max-width: 880px;
      color: var(--muted);
      font-size: 15px;
      line-height: 1.6;
    }}
    .stats {{
      display: flex;
      gap: 8px;
      justify-content: end;
      flex-wrap: wrap;
      color: var(--muted);
      font-size: 12px;
      font-weight: 650;
    }}
    .stats span {{
      padding: 6px 9px;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: var(--panel);
    }}
    .watch-layout {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(320px, 380px);
      gap: 18px;
      align-items: start;
    }}
    .player-column {{ min-width: 0; }}
    .player-frame {{
      border: 1px solid #111111;
      border-radius: 8px;
      background: #050505;
      overflow: hidden;
    }}
    .player-frame video {{
      display: block;
      width: 100%;
      height: min(68vh, 760px);
      min-height: 420px;
      background: #050505;
      object-fit: contain;
    }}
    .active-panel {{
      margin-top: 14px;
      padding: 18px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
    }}
    .active-meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 650;
    }}
    .active-meta span,
    .tags span {{
      padding: 4px 8px;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: var(--subtle);
    }}
    h2 {{
      margin: 10px 0 8px;
      font-size: 24px;
      line-height: 1.2;
      letter-spacing: 0;
    }}
    p {{ color: var(--muted); line-height: 1.62; }}
    .reason {{ color: var(--text); }}
    blockquote {{
      margin: 14px 0;
      padding: 12px 14px;
      border-left: 3px solid var(--text);
      background: var(--subtle);
      color: var(--text);
      line-height: 1.55;
    }}
    .takeaways {{
      margin: 12px 0 0;
      padding-left: 18px;
      color: var(--muted);
      line-height: 1.55;
    }}
    .tags {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin: 14px 0;
      color: var(--muted);
      font-size: 12px;
    }}
    .active-actions {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 14px;
    }}
    .active-actions a,
    .active-actions button,
    .original-button {{
      appearance: none;
      border: 1px solid var(--text);
      border-radius: 6px;
      background: var(--text);
      color: var(--inverse);
      padding: 9px 12px;
      font: inherit;
      font-size: 13px;
      font-weight: 650;
      cursor: pointer;
    }}
    .active-actions button.secondary,
    .original-button {{
      background: var(--panel);
      color: var(--text);
    }}
    .playlist-shell {{
      position: sticky;
      top: 78px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      overflow: hidden;
    }}
    .playlist-head {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
      padding: 14px;
      border-bottom: 1px solid var(--line);
    }}
    .playlist-head h2 {{
      margin: 0;
      font-size: 18px;
    }}
    .playlist-head span {{
      color: var(--muted);
      font-size: 12px;
    }}
    .playlist {{
      max-height: calc(100vh - 168px);
      overflow: auto;
      padding: 8px;
    }}
    .playlist-item {{
      width: 100%;
      display: grid;
      grid-template-columns: 116px minmax(0, 1fr);
      gap: 10px;
      padding: 10px;
      border: 1px solid transparent;
      border-radius: 8px;
      background: transparent;
      color: inherit;
      text-align: left;
      cursor: pointer;
    }}
    .playlist-item + .playlist-item {{ margin-top: 6px; }}
    .playlist-item:hover,
    .playlist-item.active {{
      border-color: var(--line);
      background: var(--subtle);
    }}
    .playlist-preview {{
      position: relative;
      display: block;
      width: 116px;
      height: 74px;
      overflow: hidden;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #050505;
    }}
    .playlist-preview video {{
      display: block;
      width: 100%;
      height: 100%;
      object-fit: cover;
      pointer-events: none;
    }}
    .playlist-index {{
      position: absolute;
      left: 6px;
      bottom: 6px;
      width: 28px;
      height: 24px;
      display: grid;
      place-items: center;
      border: 1px solid rgba(255, 255, 255, 0.36);
      border-radius: 6px;
      color: #ffffff;
      font-size: 12px;
      font-weight: 700;
      background: rgba(0, 0, 0, 0.72);
    }}
    .playlist-copy {{
      min-width: 0;
      display: grid;
      gap: 4px;
    }}
    .playlist-copy strong {{
      overflow: hidden;
      color: var(--text);
      font-size: 14px;
      line-height: 1.25;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    .playlist-copy span {{
      color: var(--muted);
      font-size: 12px;
      font-weight: 650;
    }}
    .playlist-copy small {{
      display: -webkit-box;
      overflow: hidden;
      color: var(--soft);
      font-size: 12px;
      line-height: 1.4;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
    }}
    .report-drawer {{
      margin-top: 16px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
    }}
    .report-drawer summary {{
      cursor: pointer;
      padding: 14px 16px;
      font-weight: 650;
    }}
    .notes-grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 14px;
      padding: 0 16px 16px;
    }}
    .notes {{
      padding: 14px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--subtle);
    }}
    .notes h2 {{ margin: 0 0 12px; font-size: 16px; }}
    .notes ul {{ margin: 0; padding-left: 18px; color: var(--muted); line-height: 1.6; }}
    .notes li + li {{ margin-top: 8px; }}
    .notes li span {{ display: block; color: var(--soft); font-size: 12px; margin-top: 2px; }}
    footer {{
      max-width: 1440px;
      margin: 0 auto;
      padding: 0 min(3vw, 36px) 44px;
      color: var(--muted);
      font-size: 14px;
    }}
    .footer-inner {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
      padding-top: 18px;
      border-top: 1px solid var(--line);
    }}
    @media (max-width: 980px) {{
      .page-title {{ grid-template-columns: 1fr; }}
      .stats {{ justify-content: start; }}
      .watch-layout {{ grid-template-columns: 1fr; }}
      .playlist-shell {{ position: static; }}
      .playlist {{ max-height: 360px; }}
      .player-frame video {{ height: min(62vh, 620px); min-height: 320px; }}
      .notes-grid {{ grid-template-columns: 1fr; }}
    }}
    @media (max-width: 640px) {{
      header {{ padding-left: 18px; padding-right: 18px; }}
      main {{ padding-left: 14px; padding-right: 14px; }}
      .nav {{ align-items: flex-start; }}
      .nav-actions {{ justify-content: flex-end; flex-wrap: wrap; }}
      .player-frame video {{ min-height: 240px; }}
      .playlist-item {{ grid-template-columns: 96px minmax(0, 1fr); }}
      .playlist-preview {{ width: 96px; height: 64px; }}
      .footer-inner {{ display: block; }}
    }}
  </style>
</head>
<body>
  <header>
    <div class="nav">
      <div class="brand">Video Recap</div>
      <div class="nav-actions">
        <span>Generated video analysis</span>
        <a class="github-link" href="{github_url}" target="_blank" rel="noreferrer" aria-label="Open GitHub repository">
          <svg viewBox="0 0 16 16" aria-hidden="true" fill="currentColor">
            <path d="M8 0C3.58 0 0 3.69 0 8.24c0 3.64 2.29 6.72 5.47 7.81.4.08.55-.18.55-.4 0-.2-.01-.85-.01-1.54-2.01.38-2.53-.5-2.69-.96-.09-.24-.48-.96-.82-1.15-.28-.15-.68-.52-.01-.53.63-.01 1.08.6 1.23.85.72 1.25 1.87.9 2.33.69.07-.54.28-.9.51-1.11-1.78-.21-3.64-.92-3.64-4.06 0-.9.31-1.63.82-2.2-.08-.21-.36-1.05.08-2.17 0 0 .67-.22 2.2.84A7.34 7.34 0 0 1 8 4.03c.68 0 1.36.09 2 .28 1.53-1.06 2.2-.84 2.2-.84.44 1.12.16 1.96.08 2.17.51.57.82 1.3.82 2.2 0 3.15-1.87 3.85-3.65 4.06.29.26.54.76.54 1.54 0 1.11-.01 2-.01 2.28 0 .22.15.48.55.4A8.18 8.18 0 0 0 16 8.24C16 3.69 12.42 0 8 0Z"/>
          </svg>
          GitHub
        </a>
      </div>
    </div>
  </header>
  <main>
    <section class="page-title">
      <div>
        <h1>{title}</h1>
        <p class="summary">{summary}</p>
      </div>
      <div class="stats">
        <span>{highlight_count} moments</span>
        <span>{scenario}</span>
      </div>
    </section>
    <section class="watch-layout">
      <div class="player-column">
        <div class="player-frame">
          <video id="mainVideo" controls preload="metadata" src="{initial_src}"></video>
        </div>
        <section class="active-panel">
          <div class="active-meta">
            <span id="activeBadge">{initial_badge}</span>
          </div>
          <h2 id="activeTitle">{initial_title}</h2>
          <p id="activeSummary">{initial_summary}</p>
          <div id="activeDetails">{active_details}</div>
        </section>
        <details class="report-drawer">
          <summary>View structured report</summary>
          {report}
        </details>
      </div>
      <aside class="playlist-shell">
        <div class="playlist-head">
          <div>
            <h2>Selected moments</h2>
            <span>Click a segment to load it in the main player.</span>
          </div>
          <button class="original-button" id="originalButton" type="button">Original</button>
        </div>
        <div class="playlist">
          {playlist}
        </div>
      </aside>
    </section>
  </main>
  <footer>
    <div class="footer-inner">
      <span>Built with LP Video Analysis Skill.</span>
      <a class="github-link" href="{github_url}" target="_blank" rel="noreferrer">Download on GitHub</a>
    </div>
  </footer>
  <script>
    const mainVideo = document.getElementById('mainVideo');
    const activeBadge = document.getElementById('activeBadge');
    const activeTitle = document.getElementById('activeTitle');
    const activeSummary = document.getElementById('activeSummary');
    const activeDetails = document.getElementById('activeDetails');
    const originalButton = document.getElementById('originalButton');
    const sourceSrc = "{source_video}";
    const sourceTitle = "{title}";
    const sourceSummary = "{summary}";

    function escapeHtml(value) {{
      return String(value || '')
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#039;');
    }}

    function parseList(value) {{
      try {{
        const parsed = JSON.parse(value || '[]');
        return Array.isArray(parsed) ? parsed : [];
      }} catch {{
        return [];
      }}
    }}

    function setVideo(src, start = 0, play = true) {{
      if (!src) return;
      const shouldReload = mainVideo.getAttribute('src') !== src;
      if (shouldReload) {{
        mainVideo.setAttribute('src', src);
        mainVideo.load();
      }}
      const seek = () => {{
        mainVideo.currentTime = Number(start || 0);
        if (play) mainVideo.play();
      }};
      if (shouldReload) {{
        mainVideo.addEventListener('loadedmetadata', seek, {{ once: true }});
      }} else {{
        seek();
      }}
    }}

    function renderDetails(button) {{
      const takeaways = parseList(button.dataset.takeaways);
      const tags = parseList(button.dataset.tags);
      const quote = button.dataset.quote || '';
      const start = button.dataset.start || '0';
      const end = button.dataset.end || '';
      const clipSrc = button.dataset.src || '';
      const takeawaysHtml = takeaways.length
        ? `<ul class="takeaways">${{takeaways.map((item) => `<li>${{escapeHtml(item)}}</li>`).join('')}}</ul>`
        : '';
      const tagsHtml = tags.length
        ? `<div class="tags">${{tags.map((item) => `<span>${{escapeHtml(item)}}</span>`).join('')}}</div>`
        : '';
      activeDetails.innerHTML = `
        <div class="active-meta">
          <span>${{escapeHtml(start)}}s - ${{escapeHtml(end)}}s</span>
          <span>Score ${{escapeHtml(button.dataset.score)}}</span>
        </div>
        ${{quote ? `<blockquote>${{escapeHtml(quote)}}</blockquote>` : ''}}
        <p class="reason">${{escapeHtml(button.dataset.reason)}}</p>
        ${{takeawaysHtml}}
        ${{tagsHtml}}
        <div class="active-actions">
          <a href="${{escapeHtml(clipSrc)}}" download>Download clip</a>
          <button class="source-jump-button secondary" type="button" data-start="${{escapeHtml(start)}}">Play in original</button>
        </div>
      `;
    }}

    document.querySelectorAll('.playlist-item').forEach((button) => {{
      button.addEventListener('click', () => {{
        document.querySelectorAll('.playlist-item').forEach((item) => item.classList.remove('active'));
        button.classList.add('active');
        activeBadge.textContent = 'Selected Moment';
        activeTitle.textContent = button.dataset.title || 'Selected Moment';
        activeSummary.textContent = button.dataset.summary || '';
        renderDetails(button);
        setVideo(button.dataset.src, 0, true);
      }});
    }});

    document.addEventListener('click', (event) => {{
      const button = event.target.closest('.source-jump-button');
      if (!button || !sourceSrc) return;
      activeBadge.textContent = 'Original Video';
      setVideo(sourceSrc, Number(button.dataset.start || 0), true);
    }});

    originalButton.addEventListener('click', () => {{
      if (!sourceSrc) return;
      document.querySelectorAll('.playlist-item').forEach((item) => item.classList.remove('active'));
      activeBadge.textContent = 'Original Video';
      activeTitle.textContent = sourceTitle;
      activeSummary.textContent = sourceSummary;
      setVideo(sourceSrc, 0, true);
    }});

    if (!sourceSrc) {{
      originalButton.hidden = true;
    }}
  </script>
</body>
</html>
"""


def build_parser():
    parser = argparse.ArgumentParser(description="General video understanding workflow helper.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init-analysis", help="Create a video understanding work directory and starter files.")
    p.add_argument("--output", required=True)
    p.add_argument("--scenario", choices=sorted(SCENARIOS), default="summary")
    p.set_defaults(func=cmd_init_analysis)

    p = sub.add_parser("init-project", help="Create a work directory and starter files.")
    p.add_argument("--output", required=True)
    p.add_argument("--scenario", choices=sorted(SCENARIOS), default="clips")
    p.set_defaults(func=cmd_init_project)

    p = sub.add_parser("probe", help="Write ffprobe metadata JSON.")
    p.add_argument("video")
    p.add_argument("--output", required=True)
    p.set_defaults(func=cmd_probe)

    p = sub.add_parser("plan-analysis", help="Choose coarse ASR/frame/VLM strategy from metadata.")
    p.add_argument("--metadata", default="", help="ffprobe metadata JSON.")
    p.add_argument("--output", required=True)
    p.add_argument("--scenario", choices=sorted(SCENARIOS), default="summary")
    p.add_argument("--content-type", choices=["auto", "balanced", "transcript_primary", "visual_dense"], default="auto")
    p.add_argument("--budget", choices=["quick", "standard", "deep"], default="standard")
    p.set_defaults(func=cmd_plan_analysis)

    p = sub.add_parser("extract-audio", help="Extract mono 16 kHz WAV audio.")
    p.add_argument("video")
    p.add_argument("--output", required=True)
    p.set_defaults(func=cmd_extract_audio)

    p = sub.add_parser("sample-frames", help="Sample periodic frames for visual analysis.")
    p.add_argument("video")
    p.add_argument("--output-dir", required=True)
    p.add_argument("--interval", type=float, default=30)
    p.add_argument("--width", type=int, default=1280)
    p.add_argument("--max-frames", type=int, default=0)
    p.set_defaults(func=cmd_sample_frames)

    p = sub.add_parser("prepare-frame-review", help="Create a VLM frame review manifest and prompt from sampled frames.")
    p.add_argument("--frames-dir", required=True)
    p.add_argument("--output", required=True, help="Output frame review manifest JSON.")
    p.add_argument("--prompt-output", default="", help="Optional Markdown prompt for the multimodal model.")
    p.add_argument("--interval", type=float, default=30, help="Seconds between sampled frames.")
    p.add_argument("--start-time", type=float, default=0, help="Timestamp for the first sampled frame.")
    p.add_argument("--relative-to", default="", help="Base directory used for relative frame paths.")
    p.add_argument("--language", default="Chinese", help="Language requested for captions and object labels.")
    p.set_defaults(func=cmd_prepare_frame_review)

    p = sub.add_parser("ingest-frame-review", help="Normalize VLM frame review output into frame_observations.json.")
    p.add_argument("--review", required=True, help="Model-produced frame review JSON.")
    p.add_argument("--output", required=True, help="Output frame_observations.json.")
    p.add_argument("--manifest", default="", help="Optional frame review manifest for timestamp/path backfill.")
    p.set_defaults(func=cmd_ingest_frame_review)

    p = sub.add_parser("refine-plan", help="Select candidate windows for second-pass ASR/VLM/OCR review.")
    p.add_argument("--analysis", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--min-conditions", type=int, default=1, help="Minimum matched refine conditions required.")
    p.add_argument("--refine-interval", type=float, default=5, help="Default dense frame interval in seconds.")
    p.add_argument("--padding", type=float, default=5, help="Seconds of context added around each selected segment.")
    p.set_defaults(func=cmd_refine_plan)

    p = sub.add_parser("execute-refine-plan", help="Prepare dense frames, prompts, and local audio for refine windows.")
    p.add_argument("video")
    p.add_argument("--plan", required=True, help="refine_plan.json produced by refine-plan.")
    p.add_argument("--output-dir", required=True)
    p.add_argument("--output-manifest", default="", help="Optional output path for refine_execution_manifest.json.")
    p.add_argument("--priorities", default="P0,P1", help="Comma-separated priorities to execute, e.g. P0,P1 or P0,P1,P2.")
    p.add_argument("--language", default="Chinese")
    p.add_argument("--width", type=int, default=960)
    p.add_argument("--skip-audio", action="store_true", help="Do not extract per-window audio even when needs_asr is true.")
    p.set_defaults(func=cmd_execute_refine_plan)

    p = sub.add_parser("merge-refine-results", help="Merge per-window ASR/VLM/OCR outputs back into video_analysis.json.")
    p.add_argument("--analysis", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--execution-manifest", default="", help="refine_execution_manifest.json from execute-refine-plan.")
    p.add_argument("--refine-dir", default="", help="Directory containing per-window window.json files.")
    p.add_argument("--normalize-outputs", action="store_true", help="Write frame_observations.json from frame_review_output.json when needed.")
    p.set_defaults(func=cmd_merge_refine_results)

    p = sub.add_parser("validate-plan", help="Validate clip plan JSON.")
    p.add_argument("plan")
    p.add_argument("--duration", default="")
    p.set_defaults(func=cmd_validate_plan)

    p = sub.add_parser("validate-analysis", help="Validate video_analysis.json.")
    p.add_argument("analysis")
    p.set_defaults(func=cmd_validate_analysis)

    p = sub.add_parser("validate-transcript", help="Validate timestamped transcript JSON.")
    p.add_argument("transcript")
    p.set_defaults(func=cmd_validate_transcript)

    p = sub.add_parser("validate-frames", help="Validate frame observation JSON.")
    p.add_argument("frames")
    p.set_defaults(func=cmd_validate_frames)

    p = sub.add_parser("build-segments", help="Build video_analysis.json from transcript, frame observations, and metadata.")
    p.add_argument("--transcript", default="", help="Transcript JSON list or object with a transcript list.")
    p.add_argument("--frames", default="", help="Frame observation JSON list or object with a frames list.")
    p.add_argument("--metadata", default="", help="ffprobe metadata JSON.")
    p.add_argument("--output", required=True)
    p.add_argument("--scenario", choices=sorted(SCENARIOS), default="summary")
    p.add_argument("--title", default="")
    p.add_argument("--summary", default="")
    p.add_argument("--max-segment-duration", type=float, default=90)
    p.add_argument("--gap", type=float, default=8)
    p.set_defaults(func=cmd_build_segments)

    p = sub.add_parser("derive-clips", help="Create an optional clip_plan.json from video_analysis.json.")
    p.add_argument("--analysis", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--target-count", type=int, default=5)
    p.set_defaults(func=cmd_derive_highlight)

    p = sub.add_parser("summary", help="Write a Markdown summary from video_analysis.json.")
    p.add_argument("--analysis", required=True)
    p.add_argument("--output", required=True)
    p.set_defaults(func=cmd_summary)

    p = sub.add_parser("search-index", help="Write segment-level JSONL for Video RAG indexing.")
    p.add_argument("--analysis", required=True)
    p.add_argument("--output", required=True)
    p.set_defaults(func=cmd_search_index)

    p = sub.add_parser("cut", help="Cut clips from a source video using a clip plan.")
    p.add_argument("video")
    p.add_argument("--plan", required=True)
    p.add_argument("--output-dir", required=True)
    p.add_argument("--copy", action="store_true", help="Use stream copy instead of re-encoding.")
    p.set_defaults(func=cmd_cut)

    p = sub.add_parser("page", help="Generate an HTML recap page.")
    p.add_argument("--plan", required=True)
    p.add_argument("--clips-dir", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--source-video", default="", help="Original source video shown at the top of the page.")
    p.add_argument("--copy-media", action="store_true", help="Copy source video and clips into a publishable media folder.")
    p.add_argument("--media-dir", default="media", help="Media directory relative to the output page.")
    p.set_defaults(func=cmd_page)

    return parser


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "derive-highlight":
        sys.argv[1] = "derive-clips"
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
