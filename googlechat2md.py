"""Export accessible Google Chat group conversations and spaces to Markdown."""

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

SCOPES = [
    "https://www.googleapis.com/auth/chat.spaces.readonly",
    "https://www.googleapis.com/auth/chat.messages.readonly",
]
DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.file"
DRIVE_FULL_SCOPE = "https://www.googleapis.com/auth/drive"


def atomic_write(path, content, overwrite=False):
    """Write privately in the destination directory, then publish atomically."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=".googlechat2md-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if overwrite:
            os.replace(temporary, path)
        else:
            # A hard link makes the existence check and publication one operation.
            os.link(temporary, path)
            os.unlink(temporary)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def credentials(args):
    token = Path(args.token)
    if args.command == "auth":
        drive_scopes = ([DRIVE_FULL_SCOPE] if getattr(args, "drive_full", False)
                        else [DRIVE_SCOPE] if getattr(args, "drive", False) else [])
        flow = InstalledAppFlow.from_client_secrets_file(args.credentials, SCOPES + drive_scopes)
        creds = flow.run_local_server(host="localhost", port=args.port, open_browser=True,
                                      access_type="offline", prompt="consent")
        if not creds.refresh_token:
            raise ValueError("Google n'a pas fourni de jeton de renouvellement ; relancez auth.")
        atomic_write(token, creds.to_json(), overwrite=args.overwrite)
        print(f"Jeton enregistré dans {token}. Protégez ce fichier et le client OAuth.")
        return None
    if not token.is_file():
        raise ValueError("Jeton absent : exécutez d'abord la commande auth sur une machine avec navigateur.")
    creds = Credentials.from_authorized_user_file(str(token))
    if getattr(args, "drive_folder", None) and not {DRIVE_SCOPE, DRIVE_FULL_SCOPE}.intersection(creds.scopes or []):
        raise ValueError("Autorisation Drive absente : relancez auth --drive avec --overwrite.")
    if not creds.valid:
        if not creds.refresh_token:
            raise ValueError("Jeton de renouvellement absent ; relancez auth.")
        creds.refresh(Request())
        atomic_write(token, creds.to_json(), overwrite=True)
    return creds


def pages(make_request, key):
    token = None
    seen = set()
    while True:
        response = make_request(token).execute(num_retries=5)
        yield from response.get(key, [])
        token = response.get("nextPageToken")
        if not token:
            break
        if token in seen:
            raise ValueError("Pagination invalide : jeton de page répété.")
        seen.add(token)


def scalar(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def block(value):
    """Fence raw content with a delimiter longer than any backtick run."""
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
    longest = max((len(match) for match in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}\n{text}\n{fence}"


def render_attachments(attachments):
    lines = ["### Pièces jointes", ""]
    for attachment in attachments:
        drive_id = (attachment.get("driveDataRef") or {}).get("driveFileId")
        lines.extend(["- Nom : " + scalar(attachment.get("contentName") or "Non fourni"),
                      "  - Type MIME : " + scalar(attachment.get("contentType") or "Non fourni"),
                      "  - Source : " + scalar(attachment.get("source") or "Non fournie"),
                      "  - Identifiant Chat : " + scalar(attachment.get("name") or "Non fourni")])
        if drive_id:
            lines.append("  - Identifiant Drive : " + scalar(drive_id))
        copied_id = attachment.get("_exportDriveId")
        if copied_id:
            lines.append("  - Identifiant Drive transféré : " + scalar(copied_id))
        else:
            lines.append("  - Contenu : non téléchargé")
    lines.append("")
    return lines


def render(space, messages, drive_transfer=False):
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    lines = ["# Conversation Google Chat", "", f"- Espace : {scalar(space.get('displayName') or 'Non fourni')}",
             f"- Identifiant : {scalar(space.get('name', 'Non fourni'))}",
             f"- Type : {scalar(space.get('spaceType', 'Non fourni'))}",
             f"- Export UTC : {now}", "- Période : tous les messages accessibles retournés par l'API",
             f"- Nombre de messages : {len(messages)}",
             ("- Pièces jointes : copies dans Drive lorsque disponibles ; originaux non modifiés."
              if drive_transfer else "- Pièces jointes : métadonnées uniquement, aucun téléchargement."),
             "- Limites : contenu supprimé et messages système exclus ; lecture paginée sans instantané garanti.",
             "- Texte et données structurées conservés tels que retournés ; le rendu Chat peut différer.", ""]
    for message in messages:
        sender = message.get("sender") or {}
        thread = message.get("thread") or {}
        lines.extend(["---", "", "## Message", "",
                      f"- Identifiant : {scalar(message.get('name', 'Non fourni'))}",
                      f"- Auteur : {scalar(sender.get('displayName') or sender.get('name') or 'Non fourni')}",
                      f"- Identifiant auteur : {scalar(sender.get('name', 'Non fourni'))}",
                      f"- Création : {scalar(message.get('createTime', 'Non fournie'))}",
                      f"- Modification : {scalar(message.get('lastUpdateTime', 'Non fournie'))}",
                      f"- Fil : {scalar(thread.get('name', 'Non fourni'))}",
                      f"- Réponse dans un fil : {scalar(message.get('threadReply', 'Non fourni'))}", "",
                      "### Texte brut", "", block(message.get('text', '')), ""])
        if message.get("formattedText") is not None:
            lines.extend(["### Texte formaté par Google Chat", "", block(message["formattedText"]), ""])
        if message.get("attachment"):
            lines.extend(render_attachments(message["attachment"]))
        for field, title in (("emojiReactionSummaries", "Réactions"), ("cards", "Cartes non interprétées"),
                             ("cardsV2", "Cartes non interprétées"), ("annotations", "Annotations"),
                             ("quotedMessageMetadata", "Message cité — métadonnées")):
            if message.get(field):
                lines.extend([f"### {title}", "", block(message[field]), ""])
    return "\n".join(lines)


def filename(space):
    name = space.get("name")
    if not name:
        raise ValueError("Espace sans identifiant : export interrompu.")
    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:12]
    display = space.get("displayName") or "Conversation sans nom"
    display = re.sub(r'[\\<>:"/|?*\x00-\x1f]', "_", display).strip(" .")[:100].rstrip(" .")
    if not display or display.upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        display = "Conversation sans nom"
    return f"{display} - {digest}"


def drive_matches(drive, folder, marker):
    escaped_folder = folder.replace("\\", "\\\\").replace("'", "\\'")
    query = (f"'{escaped_folder}' in parents and trashed = false and "
             f"appProperties has {{ key='googlechat2md' and value='{marker}' }}")
    return list(pages(lambda token: drive.files().list(
        q=query, spaces="drive", fields="nextPageToken,files(id)", pageSize=1000,
        pageToken=token, supportsAllDrives=True, includeItemsFromAllDrives=True), "files"))


def drive_marker(kind, identity):
    return hashlib.sha256(f"{kind}:{identity}".encode("utf-8")).hexdigest()


def drive_existing(drive, folder, marker):
    matches = drive_matches(drive, folder, marker)
    if len(matches) > 1:
        raise ValueError("Plusieurs éléments Drive avec le même identifiant ; vérification manuelle nécessaire.")
    return matches[0]["id"] if matches else None


def drive_folder(drive, parent, name, marker):
    existing = drive_existing(drive, parent, marker)
    if existing:
        return existing
    return drive.files().create(
        body={"name": name, "mimeType": "application/vnd.google-apps.folder",
              "parents": [parent], "appProperties": {"googlechat2md": marker}},
        fields="id", supportsAllDrives=True).execute(num_retries=0)["id"]


def message_date(message):
    value = message.get("createTime")
    try:
        if not isinstance(value, str) or not re.fullmatch(
                r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})", value):
            raise ValueError("format RFC 3339 attendu")
        timestamp = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        return timestamp.astimezone(dt.timezone.utc).date().isoformat()
    except ValueError as exc:
        raise ValueError(f"Message {message.get('name', 'sans identifiant')} : createTime absent ou invalide ({value!r}).") from exc


def upload_conversation(drive, folder, space_name, path):
    marker = drive_marker("conversation", space_name)
    existing = drive_existing(drive, folder, marker)
    media = MediaFileUpload(str(path), mimetype="text/markdown", resumable=True)
    try:
        if existing:
            request = drive.files().update(fileId=existing, media_body=media,
                                           fields="id", supportsAllDrives=True)
        else:
            request = drive.files().create(
                body={"name": "conversation.md", "parents": [folder],
                      "appProperties": {"googlechat2md": marker}},
                media_body=media, fields="id", supportsAllDrives=True)
        response = None
        while response is None:
            _, response = request.next_chunk(num_retries=0)
        return response["id"]
    finally:
        media.stream().close()


def transfer_attachment(chat, drive, folder, attachment):
    """Find a previous transfer by immutable Chat resource name, or create one."""
    name = attachment.get("name")
    source = attachment.get("source")
    resource = (attachment.get("attachmentDataRef") or {}).get("resourceName")
    drive_id = (attachment.get("driveDataRef") or {}).get("driveFileId")
    if not name:
        raise ValueError("Pièce jointe Chat sans identifiant.")
    if source == "DRIVE_FILE" and not drive_id:
        raise ValueError(f"Pièce jointe {name} : identifiant du fichier Drive absent.")
    if source != "DRIVE_FILE" and not resource:
        raise ValueError("Pièce jointe Chat sans identifiant ou référence de téléchargement.")
    marker = hashlib.sha256(name.encode("utf-8")).hexdigest()
    existing = drive_existing(drive, folder, marker)
    if existing:
        return existing
    if source == "DRIVE_FILE":
        body = {"parents": [folder], "appProperties": {"googlechat2md": marker}}
        if attachment.get("contentName"):
            body["name"] = attachment["contentName"]
        try:
            return drive.files().copy(fileId=drive_id, body=body, fields="id",
                                      supportsAllDrives=True).execute(num_retries=0)["id"]
        except HttpError as exc:
            if exc.resp.status in (403, 404):
                raise ValueError(
                    f"Pièce jointe {name} : accès refusé ou fichier Drive {drive_id} introuvable. "
                    "Vérifiez les droits du compte, les restrictions de copie et les scopes OAuth ; "
                    "drive.file ne donne pas accès à tous les fichiers existants."
                ) from exc
            raise
    # A temporary file bounds memory use and is removed on every failure path.
    with tempfile.TemporaryDirectory(prefix="googlechat2md-") as directory:
        local = Path(directory) / "attachment"
        with local.open("wb") as stream:
            request = chat.media().download_media(resourceName=resource)
            downloader = MediaIoBaseDownload(stream, request)
            done = False
            while not done:
                _, done = downloader.next_chunk(num_retries=5)
        media = MediaFileUpload(str(local), mimetype=attachment.get("contentType") or "application/octet-stream",
                                resumable=True)
        try:
            request = drive.files().create(
                body={"name": attachment.get("contentName") or "Pièce jointe Chat",
                      "parents": [folder], "appProperties": {"googlechat2md": marker}},
                media_body=media, fields="id", supportsAllDrives=True)
            # Do not retry an ambiguous create: a later run searches the durable marker.
            response = None
            while response is None:
                _, response = request.next_chunk(num_retries=0)
            return response["id"]
        finally:
            media.stream().close()


def export(args, creds):
    service = build("chat", "v1", credentials=creds, cache_discovery=False)
    folder = getattr(args, "drive_folder", None)
    drive = build("drive", "v3", credentials=creds, cache_discovery=False) if folder else None
    spaces_resource = service.spaces()
    spaces = list(pages(lambda token: spaces_resource.list(pageSize=1000, pageToken=token), "spaces"))
    counts = {}
    for space in spaces:
        kind = space.get("spaceType") or "INCONNU"
        counts[kind] = counts.get(kind, 0) + 1
    print("Types retournés par Google : " + (", ".join(f"{kind}={count}" for kind, count in sorted(counts.items())) or "aucun"))
    spaces = [space for space in spaces if space.get("spaceType") in {"GROUP_CHAT", "SPACE"}]
    print(f"{len(spaces)} conversation(s) de groupe et espace(s) accessible(s).")
    failures = 0
    for space in spaces:
        name = space.get("name")
        try:
            path = Path(args.output) / filename(space) / "conversation.md"
            if path.exists() and not args.overwrite:
                raise FileExistsError(f"{path} existe ; utilisez --overwrite pour actualiser")
            messages_resource = spaces_resource.messages()
            messages = list(pages(lambda token: messages_resource.list(
                parent=name, pageSize=1000, pageToken=token, orderBy="createTime asc"), "messages"))
            unique = {}
            for message in messages:
                message_id = message.get("name")
                if not message_id:
                    raise ValueError("Message sans identifiant : export interrompu.")
                unique[message_id] = message
            messages = sorted(unique.values(), key=lambda item: (item.get("createTime", ""), item["name"]))
            if drive:
                dates = {message["name"]: message_date(message) for message in messages
                         if any(a.get("source") in {"UPLOADED_CONTENT", "DRIVE_FILE"} for a in message.get("attachment", []))}
                space_folder = drive_folder(drive, folder, filename(space), drive_marker("space", name))
                date_folders = {}
                for message in messages:
                    for attachment in message.get("attachment", []):
                        if attachment.get("source") in {"UPLOADED_CONTENT", "DRIVE_FILE"}:
                            date = dates[message["name"]]
                            if date not in date_folders:
                                date_folders[date] = drive_folder(
                                    drive, space_folder, date, drive_marker("date", f"{name}:{date}"))
                            attachment["_exportDriveId"] = transfer_attachment(
                                service, drive, date_folders[date], attachment)
            atomic_write(path, render(space, messages, bool(drive)), overwrite=args.overwrite)
            if drive:
                upload_conversation(drive, space_folder, name, path)
            print(f"{name} : {len(messages)} message(s) → {path}")
        except (HttpError, OSError, ValueError) as exc:
            failures += 1
            print(f"Échec pour {name or 'espace sans identifiant'} : {exc}", file=sys.stderr)
    if failures:
        raise ValueError(f"Export incomplet : {failures} conversation(s) en échec.")


def confirm(question):
    return input(f"{question} [o/N] : ").strip().lower() in {"o", "oui"}


def interactive(token):
    while True:
        print("\nGoogle Chat vers Markdown")
        print(f"Jeton : {token}")
        print("1. Exporter les conversations et espaces")
        print("2. Configurer ou renouveler l'authentification")
        print("3. Quitter")
        choice = input("Votre choix [1-3] : ").strip()
        if choice == "3":
            return 0
        if choice == "2":
            if Path(token).exists() and not confirm("Remplacer le jeton existant ?"):
                print("Authentification annulée.")
                continue
            client = input("Fichier client OAuth [credentials.json] : ").strip() or "credentials.json"
            print("drive.file limite l'accès aux fichiers créés par l'application ou explicitement autorisés ; les fichiers Drive partagés dans Chat ne sont pas tous accessibles automatiquement.")
            drive = confirm("Autoriser aussi la création de fichiers dans Drive (drive.file) ?")
            drive_full = False
            if drive:
                print("L'accès Drive étendu permet à l'application de lire, modifier et supprimer les fichiers Drive accessibles au compte.")
                drive_full = confirm("Demander cet accès étendu pour copier les fichiers Drive existants ?")
            args = argparse.Namespace(command="auth", token=token, credentials=client, port=0,
                                      overwrite=Path(token).exists(), drive=drive, drive_full=drive_full)
            try:
                credentials(args)
            except (OSError, ValueError, RefreshError, HttpError) as exc:
                print(f"Erreur : {exc}", file=sys.stderr)
        elif choice == "1":
            if not Path(token).is_file():
                print("Jeton absent : choisissez d'abord l'authentification (option 2).")
                continue
            output = input("Dossier de sortie [exports] : ").strip() or "exports"
            print("Attention : remplacer les exports peut retirer les messages supprimés ou inaccessibles dans Chat.")
            overwrite = confirm("Autoriser le remplacement des fichiers existants ?")
            folder = input("ID du dossier Drive pour les conversations et pièces jointes [aucun] : ").strip()
            args = argparse.Namespace(command="export", token=token, output=output, overwrite=overwrite,
                                      drive_folder=folder or None)
            try:
                export(args, credentials(args))
            except (OSError, ValueError, RefreshError, HttpError) as exc:
                print(f"Erreur : {exc}", file=sys.stderr)
        else:
            print("Choix invalide. Saisissez 1, 2 ou 3.")


def main():
    parser = argparse.ArgumentParser(description="Export Google Chat GROUP_CHAT et SPACE en Markdown.")
    parser.add_argument("--token", default="token.json", help="Fichier privé de jeton OAuth (défaut : token.json).")
    sub = parser.add_subparsers(dest="command")
    auth = sub.add_parser("auth", help="Initialiser OAuth localement avec un navigateur.")
    auth.add_argument("--credentials", required=True, help="JSON du client OAuth de bureau Google.")
    auth.add_argument("--port", type=int, default=0, help="Port local OAuth (0 : automatique).")
    auth.add_argument("--overwrite", action="store_true", help="Remplacer le jeton existant.")
    auth.add_argument("--drive", action="store_true", help="Demander le scope drive.file : seuls les fichiers créés par l'application ou explicitement autorisés lui sont accessibles, pas tous les fichiers Drive partagés dans Chat.")
    auth.add_argument("--drive-full", action="store_true", help="Demander l'accès complet en lecture et écriture aux fichiers Drive accessibles au compte.")
    out = sub.add_parser("export", help="Exporter les conversations de groupe et espaces accessibles.")
    out.add_argument("--output", default="exports", help="Répertoire de sortie.")
    out.add_argument("--overwrite", action="store_true", help="Actualiser les fichiers existants.")
    out.add_argument("--drive-folder", help="ID du dossier Drive destiné aux conversations et aux pièces jointes Chat et Drive accessibles avec drive.file.")
    args = parser.parse_args()
    if args.command is None:
        if not sys.stdin.isatty():
            print("Une commande est nécessaire sans terminal interactif ; consultez --help.", file=sys.stderr)
            return 2
        try:
            return interactive(args.token)
        except (EOFError, KeyboardInterrupt):
            print("\nOpération annulée.")
            return 1
    try:
        creds = credentials(args)
        if args.command == "export":
            export(args, creds)
    except (OSError, ValueError, RefreshError, HttpError) as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
