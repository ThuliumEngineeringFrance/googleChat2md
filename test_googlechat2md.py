import argparse
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

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

    def test_message_date_uses_utc_and_rejects_missing_date(self):
        self.assertEqual(app.message_date({"createTime": "2026-09-10T00:30:00+02:00"}), "2026-09-09")
        with self.assertRaises(ValueError):
            app.message_date({})

    @patch.object(app, "MediaFileUpload")
    def test_upload_conversation_updates_existing(self, upload):
        drive = Mock()
        drive.files.return_value.list.return_value.execute.return_value = {"files": [{"id": "old"}]}
        drive.files.return_value.update.return_value.next_chunk.return_value = (None, {"id": "old"})
        self.assertEqual(app.upload_conversation(drive, "folder", "spaces/a", "conversation.md"), "old")
        drive.files.return_value.update.assert_called_once()
        drive.files.return_value.create.assert_not_called()
        upload.return_value.stream.return_value.close.assert_called_once()

    def test_existing_drive_transfer_is_reused(self):
        drive = Mock()
        drive.files.return_value.list.return_value.execute.return_value = {"files": [{"id": "existing"}]}
        attachment = {"name": "spaces/a/messages/b/attachments/c",
                      "attachmentDataRef": {"resourceName": "media"}}
        chat = Mock()
        self.assertEqual(app.transfer_attachment(chat, drive, "folder", attachment), "existing")
        chat.media.assert_not_called()
        drive.files.return_value.create.assert_not_called()

    @patch.object(app, "MediaFileUpload")
    @patch.object(app, "MediaIoBaseDownload")
    def test_transfer_uses_media_download(self, downloader, media_upload):
        chat, drive = Mock(), Mock()
        drive.files.return_value.list.return_value.execute.return_value = {"files": []}
        drive.files.return_value.create.return_value.next_chunk.return_value = (None, {"id": "new-id"})
        downloader.return_value.next_chunk.return_value = (None, True)
        attachment = {"name": "spaces/a/messages/b/attachments/c",
                      "attachmentDataRef": {"resourceName": "media-ref"}}
        self.assertEqual(app.transfer_attachment(chat, drive, "folder", attachment), "new-id")
        chat.media.return_value.download_media.assert_called_once_with(resourceName="media-ref")
        chat.media.return_value.download.assert_not_called()
        media_upload.return_value.stream.return_value.close.assert_called_once()

    @patch.object(app, "MediaFileUpload")
    @patch.object(app, "MediaIoBaseDownload")
    def test_transfer_closes_upload_on_failure(self, downloader, media_upload):
        chat, drive = Mock(), Mock()
        drive.files.return_value.list.return_value.execute.return_value = {"files": []}
        drive.files.return_value.create.return_value.next_chunk.side_effect = OSError("upload failed")
        downloader.return_value.next_chunk.return_value = (None, True)
        attachment = {"name": "attachment", "attachmentDataRef": {"resourceName": "media"}}
        with self.assertRaises(OSError):
            app.transfer_attachment(chat, drive, "folder", attachment)
        media_upload.return_value.stream.return_value.close.assert_called_once()

    def test_drive_attachment_is_copied_without_moving_original(self):
        chat, drive = Mock(), Mock()
        drive.files.return_value.list.return_value.execute.return_value = {"files": []}
        drive.files.return_value.copy.return_value.execute.return_value = {"id": "copy-id"}
        attachment = {"name": "attachment", "source": "DRIVE_FILE",
                      "driveDataRef": {"driveFileId": "source-id"}, "contentName": "test.pdf"}
        self.assertEqual(app.transfer_attachment(chat, drive, "folder", attachment), "copy-id")
        self.assertEqual(drive.files.return_value.copy.call_args.kwargs["fileId"], "source-id")
        drive.files.return_value.update.assert_not_called()
        chat.media.assert_not_called()

    def test_export_error_includes_space_and_attachment_name(self):
        chat, drive = Mock(), Mock()
        space = {"name": "spaces/a", "displayName": "dev test", "spaceType": "SPACE"}
        message = {"name": "message", "createTime": "2026-01-01T00:00:00Z",
                   "attachment": [{"name": "attachment", "source": "DRIVE_FILE", "contentName": "test.pdf"}]}
        chat.spaces.return_value.list.return_value.execute.return_value = {"spaces": [space]}
        chat.spaces.return_value.messages.return_value.list.return_value.execute.return_value = {"messages": [message]}
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(app, "build", side_effect=[chat, drive]), \
                patch.object(app, "drive_folder", return_value="folder"), \
                patch.object(app, "transfer_attachment", side_effect=ValueError("accès refusé")), \
                contextlib.redirect_stderr(io.StringIO()) as errors:
            args = argparse.Namespace(output=directory, overwrite=True, drive_folder="folder")
            with self.assertRaises(ValueError):
                app.export(args, Mock())
            self.assertIn('"dev test"', errors.getvalue())
            self.assertIn('"test.pdf"', errors.getvalue())
            self.assertIn('accès refusé', errors.getvalue())

    def test_drive_attachment_without_id_fails(self):
        with self.assertRaises(ValueError):
            app.transfer_attachment(Mock(), Mock(), "folder", {"name": "attachment", "source": "DRIVE_FILE"})

    def test_transfer_requires_download_reference(self):
        with self.assertRaises(ValueError):
            app.transfer_attachment(Mock(), Mock(), "folder", {"name": "attachment"})

    def test_transferred_drive_id_is_rendered(self):
        result = app.render({}, [{"attachment": [{"contentName": "image.png", "_exportDriveId": "copied"}]}])
        self.assertIn('Identifiant Drive transféré : "copied"', result)

    def test_folder_name_sanitizes_and_disambiguates(self):
        folder = app.filename({"name": "spaces/a", "displayName": "Projet / équipe"})
        self.assertTrue(folder.startswith("Projet _ équipe - "))
        self.assertNotIn("/", folder)
        self.assertNotEqual(folder, app.filename({"name": "spaces/b", "displayName": "Projet / équipe"}))
        self.assertTrue(app.filename({"name": "spaces/a"}).startswith("Conversation sans nom - "))

    def test_interactive_export_confirms_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            token = Path(directory) / "token.json"
            token.touch()
            with patch("builtins.input", side_effect=["1", "", "oui", "", "3"]), \
                    patch.object(app, "credentials", return_value="creds"), \
                    patch.object(app, "export") as export:
                self.assertEqual(app.interactive(str(token)), 0)
                args, creds = export.call_args.args
                self.assertTrue(args.overwrite)
                self.assertEqual(args.output, "exports")
                self.assertEqual(creds, "creds")

    def test_interactive_does_not_replace_token_without_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            token = Path(directory) / "token.json"
            token.touch()
            with patch("builtins.input", side_effect=["2", "", "3"]), \
                    patch.object(app, "credentials") as credentials:
                self.assertEqual(app.interactive(str(token)), 0)
                credentials.assert_not_called()

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
