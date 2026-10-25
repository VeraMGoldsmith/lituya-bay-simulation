"""Small synthetic examples and regressions against the public summaries only."""
import copy
import csv
from decimal import Decimal as D
from html.parser import HTMLParser
import importlib.util
from pathlib import Path
import shutil
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location("measurement_analysis", Path(__file__).with_name("analyze.py"))
a = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(a)


class TableReader(HTMLParser):
    def __init__(self):
        super().__init__()
        self.cells = []
        self.cell = None

    def handle_starttag(self, tag, attrs):
        if tag == "td":
            self.cell = dict(attrs)
            self.cell["text"] = ""

    def handle_data(self, text):
        if self.cell is not None:
            self.cell["text"] += text

    def handle_endtag(self, tag):
        if tag == "td":
            self.cells.append(self.cell)
            self.cell = None


class Calculations(unittest.TestCase):
    def test_signed_arithmetic_and_conversion(self):
        self.assertEqual(a.difference(80, 100), (D(20), D(25)))
        self.assertEqual(a.difference(100, 80), (D(-20), D(-20)))
        self.assertEqual(a.area_km2(4, 20, 25), D("0.002"))
        self.assertEqual(a.area_km2(0, 20, 25), 0)

    def test_unsuitable_percentage_baselines(self):
        for left, right in ((0, 1), (-2, -1), (-2, 2), (2, -1)):
            with self.subTest(left=left, right=right):
                self.assertIsNone(a.difference(left, right)[1])
        self.assertEqual(a.difference(2, 0), (D(-2), D(-100)))

    def test_invalid_numbers_and_cell_counts(self):
        for value in (None, True, "NaN", "Infinity", "-Infinity", "missing"):
            with self.subTest(value=value), self.assertRaises(a.RecordError):
                a.number(value)
        for count, dx, dy in ((-1, 1, 1), (1.5, 1, 1), (1, 0, 1), (1, 1, -2)):
            with self.subTest(count=count, dx=dx, dy=dy), self.assertRaises(a.RecordError):
                a.area_km2(count, dx, dy)


class ThresholdReasoning(unittest.TestCase):
    def setUp(self):
        self.metric = {a.RUNUP: 20, "depth_threshold_m": D("0.1"),
                       "all_points_observed": True, "metric_scope": "provided_monitor_only",
                       "peak_locations": [{"x_m": 1, "y_m": 1, "maximum_depth_m": D("1.2"),
                                           "time_at_maximum_depth_s": 5}]}

    def bound(self, **kw):
        args = dict(lower=D("0.1"), upper=1, bounds=[0, 0, 2, 2], duration=10, evidence_supported=True)
        args.update(kw)
        return a.threshold_bound(self.metric, **args)

    def test_valid_bound_matches_tiny_cell_example(self):
        # Eligible ground/depth pairs; the higher dry cell never qualified.
        cells = [(5, D("0.2")), (20, D("1.2")), (30, D("0.05"))]
        self.assertIsNotNone(self.bound()["peak"])
        for threshold in map(D, ("0.1", "0.2", "0.8", "1.0")):
            self.assertEqual(max(b for b, h in cells if h >= threshold), 20)

    def test_equality_at_upper_threshold_and_ties(self):
        self.metric["peak_locations"][0]["maximum_depth_m"] = D("0.2")
        self.metric["peak_locations"].append(dict(x_m=2, y_m=1, maximum_depth_m=1, time_at_maximum_depth_s=8))
        self.assertEqual(self.bound()["peak"]["maximum_depth_m"], 1)

    def test_deep_water_elsewhere_cannot_prove_bound(self):
        self.metric["peak_locations"][0]["maximum_depth_m"] = D("0.9")
        self.metric["maximum_depth_on_wetted_eligible_land_m"] = 1000
        self.assertIsNone(self.bound()["peak"])

    def test_missing_or_invalid_premises_are_not_established(self):
        for field, value in (("peak_locations", []), ("all_points_observed", False),
                             ("metric_scope", "whole_bay"), ("depth_threshold_m", D("0.2"))):
            before = copy.deepcopy(self.metric)
            self.metric[field] = value
            self.assertEqual(self.bound()["status"], "not established from available records")
            self.metric = before
        self.assertIsNone(self.bound(evidence_supported=False)["peak"])
        self.assertIsNone(self.bound(upper=D("0.05"))["peak"])

    def test_invalid_peak_depth_coordinates_and_time(self):
        for key, value in (("x_m", 3), ("y_m", -1), ("maximum_depth_m", D("NaN")),
                           ("maximum_depth_m", None), ("time_at_maximum_depth_s", 11)):
            before = copy.deepcopy(self.metric)
            self.metric["peak_locations"][0][key] = value
            self.assertIsNone(self.bound()["peak"])
            self.metric = before


class ArchivedRecords(unittest.TestCase):
    def setUp(self):
        self.results, self.figures, self.hashes = a.verify_inputs(a.ROOT)

    def test_all_seven_quantities_and_recorded_checkpoints(self):
        result = a.compare_records(self.results, self.figures)
        rows = {x["metric"]: x for x in result["comparison"]}
        expected = {"legacy": ("339.72425", "463.9969"), "expanded": ("339.72425", "469.84918"),
                    "area": ("1.1390413907284736646", "1.2693973509933739656"),
                    "depth": ("119.84009", "126.8762"), "P2": ("196.0448", "196.0448"),
                    "P3": ("73.39219", "78.13353"), "P5": ("22.72904", "22.34237")}
        self.assertEqual(set(rows), set(expected))
        for key, values in expected.items():
            self.assertEqual((rows[key]["value_50"], rows[key]["value_100"]), tuple(map(D, values)))
        self.assertEqual(result["monitoring_choice"][1]["difference_m"], D("5.85228"))
        self.assertEqual([x["peak_cell_depth_m"] for x in result["threshold_bound"]],
                         [D("4.857501"), D("1.5597324")])
        self.assertTrue(all(x["threshold_max_m"] == 1 for x in result["threshold_bound"]))

    def test_overlapping_values_disagree(self):
        for area, key, value in (("legacy", a.RUNUP, 1), ("expanded", "depth_threshold_m", 1),
                                 ("expanded", "eligible_natural_land_cells", 12)):
            figures = copy.deepcopy(self.figures)
            figures["runup_metrics"]["cap_100"][area][key] = value
            with self.subTest(area=area, key=key), self.assertRaises(a.RecordError):
                a.compare_records(self.results, figures)

    def test_peak_from_different_cell_rejected(self):
        self.figures["runup_metrics"]["cap_100"]["expanded"]["peak_locations"][0]["x_m"] += 30
        with self.assertRaisesRegex(a.RecordError, "Cross-file discrepancy"):
            a.compare_records(self.results, self.figures)

    def test_figure_display_values_must_match_measurements(self):
        self.figures["presentation"]["sensitivity_bar_heights_m"].reverse()
        with self.assertRaisesRegex(a.RecordError, "Figure sensitivity"):
            a.compare_records(self.results, self.figures)

    def test_case_or_session_mismatch_rejected(self):
        self.figures["session"] = "other-session"
        with self.assertRaisesRegex(a.RecordError, "Session mismatch"):
            a.compare_records(self.results, self.figures)

    def test_failed_case_cannot_become_comparison(self):
        # Failed diagnostic values are deliberately ignored, not interpreted as zero.
        self.results["cases"]["cap_200"][a.GAUGES] = {}
        self.results["cases"]["cap_200"][a.MONITORS] = {}
        self.assertEqual(len(a.compare_records(self.results, self.figures)["comparison"]), 7)
        self.results["cases"]["cap_200"]["valid_for_comparison"] = True
        with self.assertRaisesRegex(a.RecordError, "Only accepted"):
            a.compare_records(self.results, self.figures)

    def test_accepted_case_with_failed_check_rejected(self):
        self.results["cases"]["cap_050"]["time_step_check"]["status"] = "failed"
        with self.assertRaises(a.RecordError):
            a.compare_records(self.results, self.figures)

    def test_missing_nonfinite_or_invalid_metric_stops_comparison(self):
        for value in (None, D("NaN"), D("Infinity")):
            results = copy.deepcopy(self.results)
            results["cases"]["cap_100"][a.GAUGES]["P2"]["maximum_eta_m"] = value
            with self.subTest(value=value), self.assertRaises(a.RecordError):
                a.compare_records(results, self.figures)
        del self.figures["runup_metrics"]["cap_050"]["expanded"]["wetted_eligible_cells"]
        with self.assertRaises(KeyError):
            a.compare_records(self.results, self.figures)

    def test_grid_spacing_must_match_domain(self):
        self.figures["simulation_settings"]["dy_m"] = 30
        with self.assertRaisesRegex(a.RecordError, "Grid spacing"):
            a.compare_records(self.results, self.figures)

    def test_missing_peak_evidence_continues_other_comparisons(self):
        for source in (self.results["cases"]["cap_100"][a.MONITORS], self.figures["runup_metrics"]["cap_100"]):
            del source["expanded"]["peak_locations"]
        result = a.compare_records(self.results, self.figures)
        self.assertEqual(len(result["comparison"]), 7)
        self.assertEqual(result["threshold_bound"][1]["status"], "not established from available records")

    def test_public_only_inputs_and_hash_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in a.INPUTS:
                (root/name).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(a.ROOT/name, root/name)
            results, figures, _ = a.verify_inputs(root)
            self.assertEqual(len(a.compare_records(results, figures)["comparison"]), 7)
            with (root/a.RESULTS).open("a") as f:
                f.write("\n")
            with self.assertRaisesRegex(a.RecordError, "Result hash mismatch"):
                a.verify_inputs(root)

    def test_csv_markdown_html_agreement_and_determinism(self):
        result = a.compare_records(self.results, self.figures)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            a.write_reports(result, path, "test-commit")
            reader = TableReader()
            reader.feed((path/"report.html").read_text())
            md = (path/"report.md").read_text()
            index = 0
            for key, (_, columns) in a.TABLES.items():
                with (path/f"{key}.csv").open(newline="") as f:
                    csv_rows = list(csv.DictReader(f))
                self.assertEqual(len(csv_rows), len(result[key]))
                for model, recorded in zip(result[key], csv_rows):
                    texts = []
                    for field, _, digits in columns:
                        cell = reader.cells[index]
                        index += 1
                        self.assertEqual(recorded[field], a.raw(model[field]))
                        self.assertEqual(cell["data-value"], recorded[field])
                        self.assertEqual(cell["text"], a.display(model, field, digits))
                        texts.append(cell["text"])
                    self.assertIn("| " + " | ".join(texts) + " |", md)
            first = {p.name: p.read_bytes() for p in path.iterdir()}
            a.write_reports(result, path, "test-commit")
            self.assertEqual(first, {p.name: p.read_bytes() for p in path.iterdir()})


if __name__ == "__main__":
    unittest.main()
