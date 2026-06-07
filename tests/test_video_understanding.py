import importlib.util
import tempfile
from pathlib import Path
import unittest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "video_understanding.py"
SPEC = importlib.util.spec_from_file_location("video_understanding", SCRIPT_PATH)
video_understanding = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(video_understanding)


class VideoUnderstandingTest(unittest.TestCase):
    def test_parse_time_accepts_seconds_and_clock_values(self):
        self.assertEqual(video_understanding.parse_time(12), 12.0)
        self.assertEqual(video_understanding.parse_time("01:02"), 62.0)
        self.assertEqual(video_understanding.parse_time("01:02:03.5"), 3723.5)

    def test_validate_analysis_accepts_minimal_valid_analysis(self):
        analysis = {
            "source": {"duration": 20.0},
            "summary": "Demo",
            "transcript": [{"start": 0, "end": 4, "text": "Hello"}],
            "frames": [],
            "segments": [{"id": "seg_1", "start": 0, "end": 5, "title": "Intro", "summary": "Opening", "importance": 3}],
            "moments": [],
            "entities": [],
            "claims": [],
            "actions": [],
            "questions": [],
        }
        self.assertEqual(video_understanding.validate_analysis_data(analysis), [])

    def test_validate_analysis_rejects_overlapping_segments(self):
        analysis = {
            "source": {"duration": 20.0},
            "transcript": [],
            "frames": [],
            "segments": [
                {"start": 0, "end": 10, "title": "A", "summary": "A"},
                {"start": 9, "end": 12, "title": "B", "summary": "B"},
            ],
            "moments": [],
            "entities": [],
            "claims": [],
            "actions": [],
            "questions": [],
        }
        errors = video_understanding.validate_analysis_data(analysis)
        self.assertTrue(any("overlaps previous segment" in error for error in errors))

    def test_segment_to_highlight_preserves_timestamps(self):
        segment = {
            "start": 5.2,
            "end": 12.4,
            "title": "Product benefits",
            "summary": "Benefits are explained.",
            "topics": ["product"],
            "importance": 5,
        }
        highlight = video_understanding.segment_to_highlight(segment, 1)
        self.assertEqual(highlight["start"], 5.2)
        self.assertEqual(highlight["end"], 12.4)
        self.assertEqual(highlight["title"], "Product benefits")
        self.assertGreaterEqual(highlight["score"], 90)

    def test_get_moments_prefers_new_field_and_supports_legacy_fields(self):
        self.assertEqual(video_understanding.get_moments({"moments": [{"title": "A"}]})[0]["title"], "A")
        self.assertEqual(video_understanding.get_moments({"highlights": [{"title": "B"}]})[0]["title"], "B")
        self.assertEqual(video_understanding.get_moments({"clips": [{"title": "C"}]})[0]["title"], "C")

    def test_validate_transcript_and_frame_items(self):
        transcript = [{"start": 0, "end": 4, "text": "Hello"}]
        frames = [{"timestamp": 1.0, "caption": "A frame", "ocr": [], "objects": []}]
        self.assertEqual(video_understanding.validate_transcript_items(transcript), [])
        self.assertEqual(video_understanding.validate_frame_items(frames), [])

    def test_build_segments_from_inputs_merges_nearby_transcript(self):
        transcript = [
            {"start": 0, "end": 4, "text": "Opening context."},
            {"start": 6, "end": 10, "text": "More detail."},
            {"start": 30, "end": 34, "text": "New topic."},
        ]
        frames = [{"timestamp": 7, "caption": "A useful slide.", "ocr": ["Slide"], "objects": []}]
        segments = video_understanding.build_segments_from_inputs(transcript, frames, max_duration=20, gap=8)
        self.assertEqual(len(segments), 2)
        self.assertEqual(segments[0]["start"], 0.0)
        self.assertIn("A useful slide", segments[0]["summary"])

    def test_prepare_frame_review_manifest_uses_sample_interval(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frames = root / "frames"
            frames.mkdir()
            (frames / "frame_00001.jpg").write_bytes(b"one")
            (frames / "frame_00002.jpg").write_bytes(b"two")
            manifest = video_understanding.build_frame_review_manifest(frames, interval=5, relative_to=root)
            self.assertEqual(len(manifest["frames"]), 2)
            self.assertEqual(manifest["frames"][0]["timestamp"], 0.0)
            self.assertEqual(manifest["frames"][1]["timestamp"], 5.0)
            self.assertEqual(manifest["frames"][0]["path"], "frames/frame_00001.jpg")

    def test_ingest_frame_review_normalizes_model_output(self):
        manifest = {
            "frames": [
                {"id": "frame_00001", "timestamp": 10, "path": "frames/frame_00001.jpg"}
            ]
        }
        review = {
            "frames": [
                {
                    "id": "frame_00001",
                    "description": "湖边人物和远山。",
                    "text_overlays": "北疆",
                    "visual_elements": ["湖泊", "人物"],
                }
            ]
        }
        frames = video_understanding.normalize_frame_review_payload(review, manifest=manifest)
        self.assertEqual(frames[0]["timestamp"], 10.0)
        self.assertEqual(frames[0]["path"], "frames/frame_00001.jpg")
        self.assertEqual(frames[0]["caption"], "湖边人物和远山。")
        self.assertEqual(frames[0]["ocr"], ["北疆"])
        self.assertEqual(frames[0]["objects"], ["湖泊", "人物"])

    def test_plan_analysis_uses_long_video_conservative_sampling(self):
        metadata = {
            "format": {"duration": "2700"},
            "streams": [
                {"codec_type": "video", "width": 1920, "height": 1080, "avg_frame_rate": "30/1"},
                {"codec_type": "audio"},
            ],
        }
        strategy = video_understanding.build_analysis_strategy(metadata, scenario="report", budget="standard")
        self.assertEqual(strategy["recommended"]["asr_scope"], "full")
        self.assertEqual(strategy["recommended"]["vlm_scope"], "coarse_frames_then_refine_windows")
        self.assertGreaterEqual(strategy["recommended"]["coarse_frame_interval"], 120)
        self.assertLessEqual(strategy["recommended"]["estimated_coarse_frames"], strategy["recommended"]["coarse_max_frames"])

    def test_refine_plan_selects_windows_from_rules(self):
        analysis = {
            "source": {"duration": 120, "has_audio": True, "title": "Demo"},
            "observations": {"transcript_count": 0, "frame_count": 4},
            "transcript": [],
            "frames": [],
            "segments": [
                {
                    "id": "seg_1",
                    "start": 0,
                    "end": 60,
                    "title": "普通段落",
                    "summary": "Opening.",
                    "importance": 2,
                },
                {
                    "id": "seg_2",
                    "start": 60,
                    "end": 120,
                    "title": "片尾视觉冲击",
                    "summary": "适合作为封面，地点不确定。",
                    "importance": 5,
                },
            ],
            "moments": [
                {"start": 70, "end": 100, "title": "高潮", "summary": "Strong", "reason": "适合预告", "score": 92}
            ],
            "entities": [],
            "claims": [],
            "actions": [],
            "questions": [{"timestamp": 80, "question": "地点是哪？"}],
        }
        plan = video_understanding.build_refine_plan(analysis, min_conditions=1)
        selected = [item for item in plan["windows"] if item["segment_id"] == "seg_2"][0]
        self.assertEqual(selected["priority"], "P0")
        self.assertTrue(selected["needs_vlm"])
        self.assertTrue(selected["needs_asr"])
        self.assertGreaterEqual(selected["condition_count"], 3)

    def test_merge_refine_results_adds_window_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            window = root / "01-P0-demo"
            window.mkdir()
            manifest_path = window / "frame_review_manifest.json"
            review_path = window / "frame_review_output.json"
            observations_path = window / "frame_observations.json"
            transcript_path = window / "transcript.json"
            manifest_path.write_text(
                '{"frames":[{"id":"frame_00001","timestamp":65,"path":"frames/frame_00001.jpg"}]}',
                encoding="utf-8",
            )
            review_path.write_text(
                '{"frames":[{"id":"frame_00001","caption":"重点画面","ocr":[],"objects":["湖泊"]}]}',
                encoding="utf-8",
            )
            transcript_path.write_text(
                '{"transcript":[{"start":60,"end":66,"text":"这里是重点旁白。"}]}',
                encoding="utf-8",
            )
            analysis = {
                "source": {"duration": 120, "has_audio": True, "title": "Demo"},
                "observations": {"transcript_count": 0, "frame_count": 0},
                "summary": "Demo",
                "transcript": [],
                "frames": [],
                "segments": [{"id": "seg_1", "start": 0, "end": 120, "title": "All", "summary": "All"}],
                "moments": [],
                "entities": [],
                "claims": [],
                "actions": [],
                "questions": [],
            }
            execution = {
                "source_video": "input.mp4",
                "windows": [
                    {
                        "window": {"segment_id": "seg_1", "priority": "P0"},
                        "frame_review_manifest": str(manifest_path),
                        "frame_review_output": str(review_path),
                        "frame_observations": str(observations_path),
                        "transcript": str(transcript_path),
                    }
                ],
            }
            merged = video_understanding.merge_refine_results(analysis, execution, normalize_outputs=True)
            self.assertEqual(len(merged["frames"]), 1)
            self.assertEqual(len(merged["transcript"]), 1)
            self.assertEqual(merged["observations"]["refined_frame_count"], 1)
            self.assertTrue(observations_path.exists())


if __name__ == "__main__":
    unittest.main()
