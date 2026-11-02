# Cahier des charges — Export Google Chat vers Markdown

- Auteur : Yann Challet
- Statut : proposition à valider
- Date : 2 novembre 2026

## 1. Objectif

Créer un outil local permettant à une personne d'exporter en Markdown les conversations Google Chat auxquelles son compte a accès, à partir de l'API officielle Google Chat. L'export doit être lisible, identifiable et exploitable sans Google Chat pour le texte récupéré.

Ce document définit une première version et les questions ouvertes ; il ne constitue pas encore une validation par un essai sur un compte réel.

### Choix confirmés

- Environnement : Google Workspace ; Yann est administrateur.
- Cible : toutes les conversations de groupe et tous les espaces dont l'utilisateur authentifié est membre, avec noms des participants lorsqu'ils sont disponibles.
- Exécution : Python sur un serveur Linux, planifiée régulièrement sans intervention après configuration.
- Sortie : un fichier Markdown par conversation contenant les messages accessibles, chacun avec sa date et son auteur ; l'utilisateur ne souhaite pas de versions datées séparées. Le format doit être facile à relire et analyser par une IA.
- Métadonnées souhaitées lorsqu'elles sont disponibles : date de modification, réactions, pièces jointes et informations de fil ; identifiants stables conservés pour le suivi.
- Étudier le téléchargement des pièces jointes ; son périmètre exact reste à valider.

## 2. Faisabilité

**Conclusion : faisable sous conditions**, pour les messages que l'API retourne au compte authentifié. Les appels `spaces.list` et `spaces.messages.list` permettent respectivement de découvrir les conversations et de lire leurs messages avec pagination. Une authentification OAuth utilisateur est l'approche proposée pour un export personnel.

| Sujet | Constat et limite |
| --- | --- |
| Accès | Le compte doit avoir accès aux espaces ; les politiques Workspace et le consentement OAuth peuvent empêcher l'utilisation. Aucun accès global à une organisation n'est garanti. |
| Conversations | `spaces.list` liste les espaces dont le compte est membre ; les conversations individuelles et de groupe sans premier message ne sont pas listées. |
| Historique | Seul le contenu encore disponible et retourné par l'API peut être exporté. La conservation, les droits et les suppressions peuvent limiter l'historique ; l'exhaustivité historique ne peut pas être garantie. |
| Messages supprimés | `showDeleted` peut renvoyer des métadonnées de suppression, pas le contenu supprimé. La V1 ne demande pas ces messages. |
| Messages système | Les messages système, notamment les annonces de membres, ne sont pas inclus dans `messages.list`. |
| Fils | Les messages exposent `thread.name` et `threadReply` ; leur restitution est envisageable, mais doit être vérifiée sur des conversations réelles et en cas de filtrage par date. |
| Auteurs | Le nom affiché n'est pas toujours fourni. Conserver l'identifiant `users/...` comme solution de repli, sans promettre une résolution systématique des noms. |
| Mise en forme | `formattedText` ne restitue pas forcément toute la mise en forme de l'interface. La conversion vers Markdown nécessite des règles et des tests ; préserver le texte en cas de syntaxe non reconnue. |
| Pièces jointes | Les fichiers téléversés dans Chat peuvent être téléchargés par `media.download` avec `chat.messages.readonly` si leur référence est accessible. Les fichiers Drive nécessitent l'API Drive et des droits propres. La disponibilité concrète des références et les droits restent à tester. |
| Instantané | Une lecture paginée pendant que la conversation évolue n'est pas nécessairement un instantané cohérent ; ne pas présenter l'export comme une archive probante ou exhaustive. |

### Authentification et prérequis

- Projet Google Cloud avec API Google Chat activée, écran de consentement configuré et client OAuth adapté à une application de bureau.
- Scopes en lecture seule proposés : `https://www.googleapis.com/auth/chat.spaces.readonly` et `https://www.googleapis.com/auth/chat.messages.readonly`.
- Compte autorisé à utiliser l'application et à accéder aux conversations visées. Selon le type de compte, le statut de publication de l'application et les politiques de l'organisation, une configuration, une validation ou une approbation supplémentaire peut être nécessaire.
- Proposition initiale : OAuth utilisateur, y compris sur serveur sans navigateur via une initialisation sécurisée à définir (par exemple tunnel SSH et redirection locale), puis conservation protégée du jeton de renouvellement pour l'exécution ultérieure. Le flux OAuth pour appareils à saisie limitée ne prend pas en charge les scopes Chat dans la liste Google actuelle.
- Alternative à étudier : délégation à l'échelle du domaine avec compte de service agissant comme un utilisateur précis ; elle requiert une autorisation administrateur étendue et ne donne pas automatiquement accès à toutes les conversations. Une authentification d'application seule ne remplace pas l'accès personnel : `chat.app.messages.readonly` nécessite une approbation administrateur et ne retourne que les messages publics de l'espace.
- **À vérifier par prototype** : accès effectif avec le type de compte cible, consentement et éventuelles restrictions administrateur. La documentation consultée ne suffit pas à garantir l'accès pour tous les comptes personnels ou toutes les configurations Workspace.

## 3. Périmètre fonctionnel proposé pour la V1

1. Authentifier l'utilisateur via OAuth, sans mot de passe saisi dans l'outil.
2. Lister toutes les conversations de groupe (`GROUP_CHAT`) et les espaces (`SPACE`) accessibles dont le compte est membre et les exporter en lot.
3. Exporter tous les messages retournés pour cet espace ou une période facultative, en suivant toutes les pages de résultats.
4. Produire un fichier Markdown UTF-8 par espace sélectionné, dans un répertoire choisi. Éviter les collisions et les noms de fichiers invalides ; ne pas écraser un fichier existant sans accord explicite.
5. Pour chaque message disponible : restituer texte, auteur ou identifiant de repli, date de création avec fuseau, identifiant stable et informations de fil lorsqu'elles sont disponibles. Signaler une modification si sa date est fournie.
6. Convertir au mieux la mise en forme, les liens et mentions, sans perte silencieuse pour les éléments non reconnus. Étudier le téléchargement des fichiers Chat et mentionner les pièces jointes indisponibles ; modalités et périmètre à confirmer.
7. Informer de la progression et produire un bilan : espace, période, nombre de messages et avertissements. Une erreur de page ne doit jamais produire un export présenté comme complet.

### Hors périmètre V1

Téléchargement des fichiers Drive (sous réserve de décision), synchronisation incrémentale, export automatique de toute une organisation, interface graphique, restauration dans Chat, messages système, récupération du contenu supprimé et restitution fidèle des cartes interactives. Les réactions et cartes ne sont pas garanties ; signaler les contenus non pris en charge lorsqu'ils sont détectés.

## 4. Format de sortie proposé

- Un en-tête identifie l'espace, son identifiant et la date d'export ; préciser la période demandée et les limites éventuelles.
- Messages ordonnés chronologiquement, avec identifiant de fil permettant de relier les réponses. L'organisation visuelle des fils reste à arrêter après prototype.
- Dates au format ISO 8601 avec fuseau, en UTC par défaut.
- Markdown lisible sans extension obligatoire, structuré de manière cohérente pour une IA : en-tête de conversation, séparateur et champs explicites par message, texte délimité sans ambiguïté ; préserver le contenu et échapper les caractères lorsque nécessaire.
- Inclure les identifiants stables de message et de fil, les dates et l'auteur, ainsi que les métadonnées disponibles approuvées ; distinguer explicitement les valeurs absentes des valeurs connues. Ne pas inventer de données.
- Une période, si demandée, sera définie comme un intervalle ouvert aux deux bornes, conformément aux opérateurs `createTime >` et `<` documentés. Les bornes et leur fuseau seront indiqués dans l'export.

## 5. Contraintes techniques et sécurité

- Script Python en ligne de commande utilisant les bibliothèques clientes Google officielles, exécutable sur serveur Linux sans interface graphique ; version minimale de Python à confirmer.
- Autorisations limitées aux scopes nécessaires et uniquement en lecture. Aucun envoi de message ni modification de conversation.
- Fichier de configuration OAuth et jetons locaux exclus du dépôt ; ne jamais journaliser les secrets ni le contenu des messages par défaut. Documenter leur emplacement, leur protection et leur révocation.
- Les exports contiennent potentiellement des données personnelles ou confidentielles : stockage local sous la responsabilité de l'utilisateur, avec permissions adaptées et respect des règles applicables de conservation et de partage.
- Gérer les erreurs d'authentification et d'autorisation, les quotas et erreurs réseau avec messages exploitables ; réessais bornés avec temporisation pour les erreurs transitoires. Code de sortie non nul si l'export échoue ou reste incomplet.
- Sur interruption ou échec, ne pas remplacer un export complet préexistant par un fichier partiel ; écriture temporaire puis finalisation après succès.

## 6. Critères d'acceptation

- Sur un compte de test autorisé, l'outil liste les espaces accessibles puis exporte un espace choisi sans modifier Google Chat.
- Une conversation de plus d'une page est exportée intégralement selon les réponses obtenues ; aucun message retourné n'est perdu ni dupliqué entre pages.
- Les champs absents, messages vides, caractères Unicode, liens, mentions, blocs de code et réponses de fil sont traités sans erreur ; les limites de rendu sont signalées.
- Le filtre de dates respecte les bornes documentées et affiche clairement la période effectivement demandée.
- Une erreur d'accès ou de pagination provoque un diagnostic et un échec explicite, sans annoncer un export complet ni écraser un export existant.
- Les tests automatisés utilisent des réponses API fictives et couvrent pagination, conversion, erreurs et protection contre l'écrasement ; un essai manuel distinct valide OAuth et accès réels.

## 7. Pièces jointes : étude initiale

- **Fichiers téléversés dans Chat** : le champ `attachmentDataRef.resourceName` sert à `media.download`, qui accepte le scope utilisateur `chat.messages.readonly`. Contrairement à cette méthode, `attachments.get` exige `chat.bot` et une authentification d'application : il faut vérifier si les références nécessaires figurent bien dans les réponses `messages.list` du compte cible.
- **Fichiers Google Drive** : `driveDataRef` désigne une ressource Drive. Les fichiers binaires utilisent l'API Drive pour leur contenu ; les documents natifs Google nécessitent un export vers un format choisi. Une API et des scopes supplémentaires, ainsi que l'accès du compte au fichier, peuvent être nécessaires. Aucun accès à un fichier n'est garanti du seul fait qu'il apparaît dans Chat.
- **Proposition** : ranger les téléchargements dans un dossier associé à chaque conversation, avec liens Markdown relatifs ; assainir les noms, éviter les collisions, et signaler les échecs sans prétendre que les pièces jointes sont complètes. Définir une limite de taille et le comportement en cas d'échec.
- Ne pas utiliser `downloadUri` pour le téléchargement automatisé : Google le destine à l'utilisation humaine.

## 8. Plan de validation de faisabilité

1. Identifier le type de compte cible et les contraintes administrateur, puis créer les identifiants OAuth de test.
2. Réaliser un prototype minimal : consentement, `spaces.list`, puis `spaces.messages.list` sur un espace de test, sans conserver de données sensibles dans le dépôt.
3. Tester une conversation individuelle, une conversation de groupe et un espace nommé accessibles, ainsi que pagination, fils, noms d'auteurs, messages modifiés, formatage et métadonnées de pièces jointes. Noter explicitement les cas non accessibles ou non testés.
4. Comparer un échantillon avec l'interface Google Chat, puis documenter les écarts et les restrictions réellement observées.
5. Valider le périmètre V1 et seulement ensuite implémenter l'outil complet.

## 9. Décisions à prendre

- Quelle fréquence de planification et quel outil d'ordonnancement (`cron`, minuterie systemd ou autre) ?
- Les espaces nommés (`SPACE`) sont inclus ; les conversations individuelles restent exclues.
- Compte à utiliser : uniquement les conversations dont il est membre, ou besoin d'une couverture plus large nécessitant une étude spécifique et des garanties juridiques ?
- Quelle politique de téléchargement : fichiers Chat seulement ou aussi Drive, formats des documents Google, limite de taille et comportement en cas d'échec ?
- Préférer une chronologie globale avec identifiants de fils ou un regroupement visuel par fil ?
- Lors des mises à jour quotidiennes, faut-il conserver dans le fichier les messages déjà exportés qui ne sont plus accessibles dans Chat, ou refléter uniquement l'état actuel ?
- Comment signaler les échecs ou la nécessité de renouveler les autorisations ?

## 10. Sources officielles

Consultées le 2 novembre 2026 :

- [Lister les espaces](https://developers.google.com/workspace/chat/api/reference/rest/v1/spaces/list)
- [Lister les messages : authentification, pagination, filtres et suppressions](https://developers.google.com/workspace/chat/api/reference/rest/v1/spaces.messages/list)
- [Ressource Message : champs, auteurs, formatage et fils](https://developers.google.com/workspace/chat/api/reference/rest/v1/spaces.messages)
- [Métadonnées des pièces jointes](https://developers.google.com/workspace/chat/api/reference/rest/v1/spaces.messages.attachments/get)
- [Ressource pièce jointe et références Chat ou Drive](https://developers.google.com/workspace/chat/api/reference/rest/v1/spaces.messages.attachments)
- [Téléchargement des médias Chat](https://developers.google.com/workspace/chat/api/reference/rest/v1/media/download)
- [Authentification utilisateur et délégation](https://developers.google.com/workspace/chat/authenticate-authorize-chat-user)
- [Scopes autorisés pour le flux appareils à saisie limitée](https://developers.google.com/identity/protocols/oauth2/limited-input-device)
- [Authentification en tant qu'application et approbation administrateur](https://developers.google.com/workspace/chat/api/guides/auth/service-accounts)
