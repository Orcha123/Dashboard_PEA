# Protocole pré-enregistré : peut-on anticiper les grandes tendances à 6 et 12 mois ?

Ce document fixe **avant tout calcul sur les données réelles** les questions, les candidats, leurs paramètres, les
périodes, les mesures et les critères de réussite. Sa date de dépôt dans le dépôt Git (commit) en fait foi. Aucun
paramètre ne sera ajusté après avoir vu les résultats ; tout ajout ultérieur sera signalé comme exploratoire.

## Données

- **Actions** : les actions du catalogue Boursy (`catalogue_valeurs.py`, hors ETF), historique quotidien sur 10 ans de
  Yahoo Finance, dividendes compris, séances closes uniquement. Les performances sont converties en euros pour les
  valeurs en dollars (historique EUR/USD).
- **Indices** (grandes tendances de marché, historique le plus long disponible, données mensuelles) : S&P 500
  (`^GSPC`), CAC 40 (`^FCHI`), DAX (`^GDAXI`), Euro Stoxx 50 (`^STOXX50E`), Nikkei 225 (`^N225`), FTSE 100 (`^FTSE`).
  Ce sont des indices de prix, sans dividendes.
- **Limites connues, non corrigeables ici** : le catalogue ne contient que des entreprises qui existent encore
  (biais du survivant) ; pas d'historique des bénéfices ni des valorisations ; liquidités rémunérées à 0 % quand une
  règle sort du marché (hypothèse prudente, défavorable aux règles de tendance).

## Dates de décision et périodes

- Une décision par mois, au dernier cours connu de chaque fin de mois, avec uniquement les données disponibles à
  cette date.
- **Période de conception** : décisions prises avant le 1er janvier 2022. **Période de test** : décisions prises à
  partir du 1er janvier 2022. Le verdict se fonde sur la période de test ; la période de conception sert seulement à
  vérifier que le résultat va dans le même sens.

## Question A — Sélection : quelles actions feront mieux que les autres sur 6 et 12 mois ?

Chaque mois, les actions sont classées selon chaque signal ; les 20 % les mieux classées forment le groupe « haut »,
les 20 % les moins bien classées le groupe « bas ».

| Signal | Définition (paramètres fixés) |
| --- | --- |
| S1 Momentum 12-1 | Performance (dividendes compris) entre il y a 12 mois et il y a 1 mois |
| S2 Tendance | Dernier cours / moyenne des 200 dernières clôtures − 1 |
| S3 Faible volatilité | Opposé de la volatilité des rendements quotidiens des 252 dernières séances |
| S4 Retournement long | Opposé de la performance des 36 derniers mois (les plus fortes baisses en tête) |
| S5 Combiné | Moyenne des rangs centiles de S1, S3 et du rendement du dividende sur 12 mois |

**Mesure** : écart moyen entre la performance du groupe « haut » sur 6 et 12 mois et celle des autres actions du même
mois, avec une fourchette à 95 % (regroupement par mois avec Newey-West jusqu'à l'horizon moins un mois, et par
action : `ecart_vs_autres_actions_du_mois`, déjà calibrée par simulation). Même mesure pour le groupe « bas ».

**Critère de réussite d'un signal** : sur la période de test, l'écart du groupe « haut » à 12 mois a une fourchette
**corrigée pour les 10 essais** (5 signaux × 2 horizons, correction de Bonferroni : 2,81 erreurs-types au lieu de 1,96)
entièrement au-dessus de zéro, et l'écart a le même signe sur la période de conception.

## Question B — Suivre la tendance de chaque action (swing trading de fond)

**Règle fixée** : à chaque fin de mois, être investi sur l'action pendant le mois suivant si son dernier cours est
au-dessus de la moyenne de ses 200 dernières clôtures, sinon rester en liquidités (0 %). Coût de 0,25 % à chaque
entrée ou sortie.

**Comparaison** : la même action achetée et conservée. Portefeuille à parts égales de toutes les actions, chacune
gérée par la règle, contre le même portefeuille conservé. **Mesures** : rendement annualisé, volatilité, perte maximale
(baisse la plus forte depuis un sommet) ; écarts avec fourchettes à 95 % par rééchantillonnage par blocs de 12 mois
(2 000 tirages, graine fixée). Part des actions pour lesquelles la règle améliore le rendement et réduit la perte
maximale.

**Critères** : « améliore le rendement » si la fourchette de l'écart de rendement annualisé (règle − conservation),
sur la période de test, est entièrement au-dessus de zéro ; « réduit le risque » si la fourchette de l'écart de perte
maximale l'est aussi (perte plus faible avec la règle).

## Question C — Grandes tendances du marché (indices, historique long)

**Règle fixée** (moyenne mobile de 10 mois) : investi le mois suivant si la clôture mensuelle de l'indice est
au-dessus de la moyenne de ses 10 dernières clôtures mensuelles, sinon liquidités (0 %). Coût de 0,25 % par
changement.

**Mesures** pour chaque indice : rendement annualisé, volatilité, perte maximale, part du temps investi, contre
l'indice conservé ; fourchettes par blocs de 12 mois comme en B. Sous-périodes : avant 2000, 2000-2012, depuis 2013.
Mesure complémentaire : performance moyenne des 6 et 12 mois suivants quand l'indice est au-dessus de sa moyenne,
comparée à quand il est en dessous.

**Critères** : mêmes définitions qu'en B, appliquées à l'ensemble des indices et sous-périodes ; un résultat n'est
retenu que s'il se retrouve sur la majorité des indices.

## Ce qui est attendu d'après la recherche publiée (écrit avant les calculs)

- A : effets de momentum et de faible volatilité positifs mais modestes, instables d'une période à l'autre, et
  difficiles à démontrer sur environ 120 actions et quelques années.
- B et C : les règles de tendance réduisent surtout les grosses pertes (2008, 2020, 2022) sans améliorer
  nettement le rendement, et peuvent coûter du rendement lors des rebonds rapides.

## Ce qui sera fait du résultat

- Un signal ou une règle qui remplit ses critères pourra être proposé dans Boursy, avec ses fourchettes, et suivi
  ensuite dans le journal en direct.
- Sinon, le rapport le dira tel quel, et rien ne sera ajouté à l'application.
- Le rapport complet (`etudes/resultats_tendances.md`) publiera tous les résultats, favorables ou non.
