# Résultats : peut-on anticiper les grandes tendances à 6 et 12 mois ?

Calculé le 18/11/2026 sur les données de Yahoo Finance, selon le protocole pré-enregistré `etudes/protocole_tendances.md` (aucun paramètre ajusté).

## En bref

- **Choisir les actions qui feront mieux que les autres sur 6 ou 12 mois** (question A) : aucun des 5 signaux ne
  remplit son critère. Leurs écarts changent même de sens entre la période de conception et la période de test
  (retournement long : +9,0 points avant 2022, −5,1 points depuis ; combiné : −6,2 puis +0,7). Rien n'est démontré.
- **Suivre la tendance de chaque action** (question B : investi seulement au-dessus de la moyenne 200 jours) : le
  risque baisse nettement (perte maximale de 12,9 % à 6,1 % sur la période de test, et de 24,7 % à 9,0 % sur toute la
  période), mais le rendement aussi, d'environ 6 points par an (+10,6 % contre +4,8 % par an sur la période de test).
  Critère « risque » rempli, critère « rendement » non : le rendement est même **démontré plus faible**.
- **Suivre la grande tendance du marché** (question C : règle des 10 mois sur 6 indices, depuis 1985) : le rendement
  n'est amélioré de façon démontrée sur **aucun** indice. La règle a fortement réduit les pertes en 2000-2012 (deux
  longs marchés baissiers, sur 5 indices sur 6), mais pas ailleurs, et depuis 2013 elle coûte 2 à 6 points par an.
  Savoir si un indice est au-dessus ou en dessous de sa moyenne ne prédit pas de façon démontrée ses 6 ou 12 mois
  suivants ; pour l'Euro Stoxx 50 à 12 mois, c'est même l'inverse.

**Conclusion** : ces méthodes, parmi les plus étudiées, ne permettent pas de prévoir la direction des 6 à 12 prochains
mois. Les règles de tendance sont une **assurance contre les longs marchés baissiers**, payée par un rendement plus
faible les autres années ; elles ne sont pas un moyen de gagner davantage. Conformément au protocole, rien n'est ajouté
automatiquement à l'application.

**Limites** (fixées dans le protocole) : catalogue limité aux entreprises qui existent encore (biais du survivant) ;
indices sans dividendes ; liquidités rémunérées à 0 % quand une règle sort du marché ; période de test courte
(58 mois, de janvier 2022 à octobre 2026).

---

- Actions : 120 du catalogue (hors ETF), cours du 18/11/2016 au 17/11/2026.
- Décisions mensuelles de conception avant le 01/01/2022, de test ensuite.

## A. Sélection : les actions du groupe « haut » font-elles mieux que les autres actions du même mois ?

Écart moyen avec les autres actions du même mois, en points, avec la fourchette à 95 %. Colonne « corrigée » : fourchette élargie pour les 10 essais (critère pré-enregistré).

| Signal | Haut, 6 mois (test) | Haut, 12 mois (test) | Haut, 12 mois (test, corrigée) | Haut, 12 mois (conception) | Bas, 12 mois (test) | Critère |
| --- | --- | --- | --- | --- | --- | --- |
| S1 Momentum 12-1 | +1,4 pt [-2,6 ; +5,3] (1248 obs.) | +2,7 pt [-4,8 ; +10,3] (1104 obs.) | +2,7 pt [-8,0 ; +13,5] (1104 obs.) | +1,0 pt [-3,5 ; +5,5] (1165 obs.) | -2,5 pt [-10,4 ; +5,3] (1104 obs.) | ❌ non rempli |
| S2 Tendance (cours / moyenne 200 j) | +1,7 pt [-0,8 ; +4,3] (1248 obs.) | +3,6 pt [-2,6 ; +9,8] (1104 obs.) | +3,6 pt [-5,3 ; +12,5] (1104 obs.) | +0,7 pt [-3,7 ; +5,1] (1231 obs.) | -2,9 pt [-11,3 ; +5,5] (1104 obs.) | ❌ non rempli |
| S3 Faible volatilité | -0,6 pt [-4,2 ; +2,9] (1248 obs.) | -2,2 pt [-9,7 ; +5,3] (1104 obs.) | -2,2 pt [-12,9 ; +8,5] (1104 obs.) | -1,0 pt [-7,1 ; +5,0] (1166 obs.) | +5,6 pt [-3,7 ; +14,8] (1104 obs.) | ❌ non rempli |
| S4 Retournement long (36 mois) | -2,0 pt [-5,5 ; +1,5] (1239 obs.) | -5,1 pt [-12,3 ; +2,2] (1095 obs.) | -5,1 pt [-15,5 ; +5,3] (1095 obs.) | +9,0 pt [+2,1 ; +16,0] (598 obs.) | +6,1 pt [-2,6 ; +14,7] (1095 obs.) | ❌ non rempli |
| S5 Combiné (momentum, faible volatilité, dividende) | +1,0 pt [-1,7 ; +3,8] (1248 obs.) | +0,7 pt [-5,9 ; +7,3] (1104 obs.) | +0,7 pt [-8,8 ; +10,2] (1104 obs.) | -6,2 pt [-12,3 ; -0,1] (1165 obs.) | +2,9 pt [-7,2 ; +13,0] (1104 obs.) | ❌ non rempli |

## B. Suivre la tendance de chaque action (investi si cours > moyenne 200 jours)

Portefeuille à parts égales de toutes les actions, chacune gérée par la règle, contre le même portefeuille conservé. Coût de 0,25 % par entrée ou sortie, liquidités à 0 %.

| Période | Mois | Conservation : rendement annualisé | Règle : rendement annualisé | Écart [fourchette 95 %] | Conservation : perte max. | Règle : perte max. | Perte évitée [fourchette 95 %] | Critères |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Toute la période | 110 | +12,5 % | +6,5 % | -6,0 pt [-11,2 ; -1,2] | 24,7 % | 9,0 % | +15,8 pt [+5,2 ; +22,3] | ❌ rendement · ✅ risque |
| Conception (avant 2022) | 52 | +14,7 % | +8,3 % | -6,4 pt [-17,2 ; +2,6] | 24,7 % | 9,0 % | +15,8 pt [+3,9 ; +25,8] | ❌ rendement · ✅ risque |
| Test (depuis 2022) | 58 | +10,6 % | +4,8 % | -5,7 pt [-11,0 ; -3,4] | 12,9 % | 6,1 % | +6,8 pt [+2,2 ; +9,0] | ❌ rendement · ✅ risque |

- Sur toute la période : la règle améliore le rendement de 15 % des actions (120) et réduit la perte maximale de 74 % d'entre elles.
- Sur période de test : la règle améliore le rendement de 26 % des actions (120) et réduit la perte maximale de 65 % d'entre elles.

## C. Grandes tendances du marché (indices, investi si clôture mensuelle > moyenne 10 mois)

### S&P 500 (`^GSPC`, depuis 01/1985)

| Période | Mois | Conservation : rendement annualisé | Règle : rendement annualisé | Écart [fourchette 95 %] | Conservation : perte max. | Règle : perte max. | Perte évitée [fourchette 95 %] | Critères |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Tout l'historique (investi 77 % du temps) | 492 | +9,4 % | +7,1 % | -2,3 pt [-5,6 ; +1,5] | 52,6 % | 27,4 % | +25,2 pt [-7,0 ; +41,3] | ❌ rendement · ❌ risque |
| avant 2000 (investi 83 % du temps) | 170 | +15,5 % | +8,8 % | -6,7 pt [-10,3 ; -3,4] | 30,2 % | 27,4 % | +2,8 pt [-15,2 ; +6,3] | ❌ rendement · ❌ risque |
| 2000-2012 (investi 62 % du temps) | 156 | -0,2 % | +4,8 % | +5,0 pt [-2,4 ; +14,2] | 52,6 % | 13,2 % | +39,3 pt [+9,1 ; +70,2] | ❌ rendement · ✅ risque |
| depuis 2013 (investi 85 % du temps) | 166 | +12,8 % | +7,6 % | -5,3 pt [-8,7 ; -2,1] | 24,8 % | 24,5 % | +0,3 pt [-14,0 ; +10,7] | ❌ rendement · ❌ risque |
| période de test (depuis 2022) (investi 78 % du temps) | 58 | +10,1 % | +2,4 % | -7,7 pt [-13,1 ; -4,1] | 24,8 % | 24,5 % | +0,3 pt [-7,5 ; +5,8] | ❌ rendement · ❌ risque |

- 6 mois suivants : +5,5 % en moyenne au-dessus de la moyenne (373 mois), +3,7 % en dessous (114 mois) ; écart +1,9 pt [-4,3 ; +7,4].
- 12 mois suivants : +11,0 % en moyenne au-dessus de la moyenne (368 mois), +7,8 % en dessous (113 mois) ; écart +3,2 pt [-6,7 ; +12,1].

### CAC 40 (`^FCHI`, depuis 03/1990)

| Période | Mois | Conservation : rendement annualisé | Règle : rendement annualisé | Écart [fourchette 95 %] | Conservation : perte max. | Règle : perte max. | Perte évitée [fourchette 95 %] | Critères |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Tout l'historique (investi 64 % du temps) | 430 | +4,8 % | +3,6 % | -1,1 pt [-5,0 ; +4,3] | 60,5 % | 24,3 % | +36,2 pt [-2,8 ; +49,7] | ❌ rendement · ❌ risque |
| avant 2000 (investi 70 % du temps) | 108 | +16,5 % | +8,1 % | -8,3 pt [-13,6 ; -0,9] | 23,9 % | 24,1 % | -0,2 pt [-15,2 ; +13,2] | ❌ rendement · ❌ risque |
| 2000-2012 (investi 55 % du temps) | 156 | -3,7 % | +3,2 % | +6,9 pt [-1,3 ; +16,5] | 60,5 % | 24,3 % | +36,2 pt [+13,4 ; +70,7] | ❌ rendement · ✅ risque |
| depuis 2013 (investi 69 % du temps) | 166 | +5,8 % | +1,2 % | -4,6 pt [-8,7 ; -1,1] | 26,5 % | 23,9 % | +2,5 pt [-19,6 ; +15,9] | ❌ rendement · ❌ risque |
| période de test (depuis 2022) (investi 64 % du temps) | 58 | +2,3 % | -1,5 % | -3,8 pt [-9,4 ; -2,2] | 19,4 % | 15,3 % | +4,1 pt [-11,1 ; +8,6] | ❌ rendement · ❌ risque |

- 6 mois suivants : +3,6 % en moyenne au-dessus de la moyenne (273 mois), +2,1 % en dessous (152 mois) ; écart +1,6 pt [-3,9 ; +7,0].
- 12 mois suivants : +7,2 % en moyenne au-dessus de la moyenne (268 mois), +4,9 % en dessous (151 mois) ; écart +2,3 pt [-6,8 ; +12,0].

### DAX (`^GDAXI`, depuis 12/1987)

| Période | Mois | Conservation : rendement annualisé | Règle : rendement annualisé | Écart [fourchette 95 %] | Conservation : perte max. | Règle : perte max. | Perte évitée [fourchette 95 %] | Critères |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Tout l'historique (investi 70 % du temps) | 457 | +8,3 % | +7,7 % | -0,6 pt [-4,7 ; +4,3] | 68,3 % | 30,2 % | +38,1 pt [-6,0 ; +46,5] | ❌ rendement · ❌ risque |
| avant 2000 (investi 76 % du temps) | 135 | +16,5 % | +11,4 % | -5,1 pt [-10,0 ; -0,0] | 32,5 % | 27,3 % | +5,2 pt [-22,4 ; +16,0] | ❌ rendement · ❌ risque |
| 2000-2012 (investi 63 % du temps) | 156 | +0,7 % | +7,4 % | +6,7 pt [-2,7 ; +17,4] | 68,3 % | 30,2 % | +38,1 pt [+3,4 ; +66,9] | ❌ rendement · ✅ risque |
| depuis 2013 (investi 73 % du temps) | 166 | +9,2 % | +5,0 % | -4,2 pt [-8,7 ; -0,2] | 25,0 % | 24,6 % | +0,4 pt [-11,0 ; +19,7] | ❌ rendement · ❌ risque |
| période de test (depuis 2022) (investi 78 % du temps) | 58 | +10,6 % | +9,1 % | -1,5 pt [-8,9 ; +0,8] | 23,7 % | 10,5 % | +13,2 pt [-2,8 ; +17,5] | ❌ rendement · ❌ risque |

- 6 mois suivants : +6,3 % en moyenne au-dessus de la moyenne (317 mois), +2,4 % en dessous (135 mois) ; écart +3,8 pt [-2,3 ; +9,5].
- 12 mois suivants : +11,3 % en moyenne au-dessus de la moyenne (312 mois), +8,1 % en dessous (134 mois) ; écart +3,2 pt [-7,1 ; +13,9].

### Euro Stoxx 50 (`^STOXX50E`, depuis 03/2007)

| Période | Mois | Conservation : rendement annualisé | Règle : rendement annualisé | Écart [fourchette 95 %] | Conservation : perte max. | Règle : perte max. | Perte évitée [fourchette 95 %] | Critères |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Tout l'historique (investi 61 % du temps) | 226 | +1,8 % | +0,1 % | -1,7 pt [-7,7 ; +3,8] | 55,1 % | 28,7 % | +26,4 pt [-11,7 ; +47,6] | ❌ rendement · ❌ risque |
| 2000-2012 (investi 38 % du temps) | 60 | -9,7 % | -4,9 % | +4,8 pt [-12,3 ; +22,9] | 55,1 % | 28,0 % | +27,1 pt [-12,5 ; +65,4] | ❌ rendement · ❌ risque |
| depuis 2013 (investi 69 % du temps) | 166 | +6,3 % | +1,9 % | -4,4 pt [-7,9 ; -0,6] | 25,6 % | 20,2 % | +5,4 pt [-12,8 ; +18,1] | ❌ rendement · ❌ risque |
| période de test (depuis 2022) (investi 74 % du temps) | 58 | +7,6 % | +2,7 % | -4,9 pt [-11,1 ; -2,9] | 22,8 % | 13,1 % | +9,7 pt [-4,1 ; +10,3] | ❌ rendement · ❌ risque |

- 6 mois suivants : +1,2 % en moyenne au-dessus de la moyenne (132 mois), +3,5 % en dessous (89 mois) ; écart -2,3 pt [-8,7 ; +1,8].
- 12 mois suivants : +2,3 % en moyenne au-dessus de la moyenne (127 mois), +7,9 % en dessous (88 mois) ; écart -5,6 pt [-15,2 ; -0,7].

### Nikkei 225 (`^N225`, depuis 01/1985)

| Période | Mois | Conservation : rendement annualisé | Règle : rendement annualisé | Écart [fourchette 95 %] | Conservation : perte max. | Règle : perte max. | Perte évitée [fourchette 95 %] | Critères |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Tout l'historique (investi 58 % du temps) | 492 | +3,9 % | +4,4 % | +0,4 pt [-4,4 ; +5,2] | 80,6 % | 53,8 % | +26,7 pt [-7,1 ; +48,6] | ❌ rendement · ❌ risque |
| avant 2000 (investi 55 % du temps) | 170 | +2,7 % | +3,0 % | +0,3 pt [-7,8 ; +8,5] | 65,6 % | 53,8 % | +11,7 pt [-14,0 ; +44,6] | ❌ rendement · ❌ risque |
| 2000-2012 (investi 44 % du temps) | 156 | -4,5 % | +1,8 % | +6,3 pt [-3,3 ; +17,0] | 62,8 % | 30,5 % | +32,3 pt [+6,5 ; +71,7] | ❌ rendement · ✅ risque |
| depuis 2013 (investi 73 % du temps) | 166 | +13,9 % | +8,3 % | -5,7 pt [-10,2 ; -1,9] | 24,3 % | 31,4 % | -7,1 pt [-26,7 ; +11,3] | ❌ rendement · ❌ risque |
| période de test (depuis 2022) (investi 76 % du temps) | 58 | +17,7 % | +10,0 % | -7,7 pt [-15,0 ; -3,3] | 13,2 % | 18,3 % | -5,0 pt [-22,3 ; +0,8] | ❌ rendement · ❌ risque |

- 6 mois suivants : +4,8 % en moyenne au-dessus de la moyenne (278 mois), +1,1 % en dessous (209 mois) ; écart +3,6 pt [-2,1 ; +7,6].
- 12 mois suivants : +7,0 % en moyenne au-dessus de la moyenne (272 mois), +4,8 % en dessous (209 mois) ; écart +2,3 pt [-6,8 ; +9,1].

### FTSE 100 (`^FTSE`, depuis 01/1985)

| Période | Mois | Conservation : rendement annualisé | Règle : rendement annualisé | Écart [fourchette 95 %] | Conservation : perte max. | Règle : perte max. | Perte évitée [fourchette 95 %] | Critères |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Tout l'historique (investi 68 % du temps) | 492 | +5,1 % | +3,0 % | -2,1 pt [-5,3 ; +1,1] | 48,5 % | 42,6 % | +5,9 pt [-15,7 ; +36,6] | ❌ rendement · ❌ risque |
| avant 2000 (investi 74 % du temps) | 170 | +12,1 % | +4,7 % | -7,4 pt [-11,3 ; -4,2] | 33,2 % | 42,6 % | -9,4 pt [-23,1 ; +7,0] | ❌ rendement · ❌ risque |
| 2000-2012 (investi 56 % du temps) | 156 | -1,2 % | +2,3 % | +3,6 pt [-2,4 ; +11,5] | 48,5 % | 24,6 % | +23,9 pt [+3,2 ; +64,7] | ❌ rendement · ✅ risque |
| depuis 2013 (investi 72 % du temps) | 166 | +4,4 % | +2,0 % | -2,4 pt [-5,9 ; +1,4] | 28,0 % | 20,6 % | +7,4 pt [-18,8 ; +25,0] | ❌ rendement · ❌ risque |
| période de test (depuis 2022) (investi 83 % du temps) | 58 | +8,0 % | +3,5 % | -4,6 pt [-8,0 ; -2,2] | 9,4 % | 13,2 % | -3,8 pt [-10,8 ; +0,8] | ❌ rendement · ❌ risque |

- 6 mois suivants : +3,2 % en moyenne au-dessus de la moyenne (329 mois), +2,6 % en dessous (158 mois) ; écart +0,5 pt [-3,7 ; +4,4].
- 12 mois suivants : +6,1 % en moyenne au-dessus de la moyenne (323 mois), +5,4 % en dessous (158 mois) ; écart +0,7 pt [-6,0 ; +6,6].

## Verdict selon les critères pré-enregistrés

- **A. Sélection** : aucun signal ne remplit le critère sur la période de test.
- **B. Tendance par action** (période de test) : rendement non amélioré de façon démontrée, perte maximale réduite.
- **C. Tendance des indices** (tout l'historique, 6 indices) : rendement amélioré de façon démontrée sur 0, perte maximale réduite de façon démontrée sur 0 — retenu pour le rendement : non ; pour le risque : non.
- **C. Tendance des indices** (avant 2000, 5 indices) : rendement amélioré de façon démontrée sur 0, perte maximale réduite de façon démontrée sur 0 — retenu pour le rendement : non ; pour le risque : non.
- **C. Tendance des indices** (2000-2012, 6 indices) : rendement amélioré de façon démontrée sur 0, perte maximale réduite de façon démontrée sur 5 — retenu pour le rendement : non ; pour le risque : oui.
- **C. Tendance des indices** (depuis 2013, 6 indices) : rendement amélioré de façon démontrée sur 0, perte maximale réduite de façon démontrée sur 0 — retenu pour le rendement : non ; pour le risque : non.
- **C. Tendance des indices** (période de test (depuis 2022), 6 indices) : rendement amélioré de façon démontrée sur 0, perte maximale réduite de façon démontrée sur 0 — retenu pour le rendement : non ; pour le risque : non.

*Calcul effectué en 19 secondes.*

---

## Journal du calcul

- **Avant tout calcul sur les vraies données** (commit 147ee9e) : pour la question A, la comparaison se fait avec les
  autres actions **classées par le même signal** le même mois (celles qui ont assez d'historique pour ce signal).
- **Premier calcul** (tâche GitHub n° 1) : erreur de lecture des données de la question C. Avec `range=max`, Yahoo a
  renvoyé un point par trimestre au lieu d'un par mois pour le S&P 500, le DAX, le Nikkei et le FTSE : la « moyenne
  10 mois » portait sur 10 trimestres et les rendements annualisés étaient faux (S&P 500 à +27,9 % par an). Corrigé
  dans le commit c2b8f0f, sans toucher au protocole : lecture de tout l'historique par dates explicites et contrôle
  qu'aucun mois ne manque. Les questions A et B, calculées sur les cours quotidiens des actions, sont identiques dans
  les deux calculs.
- **Calcul retenu** (tâche GitHub n° 2, ci-dessus). Mois lus, sans aucun mois manquant : S&P 500, Nikkei 225 et
  FTSE 100 502 mois (01/1985 à 10/2026), DAX 467 (depuis 12/1987), CAC 40 440 (depuis 03/1990), Euro Stoxx 50 236
  (depuis 03/2007). La part « avant 2000 » du S&P 500 commence donc en 1985, et non en 1928.
- Pour refaire le calcul : `python -m etudes.lancer_etude_tendances` depuis la racine du dépôt, ou la tâche GitHub
  « Étude des grandes tendances » (elle se lance à chaque pull request qui modifie `etudes/`).
