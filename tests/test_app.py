import io
import unittest
from unittest.mock import patch

from app import app


class AppRouteTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True)
        self.client = app.test_client()

    def test_index_describes_preview_workflow(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Preview names", response.data)
        self.assertIn(b"../static/style.css?v=20260731c", response.data)
        self.assertIn(b"width=\"48\" height=\"48\"", response.data)
        self.assertIn(b"Receipty isn\xe2\x80\x99t running", response.data)

    @patch("app.preview_receipt")
    def test_analyze_returns_preview(self, preview):
        preview.return_value = {
            "status": "success",
            "original_name": "receipt.pdf",
            "new_name": "1_2_26_Coffee_Pret_3.50.pdf",
        }
        response = self.client.post(
            "/api/analyze",
            data={"file": (io.BytesIO(b"pdf"), "receipt.pdf")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "success")
        preview.assert_called_once_with(b"pdf", "receipt.pdf")

    @patch("app.commit_receipt")
    def test_apply_passes_reviewed_name_and_fingerprint(self, commit):
        commit.return_value = {"status": "success", "new_name": "reviewed.pdf"}
        response = self.client.post(
            "/api/apply",
            json={
                "filename": "receipt.pdf",
                "new_name": "1_2_26_Coffee_Pret_3.50.pdf",
                "source_dir": "/receipts",
                "mode": "rename",
                "fingerprint": "abc123",
            },
        )
        self.assertEqual(response.status_code, 200)
        commit.assert_called_once_with(
            filename="receipt.pdf",
            new_name="1_2_26_Coffee_Pret_3.50.pdf",
            source_dir="/receipts",
            mode="rename",
            output_dir=None,
            expected_fingerprint="abc123",
        )

    def test_apply_rejects_incomplete_request(self):
        response = self.client.post("/api/apply", json={"mode": "rename"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["status"], "error")


if __name__ == "__main__":
    unittest.main()
