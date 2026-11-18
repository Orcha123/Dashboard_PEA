# Protocole pré-enregistré : un dividende régulier dans le passé annonce-t-il un dividende fiable ?

Ce document fixe **avant tout calcul sur les données réelles** les questions, les candidats, leurs paramètres, les
périodes, les mesures et les critères de réussite. Sa date de dépôt dans le dépôt Git (commit) en fait foi. Aucun
paramètre ne sera ajusté après avoir vu les résultats ; tout ajout ultérieur sera signalé comme exploratoire.

Objectif de l'investisseur : construire une rente à partir des dividendes. La question principale n'est donc pas
« quelle action montera ? » mais « **quel dividende sera encore là, et pas en baisse, dans les années qui viennent ?** ».

## Données

- **Actions** : les actions du catalogue Boursy (`catalogue_valeurs.py`, hors ETF), **historique le plus long
  disponible** chez Yahoo Finance : clôtures mensuelles et dividendes détachés (date de détachement et montant par
  action, ajustés des divisions d'actions). Lecture par dates explicites, avec le contrôle de la première étude :
  aucun mois manquant (en cas de trou, seuls les mois qui suivent le dernier trou sont gardés).
- **Dividende de l'année** D(a) : somme des dividendes détachés pendant l'année civile a, dans la devise de l'action.
  Seules les années civiles complètes comptent : la dernière est 2025.
- **Baisse du dividende** l'année a : D(a−1) > 0 et D(a) < 0,9 × D(a−1) (baisse de plus de 10 %, suppression
  comprise ; la marge de 10 % absorbe les petites variations).
- **Rendement total** : clôtures mensuelles et dividendes réinvestis, converti en euros pour les valeurs en dollars
  (historique mensuel EUR/USD).
- **Limites connues, non corrigeables ici** : le catalogue ne contient que des entreprises qui existent encore (biais
  du survivant, qui sous-estime le risque de baisse, surtout pour les entreprises fragiles) ; les données de
  dividendes de Yahoo peuvent être incomplètes ou contenir des erreurs ; un dividende exceptionnel fait apparaître une
  « baisse » l'année suivante, et un versement décalé de décembre à janvier peut faire de même ; pas d'historique des
  bénéfices ni du taux de distribution (celui du catalogue est une valeur d'aujourd'hui, inutilisable sur le passé).

## Dates de décision et périodes

- Une décision par an, au 31 décembre de l'année a, avec uniquement les données connues à cette date.
- **Actions retenues l'année a** : clôtures mensuelles disponibles depuis janvier de l'année a−5 au moins (pour
  qu'une année sans dividende ne soit pas un simple manque de données) et dividende versé l'année a (D(a) > 0).
  Une année n'est étudiée que si au moins 10 actions sont retenues.
- **Période de conception** : décisions jusqu'au 31/12/2014. **Période de test** : décisions du 31/12/2015 au
  31/12/2024 (2022 au plus tard pour les mesures sur 3 ans). Le verdict se fonde sur la période de test ; la période
  de conception sert seulement à vérifier que le résultat va dans le même sens.

## Candidats (paramètres fixés)

| Candidat | Définition au 31 décembre de l'année a | Groupe étudié |
| --- | --- | --- |
| R Régularité | Dividende versé chaque année de a−4 à a, sans aucune baisse ces 5 années | Les actions régulières |
| G Croissance | Croissance annuelle moyenne du dividende de a−5 à a (si D(a−5) > 0) | Les 20 % les plus fortes |
| H Rendement élevé | D(a) / clôture de décembre de l'année a | Les 20 % les plus élevés |
| Q Rendement anormal | Rendement H divisé par la médiane de ses rendements de fin d'année de a−5 à a−1 (si elle est > 0) | Les 20 % les plus élevés |
| S Solide | R, et D(a) ≥ D(a−5), et rendement H hors des 20 % les plus élevés | Les actions « solides » |

Chaque groupe est comparé aux **autres actions retenues la même année** (pour G, H et Q : celles pour lesquelles le
candidat est défini).

## Mesures

Pour chaque candidat, écart moyen entre le groupe et les autres actions retenues la même année, avec une fourchette à
95 % (regroupement par année avec Newey-West jusqu'à l'horizon moins un mois, et par action :
`ecart_vs_autres_actions_du_mois`, comme dans la première étude) :

1. **Baisse du dividende dans les 3 années suivantes** (au moins une baisse de a+1 à a+3) — **mesure principale** ;
2. **Rendement total sur 36 mois** (fin a → fin a+3, en euros) ;
3. **Perte maximale sur ces 36 mois** (baisse la plus forte depuis un sommet, rendement total).

Mesures complémentaires, sans critère : baisse du dividende l'année suivante, rendement total sur 12 mois, croissance
du dividende sur 3 ans (D(a+3) / D(a) − 1), taux de baisse du dividende de chaque année (toutes les actions retenues),
et taux absolus de baisse dans chaque groupe.

## Critères de réussite

Fourchettes **corrigées pour les 15 essais** (5 candidats × 3 mesures, correction de Bonferroni : 2,94 erreurs-types
au lieu de 1,96), sur la période de test, avec le même signe sur la période de conception :

- **Dividende plus fiable** (R, G, S) : écart de la mesure 1 entièrement en dessous de zéro.
- **Signal d'alerte** (H, Q) : écart de la mesure 1 entièrement au-dessus de zéro.
- **Rendement** : « plus élevé » ou « plus faible » démontré si la fourchette de la mesure 2 est entièrement au-dessus
  ou en dessous de zéro ; sinon « pas de différence démontrée ».
- **Risque** : « perte plus faible » démontrée si la fourchette de la mesure 3 est entièrement en dessous de zéro.

## Ce qui sera fait du résultat

- **Score de solidité du dividende dans Boursy** : ajouté si S remplit « dividende plus fiable » sans rendement
  démontré plus faible ; à défaut, si R le remplit aux mêmes conditions (R sert alors de score). Il sera présenté avec
  les taux de baisse mesurés et leurs fourchettes, sans promesse de rendement.
- **Alerte « rendement élevé, risque de baisse »** : ajoutée si H (ou Q) remplit « signal d'alerte ».
- **Projection de rente prudente** : si un score est ajouté, elle utilisera les taux de baisse et la croissance du
  dividende mesurés ici, pas des hypothèses favorables.
- Sinon, le rapport le dira tel quel, et rien ne sera ajouté à l'application.
- Le rapport complet (`etudes/resultats_dividendes.md`) publiera tous les résultats, favorables ou non.

## Ce qui est attendu d'après la recherche publiée (écrit avant les calculs)

- Les entreprises lissent leurs dividendes et ne les baissent qu'à contrecœur (Lintner, 1956) : R et S devraient
  connaître nettement moins de baisses que les autres.
- Un rendement très élevé reflète souvent une baisse attendue par le marché : H et Q devraient en connaître davantage.
- Pour le rendement total, pas de différence nette attendue ; une perte maximale un peu plus faible pour S est
  possible.
- Années de baisses massives attendues : 2009 (crise financière) et 2020 (pandémie, dividendes des banques suspendus
  à la demande des autorités).
