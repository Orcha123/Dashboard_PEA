"""
Étude des dividendes : un dividende régulier dans le passé annonce-t-il un dividende fiable ? (sans réseau ni Streamlit)

Met en œuvre exactement le protocole pré-enregistré etudes/protocole_dividendes.md. Une décision par an, au 31 décembre,
avec les seules données connues à cette date ; chaque groupe est comparé aux autres actions retenues la même année.

Une « série » décrit une action : {"mois": ["AAAA-MM", ...] consécutifs, "clotures": [...], "dividendes": [(date ISO,
montant)]}. Le change est un dictionnaire {"AAAA-MM": dollars pour 1 euro en fin de mois}.
"""
from moteur_signaux import ecart_vs_autres_actions_du_mois

SEUIL_BAISSE = 0.9  # baisse : dividende de l'année < 90 % de celui de l'année précédente
DERNIERE_ANNEE = 2025  # dernière année civile complète
FIN_CONCEPTION = 2014
DEBUT_TEST, FIN_TEST = 2015, 2024
ANNEES_HISTORIQUE = 5
PART_GROUPE = 0.20
MINIMUM_ACTIONS = 10
Z_95 = 1.96
Z_BONFERRONI = 2.935  # 15 essais (5 candidats x 3 mesures) : seuil bilatéral 0,05 / 15

CANDIDATS = {
    "R": "Régularité (5 ans sans baisse)",
    "G": "Croissance du dividende (5 ans)",
    "H": "Rendement élevé",
    "Q": "Rendement anormal (vs ses 5 dernières années)",
    "S": "Solide (régulier, en hausse sur 5 ans, rendement non extrême)",
}
CANDIDATS_FIABILITE = ("R", "G", "S")
CANDIDATS_ALERTE = ("H", "Q")
# mesure -> horizon en mois
MESURES = {"baisse_3_ans": 36, "rendement_36_mois": 36, "perte_36_mois": 36}
COMPLEMENTS = {"baisse_1_an": 12, "rendement_12_mois": 12, "croissance_dividende_3_ans": 36}
# ajouté après le premier calcul, signalé comme exploratoire : baisse « durable », qui ne se contente pas d'effacer la
# hausse de l'année précédente (dividende exceptionnel, versement décalé d'une année civile à l'autre)
EXPLORATOIRES = {"baisse_durable_3_ans": 36}


# ==============================================================================
# OUTILS
# ==============================================================================
def dividendes_par_annee(dividendes):
    """{année: somme des dividendes détachés pendant l'année civile}."""
    par_annee = {}
    for jour, montant in dividendes:
        annee = int(jour[:4])
        par_annee[annee] = par_annee.get(annee, 0.0) + float(montant)
    return par_annee


def est_baisse(precedent, courant):
    """Baisse de plus de 10 % (suppression comprise) d'un dividende qui était versé."""
    return precedent > 0 and courant < SEUIL_BAISSE * precedent


def est_baisse_durable(d, annee):
    """
    Baisse de plus de 10 % par rapport aux DEUX années précédentes (à la plus faible des deux, si les deux étaient
    versées) : un dividende exceptionnel ou un versement décalé d'une année civile à l'autre n'en est pas une.
    """
    precedent, avant = d.get(annee - 1, 0.0), d.get(annee - 2, 0.0)
    base = min(precedent, avant) if avant > 0 else precedent
    return precedent > 0 and d.get(annee, 0.0) < SEUIL_BAISSE * base


def preparer_serie(mois, clotures, dividendes):
    """Série prête pour les calculs : index des mois, dividendes par année et par mois."""
    par_mois = {}
    for jour, montant in dividendes:
        par_mois[jour[:7]] = par_mois.get(jour[:7], 0.0) + float(montant)
    return {
        "mois": list(mois), "clotures": list(clotures), "dividendes": list(dividendes),
        "rang": {m: i for i, m in enumerate(mois)},
        "par_annee": dividendes_par_annee(dividendes),
        "par_mois": par_mois,
    }


def dividende(serie, annee):
    return serie["par_annee"].get(annee, 0.0)


def cloture_fin_annee(serie, annee):
    rang = serie["rang"].get(f"{annee}-12")
    return serie["clotures"][rang] if rang is not None else None


def couverte_depuis(serie, mois):
    """Clôtures disponibles sans trou depuis ce mois (inclus) au moins."""
    return bool(serie["mois"]) and serie["mois"][0] <= mois


# ==============================================================================
# CANDIDATS (au 31 décembre de l'année de décision)
# ==============================================================================
def caracteristiques(serie, annee):
    """
    Valeurs des candidats R, G, H, Q pour une action retenue l'année de décision, None si elle n'est pas retenue
    (historique insuffisant, pas de dividende cette année-là, ou année non terminée).
    S dépend du classement de H parmi les actions de l'année : il est calculé dans observations_dividendes.
    """
    if annee > DERNIERE_ANNEE or not couverte_depuis(serie, f"{annee - ANNEES_HISTORIQUE}-01"):
        return None
    cloture = cloture_fin_annee(serie, annee)
    d = {a: dividende(serie, a) for a in range(annee - ANNEES_HISTORIQUE, annee + 1)}
    if cloture is None or cloture <= 0 or d[annee] <= 0:
        return None
    reguliere = all(d[a] > 0 and not est_baisse(d[a - 1], d[a]) for a in range(annee - 4, annee + 1))
    valeurs = {"R": reguliere, "H": d[annee] / cloture, "hausse_5_ans": d[annee] >= d[annee - 5]}
    if d[annee - 5] > 0:
        valeurs["G"] = (d[annee] / d[annee - 5]) ** (1.0 / ANNEES_HISTORIQUE) - 1.0
    rendements_passes = []
    for a in range(annee - 5, annee):
        cloture_a = cloture_fin_annee(serie, a)
        if cloture_a is None or cloture_a <= 0:
            break
        rendements_passes.append(d[a] / cloture_a)
    if len(rendements_passes) == 5:
        mediane = sorted(rendements_passes)[2]
        if mediane > 0:
            valeurs["Q"] = valeurs["H"] / mediane
    return valeurs


# ==============================================================================
# MESURES SUIVANTES
# ==============================================================================
def rendements_mensuels(serie, change, devise, premier_mois, nombre):
    """Rendements totaux mensuels (dividendes réinvestis, en euros) des `nombre` mois depuis premier_mois ; None si absent."""
    rang = serie["rang"].get(premier_mois)
    if rang is None or rang < 1 or rang + nombre > len(serie["mois"]):
        return None
    resultat = []
    for i in range(rang, rang + nombre):
        mois, precedent = serie["mois"][i], serie["mois"][i - 1]
        r = (serie["clotures"][i] + serie["par_mois"].get(mois, 0.0)) / serie["clotures"][i - 1]
        if devise == "USD":
            if not change or change.get(mois) is None or change.get(precedent) is None:
                return None
            r *= change[precedent] / change[mois]
        resultat.append(r - 1.0)
    return resultat


def rendement_et_perte(rendements):
    """(rendement cumulé, perte maximale positive depuis un sommet) d'une suite de rendements mensuels."""
    richesse, sommet, perte = 1.0, 1.0, 0.0
    for r in rendements:
        richesse *= 1.0 + r
        sommet = max(sommet, richesse)
        perte = max(perte, 1.0 - richesse / sommet)
    return richesse - 1.0, perte


def mesures_suivantes(serie, change, devise, annee):
    """Mesures des années qui suivent la décision (absentes si les données ne couvrent pas l'horizon)."""
    resultat = {}
    d = {a: dividende(serie, a) for a in range(annee - 1, annee + 4)}
    if annee + 1 <= DERNIERE_ANNEE:
        resultat["baisse_1_an"] = 1.0 if est_baisse(d[annee], d[annee + 1]) else 0.0
    if annee + 3 <= DERNIERE_ANNEE:
        resultat["baisse_3_ans"] = 1.0 if any(est_baisse(d[a - 1], d[a]) for a in range(annee + 1, annee + 4)) else 0.0
        resultat["croissance_dividende_3_ans"] = d[annee + 3] / d[annee] - 1.0
        resultat["baisse_durable_3_ans"] = 1.0 if any(est_baisse_durable(d, a) for a in range(annee + 1, annee + 4)) else 0.0
        rendements = rendements_mensuels(serie, change, devise, f"{annee + 1}-01", 36)
        if rendements is not None:
            resultat["rendement_36_mois"], resultat["perte_36_mois"] = rendement_et_perte(rendements)
    if annee + 1 <= DERNIERE_ANNEE:
        rendements = rendements_mensuels(serie, change, devise, f"{annee + 1}-01", 12)
        if rendements is not None:
            resultat["rendement_12_mois"] = rendement_et_perte(rendements)[0]
    return resultat


# ==============================================================================
# OBSERVATIONS ET GROUPES
# ==============================================================================
def _plus_hauts(valeurs):
    """Les 20 % de valeurs les plus élevées (égalités départagées par le nom, pour un résultat reproductible)."""
    ordre = sorted(valeurs, key=lambda nom: (valeurs[nom], nom))
    taille = max(1, int(round(len(ordre) * PART_GROUPE)))
    return set(ordre[-taille:])


def observations_dividendes(series, change, devises, annees):
    """
    Une observation par action retenue et par année de décision : candidats, groupes (decision_X = « HAUT » pour le
    groupe étudié, « AUTRE » sinon ; absent si le candidat n'est pas défini) et mesures suivantes.
    """
    observations = []
    for annee in annees:
        de_l_annee = []
        for nom, serie in series.items():
            valeurs = caracteristiques(serie, annee)
            if valeurs is None:
                continue
            obs = {"date": f"{annee}-12-31", "annee": annee, "action": nom, "valeurs": valeurs}
            obs.update(mesures_suivantes(serie, change, devises.get(nom, "EUR"), annee))
            de_l_annee.append(obs)
        if len(de_l_annee) < MINIMUM_ACTIONS:
            continue
        hauts = {}
        for candidat in ("G", "H", "Q"):
            valeurs = {o["action"]: o["valeurs"][candidat] for o in de_l_annee if candidat in o["valeurs"]}
            if len(valeurs) >= MINIMUM_ACTIONS:
                hauts[candidat] = _plus_hauts(valeurs)
                for o in de_l_annee:
                    if o["action"] in valeurs:
                        o[f"decision_{candidat}"] = "HAUT" if o["action"] in hauts[candidat] else "AUTRE"
        for o in de_l_annee:
            o["decision_R"] = "HAUT" if o["valeurs"]["R"] else "AUTRE"
            if "H" in hauts:
                solide = o["valeurs"]["R"] and o["valeurs"]["hausse_5_ans"] and o["action"] not in hauts["H"]
                o["decision_S"] = "HAUT" if solide else "AUTRE"
        observations.extend(de_l_annee)
    return observations


def periode(observations, nom):
    if nom == "conception":
        return [o for o in observations if o["annee"] <= FIN_CONCEPTION]
    if nom == "test":
        return [o for o in observations if DEBUT_TEST <= o["annee"] <= FIN_TEST]
    return list(observations)


# ==============================================================================
# MESURE DES ÉCARTS ET VERDICTS
# ==============================================================================
def mesurer(observations):
    """Écart groupe - autres actions de la même année, par candidat, mesure et période, avec fourchettes 95 % et corrigées."""
    resultats = {}
    for nom_periode in ("conception", "test", "tout"):
        obs = periode(observations, nom_periode)
        for candidat in CANDIDATS:
            classees = [o for o in obs if f"decision_{candidat}" in o]
            for cle, horizon in {**MESURES, **COMPLEMENTS, **EXPLORATOIRES}.items():
                r = ecart_vs_autres_actions_du_mois(classees, "HAUT", cle, horizon, cle_decision=f"decision_{candidat}")
                if r and r["bas"] is not None:
                    erreur_type = (r["haut"] - r["bas"]) / (2 * Z_95)
                    r = dict(r, bas_corrige=r["moyenne"] - Z_BONFERRONI * erreur_type,
                             haut_corrige=r["moyenne"] + Z_BONFERRONI * erreur_type)
                resultats[(candidat, cle, nom_periode)] = r
    return resultats


def taux_par_groupe(observations, candidat, cle, nom_periode):
    """(moyenne du groupe, moyenne des autres, nombre dans le groupe, nombre d'autres) d'une mesure sur une période."""
    groupe, autres = [], []
    for o in periode(observations, nom_periode):
        if o.get(cle) is None or f"decision_{candidat}" not in o:
            continue
        (groupe if o[f"decision_{candidat}"] == "HAUT" else autres).append(o[cle])
    moyenne = lambda v: sum(v) / len(v) if v else None  # noqa: E731
    return moyenne(groupe), moyenne(autres), len(groupe), len(autres)


def _sous_zero(r):
    return bool(r and r.get("haut_corrige") is not None and r["haut_corrige"] < 0)


def _sur_zero(r):
    return bool(r and r.get("bas_corrige") is not None and r["bas_corrige"] > 0)


def _meme_signe(r, signe):
    return bool(r and r["moyenne"] * signe > 0)


def verdicts(resultats):
    """Critères pré-enregistrés : test (fourchette corrigée) et même signe en conception."""
    sortie = {}
    for candidat in CANDIDATS:
        test = lambda cle: resultats.get((candidat, cle, "test"))  # noqa: E731
        conception = lambda cle: resultats.get((candidat, cle, "conception"))  # noqa: E731
        v = {}
        if candidat in CANDIDATS_FIABILITE:
            v["fiable"] = _sous_zero(test("baisse_3_ans")) and _meme_signe(conception("baisse_3_ans"), -1)
        else:
            v["alerte"] = _sur_zero(test("baisse_3_ans")) and _meme_signe(conception("baisse_3_ans"), +1)
        if _sur_zero(test("rendement_36_mois")) and _meme_signe(conception("rendement_36_mois"), +1):
            v["rendement"] = "plus élevé"
        elif _sous_zero(test("rendement_36_mois")) and _meme_signe(conception("rendement_36_mois"), -1):
            v["rendement"] = "plus faible"
        else:
            v["rendement"] = "pas de différence démontrée"
        v["perte_plus_faible"] = _sous_zero(test("perte_36_mois")) and _meme_signe(conception("perte_36_mois"), -1)
        sortie[candidat] = v
    return sortie


def decisions_pour_boursy(verdicts_candidats):
    """Ce que le protocole prévoit d'ajouter : score de solidité (S, sinon R) et alertes (H, Q)."""
    score = next((c for c in ("S", "R") if verdicts_candidats[c]["fiable"]
                  and verdicts_candidats[c]["rendement"] != "plus faible"), None)
    alertes = [c for c in CANDIDATS_ALERTE if verdicts_candidats[c]["alerte"]]
    return {"score": score, "alertes": alertes}


def taux_de_baisse_par_annee(series, premiere, derniere=DERNIERE_ANNEE):
    """{année: (actions qui versaient un dividende l'année précédente, baisses)}, actions couvertes depuis janvier a-1."""
    resultat = {}
    for annee in range(premiere, derniere + 1):
        versantes = baisses = 0
        for serie in series.values():
            if not couverte_depuis(serie, f"{annee - 1}-01") or dividende(serie, annee - 1) <= 0:
                continue
            versantes += 1
            baisses += est_baisse(dividende(serie, annee - 1), dividende(serie, annee))
        if versantes >= MINIMUM_ACTIONS:
            resultat[annee] = (versantes, baisses)
    return resultat


def baisses_de_l_annee(series, annee):
    """Journal de contrôle : [(action, D(a-1), D(a), D(a+1))] des baisses de l'année a (actions couvertes depuis a-1)."""
    resultat = []
    for nom, serie in sorted(series.items()):
        if couverte_depuis(serie, f"{annee - 1}-01") and est_baisse(dividende(serie, annee - 1), dividende(serie, annee)):
            resultat.append((nom, dividende(serie, annee - 1), dividende(serie, annee), dividende(serie, annee + 1)))
    return resultat
