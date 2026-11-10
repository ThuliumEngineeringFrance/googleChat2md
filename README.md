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

## Mode interactif

Sur Windows, depuis le dossier du projet :

```powershell
.\.venv\Scripts\python.exe googlechat2md.py
```

Sur Linux, après activation de l'environnement virtuel : `python googlechat2md.py`. Le menu permet de configurer l'authentification et de choisir le dossier d'export. Le remplacement des fichiers existants nécessite une confirmation explicite ; il peut retirer des messages devenus inaccessibles. L'authentification initiale nécessite toujours un navigateur sur la machine où elle est lancée.

Pour un serveur sans terminal ou une tâche planifiée, utilisez les commandes explicites ci-dessous : le menu interactif ne démarre pas sans terminal.

## Export

```bash
python googlechat2md.py --token token.json export --output exports --overwrite
```

Un dossier par conversation est créé à partir du nom fourni par Google, suivi d'un identifiant court pour éviter les collisions ; il contient `conversation.md`. Si Google ne fournit pas de nom, le dossier utilise « Conversation sans nom ». Un changement de nom peut créer un nouveau dossier ; les anciens exports ne sont pas supprimés. Le script affiche aussi le nombre de conversations par type : les `GROUP_CHAT` et `SPACE` sont exportés, mais pas les conversations individuelles. `--overwrite` autorise le remplacement des exports existants ; sans ce drapeau, le programme refuse de les écraser. Le processus retourne un code non nul si une conversation échoue. Les fichiers sont écrits de manière atomique, avec permissions privées sur Linux.

La commande peut être lancée chaque jour par `cron` ou une minuterie `systemd`, avec des chemins absolus, le Python de l'environnement virtuel et un compte système dédié. Prévoir une surveillance des erreurs et du jeton. L'ordonnancement n'est pas installé automatiquement.

## Copie des pièces jointes Chat dans Drive (optionnel)

Pour copier des fichiers Drive existants qui ne sont pas accessibles via `drive.file`, une option explicite `auth --drive-full --overwrite` demande le scope `https://www.googleapis.com/auth/drive`. Ce scope donne à l'application un accès étendu en lecture, modification et suppression aux fichiers Drive accessibles au compte, même si ce script ne déplace ni ne supprime les originaux. Utilisez-le uniquement si nécessaire et après validation de l'administrateur ; il ne contourne ni les restrictions de partage ou de copie ni les politiques Workspace. Renouvelez le jeton sur une machine avec navigateur et transférez-le de manière sécurisée sur le serveur.

Activez l'API Google Drive dans le projet Google Cloud. Ajoutez le scope `https://www.googleapis.com/auth/drive.file` à la configuration OAuth si nécessaire, puis renouez le consentement :

```bash
python googlechat2md.py --token token.json auth --credentials credentials.json --drive --overwrite
```

Ce scope autorise l'application à créer et gérer les fichiers qu'elle crée ou que l'utilisateur lui ouvre explicitement ; il ne donne pas accès à tous les fichiers Drive. Choisissez un dossier que l'application est autorisée à utiliser : un dossier préexistant peut ne pas être accessible avec `drive.file`. Un refus nécessite un dossier ouvert à l'application par un mécanisme compatible ou une autre configuration d'autorisations, sans élargir les droits automatiquement. Le dossier cible et ses permissions déterminent qui peut lire les copies.

Pour transférer les fichiers téléversés dans Chat lors de l'export :

```bash
python googlechat2md.py --token token.json export --output exports --overwrite --drive-folder ID_DU_DOSSIER
```

L'ID figure dans l'URL du dossier Drive après `/folders/`. Le mode interactif permet aussi de saisir l'ID et de demander l'autorisation Drive. Dans ce dossier, l'outil crée un sous-dossier par espace, contenant `conversation.md` et des sous-dossiers `AAAA-MM-JJ` pour les pièces jointes, selon la date UTC de création du message. Le Markdown Drive est actualisé à chaque export réussi. Les fichiers téléversés dans Chat sont téléchargés temporairement puis copiés dans Drive ; les fichiers déjà présents dans Drive sont copiés sans déplacer les originaux. La copie requiert que l'application ait accès au fichier source et que sa copie soit autorisée ; `drive.file` ne donne pas automatiquement accès aux fichiers existants. Les copies effectuées avant cette organisation et situées à la racine ne sont ni déplacées ni supprimées et peuvent être copiées à nouveau. Les identifiants des copies figurent dans le Markdown. Une marque Drive permet de retrouver les copies lors des exécutions suivantes : ne pas exécuter deux exports simultanément, et conserver l'accès de l'application aux fichiers créés. Après un échec, certaines copies peuvent déjà exister ; relancer pour les réutiliser. Le téléchargement nécessite de l'espace disque temporaire ; les fichiers temporaires sont supprimés après traitement. Si un transfert échoue, la conversation concernée n'est pas actualisée et la commande retourne une erreur.

Le transfert nécessite une authentification renouvelée ; la première configuration doit se faire avec navigateur puis le jeton doit être transmis de façon sécurisée au serveur. Vérifiez le dossier et ses droits avant activation, car cette option crée des fichiers dans Drive. Aucun transfert réel n'a encore été validé.

## Déploiement sur un serveur Linux

Exemple pour Debian ou Ubuntu. Les commandes supposent un compte système non privilégié dédié à l'export, avec accès HTTPS sortant aux API Google et suffisamment d'espace disque pour les fichiers temporaires. Remplacez les valeurs `UTILISATEUR`, `VPS` et `ID_DU_DOSSIER` par vos valeurs. Le serveur et ses sauvegardes doivent protéger les conversations et le jeton.

### 1. Installer l'application

Sur le serveur, connecté en SSH avec le compte dédié :

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip cron
cd ~
git clone https://github.com/ThuliumEngineeringFrance/googleChat2md.git
cd googleChat2md
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Si le dépôt est privé, configurez un accès GitHub approprié. L'exemple suppose un répertoire `/home/UTILISATEUR/googleChat2md` : adaptez-le si votre répertoire personnel diffère.

### 2. Préparer et transférer le jeton

Effectuez l'authentification sur une machine dotée d'un navigateur, avec `auth --drive` si l'export Drive est souhaité. Depuis PowerShell sur Windows, transférez le fichier **autorisé** par SSH :

```powershell
scp C:\Users\User\Documents\GitHub\googleChat2md\token.json UTILISATEUR@VPS:~/googleChat2md/token.json
```

Sur le serveur, limitez l'accès :

```bash
chmod 700 ~/googleChat2md
chmod 600 ~/googleChat2md/token.json
```

Ne versionnez pas le jeton et ne l'envoyez pas par messagerie. Le fichier `credentials.json` n'est pas nécessaire pour les exports tant que le jeton fonctionne. Si l'autorisation est révoquée ou ne peut plus être renouvelée, recommencez l'authentification avec un navigateur et transférez le nouveau jeton de manière sécurisée.

### 3. Tester l'export sur le serveur

Depuis `~/googleChat2md`, remplacez `ID_DU_DOSSIER` par l'identifiant Drive réel :

```bash
.venv/bin/python googlechat2md.py --token token.json export --output exports --overwrite --drive-folder ID_DU_DOSSIER
```

Sans copie vers Drive, omettez `--drive-folder ID_DU_DOSSIER`. Vérifiez les messages d'erreur, les exports locaux et, si activé, le Markdown et les pièces jointes dans Drive. `--overwrite` remplace les Markdown précédents : les messages supprimés ou devenus inaccessibles dans Chat peuvent disparaître de l'export.

### 4. Planifier une exécution quotidienne

Assurez-vous que le service `cron` est actif, puis ouvrez la crontab du compte dédié :

```bash
sudo systemctl enable --now cron
crontab -e
```

Ajoutez cette ligne, en adaptant les chemins et l'identifiant Drive :

```cron
0 2 * * * cd /home/UTILISATEUR/googleChat2md && /home/UTILISATEUR/googleChat2md/.venv/bin/python googlechat2md.py --token token.json export --output exports --overwrite --drive-folder ID_DU_DOSSIER >> /home/UTILISATEUR/googleChat2md/export.log 2>&1
```

La tâche s'exécute à 2 h selon le fuseau du serveur (`timedatectl`). Consultez `crontab -l` et `cat ~/googleChat2md/export.log` pour vérifier la configuration et les résultats. Limitez l'accès au journal et prévoyez sa rotation et une alerte en cas d'échec ou de jeton invalide : `cron` n'assure pas ces fonctions ici. Ne lancez pas deux exports simultanément ; choisissez une fréquence compatible avec la durée d'exécution.

### 5. Mettre à jour

Après sauvegarde et vérification des changements, depuis le dossier du projet :

```bash
git pull --ff-only
.venv/bin/python -m pip install -r requirements.txt
```

Relancez un test manuel après mise à jour. La procédure de déploiement n'a pas été validée sur tous les VPS ou distributions Linux.

## Limites du prototype

- Un export est une lecture complète actualisée des messages accessibles, **pas une archive cumulative** : une actualisation avec `--overwrite` peut retirer du fichier un message devenu inaccessible ou supprimé. Choisir une politique de conservation avant la mise en production.
- Les messages système et le contenu supprimé ne sont pas retournés. La lecture paginée n'est pas un instantané cohérent garanti.
- Les noms d'auteurs et de conversations peuvent être absents ; les identifiants servent de repli.
- Sans option Drive, les pièces jointes ne sont pas téléchargées. Avec l'option Drive, les fichiers téléversés dans Chat et les fichiers Drive accessibles sont copiés, sans modification des originaux. La lecture des documents par un MCP dépend de ses propres droits.
- Les dates, fils, réactions, annotations et textes bruts ou formatés sont conservés lorsqu'ils sont fournis. La restitution ne reproduit pas exactement l'interface Chat.
- Cet outil n'a pas encore été validé sur un compte Workspace réel. Voir [le cahier des charges](CAHIER_DES_CHARGES.md).
