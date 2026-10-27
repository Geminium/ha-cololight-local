# Plan de tests interactifs – Cololight strip 192.168.0.51

Outil : `python tools/cololight_probe.py <commande>` (journal dans `logs/`).
Chaque étape : explication → envoi → observation physique → `note` dans le journal.

| Étape | Hypothèse | Ce qu'on envoie | Ce qu'on observe |
|---|---|---|---|
| 0 | H3 | `state` (lecture seule) | Réponse ? Taille, contenu complet |
| 1 | H1 | `off`, `bright 50`, `color ff0000` en écoutant 1,5 s | La lampe renvoie-t-elle un ACK ? Effet physique |
| 2 | H2 | Deux commandes différentes avec **la même séquence** (`--seq`), puis `--b37` | La 2ᵉ est-elle appliquée ? |
| 3 | H4 | `listen 120 --register` pendant que tu manipules l'appli officielle | Paquets spontanés ? |
| 4 | H5 | `loss 20` (luminosité 20/80 alternée, vérifiée par relecture d'état) | Taux d'application |
| 5 | H6 | `burst` : deux trames espacées de 0 à 400 ms | Délai minimal sans perte |
| 6 | H7 | `bright 0/1/100/101/255`, couleurs faibles (`color 010000`, `color 808080`) | Plages valides |
| 7 | H3 | Couleur, puis `state` : la réponse change-t-elle ? | La couleur est-elle lisible ? |
| 8 | H8 | Les 12 effets par défaut, quelques effets dynamiques, `--gap` sur les multi-trames, 3–4 effets `custom` | Rendu, vitesse |
| 9 | H10 | `discover` (broadcast) | Découverte possible ? |
| 10 | H9 | Débrancher/rebrancher la lampe, redémarrer le WiFi ; `state` en boucle | Délai de retour, état restauré |
