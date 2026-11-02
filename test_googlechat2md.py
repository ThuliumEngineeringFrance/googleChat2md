import tempfile
import unittest
from pathlib import Path

import googlechat2md as app


class Request:
    def __init__(self, response):
        self.response = response

    def execute(self, num_retries):
        return self.response


class ExportTests(unittest.TestCase):
    def test_pagination(self):
        responses = {None: {"messages": [{"name": "one"}], "nextPageToken": "next"},
                     "next": {"messages": [{"name": "two"}]}}
        self.assertEqual([m["name"] for m in app.pages(lambda token: Request(responses[token]), "messages")],
                         ["one", "two"])

    def test_repeated_page_token_fails(self):
        with self.assertRaises(ValueError):
            list(app.pages(lambda token: Request({"nextPageToken": "same"}), "messages"))

    def test_render_preserves_unicode_and_fences(self):
        result = app.render({"name": "spaces/a"}, [{"name": "m", "text": "été ``` test",
                            "sender": {"displayName": "Élodie"}}])
        self.assertIn("Élodie", result)
        self.assertIn("````\nété ``` test\n````", result)
        self.assertIn("métadonnées uniquement", result)

    def test_attachments_are_readable_without_token_urls(self):
        result = app.render({}, [{"attachment": [
            {"contentName": "Tableau", "contentType": "application/vnd.google-apps.spreadsheet",
             "source": "DRIVE_FILE", "driveDataRef": {"driveFileId": "drive-id"}},
            {"contentName": "image.png", "source": "UPLOADED_CONTENT", "downloadUri": "secret-token"}]}])
        self.assertIn('Identifiant Drive : "drive-id"', result)
        self.assertIn('Nom : "image.png"', result)
        self.assertIn('Contenu : non téléchargé', result)
        self.assertNotIn('secret-token', result)

    def test_folder_name_sanitizes_and_disambiguates(self):
        folder = app.filename({"name": "spaces/a", "displayName": "Projet / équipe"})
        self.assertTrue(folder.startswith("Projet _ équipe - "))
        self.assertNotIn("/", folder)
        self.assertNotEqual(folder, app.filename({"name": "spaces/b", "displayName": "Projet / équipe"}))
        self.assertTrue(app.filename({"name": "spaces/a"}).startswith("Conversation sans nom - "))

    def test_atomic_write_does_not_overwrite_without_permission(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "export.md"
            app.atomic_write(path, "original")
            with self.assertRaises(FileExistsError):
                app.atomic_write(path, "replacement")
            self.assertEqual(path.read_text(encoding="utf-8"), "original")
            app.atomic_write(path, "replacement", overwrite=True)
            self.assertEqual(path.read_text(encoding="utf-8"), "replacement")


if __name__ == "__main__":
    unittest.main()
