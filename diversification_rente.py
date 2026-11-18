"""
Diversification de la rente : répartition des dividendes attendus par grand secteur et par pays (siège fiscal de la
société), lignes trop lourdes, et retenues à la source étrangères. Sans Streamlit.

Pourquoi : dans l'étude des dividendes de Boursy, les baisses arrivent par vagues qui frappent des secteurs entiers
(banques, aéronautique, automobile en 2020). Une rente solide, ce sont des dividendes solides ET répartis.
"""

SEUIL_SECTEUR = 0.30  # repère usuel de diversification (pas une mesure de l'étude)
SEUIL_LIGNE = 0.20

# Mesuré (exploratoire) dans l'étude des dividendes, section « les crises par grand secteur » de
# etudes/resultats_dividendes.md : {grand secteur: {année: (baisses, actions qui versaient un dividende)}}.
BAISSES_CRISES = {
    "Automobile": {2009: (5, 5), 2020: (4, 4)},
    "Aéronautique et défense": {2009: (2, 4), 2020: (4, 4)},
    "Consommation": {2009: (3, 15), 2020: (4, 15)},
    "Finance et holdings": {2009: (11, 14), 2020: (12, 19)},
    "Immobilier": {2009: (1, 5), 2020: (1, 5)},
    "Industrie et construction": {2009: (5, 15), 2020: (11, 18)},
    "Luxe et spiritueux": {2009: (5, 6), 2020: (5, 7)},
    "Santé": {2009: (2, 9), 2020: (2, 10)},
    "Services publics": {2009: (0, 4), 2020: (2, 4)},
    "Technologie": {2009: (3, 9), 2020: (5, 13)},
    "Télécoms et médias": {2009: (3, 7), 2020: (5, 7)},
    "Énergie": {2009: (1, 6), 2020: (1, 6)},
}

# Libellés de secteur du catalogue -> grand secteur. Règles appliquées dans l'ordre (mots du libellé, en minuscules).
REGLES_SECTEURS = (
    (("etf",), "ETF (déjà diversifiés)"),
    (("immobilier", "reit"), "Immobilier"),
    (("utilities", "énergie verte", "environnement"), "Services publics"),
    (("aéronautique", "défense", "aérospatial"), "Aéronautique et défense"),
    (("luxe", "spiritueux"), "Luxe et spiritueux"),
    (("automobile", "pneus"), "Automobile"),
    (("santé", "pharma", "diagnostic", "optique"), "Santé"),
    (("banque", "assurance", "réassurance", "bourse", "finance", "gestion", "paiements", "private equity", "holding"),
     "Finance et holdings"),
    (("btp", "concessions", "infrastructures", "industrie", "chimie", "matériaux", "ciment", "ferroviaire", "emballage",
      "certification", "équipement", "services industriels", "distribution élec", "câbles", "services énergie"),
     "Industrie et construction"),
    (("télécoms", "médias", "communication", "divertissement"), "Télécoms et médias"),
    (("semi-conducteurs", "logiciels", "tech", "services it", "ia ", "relation client"), "Technologie"),
    (("énergie", "gnl", "tubes"), "Énergie"),
    (("consommation", "agroalimentaire", "distribution", "restauration", "cosmétiques", "mode", "retail",
      "électroménager", "loisirs"), "Consommation"),
)

SECTEUR_PAR_SYMBOLE = {"ENEL.MI": "Services publics"}  # Enel : électricité, rangée « Énergie » dans le catalogue

# Pays du siège fiscal d'après la place de cotation, sauf sociétés domiciliées ailleurs (c'est le siège qui fixe la
# retenue à la source sur les dividendes et l'éligibilité au PEA).
PAYS_PAR_SUFFIXE = {
    "PA": "France", "DE": "Allemagne", "AS": "Pays-Bas", "MI": "Italie", "MC": "Espagne", "BR": "Belgique",
    "LS": "Portugal", "IR": "Irlande", "HE": "Finlande", "VI": "Autriche", "CO": "Danemark", "ST": "Suède",
    "OL": "Norvège", "L": "Royaume-Uni", "SW": "Suisse",
}
SIEGE_FISCAL = {
    "AIR.PA": "Pays-Bas",  # Airbus SE
    "STLAP.PA": "Pays-Bas",  # Stellantis N.V.
    "STMPA.PA": "Pays-Bas",  # STMicroelectronics N.V.
    "ENX.PA": "Pays-Bas",  # Euronext N.V.
    "RACE.MI": "Pays-Bas",  # Ferrari N.V.
    "SHELL.AS": "Royaume-Uni",  # Shell plc
    "UNA.AS": "Royaume-Uni",  # Unilever PLC
}
# Union européenne et Espace économique européen : sociétés éligibles au PEA (le Royaume-Uni ne l'est plus depuis 2021)
PAYS_PEA = {"France", "Allemagne", "Pays-Bas", "Italie", "Espagne", "Belgique", "Portugal", "Irlande", "Finlande",
            "Autriche", "Danemark", "Suède", "Norvège", "Luxembourg"}
# Taux légaux usuels de retenue à la source pour un résident français (le courtier peut appliquer un taux réduit par
# convention fiscale). Dans un PEA, cette retenue n'est pas récupérable.
RETENUE_A_LA_SOURCE = {
    "France": 0.0, "Allemagne": 0.26375, "Pays-Bas": 0.15, "Italie": 0.26, "Espagne": 0.19, "Belgique": 0.30,
    "Royaume-Uni": 0.0, "États-Unis": 0.15, "Suisse": 0.35,
}


def grand_secteur(secteur, symbole=None):
    if str(symbole or "").strip().upper() in SECTEUR_PAR_SYMBOLE:
        return SECTEUR_PAR_SYMBOLE[str(symbole).strip().upper()]
    texte = f"{secteur or ''} ".lower()
    for mots, groupe in REGLES_SECTEURS:
        if any(mot in texte for mot in mots):
            return groupe
    return "Autre"


def pays_du_siege(symbole):
    symbole = str(symbole or "").strip().upper()
    if symbole in SIEGE_FISCAL:
        return SIEGE_FISCAL[symbole]
    if "." not in symbole:
        return "États-Unis" if symbole else "Inconnu"
    return PAYS_PAR_SUFFIXE.get(symbole.rsplit(".", 1)[1], "Inconnu")


def repartition_rente(lignes):
    """
    lignes : [(nom, symbole, secteur, revenu annuel en euros)]. Renvoie la répartition de la rente par grand secteur et
    par pays (montant, part), les dépassements (secteur > 30 %, ligne > 20 %), les retenues à la source non récupérables
    dans un PEA (lignes européennes hors France) et les lignes hors PEA.
    """
    lignes = [(nom, symbole, secteur, revenu) for nom, symbole, secteur, revenu in lignes if revenu > 0]
    rente = sum(revenu for *_debut, revenu in lignes)
    par_secteur, par_pays, retenues, hors_pea = {}, {}, [], []
    for nom, symbole, secteur, revenu in lignes:
        groupe = grand_secteur(secteur, symbole)
        par_secteur[groupe] = par_secteur.get(groupe, 0.0) + revenu
        if groupe == "ETF (déjà diversifiés)":
            par_pays["ETF (déjà diversifiés)"] = par_pays.get("ETF (déjà diversifiés)", 0.0) + revenu
            continue
        pays = pays_du_siege(symbole)
        par_pays[pays] = par_pays.get(pays, 0.0) + revenu
        if pays not in PAYS_PEA:
            hors_pea.append((nom, pays))
        elif RETENUE_A_LA_SOURCE.get(pays, 0.0) > 0:
            taux = RETENUE_A_LA_SOURCE[pays]
            retenues.append({"nom": nom, "pays": pays, "taux": taux, "montant": revenu * taux})

    def trie(dictionnaire):
        return [(cle, montant, montant / rente if rente else 0.0) for cle, montant in sorted(dictionnaire.items(), key=lambda kv: -kv[1])]

    secteurs = trie(par_secteur)
    return {
        "rente": rente,
        "par_secteur": secteurs,
        "par_pays": trie(par_pays),
        "secteurs_trop_lourds": [(s, m, p) for s, m, p in secteurs if p > SEUIL_SECTEUR and s != "ETF (déjà diversifiés)"],
        "lignes_trop_lourdes": [(nom, revenu, revenu / rente) for nom, symbole, secteur, revenu in sorted(lignes, key=lambda l: -l[3])
                                if rente and revenu / rente > SEUIL_LIGNE and grand_secteur(secteur, symbole) != "ETF (déjà diversifiés)"],
        "retenues": sorted(retenues, key=lambda r: -r["montant"]),
        "retenue_totale": sum(r["montant"] for r in retenues),
        "hors_pea": hors_pea,
    }


def lignes_de_rente(portefeuille, fiches, taux_usd_eur, noms=None):
    """
    [(nom, symbole, secteur, dividende annuel brut en euros)] des lignes détenues (quantité > 0 et fiche connue), avec
    le même calcul que l'onglet Calendrier : quantité x dividende de la fiche, converti en euros pour le dollar.
    """
    lignes = []
    for nom in (noms if noms is not None else list(portefeuille or {})):
        position, fiche = (portefeuille or {}).get(nom), (fiches or {}).get(nom)
        if not isinstance(position, dict) or not isinstance(fiche, dict):
            continue
        quantite = float(position.get("qte", 0) or 0)
        if quantite <= 0:
            continue
        facteur = (1.0 / taux_usd_eur) if fiche.get("devise") == "USD" and taux_usd_eur else 1.0
        lignes.append((nom, str(fiche.get("symbole", "")).strip(), str(fiche.get("secteur", "")),
                       quantite * float(fiche.get("div_eur", 0) or 0) * facteur))
    return lignes


def phrase_crise(secteur):
    """Ce que ce secteur a vécu en 2020 et en 2009 dans le catalogue de l'étude, en une phrase (vide si inconnu)."""
    mesures = BAISSES_CRISES.get(secteur)
    if not mesures:
        return ""
    (b20, v20), (b09, v09) = mesures[2020], mesures[2009]
    faits = (f" Dans le catalogue, {b20} des {v20} valeurs de ce secteur {'a' if b20 <= 1 else 'ont'} baissé ou "
             f"suspendu {'son' if b20 <= 1 else 'leur'} dividende en 2020 ({b09} sur {v09} en 2009)")
    if b20 / v20 >= 0.5:
        return faits + " : une seule mauvaise année peut toucher une grosse part de votre rente."
    return faits + " : il a plutôt bien tenu, mais votre rente dépend fortement de lui."
