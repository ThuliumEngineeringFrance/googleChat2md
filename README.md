# googleChat2md

Prototype Python d'export des conversations de groupe et espaces Google Chat vers Markdown, conçu pour une exécution sur serveur Linux. Il exporte les conversations `GROUP_CHAT` et les espaces `SPACE` dont l'utilisateur authentifié est membre, sans les conversations individuelles.

## Prérequis

- Python 3 et accès réseau aux API Google.
- Projet Google Cloud avec API Google Chat activée et écran de consentement configuré ; autoriser l'application dans les politiques Workspace si nécessaire.
- Client OAuth Google de type **application de bureau**, téléchargé en JSON. L'utilisateur doit être membre des conversations à exporter.

## Installation et authentification

Sur une machine disposant d'un navigateur, dans un environnement Python isolé :

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python googlechat2md.py --token token.json auth --credentials credentials.json
```

Connectez-vous avec le compte qui est membre des conversations. Transférez ensuite `token.json` de manière sécurisée sur le serveur et limitez son accès à l'utilisateur chargé de l'export (`chmod 600 token.json`). Le jeton contient des informations sensibles permettant l'accès au compte ; ne le partagez pas et ne le versionnez pas. Le client OAuth et les exports sont également sensibles. Si l'autorisation est révoquée ou expire, recommencez l'authentification.

## Export

```bash
python googlechat2md.py --token token.json export --output exports --overwrite
```

Un dossier par conversation est créé à partir du nom fourni par Google, suivi d'un identifiant court pour éviter les collisions ; il contient `conversation.md`. Si Google ne fournit pas de nom, le dossier utilise « Conversation sans nom ». Un changement de nom peut créer un nouveau dossier ; les anciens exports ne sont pas supprimés. Le script affiche aussi le nombre de conversations par type : les `GROUP_CHAT` et `SPACE` sont exportés, mais pas les conversations individuelles. `--overwrite` autorise le remplacement des exports existants ; sans ce drapeau, le programme refuse de les écraser. Le processus retourne un code non nul si une conversation échoue. Les fichiers sont écrits de manière atomique, avec permissions privées sur Linux.

La commande peut être lancée chaque jour par `cron` ou une minuterie `systemd`, avec des chemins absolus, le Python de l'environnement virtuel et un compte système dédié. Prévoir une surveillance des erreurs et du jeton. L'ordonnancement n'est pas installé automatiquement.

## Limites du prototype

- Un export est une lecture complète actualisée des messages accessibles, **pas une archive cumulative** : une actualisation avec `--overwrite` peut retirer du fichier un message devenu inaccessible ou supprimé. Choisir une politique de conservation avant la mise en production.
- Les messages système et le contenu supprimé ne sont pas retournés. La lecture paginée n'est pas un instantané cohérent garanti.
- Les noms d'auteurs et de conversations peuvent être absents ; les identifiants servent de repli.
- Les pièces jointes ne sont pas téléchargées ; leur nom, type, source et identifiants disponibles sont présentés sous forme lisible, notamment l'identifiant Drive utilisable par un outil disposant des droits nécessaires. Le téléchargement via l'API média Chat reste à valider sur des données réelles ; les fichiers Drive nécessitent des autorisations distinctes.
- Les dates, fils, réactions, annotations et textes bruts ou formatés sont conservés lorsqu'ils sont fournis. La restitution ne reproduit pas exactement l'interface Chat.
- Cet outil n'a pas encore été validé sur un compte Workspace réel. Voir [le cahier des charges](CAHIER_DES_CHARGES.md).
