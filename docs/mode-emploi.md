# Mode d'emploi : Cololight (local) pour Home Assistant

Cette intégration pilote votre lampe **Cololight** (bandeau ou hexagone) **directement sur votre
réseau local**, sans passer par le cloud LifeSmart. Elle vérifie que la lampe a bien reçu chaque
commande, et elle affiche dans Home Assistant l'état **réel** de la lampe, relu régulièrement.

Ce guide vous accompagne de l'installation jusqu'aux automatisations. Il ne suppose aucune
connaissance en programmation.

> **À propos des noms d'entités dans ce guide.** Les exemples utilisent la lampe de test, nommée
> `Cololight B614`. Sa lumière s'appelle `light.cololight_b614`. Les identifiants du curseur de
> vitesse et du bouton sont construits à partir du nom de ces entités **dans la langue de Home
> Assistant au moment où la lampe a été ajoutée** (ils ne changent pas si vous changez de langue
> ensuite) :
>
> | Entité | Home Assistant en français | Home Assistant en anglais |
> |---|---|---|
> | Vitesse de l'effet | `number.cololight_b614_vitesse_de_l_effet` | `number.cololight_b614_effect_speed` |
> | Mémoriser comme état au démarrage | `button.cololight_b614_memoriser_comme_etat_au_demarrage` | `button.cololight_b614_save_as_power_on_state` |
>
> Les exemples utilisent les identifiants français. Chez vous, les 4 caractères `b614` seront
> différents (ce sont la fin de l'adresse MAC de **votre** lampe). Si vous avez renommé l'appareil ou
> les entités, les noms changent aussi. **Copiez l'identifiant exact** depuis les paramètres de
> l'entité : **Paramètres → Appareils et services → onglet Entités**, tapez « cololight » dans la
> recherche, cliquez sur l'entité puis sur ⚙ (champ **ID d'entité**).

---

## Sommaire

1. [Avant de commencer](#1-avant-de-commencer)
2. [Installation](#2-installation)
3. [Ajouter la lampe](#3-ajouter-la-lampe)
4. [Ce que vous obtenez](#4-ce-que-vous-obtenez)
5. [Les options](#5-les-options)
6. [Utilisation dans les automatisations](#6-utilisation-dans-les-automatisations)
7. [Tableau de bord](#7-tableau-de-bord)
8. [Dépannage](#8-dépannage)
9. [Limites connues](#9-limites-connues)
10. [Questions fréquentes](#10-questions-fréquentes)

---

## 1. Avant de commencer

### Ce dont vous avez besoin

- **Home Assistant 2025.2 ou plus récent.** L'intégration a été mise au point sur la version 2026.10.
- **Une lampe Cololight déjà connectée à votre WiFi.** Cette première connexion se fait avec
  l'application officielle. L'intégration ne sait pas configurer le WiFi de la lampe.
- **Home Assistant et la lampe sur le même réseau local.** C'est le cas chez la plupart des
  particuliers : tout est branché sur la même box. La découverte automatique ne traverse pas les
  réseaux séparés (réseau invité, VLAN).
- **Un moyen d'installer l'intégration.** Ce sera soit **HACS**, soit un accès aux fichiers de
  Home Assistant : module complémentaire **Samba share**, **File editor**, **Studio Code Server**,
  ou **SSH**.

> **Home Assistant dans Docker ?** La découverte automatique (DHCP et recherche sur le réseau) a
> besoin du réseau « host » (`network_mode: host`). Sans lui, ajoutez la lampe par son adresse IP
> (section 3) : le pilotage fonctionne quand même.

### Si vous utilisiez l'ancienne intégration « Cololight »

Il existe une intégration communautaire plus ancienne, appelée **Cololight** (nom technique
`cololight`, basée sur pycololight). Elle envoie chaque commande une seule fois, sans vérifier que
la lampe l'a reçue. Elle affiche ensuite l'état *espéré*, et non l'état réel. C'est elle qui obligeait
parfois à appuyer deux fois.

Les deux intégrations peuvent techniquement cohabiter, mais vous auriez alors **deux lumières pour une
seule lampe**, dont une qui affiche un état faux. **Retirez l'ancienne avant d'installer la nouvelle**,
en trois étapes :

1. **Paramètres → Appareils et services**, ouvrez **Cololight**, puis **⋮ → Supprimer** sur chaque
   lampe.
2. Si vous l'aviez installée par HACS : **HACS**, cherchez **Cololight**, puis **⋮ → Supprimer**.
3. Si vous l'aviez configurée dans `configuration.yaml` (lignes `light:` puis `- platform: cololight`),
   supprimez ces lignes.

Redémarrez ensuite Home Assistant.

**Pourquoi les entités changent de nom.** La nouvelle intégration a un autre nom technique
(`cololight_local`) et reconnaît la lampe par son **adresse MAC**, alors que l'ancienne utilisait
l'adresse IP. Home Assistant voit donc une lampe *nouvelle*, avec de nouvelles entités. Vos
automatisations, scripts, scènes et tableaux de bord qui citaient l'ancienne lumière doivent être
mis à jour. Vous pouvez aussi utiliser l'astuce suivante.

> **Astuce : garder l'ancien nom d'entité.** Une fois l'ancienne intégration supprimée, ouvrez la
> nouvelle lumière (**Paramètres → Entités → votre lumière Cololight → ⚙ Paramètres**) et remplacez
> son **ID d'entité** par l'ancien, par exemple `light.cololight`. Vos automatisations
> fonctionneront à nouveau sans modification.
>
> Les **noms d'effets** sont les mêmes que dans l'ancienne intégration : un `effect: Sunrise` reste
> valable. En revanche, les effets personnalisés que vous aviez créés dans l'ancienne intégration
> doivent être recréés (section 5).

---

## 2. Installation

Choisissez **une** des deux méthodes. HACS est plus confortable pour les mises à jour. L'installation
manuelle ne demande pas de compte GitHub.

### A. Via HACS, en dépôt personnalisé

L'intégration est publiée sur GitHub : <https://github.com/Geminium/ha-cololight-local>.

1. Dans Home Assistant, ouvrez **HACS** dans le menu latéral.
2. Cliquez sur **⋮** (en haut à droite), puis **Dépôts personnalisés**.
3. Dans **Dépôt**, collez `https://github.com/Geminium/ha-cololight-local`. Dans **Type**, choisissez
   **Intégration**, puis cliquez sur **Ajouter**.
4. Fermez la fenêtre, cherchez **Cololight (local)** dans HACS, ouvrez-la et cliquez sur
   **Télécharger** (en bas à droite), puis confirmez.
5. **Redémarrez Home Assistant** (voir plus bas).

Pour les mises à jour, HACS vous préviendra quand une nouvelle version sera publiée sur le dépôt.

### B. Installation manuelle

Il s'agit de copier un dossier au bon endroit. Le dossier à copier est
`custom_components/cololight_local` (avec tout son contenu). Il doit arriver dans
`/config/custom_components/` sur Home Assistant.

À la fin, ce fichier doit exister : `/config/custom_components/cololight_local/manifest.json`.
Si le dossier `custom_components` n'existe pas encore dans `/config`, créez-le.

Trois façons de faire :

- **Avec Samba share** (depuis un PC Windows) :
  1. Installez le module **Samba share** (**Paramètres → Modules complémentaires → Boutique**),
     définissez un mot de passe dans sa configuration, puis démarrez-le.
  2. Dans l'Explorateur Windows, tapez `\\homeassistant.local\config` (ou `\\ADRESSE_IP\config`)
     dans la barre d'adresse.
  3. Copiez le dossier `cololight_local` dans `custom_components`.
- **Avec File editor ou Studio Code Server** : ces modules permettent de créer des dossiers et des
  fichiers depuis le navigateur. Studio Code Server accepte le glisser-déposer d'un dossier entier
  dans l'arborescence de gauche. C'est le plus pratique des deux.
- **Avec SSH** (module **Terminal & SSH**). Depuis votre PC, dans le dossier du projet :

  ```bash
  scp -r custom_components/cololight_local root@homeassistant.local:/config/custom_components/
  ```

Pour mettre à jour plus tard : remplacez le dossier par la nouvelle version, puis redémarrez.

### Redémarrer Home Assistant

Le redémarrage est obligatoire après l'installation ou une mise à jour. Allez dans **Paramètres**,
puis **⋮** (en haut à droite) **→ Redémarrer Home Assistant → Redémarrer Home Assistant**.

---

## 3. Ajouter la lampe

### Découverte automatique (le plus simple)

La **première** lampe est trouvée de l'une de ces deux façons :

- **par Home Assistant lui-même**, qui repère sur le réseau les appareils dont l'adresse MAC commence
  par `4C:11:AE` (découverte « DHCP »). Si Home Assistant tourne dans Docker, il faut le réseau
  « host » ;
- **par la recherche lancée quand vous ajoutez l'intégration** (voir « Lancer la recherche
  vous-même » ci-dessous).

Une fois qu'au moins une lampe est configurée, l'intégration cherche aussi les lampes sur le réseau
au démarrage de Home Assistant, puis toutes les 15 minutes. Elle trouve ainsi vos autres lampes, et
retrouve une lampe qui a changé d'adresse IP.

Quand une lampe est découverte :

1. Une notification du type **« Nouvel appareil découvert »** apparaît. Dans **Paramètres →
   Appareils et services**, une carte **Cololight (local)** est marquée **Découvert**.
2. Cliquez sur **Ajouter** (ou **Configurer**, selon la version).
3. La fenêtre **Cololight découverte** affiche l'adresse IP et l'adresse MAC de la lampe. Choisissez
   le **modèle** (voir plus bas), puis validez.

**Lancer la recherche vous-même** : **Paramètres → Appareils et services → Ajouter une
intégration**, tapez **Cololight (local)**. La fenêtre **Ajouter une Cololight** liste les lampes qui
ont répondu en 2 secondes et qui ne sont pas encore configurées, avec leur adresse IP suivie de leur
adresse MAC entre parenthèses. Choisissez la vôtre, puis le modèle. Si aucune nouvelle lampe ne
répond, la fenêtre **Saisir l'adresse IP** s'ouvre directement.

### Ajout manuel, par l'adresse IP

Si la lampe n'apparaît pas (réseau Docker, réseau séparé…) :

1. Trouvez l'adresse IP de la lampe dans l'interface de votre box, dans la liste des appareils
   connectés. Son adresse MAC commence par `4C:11:AE`.
2. **Paramètres → Appareils et services → Ajouter une intégration → Cololight (local)**.
3. Choisissez **Saisir une adresse IP à la main**, tapez l'adresse dans **Adresse IP**, puis validez.
   L'intégration vérifie qu'une Cololight répond à cette adresse.
4. Choisissez le modèle.

Si vous obtenez **« Aucune Cololight n'a répondu à cette adresse. Vérifiez l'adresse, et que la lampe
est sous tension et connectée à votre Wi-Fi. »**, vérifiez l'adresse, que la lampe est alimentée,
et qu'elle répond dans l'application officielle.

### Choisir le modèle

| Modèle | Pour quelle lampe | Effets proposés |
|---|---|---|
| **Bandeau (Strip)** | Cololight Strip | 52 effets |
| **Hexagone (Hexagon)** | Cololight Hexagon / Pro | 12 effets |

La lampe n'indique pas son modèle sur le réseau local : c'est donc à vous de le choisir. Un mauvais
choix ne casse rien, mais la liste d'effets ne correspondra pas à votre lampe. Vous pourrez le
corriger plus tard (voir « Reconfigurer » ci-dessous).

### Conseil : réserver l'adresse IP dans la box

L'intégration reconnaît la lampe par son **adresse MAC**, qui ne change jamais. Si la box lui donne une
nouvelle adresse IP, la lampe est retrouvée automatiquement : par la recherche sur le réseau toutes
les 15 minutes, par la découverte DHCP de Home Assistant, ou par la recherche de secours lancée quand
elle ne répond plus.

L'intégration vérifie aussi l'adresse MAC dans **chaque** réponse. Si un autre appareil répond à
l'adresse enregistrée (par exemple deux lampes qui ont échangé leurs adresses), elle considère que la
lampe n'a pas répondu, et la recherche par son adresse MAC. Elle ne pilote donc jamais une autre lampe
par erreur.

Il reste préférable de **réserver son adresse IP** dans la box. Cette option s'appelle « bail DHCP
statique », « IP fixe » ou « réservation DHCP » selon les box, et se trouve dans la liste des appareils
connectés. La lampe garde alors toujours la même adresse, et aucune recherche n'est nécessaire.

### Changer l'adresse IP ou le modèle plus tard

Allez dans **Paramètres → Appareils et services → Cololight (local)**. Sur la ligne de la lampe,
cliquez sur **⋮ → Reconfigurer**. Vous pouvez y modifier l'adresse IP et le modèle. Si l'adresse saisie
correspond à une **autre** lampe, l'intégration refuse le changement pour éviter les mélanges
(« Une autre lampe a répondu à cette adresse… »).

---

## 4. Ce que vous obtenez

Chaque lampe devient un **appareil** nommé `Cololight XXXX`, par exemple `Cololight B614`, où `XXXX`
correspond à la fin de son adresse MAC. Pour le renommer (par exemple en « Bandeau salon »), ouvrez
l'appareil et cliquez sur le crayon. Home Assistant propose alors de renommer aussi les entités : leur
identifiant devient par exemple `light.bandeau_salon`.

L'appareil contient trois entités :

| Entité | Identifiant (exemple, Home Assistant en français) | Rôle |
|---|---|---|
| **Lumière** | `light.cololight_b614` | Allumer, éteindre, luminosité, couleur, effets |
| **Vitesse de l'effet** | `number.cololight_b614_vitesse_de_l_effet` | Curseur de 0 (le plus lent) à 32 (le plus rapide) |
| **Mémoriser comme état au démarrage** | `button.cololight_b614_memoriser_comme_etat_au_demarrage` | Enregistre l'état actuel dans la lampe, pour qu'elle le reprenne après une coupure de courant |

Avec Home Assistant en anglais, le curseur et le bouton s'appellent
`number.cololight_b614_effect_speed` et `button.cololight_b614_save_as_power_on_state` (voir
l'encadré au début du guide).

### La lumière

- **Allumer, éteindre.** Chaque commande est confirmée par la lampe. Si elle ne répond pas, la
  commande est retentée automatiquement (jusqu'à 4 tentatives, 8 secondes au maximum). Si elle échoue
  quand même, **un message d'erreur s'affiche** : vous savez que rien ne s'est passé.
- **Luminosité** de 1 à 100 %. La lampe ne reçoit jamais plus de 100 %, car une valeur trop forte
  peut faire planter son WiFi.
- **Couleur** : n'importe quelle couleur RVB. Les blancs « chaud » ou « froid » sont convertis en
  couleur RVB par Home Assistant.
- **Effets** : choisissez-en un dans la liste « Effet » de la fenêtre de la lumière (cliquez sur la
  lumière). Choisir une couleur arrête l'effet. Choisir l'effet **Désactivé** (`off` en YAML) revient à
  la dernière couleur fixe.
- Si vous choisissez une couleur ou un effet alors que la lampe est éteinte, elle s'allume avec la
  dernière luminosité utilisée.
- Changer la luminosité pendant un effet n'envoie que la luminosité : l'intégration ne renvoie pas
  l'effet.
- **Home Assistant retient la dernière luminosité, la dernière couleur et le dernier effet**, même
  après un redémarrage de Home Assistant ou un rechargement de l'intégration. La lampe ne les indique
  pas toujours elle-même : pas de luminosité quand elle est éteinte, pas de couleur pendant un effet,
  et seulement le dernier morceau d'un effet palette. Après un redémarrage, rallumer la lampe reprend
  donc la luminosité d'avant.
- Pendant un effet, la fenêtre « Attributs » de la lumière montre `effect_code`, le code de l'effet
  renvoyé par la lampe, et `effect_speed`, sa vitesse quand elle est réglable.
- Les **transitions** (allumage progressif) et le **clignotement** ne sont pas gérés par la lampe.
  Pour un allumage progressif, voir l'exemple 1 de la section 6.

**Ce que Home Assistant affiche est l'état réel de la lampe.** Après une commande, l'état vient de la
confirmation de la lampe. Ensuite, la lampe est interrogée toutes les 10 secondes (réglable). Si
quelqu'un change la couleur depuis l'application officielle, ou si le courant a été coupé, Home
Assistant le voit en quelques secondes.

### Le curseur « Vitesse de l'effet »

- 0 = le plus lent, 32 = le plus rapide.
- Il n'est utilisable que si l'effet en cours a une vitesse réglable. Il est **grisé
  (indisponible)** quand la lampe affiche une couleur fixe, ou un effet « palette » (marqué **(P)**
  dans la liste plus bas). C'est normal.
- Certains effets personnalisés (mode 2) n'ont que 3 vitesses : le curseur se cale sur la plus proche.

### Le bouton « Mémoriser comme état au démarrage »

Les commandes normales ne sont pas enregistrées dans la lampe. Après une coupure de courant, la lampe
revient avec son **état mémorisé** : celui choisi dans l'application officielle, ou le dernier
enregistré par ce bouton.

Chaque appui sur le bouton enregistre l'état actuel (couleur ou effet, et luminosité) dans la mémoire
de la lampe, même s'il avait déjà été mémorisé. Pour un effet palette (P), l'intégration renvoie tous
ses morceaux en les mémorisant. Ce bouton se trouve dans la partie **Configuration** de la page de
l'appareil.

- Si la lampe est **éteinte** au moment de l'appui, seule la couleur ou l'effet est mémorisé, jamais
  l'extinction. Une lampe mémorisée « éteinte » resterait probablement noire quand on la rallume à
  l'interrupteur (cela n'a pas été testé, et c'est pour cela que l'intégration ne l'enregistre jamais).
  Ce que fait la lampe quand on lui écrit une couleur pendant qu'elle est éteinte (se rallume-t-elle ?)
  n'a pas été testé non plus : mémorisez de préférence lampe allumée.
- Si la lampe affiche **« Unknown palette effect »** (un effet palette que l'intégration ne sait pas
  identifier, voir section 8), rien n'est mémorisé et ce message s'affiche : « L'effet palette en cours
  n'est pas identifié : il ne peut pas être mémorisé comme état au démarrage. Relancez-le par son nom
  depuis Home Assistant, puis mémorisez. » La lampe ne renvoie que le dernier morceau de ces effets, et
  ce seul morceau ne suffit pas à les reproduire.
- Mémoriser remplace l'état de démarrage que vous aviez choisi dans l'application officielle.
- La mémorisation d'une couleur et de la luminosité a été vérifiée sur une vraie lampe. Celle d'un
  **effet** ne l'a pas encore été.

### Que signifie « indisponible » ?

Quand les entités affichent **Indisponible**, la lampe n'a pas répondu à **3 interrogations de suite**,
soit environ 30 secondes avec le réglage par défaut. Une seule réponse perdue ne suffit pas : on évite
ainsi les fausses alertes.

Causes habituelles :

- la lampe est débranchée, ou coupée à l'interrupteur ;
- elle redémarre après une coupure (20 à 30 secondes) ;
- le WiFi est coupé ;
- elle a changé d'adresse IP et n'a pas encore été retrouvée (un autre appareil répond peut-être à son
  ancienne adresse).

Dès que la lampe répond de nouveau, tout revient **automatiquement**, sans rien faire. Pendant
l'indisponibilité, les commandes ne peuvent évidemment pas aboutir.

### La liste des effets

Les noms s'écrivent **exactement** comme ci-dessous, majuscules comprises, quand vous les utilisez
dans une automatisation.

**Effets de base (bandeau et hexagone, 12)** : `80s Club`, `Cherry Blossom`, `Cocktail Parade`,
`Instagrammer`, `Pensieve`, `Savasana`, `Sunrise`, `The Circus`, `Unicorns`, `Christmas`,
`Rainbow Flow`, `Music Mode`.

**Effets dynamiques (bandeau seulement, 40)** : `Graffiti` (P), `Color train`, `Snow`, `White link`,
`Tron` (P), `Urban beauty` (P), `Cyberpunk` (P), `Tropic affair` (P), `Go by` (P), `Break dance` (P),
`Children park` (P), `Thunder` (P), `Red meteor` (P), `Green meteor` (P), `Blue meteor` (P),
`Forest` (P), `Cherry lake` (P), `World cup` (P), `Sunset` (P), `Tide` (P), `Lilac` (P),
`Witch hut` (P), `Cranberry` (P), `Tricolor` (P), `Color star`, `Lover`, `Treasure`,
`Heavy traffic`, `Weird story`, `Green field`, `Seaman`, `Purple link`, `Blue link`, `Orange star`,
`Green star`, `Red star`, `Dusk`, `Innocence` (P), `Red alert`, `Blue alert`.

**(P)** = effet « palette », envoyé en plusieurs morceaux. Sa vitesse n'est pas réglable, et la lampe
ne renvoie que le dernier morceau (voir section 9).

Vos **effets personnalisés** (section 5) s'ajoutent à la liste sous le nom que vous leur donnez. Un
effet lancé depuis l'application officielle et que l'intégration ne connaît pas s'affiche
`Effect xxxxxxxx`, où `xxxxxxxx` est son code, ou `Unknown palette effect` s'il s'agit d'un effet
palette.

---

## 5. Les options

Pour y accéder : **Paramètres → Appareils et services → Cololight (local) → Configurer**. Un menu
propose trois choix : **Réglages**, **Ajouter un effet personnalisé** et **Supprimer des effets
personnalisés**. Chaque modification recharge l'intégration, ce qui prend une seconde (la dernière
luminosité, la dernière couleur et le dernier effet sont conservés).

### Réglages

| Réglage | Par défaut | Valeurs | À quoi ça sert |
|---|---|---|---|
| **Intervalle d'interrogation** | 10 s | 5 à 300 s | Fréquence à laquelle Home Assistant relit l'état de la lampe. Plus c'est court, plus vite il voit les changements faits ailleurs (application, coupure de courant). Chaque interrogation ne représente que deux petits messages, donc 10 s ne fatigue pas la lampe |
| **Mémoriser automatiquement comme état au démarrage** | désactivé | oui / non | Enregistre automatiquement l'état réglé depuis Home Assistant comme état au démarrage, une fois qu'il n'a plus bougé pendant le délai ci-dessous |
| **Délai avant mémorisation** | 30 s | 10 à 600 s | Temps de stabilité exigé avant la mémorisation automatique |
| **Effets masqués** | aucun | effets intégrés | Retire des listes les effets qui ne vous intéressent pas. Un effet masqué reste utilisable par son nom en YAML, et reste reconnu s'il est lancé depuis l'application |

### La mémorisation automatique et les coupures de courant

**Pourquoi elle est désactivée par défaut.** Mémoriser, c'est écrire dans la mémoire flash
(« EEPROM ») de la lampe. Cette mémoire supporte un nombre **limité** d'écritures. Une écriture de
temps en temps ne pose aucun problème. Des milliers d'écritures par jour finiraient par l'user, et la
lampe ne pourrait plus rien retenir. Les commandes normales, elles, n'écrivent rien.

Quand l'option est activée, l'intégration n'écrit **jamais** à chaque mouvement de curseur :

- Chaque commande envoyée depuis Home Assistant et confirmée par la lampe (allumer, luminosité,
  couleur, effet, vitesse, actions de l'intégration) relance un compte à rebours de **Délai avant
  mémorisation** (30 s par défaut). Tant que vous continuez à changer la lampe, rien n'est écrit. Les
  changements faits depuis l'application officielle ne lancent pas de compte à rebours.
- À la fin du délai, l'état est écrit **une seule fois** : couleur ou effet, puis luminosité. Un effet
  palette (P) est renvoyé en entier. Si c'est un effet palette non identifié (« Unknown palette
  effect »), seule la luminosité est mémorisée, et un avertissement est écrit dans le journal.
- **Rien n'est écrit tant que la lampe est éteinte**, et éteindre ne lance pas de compte à rebours.
  Une couleur réglée juste avant d'éteindre est mémorisée après le prochain allumage depuis Home
  Assistant, une fois le délai écoulé.
- **Rien n'est réécrit si l'état n'a pas changé** depuis la dernière mémorisation (automatique ou par
  le bouton). Une routine qui allume et éteint la lampe sans rien changer d'autre n'écrit donc qu'une
  fois. Cette comparaison est gardée en mémoire : après un redémarrage de Home Assistant ou un
  rechargement de l'intégration (par exemple après avoir modifié les options), la première
  mémorisation automatique écrit de nouveau.
- L'extinction n'est jamais mémorisée.

Le bouton et l'action `save_state`, eux, écrivent à chaque fois que vous les utilisez, même si l'état
a déjà été mémorisé (l'application a pu enregistrer un autre état de démarrage entre-temps).

| Après une coupure de courant… | Option désactivée (par défaut) | Option activée |
|---|---|---|
| La lampe se rallume (20 à 30 s après le retour du courant) avec… | le dernier état **mémorisé** : celui de l'application officielle, ou celui du dernier appui sur « Mémoriser comme état au démarrage » | le dernier état réglé depuis Home Assistant, resté stable 30 s lampe allumée |
| Écritures dans la mémoire de la lampe | uniquement quand vous le demandez | au plus une par série de changements, aucune si l'état est déjà mémorisé ou si la lampe est éteinte |

**Notre conseil :**

- Si vous changez la lampe à la main quelques fois par jour, et que vous voulez la retrouver telle
  quelle après une coupure, vous pouvez **activer** l'option.
- Si des automatisations changent la lampe souvent (par exemple toutes les minutes), **laissez-la
  désactivée**. Chaque changement suivi de 30 s de calme provoquerait une écriture. Choisissez plutôt
  un état de démarrage une fois pour toutes avec le bouton, ou avec l'exemple 8 de la section 6.

### Effets personnalisés

Comme dans l'application officielle, vous pouvez composer vos propres effets à partir d'un **schéma
de couleurs**, d'une **couleur**, d'une **vitesse** et d'un **mode** d'animation.

**Ajouter un effet** (menu **Ajouter un effet personnalisé**) :

1. **Nom** : celui qui apparaîtra dans la liste des effets, par exemple « Arc-en-ciel doux ». Si vous
   reprenez le nom d'un effet de base, votre effet le remplace. Le nom ne peut pas être « off » ni
   « Unknown palette effect », ni commencer par « Effect ».
2. **Schéma de couleurs** : le schéma et sa couleur, choisis ensemble dans une liste, par exemple
   `Breath | Rainbow`.
3. **Vitesse** : de 0 (le plus lent) à 32 (le plus rapide).
4. **Mode** : le type d'animation, de 1 à 13 pour le bandeau (1 à 27 pour l'hexagone). Chaque mode est
   illustré par une image dans le fichier
   [MODES.md de pycololight](https://github.com/BazaJayGee66/pycololight/blob/main/MODES.md).

L'effet apparaît ensuite dans la liste « Effet » de la lumière. Vous pouvez l'utiliser par son nom
dans les automatisations, et régler sa vitesse avec le curseur.

**Supprimer des effets** (menu **Supprimer des effets personnalisés**) : cochez ceux à retirer, puis
validez. Ce menu indique qu'il n'y a rien à supprimer si vous n'avez créé aucun effet.

**Schémas et couleurs disponibles.** Les noms restent en anglais, car ce sont ceux de la lampe :

| Schéma | Couleurs |
|---|---|
| **Breath** (respiration) | `Red, Green, Blue` · `Rainbow` · `Green` · `Azure` · `Blue` · `Purple` · `Red` · `Orange` · `Yellow` · `White` · `Green, Blue` |
| **Shadow** (ombre) | `Red, Yellow` · `Red, Green` · `Red, Purple` · `Red, Blue` · `Green, Yellow` · `Green, Azure` · `Green, Blue` · `Blue, Azure` · `Blue, Purple` · `Yellow, White` · `Red, White` · `Green, White` · `Azure, White` · `Blue, White` · `Purple, White` |
| **Flash** | `Red, Green, Blue` · `Rainbow` · `Green` · `Azure` · `Blue` · `Purple` · `Red` · `Orange` · `Yellow` · `White` |
| **Flicker** (scintillement) | mêmes couleurs que Flash |
| **Scene** | `Birthday` · `Girlfriends` · `Friends` · `Workmates` · `Family` · `Lover` |
| **Mood** (humeur) | `Red` · `Orange` · `Yellow` · `Green` · `Grass` · `Azure` · `Blue` · `Pink` · `Gold` · `Color` · `True Color` |
| **Selected** | `Savasana` · `Sunrise` · `Unicorns` |

Une couleur comme `Red, Green, Blue` est **une seule** valeur. En YAML, mettez-la entre guillemets :
`color: "Red, Green, Blue"`.

Dans l'action `set_custom_effect` (exemple 6), le champ **Couleur** se tape au clavier : écrivez-la
en anglais, **exactement** comme dans ce tableau, majuscules comprises. Une faute (`red` au lieu de
`Red`) est refusée, et le message d'erreur liste les couleurs valables du schéma choisi.

---

## 6. Utilisation dans les automatisations

### Avant de commencer

**Tester une action sans créer d'automatisation.** Ouvrez **Outils de développement → onglet
Actions**, choisissez par exemple `light.turn_on`, puis passez en mode YAML pour coller les lignes
`action:` / `target:` / `data:` d'un exemple. Cliquez sur **Exécuter l'action**. C'est le meilleur
moyen d'essayer un effet ou un nom de couleur.

**Coller un exemple complet.** Allez dans **Paramètres → Automatisations et scènes → Créer une
automatisation → Créer une nouvelle automatisation**. Cliquez sur **⋮ → Modifier en YAML**,
remplacez tout le contenu par l'exemple, adaptez les noms d'entités, puis **Enregistrer**. Si vous
repassez ensuite par **⋮ → Modifier dans l'éditeur visuel**, vous verrez l'automatisation sous forme
de blocs, plus facile à retoucher.

Dans tous les exemples, remplacez `light.cololight_b614` (et les autres entités) par les vôtres. Pour
le curseur de vitesse et le bouton, les exemples utilisent les identifiants d'un Home Assistant en
français ; en anglais, ce sont `number.cololight_b614_effect_speed` et
`button.cololight_b614_save_as_power_on_state` (voir l'encadré au début du guide).

### Exemple 1 : réveil progressif avec l'effet Sunrise

En semaine à 6 h 45, la lampe s'allume sur l'effet Sunrise à 1 %, puis la luminosité monte jusqu'à
100 % en 15 minutes. Si vous éteignez la lampe pendant ce temps, la montée s'arrête.

```yaml
alias: Cololight – réveil progressif
description: Effet Sunrise à 6 h 45 en semaine, de 1 % à 100 % en 15 minutes.
mode: single
triggers:
  - trigger: time
    at: "06:45:00"
conditions:
  # Seulement du lundi au vendredi
  - condition: time
    weekday: [mon, tue, wed, thu, fri]
actions:
  # 1. Allumer très faiblement, directement sur l'effet Sunrise
  - action: light.turn_on
    target:
      entity_id: light.cololight_b614
    data:
      effect: Sunrise
      brightness_pct: 1
  # 2. Monter la luminosité chaque minute, tant que la lampe est allumée
  - repeat:
      while:
        - condition: state
          entity_id: light.cololight_b614
          state: "on"
        - condition: template
          value_template: "{{ repeat.index <= 15 }}"
      sequence:
        - delay:
            minutes: 1
        # On revérifie : si quelqu'un a éteint pendant la minute, on ne rallume pas
        - if:
            - condition: state
              entity_id: light.cololight_b614
              state: "on"
          then:
            - action: light.turn_on
              target:
                entity_id: light.cololight_b614
              data:
                # 7 %, 13 %, 20 %… jusqu'à 100 % à la 15e minute
                brightness_pct: "{{ (repeat.index * 100 / 15) | round(0) | int }}"
```

Pendant la montée, l'intégration n'envoie que la nouvelle luminosité : elle ne renvoie pas l'effet
Sunrise.

### Exemple 2 : allumer en couleur sur un événement

Quand la porte d'entrée s'ouvre pendant la nuit, la lampe s'allume en orange à 60 % pendant
5 minutes. Remplacez `binary_sensor.porte_entree` par votre capteur d'ouverture.

```yaml
alias: Cololight – porte d'entrée la nuit
description: Orange à 60 % pendant 5 minutes quand la porte s'ouvre la nuit.
mode: restart          # une nouvelle ouverture relance les 5 minutes
triggers:
  - trigger: state
    entity_id: binary_sensor.porte_entree
    to: "on"
conditions:
  # La nuit = le soleil est sous l'horizon
  - condition: state
    entity_id: sun.sun
    state: below_horizon
actions:
  - action: light.turn_on
    target:
      entity_id: light.cololight_b614
    data:
      rgb_color: [255, 140, 0]   # rouge, vert, bleu (0 à 255)
      brightness_pct: 60
  - delay:
      minutes: 5
  - action: light.turn_off
    target:
      entity_id: light.cololight_b614
```

**Variante : une couleur qui dépend d'une valeur.** Ici, bleu s'il fait froid dehors, vert s'il fait
doux, rouge s'il fait chaud. Remplacez la partie `data:` par :

```yaml
    data:
      brightness_pct: 50
      rgb_color: >
        {% set t = states('sensor.temperature_exterieure') | float(0) %}
        {% if t < 5 %}[0, 120, 255]{% elif t < 20 %}[0, 255, 80]{% else %}[255, 60, 0]{% endif %}
```

Vous pouvez aussi écrire une couleur par son nom anglais : `color_name: red`.

### Exemple 3 : alerte quand on sonne, puis retour à l'état précédent

La lampe passe sur l'effet `Red alert` pendant 20 secondes, puis retrouve l'état d'avant (couleur ou
effet, luminosité, ou éteinte). On utilise une scène « instantané » créée à la volée.

```yaml
alias: Cololight – alerte sonnette
mode: single           # on ignore les coups de sonnette pendant l'alerte
triggers:
  - trigger: state
    entity_id: binary_sensor.sonnette
    to: "on"
actions:
  # 1. Photographier l'état actuel de la lampe
  - action: scene.create
    data:
      scene_id: cololight_avant_alerte
      snapshot_entities:
        - light.cololight_b614
  # 2. Alerte rouge à pleine luminosité
  - action: light.turn_on
    target:
      entity_id: light.cololight_b614
    data:
      effect: Red alert
      brightness_pct: 100
  - delay:
      seconds: 20
  # 3. Revenir à l'état photographié
  - action: scene.turn_on
    target:
      entity_id: scene.cololight_avant_alerte
```

Une couleur fixe revient exactement, et un effet revient par son nom. Deux précisions :

- **La vitesse de l'effet** ne fait pas partie de la photo de la lumière : l'effet revient à sa
  vitesse par défaut. Pour la retrouver aussi, ajoutez `number.cololight_b614_vitesse_de_l_effet`
  **après** la lumière dans `snapshot_entities`. Si la lampe affichait une couleur fixe, le curseur
  était indisponible : Home Assistant l'ignore alors au retour, avec un simple avertissement dans le
  journal.
- **Effet palette non identifié.** Si, au moment de la photo, la lampe affichait « Unknown palette
  effect » (voir section 8), cet effet ne peut pas être relancé, car ses morceaux sont inconnus. Au
  retour, la luminosité et l'état allumé/éteint sont bien rétablis, mais la lampe **reste sur Red
  alert**, et un avertissement est écrit dans le journal (l'automatisation, elle, ne s'arrête pas).
  Pour éviter cela, lancez vos effets palette depuis Home Assistant, par leur nom.

### Exemple 4 : lancer un effet par son nom

**4a. Au coucher du soleil**, effet `Sunset` à 50 % :

```yaml
alias: Cololight – coucher de soleil
triggers:
  - trigger: sun
    event: sunset
actions:
  - action: light.turn_on
    target:
      entity_id: light.cololight_b614
    data:
      effect: Sunset          # nom exact, majuscules comprises
      brightness_pct: 50
```

**4b. Depuis une liste déroulante** sur le tableau de bord. Créez d'abord une entrée « Liste
déroulante » (**Paramètres → Appareils et services → onglet Entrées → Créer une entrée → Liste
déroulante**), nommée « Effet Cololight », avec les effets de votre choix comme options : `Sunrise`,
`Savasana`, `Rainbow Flow`, `Christmas`, `Tron`… Puis créez cette automatisation :

```yaml
alias: Cololight – effet choisi dans la liste
mode: restart
triggers:
  - trigger: state
    entity_id: input_select.effet_cololight
actions:
  - action: light.turn_on
    target:
      entity_id: light.cololight_b614
    data:
      # L'option choisie dans la liste est envoyée telle quelle comme nom d'effet
      effect: "{{ trigger.to_state.state }}"
```

### Exemple 5 : régler la vitesse de l'effet

À 22 h, si la lampe est allumée, on passe sur l'effet `Savasana` et on le ralentit nettement.

```yaml
alias: Cololight – effet lent le soir
triggers:
  - trigger: time
    at: "22:00:00"
conditions:
  - condition: state
    entity_id: light.cololight_b614
    state: "on"
actions:
  # 1. D'abord l'effet : le curseur de vitesse n'est disponible que pendant un effet réglable
  - action: light.turn_on
    target:
      entity_id: light.cololight_b614
    data:
      effect: Savasana
  # 2. Ensuite la vitesse : 0 = le plus lent, 32 = le plus rapide
  - action: number.set_value
    target:
      # en anglais : number.cololight_b614_effect_speed
      entity_id: number.cololight_b614_vitesse_de_l_effet
    data:
      value: 4
```

L'ordre compte. Si la lampe affiche une couleur fixe ou un effet palette (P), le curseur est
indisponible et la demande de vitesse est ignorée.

### Exemple 6 : effet personnalisé avec `cololight_local.set_custom_effect`

Quand on active le « mode fête » (une entrée « Interrupteur » `input_boolean.mode_fete`), la lampe
lance un effet personnalisé rapide, sans qu'il soit nécessaire de l'avoir créé dans les options.

```yaml
alias: Cololight – mode fête
triggers:
  - trigger: state
    entity_id: input_boolean.mode_fete
    to: "on"
actions:
  - action: cololight_local.set_custom_effect
    target:
      entity_id: light.cololight_b614
    data:
      scheme: Flash            # Breath, Shadow, Flash, Flicker, Scene, Mood ou Selected
      color: Rainbow           # en anglais, majuscules comprises (tableau de la section 5)
      speed: 28                # 0 à 32, 16 par défaut
      mode: 5                  # 1 à 13 pour le bandeau, 1 par défaut
  # Par précaution, on s'assure que la lampe est allumée, à pleine luminosité
  - action: light.turn_on
    target:
      entity_id: light.cololight_b614
    data:
      brightness_pct: 100
```

Les actions `set_custom_effect` et `set_effect_code` changent l'effet, mais ne sont pas prévues pour
allumer la lampe. Si elle peut être éteinte à ce moment-là, ajoutez un `light.turn_on` comme
ci-dessus.

### Exemple 7 : envoyer un code brut avec `cololight_local.set_effect_code`

Cette action sert surtout à **rejouer un effet créé dans l'application officielle**. La méthode :

1. Lancez l'effet dans l'application officielle, puis attendez 10 secondes.
2. Dans Home Assistant, ouvrez **Outils de développement → onglet États**, cherchez
   `light.cololight_b614` et relevez l'attribut `effect_code`, par exemple `05810cc0`.
3. Utilisez ce code dans une automatisation ou un script. Voici un script (onglet **Scripts**) :

```yaml
alias: Cololight – mon effet de l'application
sequence:
  - action: cololight_local.set_effect_code
    target:
      entity_id: light.cololight_b614
    data:
      code: "05810cc0"         # 8 caractères hexadécimaux, entre guillemets
  - action: light.turn_on
    target:
      entity_id: light.cololight_b614
```

> **Si `effect_code` commence par `93`**, c'est un effet palette (P) : la lampe n'a renvoyé que son
> **dernier** morceau, qui ne suffit pas à le rejouer. Utilisez plutôt son nom, s'il s'affiche dans
> l'attribut `effect` (par exemple `effect: Tide` avec `light.turn_on`). S'il s'affiche « Unknown
> palette effect », c'est soit l'un des effets des 4 paires de la section 9 (lancez-le par son nom
> depuis Home Assistant), soit un effet de l'application absent des tables, qui ne peut être lancé
> que depuis l'application.

Un effet palette s'écrit en plusieurs codes de 8 caractères, séparés par des espaces ou des
virgules, si vous les connaissez tous (ils ne se lisent pas dans `effect_code`). Ils sont envoyés dans
l'ordre, et chacun est confirmé par la lampe :

```yaml
    data:
      code: "93fefefe 9302027d 93f04800 930046ff"   # c'est « Blue meteor »
```

Le premier octet ne peut pas être `00` : ce serait une couleur fixe, pas un effet. Utilisez alors
`rgb_color`.

> **Pour garder un effet trouvé ainsi sous un nom**, il est plus simple de le recréer dans les options
> (section 5) avec le même schéma, la même couleur, la même vitesse et le même mode que dans
> l'application.

### Exemple 8 : mémoriser l'état de démarrage

Vous voulez qu'après une coupure de courant, la lampe se rallume en blanc chaud doux, quoi qu'il se
soit passé avant. Ce **script** règle cet état et le mémorise. Il suffit de l'exécuter **une fois**.
Créez-le dans **Paramètres → Automatisations et scènes → onglet Scripts → Ajouter un script →
⋮ → Modifier en YAML** :

```yaml
alias: Cololight – définir l'état au démarrage
sequence:
  # 1. Régler l'état voulu
  - action: light.turn_on
    target:
      entity_id: light.cololight_b614
    data:
      rgb_color: [255, 170, 90]
      brightness_pct: 30
  # 2. L'enregistrer dans la mémoire de la lampe (une seule écriture)
  - action: cololight_local.save_state
    target:
      entity_id: light.cololight_b614
```

Appuyer sur le bouton fait exactement la même chose que l'étape 2 :

```yaml
  - action: button.press
    target:
      # en anglais : button.cololight_b614_save_as_power_on_state
      entity_id: button.cololight_b614_memoriser_comme_etat_au_demarrage
```

Évitez de mettre cette action dans une automatisation qui tourne souvent : chaque appel écrit dans la
mémoire de la lampe (section 5). Une fois par jour, c'est sans problème.

### Exemple 9 : scènes

Une scène enregistre un état complet, que vous rappelez d'un clic ou depuis une automatisation.

**Avec l'éditeur.** Réglez la lampe comme vous la voulez. Allez dans **Paramètres → Automatisations
et scènes → onglet Scènes → Ajouter une scène**, ajoutez la lumière Cololight, puis enregistrez. En
activant la scène, la lampe reprend la couleur fixe (ou l'effet) et la luminosité enregistrées.

**La vitesse d'un effet dans une scène.** Elle est portée par le curseur « Vitesse de l'effet »
(l'éditeur l'ajoute si vous ajoutez l'appareil entier). Home Assistant applique la lumière et le
curseur en même temps, et l'intégration exécute leurs commandes l'une après l'autre, dans l'ordre de
la scène. La vitesse n'est donc rétablie de façon fiable que si :

- la **lumière est placée avant le curseur** dans la scène (vérifiez-le avec **⋮ → Modifier en
  YAML**) ;
- et le curseur est disponible au moment où vous activez la scène, c'est-à-dire si la lampe affiche
  déjà un effet à vitesse réglable.

Sinon, la vitesse est ignorée (ou s'applique à l'effet précédent), et l'effet de la scène démarre à
sa vitesse par défaut. Pour une vitesse garantie, utilisez plutôt un script comme l'exemple 5 : d'abord
l'effet, ensuite la vitesse.

**En YAML**, dans le fichier `scenes.yaml` :

```yaml
- name: Cololight cinéma
  entities:
    light.cololight_b614:
      state: "on"
      brightness: 50          # attention : de 0 à 255 dans les scènes (50 ≈ 20 %)
      effect: Savasana
    # La vitesse, après la lumière (en anglais : number.cololight_b614_effect_speed)
    number.cololight_b614_vitesse_de_l_effet:
      state: "4"              # entre guillemets
- name: Cololight lecture
  entities:
    light.cololight_b614:
      state: "on"
      brightness: 200         # ≈ 78 %
      rgb_color: [255, 190, 120]
```

Rechargez les scènes (**Outils de développement → onglet YAML → Scènes**), puis activez-les ainsi :

```yaml
action: scene.turn_on
target:
  entity_id: scene.cololight_cinema
```

### Exemple 10 : être prévenu si la lampe ne répond plus

```yaml
alias: Cololight – alerte lampe injoignable
triggers:
  - trigger: state
    entity_id: light.cololight_b614
    to: unavailable
    for:
      minutes: 5
actions:
  - action: persistent_notification.create
    data:
      title: Cololight injoignable
      message: >
        La Cololight ne répond plus depuis 5 minutes. Vérifiez qu'elle est
        alimentée. Sinon, débranchez-la 10 secondes puis rebranchez-la.
```

### L'équivalent dans l'éditeur visuel

Tout ce qui précède peut se faire sans écrire de YAML. Par exemple, pour le réveil (exemple 1) :

1. **Paramètres → Automatisations et scènes → Créer une automatisation → Créer une nouvelle
   automatisation.**
2. **Déclencheur** : **Ajouter un déclencheur → Heure et lieu → Heure**, puis tapez 06:45.
3. **Condition** : **Ajouter une condition → Heure et lieu → Heure**, puis cochez les jours de la
   semaine.
4. **Action** : **Ajouter une action**, cherchez **Allumer la lumière**. Dans **Cibles**, choisissez
   votre lampe Cololight. Cochez **Luminosité** (1 %) et **Effet**, puis choisissez `Sunrise`.
5. Pour la boucle : **Ajouter une action → Blocs de construction → Répéter**, type **Tant que**.
   Pour une boucle de ce genre, il est souvent plus simple de coller le YAML puis de revenir à
   l'éditeur visuel.
6. **Enregistrer**, puis donnez un nom.

Pour les autres actions, cherchez dans la liste d'actions :

| Pour… | Cherchez |
|---|---|
| un effet personnalisé, un code brut, la mémorisation | **Cololight (local)**. Les trois actions de l'intégration s'affichent, avec des champs guidés (listes, curseurs) ; la couleur se tape en anglais, exactement comme dans le tableau de la section 5, majuscules comprises |
| la vitesse de l'effet | **Définir une valeur numérique**, cible : « Vitesse de l'effet » de votre lampe |
| le bouton de mémorisation | **Appuyer sur le bouton**, cible : « Mémoriser comme état au démarrage » |
| une scène | **Activer la scène** |

---

## 7. Tableau de bord

Pour ajouter une carte : ouvrez votre tableau de bord, cliquez sur le **crayon** (Modifier), puis
**Ajouter une carte**. Choisissez **Manuel** en bas de la liste, collez le YAML, puis
**Enregistrer**.

Cette carte réunit la lumière, sa luminosité, le curseur de vitesse, le bouton de mémorisation et
l'effet en cours :

```yaml
type: vertical-stack
cards:
  # Tuile : un clic sur l'icône allume/éteint, la barre règle la luminosité,
  # un clic sur la tuile ouvre la fenêtre avec la couleur et la liste d'effets.
  - type: tile
    entity: light.cololight_b614
    name: Bandeau salon
    features:
      - type: light-brightness
  - type: entities
    entities:
      - type: attribute
        entity: light.cololight_b614
        attribute: effect
        name: Effet en cours
      - entity: number.cololight_b614_vitesse_de_l_effet
        name: Vitesse de l'effet
      - entity: button.cololight_b614_memoriser_comme_etat_au_demarrage
        name: Mémoriser comme état au démarrage
```

Avec Home Assistant en anglais, remplacez les deux dernières entités par
`number.cololight_b614_effect_speed` et `button.cololight_b614_save_as_power_on_state`.

Si vous avez créé la liste déroulante de l'exemple 4b, ajoutez cette ligne dans la carte
`entities` pour changer d'effet en un clic :

```yaml
      - entity: input_select.effet_cololight
        name: Choisir un effet
```

La carte **Lumière**, plus visuelle avec sa roue de luminosité, est une autre possibilité :

```yaml
type: light
entity: light.cololight_b614
name: Bandeau salon
```

---

## 8. Dépannage

### La lampe est « indisponible »

1. **Est-elle alimentée ?** Vérifiez la prise et l'interrupteur mural.
2. **Vient-il d'y avoir une coupure ?** La lampe met 20 à 30 secondes à revenir sur le WiFi. Attendez
   une minute.
3. **L'application officielle la voit-elle ?** Si l'application ne la voit pas non plus, le problème
   vient de la lampe ou du WiFi, pas de Home Assistant.
4. **Son adresse IP a-t-elle changé ?** Regardez dans la box. L'intégration la recherche par son
   adresse MAC, mais si elle reste introuvable, corrigez l'adresse avec **⋮ → Reconfigurer**
   (section 3).
5. Si rien n'y fait, suivez la procédure « La lampe ne répond plus du tout » plus bas.

Les entités reviennent toutes seules dès que la lampe répond.

### La lampe a changé d'adresse IP

Normalement, vous n'avez rien à faire. L'intégration recherche la lampe par son adresse MAC à la
deuxième et à la troisième interrogation sans réponse, puis environ une fois par minute tant qu'elle
reste introuvable. La recherche générale toutes les 15 minutes la retrouve aussi, et Home Assistant
la repère quand elle se reconnecte à la box (découverte DHCP). Si la lampe se trouve sur un autre
réseau que Home Assistant, la recherche ne peut pas la voir : utilisez **⋮ → Reconfigurer**. Pour ne
plus être concerné, réservez son adresse IP dans la box (section 3).

### Une commande échoue (message d'erreur)

Si la lampe n'a confirmé aucune des 4 tentatives (environ 8 secondes), Home Assistant affiche ce
message, ici pour une lampe à l'adresse 192.168.0.51 : « La Cololight à l'adresse 192.168.0.51 n'a pas
répondu. Vérifiez qu'elle est sous tension et connectée au Wi-Fi, puis réessayez. » C'est voulu :
l'ancienne intégration échouait en silence. Le même message s'affiche si un autre appareil a répondu
à l'adresse de la lampe. Un avertissement est aussi écrit dans le journal, avec la commande concernée
(**Paramètres → Système → Journaux**, cherchez `cololight_local`).

À vérifier :

- **Le signal WiFi à l'endroit de la lampe.** Elle n'utilise que le 2,4 GHz. Un mur épais ou une box
  éloignée provoquent des pertes.
- **Les compteurs des diagnostics** (voir plus bas). Beaucoup de « retries » (renvois) signalent un
  WiFi faible.

Les autres messages signalent une demande incorrecte (rien n'a été envoyé à la lampe) :

| Message | Que faire |
|---|---|
| « Effet inconnu : sunrise. Écrivez le nom exactement comme dans la liste des effets, majuscules comprises. » | Corrigez le nom (ici `Sunrise`). Les effets dynamiques n'existent qu'avec le modèle Bandeau (Strip) |
| « Effet personnalisé invalide : « red » n'est pas une couleur du schéma Breath. Ses couleurs, à écrire exactement ainsi (en anglais, majuscules comprises) : Red, Green, Blue · Rainbow · Green · Azure · Blue · Purple · Red · Orange · Yellow · White · Green, Blue. » | Recopiez une des couleurs de la liste (ici `Red`) |
| « Effet personnalisé invalide : le mode doit être compris entre 1 et 13 sur ce modèle. » | Choisissez un mode de 1 à 13 (bandeau) |
| « L'effet palette en cours n'est pas identifié : il ne peut pas être mémorisé comme état au démarrage. Relancez-le par son nom depuis Home Assistant, puis mémorisez. » | Voir section 4, le bouton « Mémoriser comme état au démarrage » |
| « Code d'effet invalide : … » | Vérifiez le code de `set_effect_code` : des trames de 8 chiffres hexadécimaux, qui ne commencent pas par 00 |

Dans une automatisation, une action en échec arrête la suite. Pour une action secondaire qui ne doit
pas tout bloquer, ajoutez `continue_on_error: true` :

```yaml
  - action: light.turn_on
    continue_on_error: true
    target:
      entity_id: light.cololight_b614
    data:
      effect: Sunrise
```

### Activer les journaux détaillés (debug)

Ils montrent chaque message échangé avec la lampe. Ils sont utiles pour comprendre un problème, ou
pour le signaler.

- **Méthode simple.** Ouvrez **Paramètres → Appareils et services → Cololight (local)**, puis cliquez
  sur **Activer la journalisation de débogage**. Reproduisez le problème, puis revenez cliquer sur
  **Désactiver la journalisation de débogage** : Home Assistant vous propose alors de télécharger le
  fichier de journal.
- **Méthode permanente**, dans `configuration.yaml`, puis redémarrez :

  ```yaml
  logger:
    default: warning
    logs:
      custom_components.cololight_local: debug
  ```

  Retirez ces lignes quand vous avez terminé : le mode debug écrit beaucoup.

### Télécharger les diagnostics

Ouvrez **Paramètres → Appareils et services → Cololight (local)**, puis **⋮ → Télécharger les
diagnostics** sur la ligne de la lampe. Le fichier contient vos options, le dernier état lu, l'effet
retenu, le nombre d'échecs consécutifs et des statistiques : nombre de requêtes, de renvois et
d'échecs, réponses arrivées en retard, réponses d'un autre appareil, temps de réponse. L'adresse IP et
l'adresse MAC sont masquées. Joignez ce fichier si vous signalez un problème.

### La lampe ne répond plus du tout

Les LED sont figées, la lampe n'apparaît plus dans la box, et l'application ne la voit plus non plus.
Le module WiFi de la lampe s'est bloqué. Cela arrive par exemple si un autre logiciel lui a envoyé une
luminosité trop forte, ce que cette intégration ne fait jamais.

1. **Débranchez la lampe pendant 10 secondes**, puis rebranchez-la.
2. Attendez 20 à 30 secondes : elle revient sur le WiFi, en général avec la même adresse IP, et dans
   son état mémorisé.
3. Home Assistant la retrouve tout seul à l'interrogation suivante.

### L'application officielle n'affiche pas les changements faits par Home Assistant

C'est **normal**. L'application passe par le cloud LifeSmart et n'interroge jamais la lampe
directement. Elle ne sait donc pas ce que Home Assistant a fait. L'inverse fonctionne : ce que vous
faites dans l'application (allumer, éteindre, luminosité, couleur) est vu par Home Assistant à
l'interrogation suivante.

### La lampe n'est pas découverte

- Home Assistant et la lampe doivent être sur le même réseau. Un réseau invité ou un VLAN séparé
  bloquent la découverte.
- Home Assistant dans Docker : il faut `network_mode: host`.
- La recherche toutes les 15 minutes ne fonctionne qu'une fois une première lampe configurée. Pour la
  première, passez par **Ajouter une intégration** (section 3).
- Dans tous les cas, l'**ajout manuel par adresse IP** fonctionne (section 3).

### L'effet affiché est « Unknown palette effect » ou « Effect xxxxxxxx »

La lampe fonctionne normalement : c'est l'intégration qui ne sait pas nommer l'effet en cours.

- **« Unknown palette effect »** : un effet palette (P) que l'intégration ne peut pas identifier, car
  la lampe ne renvoie que son dernier morceau. Cela arrive quand l'un des 8 effets des 4 paires de la
  section 9 (par exemple `Sunset` ou `Tron`) a été lancé depuis l'application ou avec
  `set_effect_code`, ou pour un effet palette de l'application absent des tables. Les 14 autres effets
  palette sont toujours reconnus. Un effet lancé par son nom depuis Home Assistant reste reconnu, même
  après un redémarrage de Home Assistant, tant que la lampe n'a pas changé d'effet entre-temps.
- **« Effect xxxxxxxx »** : un effet en un seul morceau absent des tables (par exemple un effet
  personnalisé de l'application), où `xxxxxxxx` est son code. Vous pouvez le relancer sous ce nom.

Relancez l'effet depuis Home Assistant pour qu'il s'affiche par son nom, ou créez-le dans les options
(section 5). Un effet « Unknown palette effect » ne peut être ni mémorisé (section 4), ni rétabli par
une scène (exemple 3).

### Le curseur « Vitesse de l'effet » est grisé

C'est normal pendant une couleur fixe ou un effet palette (P) : leur vitesse n'est pas réglable.

---

## 9. Limites connues

- **Effets palette (P).** La lampe ne renvoie que le dernier morceau de l'effet. L'intégration se
  souvient de l'effet qu'elle a envoyé, même après un redémarrage de Home Assistant. Mais 4 paires
  d'effets se terminent par le même morceau et ne peuvent pas être distinguées d'après ce que renvoie
  la lampe : **`Tron` et `Tricolor`, `Tropic affair` et `Red meteor`, `Break dance` et `Sunset`,
  `Witch hut` et `Cranberry`**. Lancés depuis l'application (ou avec `set_effect_code`), ces 8 effets
  s'affichent « Unknown palette effect » ; si l'application passe directement de l'un à l'autre de la
  même paire, l'ancien nom reste affiché. Un effet palette non identifié ne peut être ni mémorisé, ni
  rétabli par une scène.
- **Effets voisins.** `80s Club` et `Unicorns` ne diffèrent que par leur vitesse. Changer la vitesse
  de l'un peut le faire afficher sous le nom de l'autre.
- **Pas de notification instantanée.** La lampe ne prévient jamais d'un changement : c'est vérifié.
  L'intégration l'interroge donc régulièrement. Un changement fait ailleurs (application, coupure)
  apparaît dans le délai d'interrogation (10 s par défaut).
- **Luminosité plafonnée à 100 %.** Une valeur de 255 envoyée par erreur a fait perdre le WiFi à la
  lampe jusqu'à ce qu'on la débranche. L'intégration n'envoie jamais plus de 100, ni 0 (elle éteint
  la lampe à la place).
- **L'application officielle passe par le cloud.** Elle n'affiche pas les changements locaux. Les deux
  peuvent être utilisées : la dernière commande l'emporte.
- **Usure de la mémoire.** Voir la section 5. La mémorisation automatique est désactivée par défaut
  pour cette raison.
- **L'extinction n'est jamais mémorisée.** Lampe éteinte au moment de mémoriser, seule la couleur ou
  l'effet est enregistré. Une lampe mémorisée « éteinte » resterait probablement noire au retour du
  courant, mais cela n'a pas été testé ; ce que fait la lampe quand on lui écrit une couleur pendant
  qu'elle est éteinte non plus. Dans nos essais, la lampe s'est toujours rallumée avec son état
  mémorisé après une coupure de courant.
- **Mémoriser un effet** n'a pas encore été vérifié sur une vraie lampe (la couleur et la luminosité,
  oui).
- **Vitesse dans les scènes** : rétablie seulement dans les conditions de l'exemple 9.
- **Pas de transition ni de clignotement** gérés par la lampe.
- **Hexagone non testé.** Il utilise le même protocole selon pycololight, mais n'a pas été testé :
  seul le bandeau l'a été. Le modèle se choisit à la main.

---

## 10. Questions fréquentes

**Faut-il une connexion Internet ?**
Non. Tout passe par votre réseau local. Seule l'application officielle a besoin d'Internet.

**Puis-je garder l'application officielle ?**
Oui. Les deux fonctionnent en même temps. L'application ne verra simplement pas ce que fait Home
Assistant.

**J'ai plusieurs lampes. Comment faire ?**
Chacune est découverte et ajoutée séparément. Chacune devient un appareil `Cololight XXXX` avec ses
propres entités et ses propres options.

**Pourquoi Home Assistant interroge-t-il la lampe toutes les 10 secondes ? Cela l'use-t-il ?**
Non. Une interrogation, ce sont deux petits messages lus par la lampe. Rien n'est écrit dans sa
mémoire. Seule la mémorisation (bouton, action `save_state` ou option automatique) écrit dans sa
mémoire.

**Après une coupure de courant, la lampe se rallume-t-elle ?**
Dans nos essais, oui : elle est revenue à chaque fois en 20 à 30 secondes, avec son état mémorisé
(section 5). L'intégration n'enregistre jamais l'extinction.

**Comment faire un allumage progressif ?**
La lampe ne gère pas les transitions. Augmentez la luminosité par paliers, comme dans l'exemple 1.

**Puis-je utiliser des blancs (chaud/froid) ?**
Oui. Choisissez une température de blanc dans Home Assistant : elle est convertie en couleur RVB. Le
rendu dépend des LED de la lampe.

**Le nom d'un effet ne marche pas dans mon automatisation.**
Vérifiez l'orthographe exacte, majuscules comprises (section 4). Les effets dynamiques n'existent que
pour le modèle Bandeau (Strip). Un effet masqué dans les options n'apparaît plus dans les listes, mais reste
utilisable par son nom en YAML.

**J'ai un Cololight Hexagon. Ça marche ?**
Normalement oui (choisissez le modèle Hexagone (Hexagon)), mais il n'a pas pu être testé. Vos retours sont les
bienvenus.

**Où trouver plus de détails techniques ?**
Le `README.md` (en anglais) résume le fonctionnement, et `docs/findings.md` décrit les mesures faites
sur la lampe.
