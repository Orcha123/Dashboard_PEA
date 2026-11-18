"""
Étude des grandes tendances à 6 et 12 mois : calculs (sans réseau ni Streamlit).

Met en œuvre exactement le protocole pré-enregistré etudes/protocole_tendances.md :
- question A : sélection des actions par 5 signaux (groupes « haut » et « bas » à 20 %), écart avec les autres
  actions du même mois sur 6 et 12 mois ;
- question B : règle de tendance par action (investi si cours > moyenne 200 jours), contre la conservation ;
- question C : règle de tendance sur les indices (moyenne 10 mois), contre la conservation.
Toutes les décisions n'utilisent que les données connues à leur date.
"""
import bisect
import math
import random
from datetime import date, timedelta

from carnet_decisions import ajouter_mois, performance_entre
from moteur_signaux import ecart_vs_autres_actions_du_mois

DEBUT_TEST = "2022-01-01"
HORIZONS = (6, 12)
SIGNAUX = {
    "S1": "Momentum 12-1",
    "S2": "Tendance (cours / moyenne 200 j)",
    "S3": "Faible volatilité",
    "S4": "Retournement long (36 mois)",
    "S5": "Combiné (momentum, faible volatilité, dividende)",
}
PART_GROUPE = 0.20
MINIMUM_ACTIONS_PAR_MOIS = 10
Z_95 = 1.96
Z_BONFERRONI = 2.807  # 10 essais (5 signaux x 2 horizons) : seuil bilatéral 0,05 / 10
COUT_CHANGEMENT = 0.0025
TIRAGES_BOOTSTRAP = 2000
BLOC_BOOTSTRAP = 12
GRAINE = 20261118
SOUS_PERIODES_INDICES = (("avant 2000", None, "2000-01-01"), ("2000-2012", "2000-01-01", "2013-01-01"), ("depuis 2013", "2013-01-01", None))


# ==============================================================================
# OUTILS
# ==============================================================================
def fins_de_mois(premier, dernier):
    """Derniers jours calendaires de chaque mois entre deux dates (ISO), inclus."""
    jour = date.fromisoformat(str(premier)[:10])
    fin = date.fromisoformat(str(dernier)[:10])
    resultat = []
    courant = date(jour.year, jour.month, 1)
    while True:
        suivant = date(courant.year + (courant.month == 12), courant.month % 12 + 1, 1)
        dernier_jour = suivant - timedelta(days=1)
        if dernier_jour > fin:
            return resultat
        if dernier_jour >= jour:
            resultat.append(dernier_jour.isoformat())
        courant = suivant


def rang_au(historique, jour_iso):
    """Dernière séance close au plus tard à cette date, à moins de 7 jours ; None sinon."""
    dates = historique[0]
    rang = bisect.bisect_right(dates, str(jour_iso)[:10]) - 1
    if rang < 0 or (date.fromisoformat(str(jour_iso)[:10]) - date.fromisoformat(dates[rang])).days > 7:
        return None
    return rang


def performance_en_euros(historique, change, devise, debut, fin):
    """Performance dividendes compris entre deux dates, convertie en euros pour une valeur en dollars."""
    perf = performance_entre(historique, debut, fin)
    if perf is None or devise != "USD":
        return perf
    variation_dollar = performance_entre(change, debut, fin) if change else None
    if variation_dollar is None:
        return None
    return (1.0 + perf) / (1.0 + variation_dollar) - 1.0


def rangs_centiles(valeurs):
    """{clé: rang centile entre 0 et 1} (moyenne des rangs en cas d'égalité)."""
    ordonnes = sorted(valeurs.items(), key=lambda kv: kv[1])
    n, resultat, i = len(ordonnes), {}, 0
    while i < n:
        j = i
        while j + 1 < n and ordonnes[j + 1][1] == ordonnes[i][1]:
            j += 1
        for k in range(i, j + 1):
            resultat[ordonnes[k][0]] = ((i + j) / 2.0) / (n - 1) if n > 1 else 0.5
        i = j + 1
    return resultat


# ==============================================================================
# QUESTION A : SÉLECTION
# ==============================================================================
def signaux_a_la_date(historique, change, devise, jour):
    """Valeurs brutes des signaux à une date (None si l'historique est trop court), avec les seules données connues."""
    rang = rang_au(historique, jour)
    if rang is None:
        return None
    dates, clotures, dividendes = historique[0], historique[1], historique[2]
    debut_historique = dates[0]
    valeurs = {}
    il_y_a_12_mois, il_y_a_1_mois, il_y_a_36_mois = ajouter_mois(jour, -12), ajouter_mois(jour, -1), ajouter_mois(jour, -36)
    if debut_historique <= il_y_a_12_mois.isoformat():
        valeurs["S1"] = performance_en_euros(historique, change, devise, il_y_a_12_mois, il_y_a_1_mois)
    if rang >= 199:
        moyenne_200 = sum(clotures[rang - 199:rang + 1]) / 200.0
        valeurs["S2"] = clotures[rang] / moyenne_200 - 1.0
    if rang >= 252:
        rendements = [clotures[i] / clotures[i - 1] - 1.0 for i in range(rang - 251, rang + 1)]
        moyenne = sum(rendements) / len(rendements)
        valeurs["S3"] = -math.sqrt(sum((r - moyenne) ** 2 for r in rendements) / (len(rendements) - 1))
    if debut_historique <= il_y_a_36_mois.isoformat():
        perf_36 = performance_en_euros(historique, change, devise, il_y_a_36_mois, jour)
        valeurs["S4"] = -perf_36 if perf_36 is not None else None
    un_an_avant = (date.fromisoformat(jour) - timedelta(days=365)).isoformat()
    if debut_historique <= un_an_avant:
        valeurs["rendement_dividende"] = sum(m for d, m in dividendes if un_an_avant < d <= dates[rang]) / clotures[rang]
    return {k: v for k, v in valeurs.items() if v is not None}


def observations_selection(historiques, change, devises, fins_mois):
    """
    Une observation par action et par fin de mois : signaux S1 à S5 classés en groupes « HAUT » / « BAS » / « MILIEU »
    (clés decision_S1...), performances des 6 et 12 mois suivants (r6, r12, en euros, dividendes compris).
    """
    observations = []
    for jour in fins_mois:
        du_mois = []
        for nom, historique in historiques.items():
            signaux = signaux_a_la_date(historique, change, devises.get(nom, "EUR"), jour)
            if not signaux:
                continue
            obs = {"date": jour, "action": nom, "signaux": signaux}
            for h in HORIZONS:
                obs[f"r{h}"] = performance_en_euros(historique, change, devises.get(nom, "EUR"), jour, ajouter_mois(jour, h))
            du_mois.append(obs)
        # S5 : moyenne des rangs centiles de S1, S3 et du rendement du dividende (actions qui ont les trois)
        complets = {o["action"]: o for o in du_mois if all(k in o["signaux"] for k in ("S1", "S3", "rendement_dividende"))}
        if len(complets) >= MINIMUM_ACTIONS_PAR_MOIS:
            rangs = [rangs_centiles({a: o["signaux"][k] for a, o in complets.items()}) for k in ("S1", "S3", "rendement_dividende")]
            for action, o in complets.items():
                o["signaux"]["S5"] = sum(r[action] for r in rangs) / 3.0
        for signal in SIGNAUX:
            valeurs = {o["action"]: o["signaux"][signal] for o in du_mois if signal in o["signaux"]}
            if len(valeurs) < MINIMUM_ACTIONS_PAR_MOIS:
                continue
            ordre = sorted(valeurs, key=lambda a: valeurs[a])
            taille = max(1, int(round(len(ordre) * PART_GROUPE)))
            bas, haut = set(ordre[:taille]), set(ordre[-taille:])
            for o in du_mois:
                if o["action"] in valeurs:
                    o[f"decision_{signal}"] = "HAUT" if o["action"] in haut else ("BAS" if o["action"] in bas else "MILIEU")
        observations.extend(du_mois)
    return observations


def mesurer_selection(observations):
    """Écarts des groupes « haut » et « bas » par signal, horizon et période, avec fourchettes 95 % et corrigées."""
    periodes = {
        "conception": [o for o in observations if o["date"] < DEBUT_TEST],
        "test": [o for o in observations if o["date"] >= DEBUT_TEST],
        "tout": observations,
    }
    resultats = {}
    for signal in SIGNAUX:
        for h in HORIZONS:
            for groupe in ("HAUT", "BAS"):
                for periode, obs in periodes.items():
                    # comparaison avec les autres actions classées par ce signal le même mois
                    classees = [o for o in obs if f"decision_{signal}" in o]
                    r = ecart_vs_autres_actions_du_mois(classees, groupe, f"r{h}", h, cle_decision=f"decision_{signal}")
                    if r and r["bas"] is not None:
                        erreur_type = (r["haut"] - r["bas"]) / (2 * Z_95)
                        r = dict(r, bas_corrige=r["moyenne"] - Z_BONFERRONI * erreur_type, haut_corrige=r["moyenne"] + Z_BONFERRONI * erreur_type)
                    resultats[(signal, h, groupe, periode)] = r
    return resultats


def verdict_selection(resultats):
    """Critère pré-enregistré : test, groupe haut, 12 mois, fourchette corrigée > 0 et même signe en conception."""
    verdicts = {}
    for signal in SIGNAUX:
        test = resultats.get((signal, 12, "HAUT", "test"))
        conception = resultats.get((signal, 12, "HAUT", "conception"))
        verdicts[signal] = bool(test and test.get("bas_corrige") is not None and test["bas_corrige"] > 0
                                and conception and conception["moyenne"] > 0)
    return verdicts


# ==============================================================================
# QUESTIONS B ET C : RÈGLES DE TENDANCE
# ==============================================================================
def statistiques(rendements_mensuels):
    """Rendement annualisé, volatilité annualisée et perte maximale (positive) d'une suite de rendements mensuels."""
    if not rendements_mensuels:
        return None
    richesse, sommet, perte_max = 1.0, 1.0, 0.0
    for r in rendements_mensuels:
        richesse *= 1.0 + r
        sommet = max(sommet, richesse)
        perte_max = max(perte_max, 1.0 - richesse / sommet)
    n = len(rendements_mensuels)
    moyenne = sum(rendements_mensuels) / n
    volatilite = math.sqrt(sum((r - moyenne) ** 2 for r in rendements_mensuels) / (n - 1)) * math.sqrt(12) if n > 1 else 0.0
    return {"rendement_annualise": richesse ** (12.0 / n) - 1.0, "volatilite": volatilite, "perte_maximale": perte_max, "mois": n}


def appliquer_regle(rendements, positions, cout=COUT_CHANGEMENT):
    """
    Rendements de la règle : positions[i] (0 ou 1, décidée en fin du mois i-1 avec les données connues) appliquée au
    rendement du mois i, moins le coût à chaque changement de position (départ : investi, sans coût).
    """
    resultat, precedente = [], 1
    for r, p in zip(rendements, positions):
        resultat.append(p * r - (cout if p != precedente else 0.0))
        precedente = p
    return resultat


def comparer_avec_fourchettes(regle, conservation, graine=GRAINE):
    """Statistiques des deux suites et écarts (règle - conservation) avec fourchettes 95 % par blocs de 12 mois."""
    stats_regle, stats_conservation = statistiques(regle), statistiques(conservation)
    n = len(regle)
    hasard = random.Random(graine)
    ecarts_rendement, ecarts_perte = [], []
    if n >= 2 * BLOC_BOOTSTRAP:
        for _ in range(TIRAGES_BOOTSTRAP):
            indices = []
            while len(indices) < n:
                debut = hasard.randrange(0, n - BLOC_BOOTSTRAP + 1)
                indices.extend(range(debut, debut + BLOC_BOOTSTRAP))
            indices = indices[:n]
            a, b = statistiques([regle[i] for i in indices]), statistiques([conservation[i] for i in indices])
            ecarts_rendement.append(a["rendement_annualise"] - b["rendement_annualise"])
            ecarts_perte.append(b["perte_maximale"] - a["perte_maximale"])  # positif = perte plus faible avec la règle

    def _fourchette(valeurs):
        if not valeurs:
            return None, None
        valeurs = sorted(valeurs)
        return valeurs[int(0.025 * len(valeurs))], valeurs[int(0.975 * len(valeurs)) - 1]

    return {
        "regle": stats_regle,
        "conservation": stats_conservation,
        "ecart_rendement": stats_regle["rendement_annualise"] - stats_conservation["rendement_annualise"],
        "fourchette_rendement": _fourchette(ecarts_rendement),
        "reduction_perte": stats_conservation["perte_maximale"] - stats_regle["perte_maximale"],
        "fourchette_perte": _fourchette(ecarts_perte),
    }


def series_regle_actions(historiques, change, devises, fins_mois):
    """
    Question B. Pour chaque action : rendements mensuels (euros, dividendes compris) et position décidée en fin de mois
    précédent (cours > moyenne des 200 dernières clôtures). Renvoie {action: [(fin du mois, rendement, position)]}.
    """
    series = {}
    for nom, historique in historiques.items():
        devise, lignes = devises.get(nom, "EUR"), []
        for debut, fin in zip(fins_mois[:-1], fins_mois[1:]):
            rang = rang_au(historique, debut)
            if rang is None or rang < 199:
                continue
            r = performance_en_euros(historique, change, devise, debut, fin)
            if r is None:
                continue
            clotures = historique[1]
            position = 1 if clotures[rang] > sum(clotures[rang - 199:rang + 1]) / 200.0 else 0
            lignes.append((fin, r, position))
        if lignes:
            series[nom] = lignes
    return series


def portefeuilles_regle_actions(series, debut=None, fin=None):
    """Portefeuilles à parts égales, mois par mois : (rendements conservation, rendements règle) sur la période."""
    par_mois = {}
    for lignes in series.values():
        regle = appliquer_regle([r for _, r, _ in lignes], [p for _, _, p in lignes])
        for (mois, r, _), r_regle in zip(lignes, regle):
            if (debut is None or mois >= debut) and (fin is None or mois < fin):
                par_mois.setdefault(mois, []).append((r, r_regle))
    mois_retenus = sorted(m for m, v in par_mois.items() if len(v) >= MINIMUM_ACTIONS_PAR_MOIS)
    conservation = [sum(r for r, _ in par_mois[m]) / len(par_mois[m]) for m in mois_retenus]
    regle = [sum(r for _, r in par_mois[m]) / len(par_mois[m]) for m in mois_retenus]
    return conservation, regle, mois_retenus


def parts_actions_ameliorees(series, debut=None):
    """Part des actions pour lesquelles la règle améliore le rendement annualisé, et réduit la perte maximale."""
    meilleures_rendement = meilleures_perte = total = 0
    for lignes in series.values():
        lignes = [l for l in lignes if debut is None or l[0] >= debut]
        if len(lignes) < 24:
            continue
        conservation = [r for _, r, _ in lignes]
        regle = appliquer_regle(conservation, [p for _, _, p in lignes])
        a, b = statistiques(regle), statistiques(conservation)
        total += 1
        meilleures_rendement += a["rendement_annualise"] > b["rendement_annualise"]
        meilleures_perte += a["perte_maximale"] < b["perte_maximale"]
    return {"actions": total, "rendement": meilleures_rendement / total if total else None,
            "perte": meilleures_perte / total if total else None}


def regle_indice(dates_mensuelles, clotures_mensuelles, fenetre=10):
    """
    Question C. Rendements mensuels de l'indice et positions (clôture > moyenne des `fenetre` dernières clôtures
    mensuelles, décidée en fin de mois précédent). Renvoie [(mois, rendement, position)].
    """
    lignes = []
    for i in range(fenetre - 1, len(clotures_mensuelles) - 1):
        moyenne = sum(clotures_mensuelles[i - fenetre + 1:i + 1]) / fenetre
        position = 1 if clotures_mensuelles[i] > moyenne else 0
        lignes.append((dates_mensuelles[i + 1], clotures_mensuelles[i + 1] / clotures_mensuelles[i] - 1.0, position))
    return lignes


def rendements_suivants_selon_signal(dates_mensuelles, clotures_mensuelles, horizon, fenetre=10, graine=GRAINE):
    """Performance moyenne des `horizon` mois suivants quand l'indice est au-dessus / en dessous de sa moyenne."""
    au_dessus, en_dessous, paires = [], [], []
    for i in range(fenetre - 1, len(clotures_mensuelles) - horizon):
        moyenne = sum(clotures_mensuelles[i - fenetre + 1:i + 1]) / fenetre
        suite = clotures_mensuelles[i + horizon] / clotures_mensuelles[i] - 1.0
        signal = clotures_mensuelles[i] > moyenne
        (au_dessus if signal else en_dessous).append(suite)
        paires.append((signal, suite))
    if not au_dessus or not en_dessous:
        return None
    ecart = sum(au_dessus) / len(au_dessus) - sum(en_dessous) / len(en_dessous)
    hasard, ecarts, n = random.Random(graine), [], len(paires)
    if n >= 2 * BLOC_BOOTSTRAP:
        for _ in range(TIRAGES_BOOTSTRAP):
            echantillon = []
            while len(echantillon) < n:
                debut = hasard.randrange(0, n - BLOC_BOOTSTRAP + 1)
                echantillon.extend(paires[debut:debut + BLOC_BOOTSTRAP])
            haut = [s for sig, s in echantillon[:n] if sig]
            bas = [s for sig, s in echantillon[:n] if not sig]
            if haut and bas:
                ecarts.append(sum(haut) / len(haut) - sum(bas) / len(bas))
    ecarts.sort()
    return {"au_dessus": sum(au_dessus) / len(au_dessus), "en_dessous": sum(en_dessous) / len(en_dessous),
            "mois_au_dessus": len(au_dessus), "mois_en_dessous": len(en_dessous), "ecart": ecart,
            "fourchette": (ecarts[int(0.025 * len(ecarts))], ecarts[int(0.975 * len(ecarts)) - 1]) if ecarts else (None, None)}
