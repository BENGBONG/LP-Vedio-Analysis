import importlib.util
from pathlib import Path
import unittest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "evaluate_fixtures.py"
SPEC = importlib.util.spec_from_file_location("evaluate_fixtures", SCRIPT_PATH)
evaluate_fixtures = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(evaluate_fixtures)


class EvalFixturesTest(unittest.TestCase):
    def test_eval_fixtures_pass(self):
        eval_dir = Path(__file__).resolve().parents[1] / "examples" / "eval"
        results = evaluate_fixtures.evaluate_all(eval_dir)
        self.assertGreaterEqual(len(results), 1)
        self.assertEqual(results[0]["id"], "product-ad")


if __name__ == "__main__":
    unittest.main()
