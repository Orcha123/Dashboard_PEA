"""
Solidité du dividende et alertes « rendement élevé », issues de l'étude pré-enregistrée des dividendes
(etudes/protocole_dividendes.md ; résultats : etudes/resultats_dividendes.md). Sans Streamlit.

Les définitions sont exactement celles de l'étude (etudes/dividendes.py), appliquées au 31 décembre de la dernière
année civile complète :
- dividende solide : versé chaque année depuis 5 ans sans baisse de plus de 10 %, plus élevé qu'il y a 5 ans, et
  rendement (dividende de l'année / cours du 31 décembre) hors des 20 % les plus élevés du catalogue ;
- alerte « rendement élevé » : rendement parmi les 20 % les plus élevés du catalogue ;
- alerte « rendement anormal » : rendement divisé par la médiane de ses 5 rendements de fin d'année précédents, parmi
  les 20 % les plus élevés du catalogue.
"""
from etudes import dividendes as D

# Mesuré sur la période de test de l'étude (décisions 2015-2022, 2020 compris) : part des actions qui ont baissé leur
# dividende (de plus de 10 %) au moins une fois dans les 3 années suivantes, dans le groupe et chez les autres.
TAUX_MESURES = {
    "solide": (0.22, 0.43),
    "rendement_eleve": (0.58, 0.26),
    "rendement_anormal": (0.53, 0.27),
}


def annee_de_reference(aujourd_hui):
    """Dernière année civile complète : la situation est celle du 31 décembre de cette année-là."""
    return aujourd_hui.year - 1


def _rang_mois(mois):
    return int(mois[:4]) * 12 + int(mois[5:7])


def serie_mensuelle(historique):
    """Série de l'étude (dernière clôture de chaque mois, dividendes) à partir d'un historique quotidien."""
    dates, clotures, dividendes = historique[0], historique[1], historique[2]
    par_mois = {}
    for jour, cloture in zip(dates, clotures):
        if cloture is not None and float(cloture) > 0:
            par_mois[str(jour)[:7]] = float(cloture)
    mois = sorted(par_mois)
    debut = len(mois) - 1  # les calculs supposent des mois consécutifs : on garde ceux qui suivent le dernier trou
    while debut > 0 and _rang_mois(mois[debut]) - _rang_mois(mois[debut - 1]) == 1:
        debut -= 1
    mois = mois[max(debut, 0):]
    return D.preparer_serie(mois, [par_mois[m] for m in mois], dividendes)


def caracteristiques(historique, annee):
    """
    Valeurs de l'étude pour une action au 31 décembre de l'année, avec les dividendes des 6 dernières années.
    Renvoie {"retenue": False, "raison": ...} si l'action n'est pas classable (historique court, pas de dividende).
    """
    if not historique or len(historique) < 3 or not historique[0]:
        return {"retenue": False, "raison": "historique indisponible"}
    serie = serie_mensuelle(historique)
    dividendes = {a: D.dividende(serie, a) for a in range(annee - D.ANNEES_HISTORIQUE, annee + 1)}
    valeurs = D.caracteristiques(serie, annee)
    if valeurs is None:
        if not D.couverte_depuis(serie, f"{annee - D.ANNEES_HISTORIQUE}-01"):
            raison = f"historique trop court (depuis {annee - D.ANNEES_HISTORIQUE} nécessaire)"
        elif dividendes[annee] <= 0:
            raison = f"pas de dividende en {annee}"
        else:
            raison = f"cours du 31/12/{annee} indisponible"
        return {"retenue": False, "raison": raison, "dividendes": dividendes}
    return dict(valeurs, retenue=True, dividendes=dividendes)


def seuils(caracteristiques_catalogue):
    """
    Seuils des 20 % les plus élevés du catalogue pour le rendement (H) et le rendement anormal (Q) : la plus petite
    valeur du groupe, classé exactement comme dans l'étude. Absent s'il y a moins de 10 actions classables.
    """
    resultat = {}
    for cle in ("H", "Q"):
        valeurs = {nom: v[cle] for nom, v in caracteristiques_catalogue.items() if v and v.get("retenue") and cle in v}
        if len(valeurs) >= D.MINIMUM_ACTIONS:
            resultat[cle] = min(valeurs[nom] for nom in D.plus_hauts(valeurs))
    return resultat


def statut(valeurs, seuils_catalogue, annee):
    """
    Verdict pour une action : {"solide", "alertes" (liste), "libelle", "explication"}.
    Une action peut être solide et en alerte « rendement anormal » à la fois (son cours a beaucoup baissé).
    """
    if not valeurs or not valeurs.get("retenue"):
        raison = (valeurs or {}).get("raison", "historique indisponible")
        return {"solide": False, "alertes": [], "libelle": "— Non classée", "explication": raison}
    alertes = []
    if "H" in seuils_catalogue and valeurs["H"] >= seuils_catalogue["H"]:
        alertes.append("rendement parmi les 20 % les plus élevés du catalogue")
    if "Q" in seuils_catalogue and valeurs.get("Q") is not None and valeurs["Q"] >= seuils_catalogue["Q"]:
        alertes.append("rendement anormalement élevé pour cette action (cours en forte baisse ?)")
    rendement_eleve = "H" in seuils_catalogue and valeurs["H"] >= seuils_catalogue["H"]
    solide = bool(valeurs["R"] and valeurs["hausse_5_ans"] and "H" in seuils_catalogue and not rendement_eleve)

    if alertes:
        libelle = ("🛡️ Solide, mais ⚠️ à surveiller" if solide else "⚠️ Risque de baisse du dividende")
        explication = " ; ".join(alertes)
    elif solide:
        libelle = "🛡️ Solide"
        explication = f"versé sans baisse depuis 5 ans, plus élevé qu'en {annee - 5}, rendement raisonnable"
    else:
        libelle = "Neutre"
        if not valeurs["R"]:
            explication = "baisse ou interruption du dividende ces 5 dernières années"
        elif not valeurs["hausse_5_ans"]:
            explication = f"dividende moins élevé qu'en {annee - 5}"
        else:
            explication = "classement du catalogue indisponible"
    return {"solide": solide, "alertes": alertes, "libelle": libelle, "explication": explication}


def evolution_dividende(valeurs, annee):
    """Texte « 1,20 → 1,25 → ... » des dividendes par action des 6 dernières années (devise de l'action)."""
    dividendes = (valeurs or {}).get("dividendes")
    if not dividendes:
        return "—"  # historique indisponible : rien n'est affiché plutôt que des zéros trompeurs
    return " → ".join(f"{dividendes.get(a, 0.0):.2f}".replace(".", ",") for a in range(annee - D.ANNEES_HISTORIQUE, annee + 1))


# ==============================================================================
# PROJECTION DE RENTE PRUDENTE
# ==============================================================================
# Mesuré (exploratoire) dans l'étude des dividendes, section « Pour la projection de rente » de
# etudes/resultats_dividendes.md : revenu, k ans plus tard, d'un portefeuille qui garde sans rien changer les actions
# d'une catégorie (départs de 2010 à 2024), par rapport au revenu de départ : (médiane des départs, pire départ).
EVOLUTION_REVENU = {
    "solide": {1: (1.118, 0.867), 3: (1.327, 1.068), 5: (1.567, 1.246), 10: (2.046, 1.901)},
    "neutre": {1: (1.282, 0.762), 3: (1.453, 0.815), 5: (1.617, 0.791), 10: (2.218, 1.307)},
    "alerte": {1: (0.992, 0.478), 3: (1.084, 0.754), 5: (1.229, 0.880), 10: (1.448, 1.199)},
}
# Ces hausses ne servent PAS de prévision : le catalogue ne contient que des entreprises qui existent encore (et qui
# ont souvent réussi), et 2010-2025 a été une période de rattrapage après la crise de 2009. La projection prudente
# n'en garde que ce qui est robuste : l'écart entre catégories et la baisse de la pire année (2020).
CHOC_CRISE = {categorie: mesures[1][1] - 1.0 for categorie, mesures in EVOLUTION_REVENU.items()}
INFLATION_HYPOTHESE = 0.02  # pour passer des euros d'aujourd'hui aux euros courants (objectif de la BCE)
HORIZONS_PROJECTION = (1, 3, 5, 10, 15, 20)


def categorie_projection(verdict):
    """Catégorie d'une ligne pour la projection : « alerte », « solide » ou « neutre » (non classée comprise)."""
    if verdict and verdict.get("alertes"):
        return "alerte"
    return "solide" if verdict and verdict.get("solide") else "neutre"


def facteur_relatif(categorie, annees):
    """
    Revenu d'une ligne après `annees` ans, en euros d'aujourd'hui, si une ligne solide garde le sien (hypothèse
    prudente : pas de croissance réelle). Les lignes « alerte » perdent l'écart mesuré avec les solides ; les lignes
    neutres, qui ont fait aussi bien que les solides dans l'étude, ne sont pas comptées mieux qu'elles. Entre deux
    horizons mesurés : interpolation ; au-delà de 10 ans : écart des 10 ans.
    """
    if categorie == "solide":
        return 1.0
    points = [(0, 1.0)] + [(k, EVOLUTION_REVENU[categorie][k][0] / EVOLUTION_REVENU["solide"][k][0])
                           for k in sorted(EVOLUTION_REVENU[categorie])]
    if categorie == "neutre":
        points = [(k, min(1.0, r)) for k, r in points]
    for (k1, r1), (k2, r2) in zip(points, points[1:]):
        if annees <= k2:
            return r1 + (r2 - r1) * (annees - k1) / (k2 - k1)
    return points[-1][1]


def projeter_rente(lignes, apport_annuel=0.0, rendement_achats=0.0, reinvestir=False, annees=20):
    """
    Projection prudente, en euros d'aujourd'hui. lignes : [(revenu annuel actuel, catégorie)].
    Chaque année, l'apport (et, si demandé, la rente de l'année précédente) achète des dividendes solides au rendement
    donné, eux aussi sans croissance réelle. Renvoie [(année, rente prudente, rente l'année d'une crise comme 2020)].
    """
    resultat, achats_cumules_revenu = [], 0.0
    rente_precedente = sum(revenu for revenu, _ in lignes)
    for n in range(1, annees + 1):
        achats_cumules_revenu += rendement_achats * (apport_annuel + (rente_precedente if reinvestir else 0.0))
        par_categorie = {"solide": achats_cumules_revenu}
        for revenu, categorie in lignes:
            par_categorie[categorie] = par_categorie.get(categorie, 0.0) + revenu * facteur_relatif(categorie, n)
        rente = sum(par_categorie.values())
        crise = sum(montant * (1.0 + CHOC_CRISE[categorie]) for categorie, montant in par_categorie.items())
        resultat.append((n, rente, crise))
        rente_precedente = rente
    return resultat


def en_euros_courants(montant, annees, inflation=INFLATION_HYPOTHESE):
    return montant * (1.0 + inflation) ** annees
