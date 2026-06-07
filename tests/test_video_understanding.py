import importlib.util
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


if __name__ == "__main__":
    unittest.main()
