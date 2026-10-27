# Cololight strip – fonctionnement réel et stratégie de communication

> Synthèse de la phase 2 (tests interactifs du 25/10/2026), sur **ton** bandeau.
> Preuves : `logs/cololight-20261025.log` / `.jsonl`, outil `tools/cololight_probe.py`.
> Sans mention contraire, tout ce qui suit a été **vérifié par un test**.
> Ce qui n'a pas pu l'être est marqué **[non testé]**.

---

## 1. En bref

| Question | Réponse mesurée |
|---|---|
| La lampe accuse-t-elle réception ? | **Oui, toujours.** Chaque commande reçoit une réponse qui reprend la valeur appliquée et notre numéro de séquence |
| Peut-on lire l'état complet ? | **Oui**, en deux requêtes : allumé/éteint + luminosité (élément 01), couleur ou effet (élément 02) |
| Push spontané en local ? | **Non** (2 × 150 s d'écoute pendant des manipulations dans l'appli) : **il faut interroger la lampe** |
| Taux de perte | 0/20 au rythme de 1 commande toutes les 3 s ; **1/63 en rafale**. Une perte = **pas d'ACK** |
| Latence | médiane **269 ms**, p95 **819 ms**, max **1 292 ms** (381 réponses). Des réponses arrivent parfois groupées : veille WiFi |
| Délai minimal entre commandes | Aucun : à 0 ms, les deux commandes passent |
| Luminosité | 0–101 acceptés. **255 fait perdre le WiFi jusqu'à une coupure de courant** |
| Sauvegarde | L'opération `04` est **volatile**. L'opération **`07` écrit et enregistre en EEPROM** (couleur et luminosité) |
| Après une coupure de courant | La lampe est de nouveau joignable en **20–30 s**, même IP, avec le dernier état enregistré |
| Découverte | **Oui** : une requête d'état en broadcast sur le port 8900 reçoit une réponse qui contient la MAC |
| Appli officielle | **100 % cloud** (`ict.ilifesmart.com:19110`) : elle n'envoie aucune trame locale |

---

## 2. L'appareil

| Élément | Valeur | Source |
|---|---|---|
| IP | 192.168.0.51 (inchangée après 3 coupures) | test |
| MAC | `4C:11:AE:B1:B6:14` (Espressif, donc module ESP) | ARP + réponses |
| Modèle | `ls167s6`, **120 LED** (`P_lightSpec`, `P_lightCount`) | capture cloud |
| Signal WiFi | ≈ −55 dBm vu par le cloud. L'octet 35 des réponses d'état (63–64) en est probablement la valeur absolue **[hyp]** | capture + réponses |
| Ping | 147–364 ms : le module est en veille WiFi | test |

---

## 3. Protocole local vérifié (UDP 8900)

### 3.1 Trame

```
off  53 5a 30 30 | 00 00 00 00 | 00 20 | 00×6 | 00 00 | 00×8 | 27 | 00×9 | 04 01 03 01 | ce 1e
     "SZ00"        drapeaux      long.          somme          séq.         en-tête        données
```

| Offset | Requête | Réponse | Vérifié |
|---|---|---|---|
| 0–3 | `SZ00` | `SZ00` | ✅ |
| 4 | `00` | **`80`** = drapeau réponse | ✅ |
| 8–9 | uint16 BE = taille − 10 | idem | ✅ |
| 16–17 | `00 00` | **somme 16 bits de tous les octets à partir de l'offset 18** | ✅ sur toutes les réponses. La lampe **ne vérifie pas** la somme des requêtes (zéro, juste ou fausse : tout est accepté) |
| 26 | séquence (1 octet) | **renvoyée à l'identique** | ✅ Pas de rejet des doublons (même séquence deux fois à 2 s d'écart : les deux sont appliquées) |
| 35 | `00` | `3f`/`40` dans les réponses d'état | signal WiFi ? **[hyp]** |
| 36 | **opération** | opération + `0x80` | ✅ |
| 37 | libre | **renvoyé à l'identique**, aucun effet (02–05 testés) | ✅ |
| 38… | blocs TLV | blocs TLV | ✅ |

### 3.2 Opérations (offset 36)

| Op | Rôle | Réponse | Vérifié |
|---|---|---|---|
| `03` | **lecture** d'un élément | `83` + élément | ✅ |
| `04` | **écriture volatile** | `84` + élément tel qu'appliqué | ✅ |
| `07` | **écriture + EEPROM** (survit à une coupure) | `87` + élément | ✅ couleur et luminosité. Effet : **[non testé]** |
| `09` | **infos appareil** (bloc de 24 octets avec la MAC en binaire) | `89 01 18 01 …` | ✅ réponse ; contenu partiellement compris |
| `05 06 08 0a 0c–0f` | inconnues | erreur `01 43` | ✅ refusées, sans effet |
| `0b` | inconnue | erreur `01 49` | ✅ refusée, sans effet |

### 3.3 Blocs TLV : `[longueur][id][données (longueur−1 octets)]`

| Élément | Écriture | Lecture (requête `03 xx 01 id`) | Remarques |
|---|---|---|---|
| **01** puissance | `03 01 cf NN` = allumé à NN % ; `03 01 ce 1e` = éteint | réponse `03 01 cf NN` / `03 01 ce 1e` | ✅ |
| **02** mode | `06 02 ff 00 RR GG BB` = couleur fixe ; `06 02 ff A B C D` = effet | réponse au même format | ✅ couleur **et** effet relus exactement |
| **03** | — | `fe 00 00 00 00` | inconnu (réglage « Distance » de FHEM ?) |
| 04–08 | — | `1e` | élément inexistant (supposé) |
| MAC | — | `0d 01 "4C11AEB1B614"` ajouté à **chaque** réponse | ✅ |

- Une requête ne lit **qu'un élément** : les TLV suivants sont ignorés. Une interrogation complète demande donc 2 requêtes.
- L'**ACK reprend l'élément tel qu'appliqué**. Il sert donc à la fois d'accusé et d'état.

### 3.4 Valeurs

| Paramètre | Plage sûre | Observé |
|---|---|---|
| Luminosité `NN` | **0–100** | 0, 1, 100, 101 acceptés et relus. **255 → perte du WiFi** (LED figées, plus d'IP, il faut débrancher). La limite exacte entre 102 et 254 est **[non testée]** |
| Couleur RGB | 00–ff par composante | `#000000`, `#010000`, `#808080`, `#ffffff` acceptés et relus. Rendu visuel **[non observé]** |
| Vitesse d'effet `C` | **`0x00` (le plus rapide) … `0x20` (le plus lent)** | vérifié visuellement aux deux extrêmes |
| Changer la couleur | garde la luminosité ; ne rallume pas la lampe si elle est éteinte **[non testé]** | ✅ luminosité conservée |
| Rallumer (`cf NN`) | rend la dernière couleur ou le dernier effet | ✅ |

### 3.5 Effets

- **Les 12 effets par défaut et 4 effets dynamiques en une trame** (Color train, Snow, Lover, Red alert) : ACK reçu et **relecture du code exact**. Le rendu visuel n'a été observé que pour Sunrise.
- **Les effets dynamiques en plusieurs trames** (Tron 6, Red meteor 4, Innocence 8) : **un ACK par trame**, aussi bien en rafale qu'avec 100 ms de pause. La relecture ne renvoie **que la dernière trame** (`93 RR GG BB`). C'est ambigu (Tron et Tricolor finissent tous deux par `00ff64`) : il faut donc **mémoriser l'effet envoyé**.
- **Les effets personnalisés** (mode, palette, vitesse ; 4 essais, dont le mode 2) : ACK reçu et relecture exacte.

### 3.6 Découverte

- Requête d'état en broadcast sur `192.168.0.255:8900` ou `255.255.255.255:8900` : la lampe répond en 166–422 ms, avec sa MAC.
- Sous Windows, `255.255.255.255` doit être émis depuis la bonne interface. Avec Home Assistant, il faudra utiliser les adresses de broadcast de chaque interface.

---

## 4. Comportements à connaître

1. **Ce que la lampe garde après une coupure de courant.** Au démarrage, elle reprend l'état enregistré par l'opération `07` locale, ou par l'appli (qui utilise `rfSetEEProm` via le cloud pour la couleur ou l'effet). Les commandes `04` sont perdues. Observé 3 fois : `#ff2222`/100 %, `01c10000`/100 %, puis `#ff8000`/30 % après une écriture `07`.
2. **Les réglages de l'appli sont visibles par l'interrogation locale.** On l'a vérifié pour allumé/éteint et la luminosité, et l'élément 02 pour la couleur. L'appli, elle, **n'affiche pas** ce qui a été réglé en local.
3. **Plantage du WiFi** avec une luminosité de 255 : la seule issue est de couper le courant. Il faut donc **plafonner strictement à 100**.
4. **Latence irrégulière** à cause de la veille WiFi. Un ACK peut mettre plus d'une seconde à revenir, et plusieurs ACK peuvent arriver en même temps.

---

## 5. Pourquoi l'intégration actuelle n'est pas fiable (confirmé)

| Cause supposée en phase 1 | Verdict |
|---|---|
| Fire-and-forget, sans retry | **Confirmé.** Environ 1–2 % de pertes, et l'ACK qui permettrait de les détecter est jeté |
| ACK jamais lu (socket fermé aussitôt) | **Confirmé.** La lampe répond à **toutes** les commandes |
| Rafales sans espacement | **Écarté** comme cause principale : à 0 ms, les deux commandes passent |
| Séquence 1/2 + anti-doublon | **Écarté** : pas de rejet des doublons |
| État optimiste + interrogation sautée | **Confirmé** (code). Aggravé par le fait que pycololight ignore l'élément 02, pourtant lisible |
| Réponse non filtrée | **Confirmé.** Les ACK de commande contiennent eux aussi `cf`/`ce` : une réponse tardive peut être prise pour l'état |
| Plafond de luminosité | pycololight refuse déjà les valeurs > 100 : l'intégration actuelle est protégée. **Il faut conserver ce garde-fou**, puisque 255 fait planter la lampe |

---

## 6. Stratégie de communication recommandée

### 6.1 Transport

- **Un seul socket UDP asyncio par lampe** (`DatagramProtocol`), ouvert pendant toute la durée de vie de l'intégration. Il ne doit jamais bloquer la boucle d'événements.
- **Séquence** de 1 à 255, incrémentée à chaque trame. Elle sert à **associer chaque réponse à sa requête**.
- Les datagrammes sont filtrés selon l'IP source, `SZ00`, le drapeau `0x80` et une séquence en attente. Tout autre datagramme est ignoré et journalisé en debug.
- **Une seule requête en vol à la fois**, via une file protégée par un verrou par lampe. Rien n'impose de délai entre deux trames, mais la sérialisation simplifie la corrélation et les retries.

### 6.2 Commandes : retry guidé par l'ACK

| Paramètre | Valeur | Justification |
|---|---|---|
| Attente d'ACK | **1,5 s** | p99 891 ms, max 1 292 ms |
| Tentatives | **4** (1 + 3 retries) | perte ≈ 2 % : échec complet ≈ 2 % ⁴, négligeable |
| Pause entre tentatives | 0,2 s puis 0,5 s puis 1 s | laisse le module sortir de veille |
| Durée maximale | ≈ 8 s | au-delà, échec visible |
| Idempotence | toutes les commandes sont **absolues** (valeur, pas bascule) | un retry ne peut pas produire un mauvais état |

- **Vérification :** l'ACK reprend l'élément appliqué. On compare son contenu à la valeur demandée et on met **immédiatement à jour l'état** de l'entité à partir de l'ACK : pas d'optimisme, pas d'attente de l'interrogation suivante.
- **Relecture de contrôle :** après une commande, on demande au coordinateur un rafraîchissement anti-rebond (environ 1 s), pour confirmer.
- **Effets en plusieurs trames :** on les envoie trame par trame, en attendant l'ACK de chacune (retry trame par trame), puis on mémorise le nom de l'effet. À la relecture, on considère l'effet actif tant que l'élément 02 vaut toujours sa dernière trame.
- **Allumer avec couleur ou effet :** on envoie d'abord l'élément 02, puis l'élément 01 (`cf NN`), chacun avec son ACK.
- **Éteindre :** `ce 1e`.
- **Luminosité :** conversion HA 1–255 → 1–100, **toujours plafonnée à 100**. 0 n'est jamais envoyé : pour éteindre, on utilise `ce`.

### 6.3 État : interrogation par `DataUpdateCoordinator`

- **Intervalle par défaut : 10 s**, configurable de 5 à 300 s (intégration livrée). Chaque cycle fait 2 requêtes d'environ 40 octets, ce qui est négligeable pour la lampe. 10 s est un bon compromis pour voir rapidement les changements faits depuis l'appli ou après une coupure.
- Chaque requête passe par la même file avec retry (2 tentatives suffisent pour une lecture).
- **Correspondance de l'état :**
  - élément 01 → `is_on`, `brightness` ;
  - élément 02 `00 RRGGBB` → `rgb_color` ;
  - élément 02 `A B C D` → nom d'effet (table connue), sinon « effet personnalisé » avec le code en attribut.

### 6.4 Disponibilité et erreurs

- **Indisponible** seulement après **3 cycles d'interrogation ratés d'affilée** (≈ 30 s), pas dès la première perte. Un redémarrage de la lampe dure 20–30 s.
- **Retour automatique** dès qu'une réponse arrive. Si l'IP ne répond plus, on relance une **découverte par broadcast** et on retrouve la lampe par sa **MAC** (utilisée comme `unique_id`).
- **Commande en échec** après toutes les tentatives : on lève une `HomeAssistantError`, ce qui rend l'échec **visible dans l'UI**, et on écrit un WARNING dans les logs avec la commande et le nombre d'essais.
- **Réponse d'erreur** (TLV `01 43` / `01 49`) : WARNING avec le code.
- Les trames brutes sont journalisées en DEBUG (hex), pour le diagnostic.

### 6.5 Sauvegarde (opération 07)

- Par défaut, on pilote avec l'opération `04` : la flash EEPROM supporte un nombre d'écritures limité, il ne faut donc pas l'user à chaque mouvement de curseur.
- **Option « mémoriser l'état comme état au démarrage »** : quand l'état reste stable **30 s**, on le réécrit une fois avec l'opération `07`.
- On peut aussi exposer un **service `cololight_local.save_state`** pour une sauvegarde explicite, par exemple depuis une automatisation.
- Effet de bord à connaître : on écrase alors l'état enregistré par l'appli officielle.

### 6.6 Découverte et configuration

- Config flow : **saisie de l'IP**, ou **découverte** par broadcast (liste des MAC qui répondent).
- `unique_id` = MAC. Le modèle (strip ou hexagon) détermine la liste d'effets. Il est choisi par l'utilisateur, car rien de lisible en local ne l'indique (à part peut-être l'opération 09 **[à creuser]**).

---

## 7. Non testé / limites

- Redémarrage de la box : sauté d'un commun accord. Le cas est couvert par la gestion « indisponible → redécouverte ».
- Sauvegarde d'un **effet** par l'opération `07`.
- Rendu visuel de la plupart des effets et des couleurs limites : seuls l'ACK et la relecture ont été vérifiés.
- Couleur envoyée pendant que la lampe est éteinte : se rallume-t-elle ?
- Signification exacte de l'octet 35, de l'élément 03, et du bloc renvoyé par l'opération 09.
- Valeur exacte du seuil de plantage de la luminosité (102–254).
- Comportement de plusieurs clients simultanés (HA + cloud) : a priori le dernier qui écrit l'emporte, rien n'a montré de conflit.
