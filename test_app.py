import json
import os
import unittest
from unittest.mock import patch

import app


class DatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sample = app.make_dataset(app.SAMPLE.name, app.SAMPLE.read_bytes())

    def test_sample_total_sales_uses_actual_rows(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
            app.HISTORY.clear()
            with patch("app.gemini_plan", side_effect=AssertionError("common questions use the local interpreter")):
                result = app.analyze("What is the total sales?", self.sample)
        self.assertEqual(result["rows"][0]["Result"], 401500)
        self.assertIn("401,500", result["statement"])
        self.assertEqual(result["warning"], "")

    def test_highest_revenue_is_grouped_by_product(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
            app.HISTORY.clear()
            result = app.analyze("Which product has the highest revenue?", self.sample)
        self.assertEqual(result["rows"][0]["product"], "Gaming Laptop")
        self.assertEqual(result["rows"][0]["sales"], 95000)

    def test_top_five_products_returns_five_ranked_rows(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
            app.HISTORY.clear()
            result = app.analyze("Identify the top 5 performing products", self.sample)
        self.assertEqual(len(result["rows"]), 5)
        self.assertEqual(result["rows"][0]["product"], "Gaming Laptop")

    def test_completed_order_count_applies_status_filter(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
            app.HISTORY.clear()
            result = app.analyze("How many orders are completed?", self.sample)
        self.assertEqual(result["rows"][0]["Result"], 15)
        self.assertIn("Completed", result["method"])

    def test_show_pending_orders_returns_filtered_source_rows(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
            app.HISTORY.clear()
            result = app.analyze("Show pending orders", self.sample)
        self.assertEqual(len(result["rows"]), 5)
        self.assertTrue(all(row["status"] == "Pending" for row in result["rows"]))

    def test_monthly_trend_uses_detected_date_column(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
            app.HISTORY.clear()
            result = app.analyze("Show monthly sales trends", self.sample)
        self.assertEqual(result["chart"]["type"], "line")
        self.assertEqual(result["rows"], [{"Month": "Jun 2026", "sales": 401500}])
        self.assertIn("one month of data", result["statement"])

    def test_monthly_trend_is_chronological_not_sorted_by_sales(self):
        data = app.make_dataset("months.csv", b"order_date,sales\n2026-03-01,20\n2026-01-01,10\n2026-02-01,30\n")
        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
            app.HISTORY.clear()
            result = app.analyze("Show monthly sales trends", data)
        self.assertEqual([row["Month"] for row in result["rows"]],
                         ["Jan 2026", "Feb 2026", "Mar 2026"])

    def test_category_comparison_groups_sales(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
            app.HISTORY.clear()
            result = app.analyze("Compare sales across categories", self.sample)
        self.assertEqual(result["rows"][0], {"category": "Electronics", "sales": 255000})
        self.assertEqual(result["chart"]["type"], "bar")

    def test_missing_requested_metric_is_not_replaced_by_another_measure(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
            app.HISTORY.clear()
            with patch("app.gemini_plan", side_effect=RuntimeError("AI is not configured")):
                with self.assertRaisesRegex(ValueError, "no numeric column for profit"):
                    app.analyze("What is the average profit by category?", self.sample)

    def test_scatter_relationship_uses_two_numeric_columns(self):
        data = app.make_dataset("relationship.csv", b"quantity,sales\n1,10\n2,20\n3,30\n")
        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
            app.HISTORY.clear()
            result = app.analyze("Show the relationship between sales and quantity", data)
        self.assertEqual(result["chart"]["type"], "scatter")
        self.assertEqual(result["columns"], ["sales", "quantity"])
        self.assertIn("Pearson r = 1.000", result["statement"])

    def test_gemini_uses_the_model_from_the_crm_notebook(self):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _size):
                plan = {"operation": "sum", "value_column": "sales", "group_by": None,
                        "sort": "desc", "limit": 10, "filters": [], "chart": "kpi"}
                response = {"candidates": [{"content": {"parts": [{"text": json.dumps(plan)}]}}]}
                return json.dumps(response).encode()

        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}, clear=True), \
                patch("app.urllib.request.urlopen", return_value=FakeResponse()) as urlopen:
            app.gemini_plan("What is the total sales?", self.sample, [])
        request = urlopen.call_args.args[0]
        self.assertIn("models/gemini-3.8-flash:generateContent", request.full_url)

    def test_csv_and_json_parsers(self):
        rows, columns = app.parse_csv(b"name,value\nA,1\nB,2\n")
        self.assertEqual(columns, ["name", "value"])
        self.assertEqual(len(rows), 2)
        json_rows, json_columns = app.parse_json(b'{"data":[{"name":"A","value":1}]}')
        self.assertEqual(json_columns, ["name", "value"])
        self.assertEqual(json_rows[0]["value"], 1)
        self.assertIsNone(app.number("Order 101"))
        self.assertEqual(app.number("(₹1,200.50)"), -1200.5)

    def test_excel_export_is_a_readable_xlsx_workbook(self):
        content = app.make_xlsx(["name", "value"], [{"name": "A", "value": 12}])
        rows, columns = app.parse_xlsx(content)
        self.assertEqual(columns, ["name", "value"])
        self.assertEqual(rows, [{"name": "A", "value": 12}])


if __name__ == "__main__":
    unittest.main()
