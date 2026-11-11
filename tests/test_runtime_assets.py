from pathlib import Path
import unittest

from fastapi.testclient import TestClient

from app.main import app


class RuntimeAssetTests(unittest.TestCase):
    def test_standard_library_is_served_inline_without_archive_filename(self):
        with TestClient(app) as client:
            response = client.get("/runtime/python-stdlib")
        expected = (Path(__file__).resolve().parents[1] / "frontend" / "assets"
                    / "pyodide" / "python_stdlib.zip").read_bytes()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/octet-stream")
        self.assertEqual(response.headers["content-disposition"], "inline")
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        self.assertEqual(response.content, expected)


if __name__ == "__main__":
    unittest.main()
