# Protocole pré-enregistré : suivi de la solidité des dividendes en conditions réelles

L'étude des dividendes (`etudes/protocole_dividendes.md`, résultats dans `etudes/resultats_dividendes.md`) a une limite
qu'aucun calcul sur le passé ne peut lever : le catalogue ne contient que des entreprises qui existent encore. Ce suivi
la lève en enregistrant les classements **avant** de connaître la suite, et en continuant de suivre chaque action
même si elle quitte un jour le catalogue. Ce document est déposé avant le premier enregistrement ; sa date de dépôt
dans le dépôt Git (commit) en fait foi.

## Ce qui est enregistré, et quand

- **Une fois par an**, au premier soir de bourse de janvier (nouvel essai chaque soir jusqu'à fin mars si les données
  manquent), la tâche planifiée (`journal_solidite.py`) enregistre dans la table protégée `suivi_solidite` le
  classement au 31 décembre de l'année écoulée, avec exactement les définitions de l'étude
  (`solidite_dividendes.py`) : **solide**, **neutre**, **à surveiller** (rendement élevé ou anormal), ou non classée.
- **Actions suivies** : celles du catalogue (hors ETF) au moment de l'enregistrement, plus toutes celles enregistrées
  les deux années précédentes, même si elles ont quitté le catalogue.
- **Pour chaque action** : son dividende de l'année écoulée et de l'année d'avant (par action, dans sa devise), son
  rendement au 31 décembre, ses alertes, et le seuil du rendement élevé de l'année.
- **Premier enregistrement** : janvier 2027 (classement au 31/12/2026). Personne d'autre que la tâche planifiée ne
  peut écrire dans la table, et une année enregistrée n'est jamais réécrite.

## Mesure

- Pour chaque année de classement a, et chaque horizon de 1 et 3 ans : part des actions de chaque catégorie qui ont
  baissé leur dividende de plus de 10 % (suppression comprise) au moins une fois entre a et a+1 (ou a+3), d'après les
  dividendes enregistrés les années suivantes.
- Une action dont le dividende n'a pas pu être relu une année suivante (cotation arrêtée, données absentes) est
  comptée à part, « illisible », et jamais comme une baisse ou une absence de baisse ; leur nombre est publié.
- Les définitions ne changeront pas. Si elles devaient changer, ce serait une nouvelle série, présentée séparément.

## Ce qui est attendu (d'après l'étude, période de test)

| Horizon | Solides | Autres | À surveiller (rendement élevé) | Autres |
| --- | --- | --- | --- | --- |
| 1 an | 7 % | 15 % | 26 % | 8 % |
| 3 ans | 22 % | 43 % | 58 % | 26 % |

## Quand conclure

- Premier résultat à 1 an : janvier 2028. Premier résultat à 3 ans : janvier 2030.
- Avant trois années de classement mesurées à 3 ans (janvier 2032), les résultats sont affichés comme provisoires :
  une seule année de crise, ou de calme, peut tout changer.
- Le score sera confirmé si, sur les classements mesurés, les solides baissent moins souvent leur dividende que les
  neutres et les actions à surveiller, et les actions à surveiller plus souvent que les solides, comme dans l'étude.
  Sinon, Boursy le dira, et le volet « Solidité des dividendes » l'affichera.
