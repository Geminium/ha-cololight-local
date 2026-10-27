# Protocole Cololight (LifeSmart) – état des connaissances avant tests

> **Mise à jour après la phase 2 (25/10/2026) :** la référence vérifiée est maintenant
> [`findings.md`](findings.md). Ce document est conservé comme trace de l'étude du code.
> Principales corrections :
> - la lampe **accuse réception de chaque commande** et renvoie la séquence (§6 point 1 confirmé, point 3 écarté) ;
> - l'octet 4 vaut `0x80` dans les réponses ; les octets 16–17 sont une **somme de contrôle**, que la lampe ne vérifie pas ;
> - l'octet 36 est une **opération** (`03` lecture, `04` écriture, `07` écriture + EEPROM, `09` infos) ; l'octet 37 est renvoyé tel quel, sans effet ;
> - la charge utile se compose de blocs **TLV** `[longueur][id][données]` ; **l'élément 02 (couleur ou effet) se lit** avec `03 02 01 02` ;
> - vitesse d'effet : `0x00` = le plus rapide, `0x20` = le plus lent (et non l'inverse) ;
> - luminosité > 100 : **255 fait perdre le WiFi à la lampe** ;
> - découverte par broadcast possible ; aucun push local.
>
> **Statut d'origine : NON VÉRIFIÉ.** Tout ce document est déduit de la lecture du code de
> [pycololight](https://github.com/BazaJayGee66/pycololight) v2.1.0 et de
> [homeassistant_cololight](https://github.com/BazaJayGee66/homeassistant_cololight) v2.0.9,
> complété par l'article de rétro-ingénierie d'origine
> ([Projekt: ColoLight in FHEM](https://haus-automatisierung.com/projekt/2019/04/05/projekt-cololight-fhem.html)).
> Chaque affirmation sera confirmée ou infirmée en phase 2, et les résultats iront dans `docs/findings.md`.
>
> Légende : **[code]** = lu dans le code ; **[FHEM]** = lu dans l'article FHEM ;
> **[hyp]** = mon interprétation, à tester.

---

## 1. Transport

| Élément | Valeur | Source |
|---|---|---|
| Protocole | UDP, sans connexion | [code] |
| Port de la lampe | **8900** | [code] [FHEM] |
| Port source | port éphémère, **nouveau socket à chaque envoi** | [code] |
| Timeout de lecture | 4 s (lecture d'état uniquement) | [code] |
| Taille du tampon de réception | 4096 octets | [code] |
| Découverte réseau | **aucune** dans le code : IP saisie à la main | [code] |
| Accusé de réception | **jamais lu** : socket fermé juste après `sendto` | [code] |

---

## 2. Format général d'une trame

Toutes les trames font 40 à 45 octets. Exemple : extinction (42 octets).

```
off       53 5a 30 30 00 00 00 00 00 20 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 01 00 00 00 00 00 00 00 00 00 04 01 03 01 ce 1e
offset    0           4           8     10                                              26 27                         36 37 38 39 40 41
```

| Offset | Longueur | Valeur | Signification | Source |
|---|---|---|---|---|
| 0–3 | 4 | `53 5a 30 30` | Magic ASCII `"SZ00"` | [code] |
| 4–7 | 4 | `00 00 00 00` | Inconnu (l'auteur FHEM pense à un n° de série, rien de prouvé) | [code] [FHEM] |
| 8–9 | 2 | `00 20` / `00 23` / `00 1e` | **Longueur de ce qui suit l'octet 9** (= taille totale − 10), probablement un uint16 big-endian | [code] ; uint16 = [hyp] |
| 10–25 | 16 | tous à `00` | Inconnu (réservé ? signature/clé ?) | [code] |
| 26 | 1 | `01` ou `02` | **Numéro de séquence.** pycololight alterne 1 et 2 à chaque trame (requêtes d'état comprises). L'appli officielle l'incrémente (`07`, `08`, `0b`, `0d`, `14`…) | [code] [FHEM] |
| 27–35 | 9 | tous à `00` | Inconnu | [code] |
| 36 | 1 | `04` / `03` | Classe : `04` = écriture (commande), `03` = lecture (état) | [code] ; sens = [hyp] |
| 37 | 1 | `01` / `02` | pycololight met `01` en écriture et `02` en lecture. **Dans les captures FHEM de l'appli officielle, cet octet reprend la valeur de l'octet 26** : c'est peut-être une 2ᵉ copie de la séquence | [code] [FHEM] |
| 38–39 | 2 | `03 01` / `06 02` / `01 01` | Sous-commande : `03 01` = alimentation/luminosité, `06 02` = couleur/effet | [code] ; sens = [hyp] |
| 40… | 2–5 | voir §3 | Charge utile | [code] |

L'article FHEM dit que la lampe accepte une séquence fixe à `01`. Il ne précise pas si deux trames
**consécutives** avec la même séquence sont toutes les deux appliquées. Point à tester (§7, H2).

---

## 3. Commandes

### 3.1 Alimentation et luminosité : sous-commande `04 01 03 01`

| Action | Octets 40–41 | Trame complète (séquence = 1) | Source |
|---|---|---|---|
| **Éteindre** | `ce 1e` | `535a3030000000000020` + 16×`00` + `01` + 9×`00` + `04010301` `ce1e` | [code] [FHEM] |
| **Allumer à N %** | `cf NN` (NN = 0x00–0x64) | idem avec `cf` + `NN` | [code] |
| Luminosité seule | `cf NN` | **c'est la même commande** : il n'y a pas de commande « allumer » distincte | [code] |

- pycololight refuse toute valeur hors de 0–100. La plage réelle (0 ? > 100 ?) n'a jamais été mesurée.
- Le `1e` (30) de l'extinction ressemble à une valeur résiduelle. On ne sait pas s'il est lu par la lampe. **[hyp]**
- Valeurs FHEM : « On » = `cf 35`, « Bri 50 » = `cf 2f`, « Bri 100 » = `cf 63`. Le code FHEM, lui,
  enverrait `cf 32` pour 50 ; l'article ne tranche pas. La correspondance entre % et octet reste à vérifier.
- Côté Home Assistant, la conversion est `max(1, int(brightness_255 / 2.55))`.

### 3.2 Couleur fixe : sous-commande `04 01 06 02` (trame de 45 octets)

| Action | Octets 40–44 | Exemple |
|---|---|---|
| Couleur RGB | `ff 00 RR GG BB` | rose : `ff 00 ff 22 22` [FHEM] ; `(255,128,0)` → `ff 00 ff 80 00` [code] |

- Home Assistant convertit HS → RGB à luminosité maximale (`color_hs_to_RGB`), puis envoie
  la luminosité dans une trame `cf NN` séparée. Ce sont deux trames.
- On ne sait pas si la lampe garde la luminosité courante après un changement de couleur, ni si
  les composantes RGB faibles sont rendues fidèlement. **[hyp]**

### 3.3 Effets prédéfinis : sous-commande `04 01 06 02`, octets 40–44 = `ff A B C D`

L'octet 41 = `00` signifie « couleur fixe » ; toute autre valeur sélectionne un effet.
pycololight déclare ces 12 effets « par défaut », **identiques pour hexagon et strip** :

| Nom | A B C D |
|---|---|
| 80s Club | `04 9a 00 00` |
| Cherry Blossom | `04 94 08 00` |
| Cocktail Parade | `05 bd 06 90` |
| Instagrammer | `03 bc 01 90` |
| Pensieve | `04 c4 06 00` |
| Savasana | `04 97 04 00` |
| Sunrise | `01 c1 0a 00` |
| The Circus | `04 81 01 30` |
| Unicorns | `04 9a 0e 00` |
| Christmas | `06 8b 09 00` |
| Rainbow Flow | `03 81 06 90` |
| Music Mode | `07 bd 09 90` |

Interprétation (tirée de `effects.py`, §3.4) : **A** = famille de mode, **B** = palette,
**C** = vitesse, **D** = sous-mode (quartet de poids fort). Exemple : Sunrise = mode `01/00`,
palette `0xc1` = « Selected / Sunrise », vitesse `0x0a`. Les familles `03`, `04` et `07` servent
aux effets par défaut mais n'existent pas dans la table des effets personnalisés.

### 3.4 Effets personnalisés (palette × mode × vitesse)

Un effet personnalisé est une seule trame `ff A B C D`, construite ainsi par `effects.py` :

- **A, D** : couple tiré de la table des modes du modèle (`MODES.md` montre une image par mode) ;
- **B (palette)** = `base_du_schéma + index_couleur`, **moins 128** pour certains modes dits « bas »
  (hexagon : 13, 14, 15, 22, 23, 24 ; strip : 10) ;
- **C (vitesse)** = `33 − cycle_speed`, avec `cycle_speed` de 1 à 32. On envoie donc `0x20` pour 1 et
  `0x01` pour 32. On ne sait pas quel bout de l'échelle est le plus rapide. **[hyp]**
- **Mode 2** : ordre `A C B D`, et seulement 3 vitesses (`0x03`, `0x0b`, `0x13`).

Palettes (`B` de base, avant le −128 éventuel) :

| Schéma | Base | Couleurs (index 0…n) |
|---|---|---|
| Breath | 128 `0x80` | Red-Green-Blue, Rainbow, Green, Azure, Blue, Purple, Red, Orange, Yellow, White, Green-Blue |
| Shadow | 138 `0x8a` | Red-Yellow, Red-Green, Red-Purple, Red-Blue, Green-Yellow, Green-Azure, Green-Blue, Blue-Azure, Blue-Purple, Yellow-White, Red-White, Green-White, Azure-White, Blue-White, Purple-White |
| Flash | 153 `0x99` | Red-Green-Blue, Rainbow, Green, Azure, Blue, Purple, Red, Orange, Yellow, White |
| Flicker | 163 `0xa3` | idem Flash |
| Scene | 173 `0xad` | Birthday, Girlfriends, Friends, Workmates, Family, Lover |
| Mood | 179 `0xb3` | Red, Orange, Yellow, Green, Grass, Azure, Blue, Pink, Gold, Color, True Color |
| Selected | 191 `0xbf` | Savasana, —, Sunrise, —, Unicorns |

Les plages se chevauchent : la dernière couleur de Breath (`0x8a`) est aussi la base de Shadow.
Le code a sans doute des incohérences ici. **[hyp]**

Tables des modes (A, D) :

| Mode | Hexagon | Strip |
|---|---|---|
| 1 | 01,00 | 01,00 |
| 2 | 02,00 | 02,00 |
| 3 | 05,10 | 05,10 |
| 4 | 05,30 | 05,30 |
| 5 | 05,40 | 05,40 |
| 6 | 05,50 | 05,50 |
| 7 | 05,70 | 05,70 |
| 8 | 05,80 | 05,c0 |
| 9 | 05,90 | 05,f0 |
| 10 | 05,a0 | 05,10 (bas) |
| 11 | 05,b0 | 06,00 |
| 12 | 05,c0 | 06,30 |
| 13 | 05,00 (bas) | 06,60 |
| 14 | 05,20 (bas) | — |
| 15 | 05,30 (bas) | — |
| 16 | 06,00 | — |
| 17 | 06,10 | — |
| 18 | 06,20 | — |
| 19 | 06,30 | — |
| 20 | 06,50 | — |
| 21 | 05,f0 | — |
| 22 | 05,10 (bas) | — |
| 23 | 05,40 (bas) | — |
| 24 | 05,50 (bas) | — |
| 25 | 06,60 | — |
| 26 | 06,70 | — |
| 27 | 06,80 | — |

Plusieurs modes ont le même couple (A, D) et ne diffèrent que par le bit de poids fort de B
(mode « bas » ou non). Ce bit fait donc probablement partie du code de mode. **[hyp]**

### 3.5 Effets « dynamiques » (strip uniquement) : séquences de plusieurs trames

Certains effets du strip ne tiennent pas en une trame. Il en faut **4 à 8, envoyées sans aucun
délai**, chacune avec `ff 93 xx yy zz`. Exemple, « Tron » :

```
93 fe fe fe   ← marqueur de début
93 04 05 8b   ← en-tête : 04 = nombre de trames suivantes ; 05, 8b = paramètres inconnus
93 f0 b0 03   ← paramètres (vitesse ? motif ?)
93 ff 00 00   ← couleur 1 (RGB)
93 00 87 ff   ← couleur 2
93 00 ff 64   ← couleur 3
```

Le format se lit comme un téléversement de palette : marqueur, compte, paramètres, puis couleurs RGB.
**[hyp]** Les autres effets dynamiques (« Color train », « Snow », « Lover »…) sont de simples trames `A B C D`.
La liste complète (43 effets) est dans `pycololight/constants.py`, `STRIP_DYANMIC_EFFECTS`.

### 3.6 Commande « Distance » (FHEM uniquement)

`06 87 00 4c 00 4c 03` (distance 4), `5f 00 5f 03` (5), `85 00 85 03` (7). Rôle inconnu (réglage
du capteur ou longueur de la bande ?). L'auteur FHEM conseille de passer par l'appli. **Je ne
l'enverrai pas sans ton accord.**

---

## 4. Différences hexagon / strip

| Aspect | Hexagon | Strip |
|---|---|---|
| Format de trame | identique | identique |
| On/off, luminosité, couleur | identiques | identiques |
| Effets par défaut | les 12 du §3.3 | les mêmes 12 (non vérifié côté strip) |
| Effets dynamiques | aucun | 43, dont des séquences multi-trames `93…` |
| Modes personnalisés | 27 | 13 (table différente à partir du mode 8) |
| Modes « bas » (palette −128) | 13, 14, 15, 22, 23, 24 | 10 |
| Icône HA | `mdi:hexagon-multiple` | `mdi:led-strip-variant` |

Le README de l'intégration cite aussi la « Cololight MIX », traitée comme hexagon ou strip.
Rien dans la lecture d'état ne permet d'identifier le modèle : c'est l'utilisateur qui le choisit.

---

## 5. Lecture de l'état

**Requête** (40 octets) : sous-commande `03 02 01 01`, sans charge utile.

```
53 5a 30 30 00 00 00 00 00 1e  00×16  01  00×9  03 02 01 01
```

**Réponse** : pycololight lit **un seul datagramme** et n'examine que deux octets.

| Offset | Valeur | Sens |
|---|---|---|
| 40 | `0xcf` (207) | allumée, avec octet 41 = luminosité (0–100) |
| 40 | `0xce` (206) | éteinte (octet 41 ignoré) |
| 40 | autre | la réponse est ignorée en silence |

Les octets 40–41 de la réponse reprennent le format de la commande `ce` / `cf`. La réponse fait au
moins 42 octets. Sa longueur réelle et le reste de son contenu (couleur ? effet ? séquence renvoyée ?)
sont **inconnus**. Personne ne les a documentés.

Conséquences dans Home Assistant :
- **seuls on/off et la luminosité** viennent de la lampe ;
- la couleur et l'effet affichés sont des **valeurs optimistes**, restaurées après redémarrage via
  `RestoreEntity` (attributs `set_effect`, `set_hs_color`, `set_brightness`) ;
- l'interrogation se fait toutes les **30 s** (`SCAN_INTERVAL`) ;
- un timeout de lecture (4 s) rend l'entité « unavailable ».

---

## 6. Causes probables du manque de fiabilité

Classées de la plus probable à la moins probable, d'après le code. **Chacune devient une hypothèse à
tester en phase 2.**

1. **Fire-and-forget pur.** Chaque commande part en un seul datagramme UDP, sans retry. Le socket est
   fermé tout de suite après l'envoi, donc un éventuel accusé de réception n'est jamais lu. Sur un WiFi
   2,4 GHz chargé, le moindre datagramme perdu fait « rater » la commande.
2. **Rafales de trames sans espacement.** `turn_on` envoie **deux trames** à quelques microsecondes
   d'écart, chacune depuis un socket et un port source différents : la couleur ou l'effet, puis la
   luminosité. Les effets dynamiques en envoient jusqu'à **8 d'affilée**. Si la lampe ne traite qu'une
   trame à la fois, ou a un petit tampon, les suivantes sont perdues. Pour une séquence `93…`, une
   seule trame perdue corrompt tout l'effet.
3. **Numéro de séquence qui alterne 1/2.** La même alternance sert aux commandes **et** aux requêtes
   d'état. Si la lampe ignore une trame dont la séquence égale celle de la dernière trame reçue (anti-
   doublon), alors une trame perdue, ou une trame de l'appli officielle intercalée, fait tomber la
   suivante sur un doublon, qui est écarté. Cela expliquerait le « il faut appuyer deux fois ».
   L'octet 37, qui semble être une 2ᵉ copie de la séquence dans l'appli officielle, reste fixe chez
   pycololight. **[hyp forte, à tester en priorité]**
4. **État optimiste, et lecture d'état volontairement sautée.** Après chaque commande, le drapeau
   `_can_update = False` fait ignorer la mise à jour suivante. HA affiche alors l'état *voulu* pendant
   jusqu'à ~60 s, même si la lampe n'a rien fait. L'utilisateur ne voit pas l'échec et doit réappuyer.
5. **Aucune vérification après commande.** Rien ne relit l'état après une commande pour la confirmer.
6. **Lecture de réponse non filtrée.** `recvfrom` prend le premier datagramme venu, sans vérifier
   l'adresse source, la séquence ou la longueur. Une réponse tardive ou spontanée peut être prise pour
   l'état courant. Une réponse de moins de 42 octets lève une `IndexError`, avalée par un `except:` nu.
7. **E/S bloquantes dans la boucle asyncio.** `async_turn_on` / `async_turn_off` appellent directement
   les setters synchrones de pycololight (création de socket et `sendto`) dans l'event loop. La lecture
   d'état tourne dans un thread executor, et le compteur `_counter` est partagé sans verrou entre ce
   thread et la boucle : deux trames peuvent donc sortir avec la même séquence.
8. **Couleur et luminosité découplées.** Une couleur est envoyée à pleine luminosité RGB, puis la
   luminosité suit dans une autre trame. Si l'une des deux est perdue, la lampe se retrouve dans un état
   intermédiaire.
9. **Identifiant fragile.** `unique_id` est l'adresse IP : un changement de bail DHCP casse l'entité.

---

## 7. Hypothèses à vérifier en phase 2

| # | Question | Pourquoi c'est important |
|---|---|---|
| H1 | La lampe **répond-elle aux commandes** (ACK), ou seulement aux requêtes d'état ? À quel port ? | Retry piloté par ACK ou par relecture d'état |
| H2 | Une trame avec **la même séquence** que la précédente est-elle ignorée ? Rôle de l'octet 37 ? | Cause n°3 |
| H3 | Format complet de la **réponse d'état** : longueur, contenu au-delà des octets 40–41 (couleur, effet ?) | Éviter l'état optimiste |
| H4 | **Push** spontané quand on agit depuis l'appli officielle ? Vers qui (broadcast, dernier client) ? | Polling ou push |
| H5 | **Taux de perte** sur 20 envois identiques | Nombre de retries |
| H6 | **Délai minimal** entre deux trames | Espacement et file d'envoi |
| H7 | Plages réelles : luminosité (0 ? > 100 ?), couleurs RGB faibles | Conversions HA |
| H8 | Rendu de chaque effet prédéfini, sens de la vitesse, quelques effets personnalisés | Liste d'effets |
| H9 | Comportement après **coupure de courant** et **redémarrage WiFi** (état restauré ? délai de retour ?) | Disponibilité, reprise |
| H10 | **Découverte** : la lampe répond-elle à une requête d'état en broadcast ? | Config flow avec découverte |
| H11 | Faut-il les octets 4–7 / 10–25 non nuls ? La lampe accepte-t-elle une trame mal formée ? | Robustesse |
