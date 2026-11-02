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

SCOPES = [
    "https://www.googleapis.com/auth/chat.spaces.readonly",
    "https://www.googleapis.com/auth/chat.messages.readonly",
]


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
        flow = InstalledAppFlow.from_client_secrets_file(args.credentials, SCOPES)
        creds = flow.run_local_server(host="localhost", port=args.port, open_browser=True,
                                      access_type="offline", prompt="consent")
        if not creds.refresh_token:
            raise ValueError("Google n'a pas fourni de jeton de renouvellement ; relancez auth.")
        atomic_write(token, creds.to_json(), overwrite=args.overwrite)
        print(f"Jeton enregistré dans {token}. Protégez ce fichier et le client OAuth.")
        return None
    if not token.is_file():
        raise ValueError("Jeton absent : exécutez d'abord la commande auth sur une machine avec navigateur.")
    creds = Credentials.from_authorized_user_file(str(token), SCOPES)
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
        lines.append("  - Contenu : non téléchargé")
    lines.append("")
    return lines


def render(space, messages):
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    lines = ["# Conversation Google Chat", "", f"- Espace : {scalar(space.get('displayName') or 'Non fourni')}",
             f"- Identifiant : {scalar(space.get('name', 'Non fourni'))}",
             f"- Type : {scalar(space.get('spaceType', 'Non fourni'))}",
             f"- Export UTC : {now}", "- Période : tous les messages accessibles retournés par l'API",
             f"- Nombre de messages : {len(messages)}",
             "- Pièces jointes : métadonnées uniquement, aucun téléchargement.",
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


def export(args, creds):
    service = build("chat", "v1", credentials=creds, cache_discovery=False)
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
            atomic_write(path, render(space, messages), overwrite=args.overwrite)
            print(f"{name} : {len(messages)} message(s) → {path}")
        except (HttpError, OSError, ValueError) as exc:
            failures += 1
            print(f"Échec pour {name or 'espace sans identifiant'} : {exc}", file=sys.stderr)
    if failures:
        raise ValueError(f"Export incomplet : {failures} conversation(s) en échec.")


def main():
    parser = argparse.ArgumentParser(description="Export Google Chat GROUP_CHAT et SPACE en Markdown.")
    parser.add_argument("--token", default="token.json", help="Fichier privé de jeton OAuth (défaut : token.json).")
    sub = parser.add_subparsers(dest="command", required=True)
    auth = sub.add_parser("auth", help="Initialiser OAuth localement avec un navigateur.")
    auth.add_argument("--credentials", required=True, help="JSON du client OAuth de bureau Google.")
    auth.add_argument("--port", type=int, default=0, help="Port local OAuth (0 : automatique).")
    auth.add_argument("--overwrite", action="store_true", help="Remplacer le jeton existant.")
    out = sub.add_parser("export", help="Exporter les conversations de groupe et espaces accessibles.")
    out.add_argument("--output", default="exports", help="Répertoire de sortie.")
    out.add_argument("--overwrite", action="store_true", help="Actualiser les fichiers existants.")
    args = parser.parse_args()
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
