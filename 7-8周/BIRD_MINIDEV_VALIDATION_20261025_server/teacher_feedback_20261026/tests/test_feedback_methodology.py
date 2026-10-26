"""Regression checks for the scientific contracts of the feedback analyses.

Run with ``python -m unittest discover -s tests`` from the consolidated project.
The retrieval integration fixture uses a deterministic embedding stub, so it
does not download models or require sentence-transformers to be installed.
"""

import importlib.util
import io
import json
import os
import sqlite3
import sys
import tempfile
import types
import unittest
from pathlib import Path
from contextlib import closing, redirect_stdout
from unittest.mock import patch

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = Path(os.environ.get("BIRD_EXPERIMENT_ROOT", str(PROJECT_ROOT.parent))).expanduser()


def load_script(name, relative_path):
    spec = importlib.util.spec_from_file_location(name, PROJECT_ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


retrieval = load_script("feedback_retrieval", "scripts/feedback/retrieval_fk_expansion.py")
bridge = load_script("feedback_bridge", "scripts/feedback/audit_bridge_api_successes.py")
synonyms = load_script("feedback_synonyms", "scripts/feedback/audit_synonym_failures.py")
relative = load_script("feedback_relative", "scripts/feedback/analyze_relative_execution.py")
scoring = load_script("official_scoring", "scripts/score_predictions_official.py")


class RetrievalContracts(unittest.TestCase):
    def test_one_hop_and_original_single_table_denominator(self):
        """A -> B -> C must add B without recursively adding C at k=5.

        The second question has no missing-schema labels; it must nevertheless
        remain in the original single-table comparison's denominator.
        """
        class DeterministicEncoder:
            def __init__(self, *args, **kwargs):
                pass

            def encode(self, texts, **kwargs):
                if texts[0].startswith("table "):
                    return np.eye(len(texts))
                return np.tile(np.arange(8, 0, -1, dtype=float), (len(texts), 1))

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / "data"
            experiment = root / "experiment"
            output = root / "result"
            perturbations = experiment / "perturbations/output"
            data.mkdir()
            perturbations.mkdir(parents=True)
            metadata = [{
                "db_id": "fixture", "table_names_original": ["A", "B", "C"],
                "column_names_original": [[-1, "*"], *[[0, f"c{i}"] for i in range(1, 6)],
                                          [1, "c6"], [2, "c7"], [0, "c8"]],
                "column_types": ["text"] * 9, "primary_keys": [[1, 5]],
                "foreign_keys": [[5, 6], [6, 7]],
            }]
            questions = [{"question_id": 1, "db_id": "fixture", "question": "single"},
                         {"question_id": 2, "db_id": "fixture", "question": "multi"}]
            structures = [
                {"question_id": 1, "question_type": "single", "gold_columns": ["A.c1"]},
                {"question_id": 2, "question_type": "multi", "gold_columns": ["B.c6", "C.c7"]},
            ]
            variants = [{"question_id": 2, "perturbation": {
                "family": "missing_fk_column", "removed": [{"join_columns": ["B.c6", "C.c7"]}]
            }}]
            (data / "dev_tables.json").write_text(json.dumps(metadata))
            (data / "mini_dev_sqlite.json").write_text(json.dumps(questions))
            for filename, rows in [("question_structures.jsonl", structures),
                                   ("mini_dev_perturbations.jsonl", variants)]:
                (perturbations / filename).write_text("\n".join(map(json.dumps, rows)) + "\n")
            arguments = ["retrieval_fk_expansion.py", "--experiment-root", str(experiment),
                         "--data-root", str(data), "--output-dir", str(output),
                         "--models", "fixture-model", "--iterations", "30"]
            with patch.dict(sys.modules, {"sentence_transformers": types.SimpleNamespace(
                    SentenceTransformer=DeterministicEncoder)}), patch.object(sys, "argv", arguments), \
                    patch.dict(os.environ, {"MPLBACKEND": "Agg", "MPLCONFIGDIR": str(root / "mpl")}):
                retrieval.main()
            summary = json.loads((output / "fk_expansion_summary.json").read_text())["fixture-model"]
            self.assertEqual(summary["question_count"], 1)
            self.assertEqual(summary["plain"]["5"]["target_columns"], 2)
            self.assertEqual(summary["plain"]["5"]["hits"], 0)
            self.assertEqual(summary["expanded"]["5"]["hits"], 1)
            self.assertGreater(summary["expanded"]["5"]["mean_schema_token_proxy"],
                               summary["plain"]["5"]["mean_schema_token_proxy"])
            hypothesis = summary["original_hypothesis"]["5"]
            self.assertEqual(hypothesis["single_target_columns"]["total"], 1)
            self.assertEqual(hypothesis["foreign_key_columns"]["total"], 2)
            self.assertEqual(hypothesis["foreign_key_columns_vs_single"]["difference_percentage_points"], 100)
            predictions = retrieval.read_jsonl(output / "fixture-model_predictions.jsonl")
            self.assertEqual(len(predictions), 2)

    def test_union_targets_are_deduplicated_and_scoped_by_question(self):
        variants = [{"question_id": 1, "perturbation": {
            "family": "missing_bridge_table", "removed": [{"columns": ["A.x", "A.y"]}]}},
            {"question_id": 1, "perturbation": {
                "family": "missing_fk_column", "removed": [{"join_columns": ["A.y", "B.z"]}]}}]
        self.assertEqual(retrieval.labels(variants)[1], {"A.x", "A.y", "B.z"})
        self.assertFalse(retrieval.labels(variants)[2])


class SQLiteAccessContracts(unittest.TestCase):
    def test_authorizer_uses_physical_lineage_and_denies_count_star(self):
        with tempfile.TemporaryDirectory() as temporary:
            # URI quoting also matters for paths containing SQLite URI syntax.
            path = Path(temporary) / "fixture #1?.sqlite"
            with closing(sqlite3.connect(path)) as connection:
                connection.executescript("CREATE TABLE hidden(id INTEGER, secret TEXT);"
                                         "INSERT INTO hidden VALUES(1, 'value');")
                connection.commit()
            sql = "WITH renamed AS (SELECT secret FROM hidden) SELECT secret FROM renamed"
            permitted = bridge.trace(path, sql, {"hidden": False})
            self.assertIsNone(permitted["error"])
            self.assertIn("hidden.secret", permitted["reads"])
            denied_column = bridge.trace(path, sql, {}, {"hidden": {"id"}})
            self.assertTrue(denied_column["error"])
            self.assertIn("hidden.secret", denied_column["denied"])
            denied_table = bridge.trace(path, "SELECT COUNT(*) FROM hidden", {"hidden": True})
            self.assertTrue(denied_table["error"])
            self.assertTrue(denied_table["denied"])
            permitted_count = bridge.trace(path, "SELECT COUNT(*) FROM hidden", {}, {"hidden": {"id"}})
            self.assertIsNone(permitted_count["error"])


class RelativeAnalysisContracts(unittest.TestCase):
    def test_common_question_set_excludes_gold_errors_for_every_model(self):
        maps = {}
        for key in relative.MODEL_KEYS:
            maps[key] = {condition: {qid: {"correct": qid != 2} for qid in (1, 2, 3)}
                         for condition in ("base", "add_random_20")}
        maps["qwen3_0_6b"]["add_random_20"][3]["gold_unscorable"] = True
        main, historical, excluded = relative.question_sets(maps, "add_random_20")
        self.assertEqual(main, [1, 2])
        self.assertEqual(historical, [1, 2, 3])
        self.assertEqual(excluded, [3])

    def test_relative_loss_reestimates_low_baseline_denominator(self):
        observations = np.array([[1, 0], [0, 0]], dtype=np.int8)
        metric = relative.metric(observations)
        self.assertEqual(metric["absolute_drop_percentage_points"], 50)
        self.assertEqual(metric["relative_loss_percent"], 100)
        samples = relative.bootstrap({"first": observations, "identical": observations.copy()}, 100, 13)
        np.testing.assert_equal(samples["first"], samples["identical"])
        self.assertTrue(np.isnan(samples["first"]).any())
        self.assertTrue(np.all(samples["first"][np.isfinite(samples["first"])] == 1))
        interval = relative.interval(samples["first"])
        self.assertGreater(interval["undefined_bootstrap_draws"], 0)


class ReviewedSampleContracts(unittest.TestCase):
    def test_versioned_seed_sample_and_replacements_match_immutable_scores(self):
        fixture_path = PROJECT_ROOT / "scripts/feedback/review_data/synonym20_review.json"
        scores_path = SOURCE_ROOT / "model_eval/scores/api_control.jsonl"
        self.assertTrue(fixture_path.is_file(), f"Missing versioned review fixture: {fixture_path}")
        self.assertTrue(scores_path.is_file(),
                        f"Missing source scores: {scores_path}; set BIRD_EXPERIMENT_ROOT to the server folder")
        fixture = json.loads(fixture_path.read_text())
        scores = synonyms.read_jsonl(scores_path)
        synonyms.verify_sampling(fixture, scores)
        cases = fixture["cases"]
        eligible = [row for row in cases if not row["excluded_legacy"]]
        self.assertEqual(len(eligible), 30)
        self.assertEqual(len({row["question_id"] for row in cases}), 32)
        ids = {row["question_id"] for row in eligible}
        self.assertFalse(ids & set(fixture["excluded_legacy_question_ids"]))
        self.assertTrue(set(fixture["replacement_question_ids"]) <= ids)


class OfficialScoringContracts(unittest.TestCase):
    def test_gold_scorability_is_independent_of_prediction_success_and_resume_checks_gold(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = root / "fixture.sqlite"
            with closing(sqlite3.connect(database)) as connection:
                connection.executescript("CREATE TABLE source(id INTEGER); INSERT INTO source VALUES(1);")
                connection.commit()
            predictions = []
            variants = {}
            for qid, (predicted, gold) in enumerate([
                    ("SELECT id FROM source", "SELECT id FROM source"),
                    ("", "SELECT missing_column FROM source"),
                    ("SELECT another_missing_column FROM source", "SELECT id FROM source")], 1):
                variant_id = f"q{qid}__base"
                variants[variant_id] = {"question_id": qid, "db_id": "fixture", "gold_sql": gold,
                                        "database_path": "fixture.sqlite"}
                predictions.append({"variant_id": variant_id, "question_id": qid, "db_id": "fixture",
                                    "family": "base", "model_key": "fixture", "model": "fixture",
                                    "predicted_sql": predicted, "error": None})
            path = root / "predictions.jsonl"
            path.write_text("\n".join(map(json.dumps, predictions)) + "\n")
            output = root / "scores"
            output.mkdir()
            with redirect_stdout(io.StringIO()):
                scoring.score_file(path, variants, root, output, 1, 1, 100, 25, {})
            rows = scoring.read_jsonl(output / "fixture.jsonl")
            self.assertTrue(rows[0]["correct"])
            self.assertTrue(rows[1]["gold_unscorable"])
            self.assertEqual(rows[1]["evaluation_status"], "evaluation_error")
            self.assertTrue(rows[1]["error"].startswith("GoldUnscorable:"))
            self.assertFalse(rows[2]["gold_unscorable"])
            self.assertFalse(rows[2]["correct"])
            summary = json.loads((output / "fixture.summary.json").read_text())["by_family"]["base"]
            self.assertEqual(summary["count"], 2)
            self.assertEqual(summary["total_records"], 3)
            self.assertEqual(summary["accuracy"], .5)
            previous_bytes = (output / "fixture.jsonl").read_bytes()
            variants["q1__base"]["gold_sql"] = "SELECT 2"
            with self.assertRaisesRegex(ValueError, "does not match prediction/gold inputs"):
                scoring.score_file(path, variants, root, output, 1, 1, 100, 25, {})
            self.assertEqual((output / "fixture.jsonl").read_bytes(), previous_bytes)

    def test_official_set_semantics_preserve_duplicate_insensitivity(self):
        self.assertTrue(scoring.rows_equal([(1,), (1,)], [(1,)]))
        self.assertFalse(scoring.rows_equal([(1,)], [(2,)]))


if __name__ == "__main__":
    unittest.main()
