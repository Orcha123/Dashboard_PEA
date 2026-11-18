"""
Coach de Boursy : dossier complet de l'utilisateur (données de tous les onglets), diagnostic à règles explicites,
plan d'action et rapport. Sans Streamlit.

Le diagnostic pointe des faits chiffrés, des critiques et des actions de méthode, chacune reliée à l'outil de Boursy
qui la réalise. Il ne dit jamais quel titre acheter ou vendre, ni en quelle quantité : Boursy n'est pas conseiller en
investissements financiers. Les repères (30 % par secteur, 20 % par ligne, une quinzaine de lignes...) sont des repères
usuels, présentés comme tels ; les autres chiffres viennent des études de Boursy (etudes/).
"""
from datetime import date

from allocation_dca import lire_allocation_cible
from carnet_decisions import decisions_a_relire, lire_carnet
from diversification_rente import BAISSES_CRISES, grand_secteur, phrase_crise
from fiscalite_pea import PLAFOND_PEA, TAUX_IMPOT_REVENU, TAUX_PRELEVEMENTS_SOCIAUX, date_fr, etat_pea
from solidite_dividendes import TAUX_MESURES

SEUIL_RENTE_A_SURVEILLER = 0.25
SEUIL_RENTE_SOLIDE = 0.60
SEUIL_BAISSE_CRISE = 0.25
LIGNES_DE_RENTE_REPERE = 15
MOIS_ACHAT_REPERE = 6
ECART_ETF = 0.01  # 1 point de rendement annualisé
VIX_NERVEUX = 25.0
HORIZONS = ("Ce mois-ci", "Ce trimestre", "Cette année", "En continu")
NIVEAUX = {"critique": "🔴", "vigilance": "🟠", "force": "🟢", "info": "🔵"}

PRINCIPES = (
    ("Ne pas chercher à prévoir le marché",
     "aucune des méthodes testées par Boursy ne prévoit les 6 à 12 prochains mois, et sortir du marché sous la moyenne "
     "de 200 jours a coûté environ 6 points de rendement par an sur la période de test (étude des grandes tendances)."),
    ("La solidité avant le rendement",
     "les dividendes solides ont baissé deux fois moins souvent que les autres (22 % contre 43 % en 3 ans), et les 20 % "
     "de rendements les plus élevés ont baissé dans 58 % des cas (étude des dividendes)."),
    ("Diversifier par secteur",
     "les crises frappent des secteurs entiers : en 2020, toutes les valeurs automobiles et aéronautiques du catalogue ont "
     "baissé leur dividende, contre 2 sur 10 dans la santé."),
    ("La rente vient d'abord des apports",
     "sans croissance réelle des dividendes (hypothèse prudente), c'est la régularité des achats qui construit la rente."),
    ("Juger sa sélection face à un ETF Monde",
     "aux mêmes dates et pour les mêmes sommes : c'est le seul juge de paix honnête d'une sélection d'actions."),
)


def _eur(x):
    return f"{x:,.0f}".replace(",", " ") + " €"


def _pc(x):
    return f"{x * 100:.0f} %"


def _taux(x):
    return f"{x * 100:.1f}".replace(".", ",") + " %"


def _pc1(x, signe=True):
    return (f"{x * 100:+.1f}" if signe else f"{x * 100:.1f}").replace(".", ",") + " %"


def _date_fr(iso):
    iso = str(iso)[:10]
    return f"{iso[8:10]}/{iso[5:7]}/{iso[0:4]}"


# ==============================================================================
# DOSSIER : LES DONNÉES DE TOUS LES ONGLETS
# ==============================================================================
def construire_dossier(*, lignes_portefeuille, valeur_totale, cout_total, budget_mensuel, dividendes_bruts,
                       dividendes_nets, rente, acces_rente, plan_dca, allocation_personnalisee, portefeuille, ventes,
                       performance_vs_etf, versements_pea, exposition_eur, exposition_usd, marche, signaux_forts,
                       fiches, taux_usd_eur, aujourd_hui=None):
    """
    Rassemble les données des onglets en un dossier. rente : contexte du coach (lignes de rente, répartition,
    solidité éventuelle, rente à 20 ans) ; acces_rente : solidité et diversification réservées à Premium et Pro.
    """
    aujourd_hui = aujourd_hui or date.today()
    portefeuille = portefeuille if isinstance(portefeuille, dict) else {}
    lignes = [l for l in (lignes_portefeuille or []) if not l.get("est_especes") and float(l.get("val_eur") or 0) > 0]
    especes = sum(float(l.get("val_eur") or 0) for l in (lignes_portefeuille or []) if l.get("est_especes"))
    actions = [{
        "nom": l["nom_act"], "valeur": float(l["val_eur"]), "poids": float(l["val_eur"]) / valeur_totale if valeur_totale else 0.0,
        "pv_eur": float(l.get("pv_eur") or 0), "pv_pct": float(l.get("pv_pct") or 0), "enveloppe": l.get("env_label", ""),
        "secteur": grand_secteur((fiches.get(l["nom_act"]) or {}).get("secteur"), (fiches.get(l["nom_act"]) or {}).get("symbole")),
    } for l in sorted(lignes, key=lambda l: -float(l["val_eur"]))]

    # Journal des achats : régularité sur les 12 derniers mois
    il_y_a_un_an = date(aujourd_hui.year - 1, aujourd_hui.month, min(aujourd_hui.day, 28)).isoformat()
    journal = [e for e in (portefeuille.get("_journal_achats") or []) if isinstance(e, dict) and str(e.get("date", "")) >= il_y_a_un_an]

    def montant_achat(e):
        taux = float(e.get("taux_change") or taux_usd_eur or 1.0) if e.get("devise") == "USD" else 1.0
        return float(e.get("qte", 0) or 0) * float(e.get("prix", 0) or 0) / taux + float(e.get("frais_eur", 0) or 0)

    # Calendrier : dividendes attendus par mois (calendrier habituel de chaque valeur)
    mois_ordre = ["Jan", "Fév", "Mar", "Avr", "Mai", "Juin", "Juil", "Août", "Sep", "Oct", "Nov", "Déc"]
    par_mois = {m: 0.0 for m in mois_ordre}
    for nom, _sym, _secteur, revenu in (rente or {}).get("lignes") or []:
        mois_div = [m for m in ((fiches.get(nom) or {}).get("mois_div") or []) if m in par_mois]
        for m in mois_div:
            par_mois[m] += revenu / len(mois_div)

    carnet = lire_carnet(portefeuille)
    ventes = [v for v in (ventes or []) if isinstance(v, dict)]
    # Lignes du PEA (actions en euros) et espèces, comme la jauge du plafond de l'onglet Portefeuille
    valeur_pea = sum(a["valeur"] for a in actions if a["enveloppe"] == "PEA") + especes
    return {
        "aujourd_hui": aujourd_hui,
        "valeur": float(valeur_totale or 0), "cout": float(cout_total or 0), "especes": especes,
        "budget": float(budget_mensuel or 0), "actions": actions,
        "dividendes_bruts": float(dividendes_bruts or 0), "dividendes_nets": float(dividendes_nets or 0),
        "acces_rente": bool(acces_rente),
        "rente": rente if acces_rente else None,
        "dividendes_par_mois": par_mois,
        "allocation_personnalisee": bool(allocation_personnalisee),
        "nb_cibles": len(lire_allocation_cible(portefeuille)),
        "plan": plan_dca or {},
        "achats_12_mois": {"nombre": len(journal), "montant": sum(montant_achat(e) for e in journal),
                           "mois": len({str(e.get("date", ""))[:7] for e in journal}),
                           "journal_vide": not (portefeuille.get("_journal_achats") or [])},
        "carnet": {"total": len(carnet), "a_relire": len(decisions_a_relire(carnet, aujourd_hui)),
                   "avec_lecon": sum(1 for d in carnet if d.get("lecon"))},
        "ventes": {"nombre": len(ventes), "pv": sum(float(v.get("plus_value_eur", 0) or 0) for v in ventes),
                   "a_perte": sum(1 for v in ventes if float(v.get("plus_value_eur", 0) or 0) < 0)},
        "performance_vs_etf": performance_vs_etf,
        "versements_pea": versements_pea,
        "pea": etat_pea(portefeuille, aujourd_hui, versements_pea, valeur_pea if versements_pea is not None else None),
        "exposition_eur": float(exposition_eur or 0), "exposition_usd": float(exposition_usd or 0),
        "marche": marche or {},
        "signaux_forts": list(signaux_forts or []),
    }


# ==============================================================================
# DIAGNOSTIC À RÈGLES EXPLICITES
# ==============================================================================
def _constat(niveau, theme, titre, preuve, poids, action=None, quand=None, ou=None):
    return {"niveau": niveau, "theme": theme, "titre": titre, "preuve": preuve, "poids": poids,
            "action": action, "quand": quand, "ou": ou}


def secteurs_absents(repartition):
    """Grands secteurs absents (moins de 5 % de la rente), du plus au moins résistant en 2020 dans le catalogue."""
    presents = {s for s, _m, p in repartition.get("par_secteur") or [] if p >= 0.05}
    absents = [s for s in BAISSES_CRISES if s not in presents]
    return sorted(absents, key=lambda s: BAISSES_CRISES[s][2020][0] / BAISSES_CRISES[s][2020][1])


def diagnostiquer(d):
    """Constats chiffrés (critiques, vigilances, forces, informations), du plus au moins important."""
    c = []
    rente_ctx, budget = d["rente"], d["budget"]
    solidite = (rente_ctx or {}).get("solidite")
    repartition = (rente_ctx or {}).get("repartition") or {}

    # --- Solidité de la rente
    if solidite and solidite["rente"] > 0:
        rente, parts = solidite["rente"], solidite["parts"]
        p_alerte, p_solide = parts["alerte"] / rente, parts["solide"] / rente
        if p_alerte > 0:
            c.append(_constat(
                "critique" if p_alerte >= SEUIL_RENTE_A_SURVEILLER else "vigilance", "Solidité",
                "Une grosse part de votre rente est à risque" if p_alerte >= SEUIL_RENTE_A_SURVEILLER else "Des dividendes à surveiller",
                f"{_pc(p_alerte)} de votre rente ({_eur(parts['alerte'])} par an) vient de dividendes à surveiller : "
                f"{', '.join(solidite['a_surveiller'])}. Dans l'étude, {_pc(TAUX_MESURES['rendement_eleve'][0])} des rendements "
                "les plus élevés ont baissé leur dividende dans les 3 ans.",
                90 if p_alerte >= SEUIL_RENTE_A_SURVEILLER else 50,
                "Ne comptez pas sur ces dividendes à leur niveau actuel, ne les renforcez pas en priorité, et vérifiez leur "
                "prochaine annonce de dividende (souvent avec les résultats annuels, en février ou mars).",
                "Ce trimestre", "Radar > Solidité des dividendes"))
        if p_solide >= SEUIL_RENTE_SOLIDE:
            c.append(_constat("force", "Solidité", "Rente majoritairement solide",
                              f"{_pc(p_solide)} de votre rente vient de dividendes solides : dans l'étude, ils ont baissé dans "
                              f"{_pc(TAUX_MESURES['solide'][0])} des cas en 3 ans, contre {_pc(TAUX_MESURES['solide'][1])} pour les autres.", 60))
        baisse = 1.0 - solidite["rente_crise"] / rente
        if baisse >= SEUIL_BAISSE_CRISE:
            c.append(_constat("vigilance", "Crise", "Rente sensible à une crise",
                              f"L'année d'une crise comme 2020, votre rente passerait d'environ {_eur(rente)} à "
                              f"{_eur(solidite['rente_crise'])} (−{_pc(baisse)}).", 60,
                              f"Gardez une réserve d'environ {_eur(rente - solidite['rente_crise'])} (la baisse d'une telle année) "
                              "pour la traverser sans vendre.", "En continu", "Calendrier > Projection prudente"))
        else:
            c.append(_constat("force", "Crise", "Rente plutôt résistante",
                              f"L'année d'une crise comme 2020, votre rente baisserait d'environ {_pc(baisse)} "
                              f"({_eur(rente)} → {_eur(solidite['rente_crise'])}).", 35))

    # --- Diversification
    if repartition.get("rente", 0) > 0:
        absents = secteurs_absents(repartition)
        for secteur, _montant, part in repartition["secteurs_trop_lourds"]:
            c.append(_constat("critique", "Diversification", f"Rente trop dépendante d'un secteur : {secteur}",
                              f"{_pc(part)} de votre rente vient de ce secteur (repère : 30 % au plus).{phrase_crise(secteur)}", 80,
                              "Fixez une allocation cible qui plafonne ce secteur et oriente vos prochains achats vers des secteurs "
                              "peu représentés" + (f" (absents de votre rente, du plus au moins résistant en 2020 : {', '.join(absents[:4])})" if absents else "") + ".",
                              "Ce mois-ci", "Radar > Définir mon allocation cible, puis la liste des dividendes solides"))
        if repartition["lignes_trop_lourdes"]:
            c.append(_constat("vigilance", "Diversification", "Quelques lignes portent la rente",
                              "Lignes qui fournissent plus de 20 % de la rente : "
                              + ", ".join(f"{n} ({_pc(p)})" for n, _m, p in repartition["lignes_trop_lourdes"]) + ".", 55,
                              "Laissez vos prochains apports aller aux autres lignes (allocation cible) plutôt que de vendre : "
                              "vendre interromprait une partie de la rente et coûterait des frais.",
                              "Ce trimestre", "Radar > Définir mon allocation cible"))
        nb_lignes_rente = sum(1 for _n, _s, _sect, r in rente_ctx.get("lignes") or [] if r > 0)
        if nb_lignes_rente < LIGNES_DE_RENTE_REPERE:
            c.append(_constat("vigilance", "Diversification", "Peu de lignes de rente",
                              f"{nb_lignes_rente} ligne(s) versent un dividende (repère usuel : une quinzaine au moins, pour "
                              "qu'une baisse isolée pèse peu).", 40,
                              "Ajoutez progressivement de nouvelles lignes solides, dans des secteurs absents, au fil des achats mensuels.",
                              "Cette année", "Radar > Solidité des dividendes (liste du catalogue)"))
        else:
            c.append(_constat("force", "Diversification", "Rente répartie", f"{nb_lignes_rente} lignes versent un dividende.", 30))
        if repartition["retenues"]:
            c.append(_constat("vigilance", "Fiscalité", "Retenues à la source perdues dans le PEA",
                              f"Environ {_eur(repartition['retenue_totale'])} par an ("
                              + ", ".join(f"{r['nom']} : {r['pays']}" for r in repartition["retenues"]) + ").", 20,
                              "À rendement et solidité comparables, une société française ne subit pas cette perte dans le PEA.",
                              "Cette année", "Calendrier > Diversification de votre rente"))
        if repartition["hors_pea"]:
            c.append(_constat("info", "Fiscalité", "Lignes hors PEA",
                              ", ".join(f"{n} ({p})" for n, p in repartition["hors_pea"]) + " : à détenir en compte-titres.", 10))

    # --- Apports, allocation, liquidités
    projection = solidite and solidite.get("rente_prudente_horizon")
    if budget > 0 and projection:
        c.append(_constat("force", "Apports", "Vos apports sont le moteur de la rente",
                          f"Avec {_eur(budget)} par mois et les dividendes réinvestis, rente prudente d'environ "
                          f"{_eur(solidite['rente_prudente_horizon'])} par an dans 10 ans et {_eur(rente_ctx['rente_20_ans'])} "
                          f"dans 20 ans (euros d'aujourd'hui), contre {_eur(solidite['rente'])} aujourd'hui.", 70,
                          "Maintenez l'apport mensuel, y compris quand les marchés baissent : c'est le premier levier de votre rente.",
                          "En continu", "Résumé mensuel par e-mail (Radar > Centre d'alertes)"))
    achats = d["achats_12_mois"]
    if achats["journal_vide"]:
        c.append(_constat("info", "Apports", "Achats non enregistrés",
                          "Le journal des achats est vide : impossible de mesurer la régularité de vos apports et votre "
                          "performance réelle face à un ETF Monde.", 30,
                          "Enregistrez vos achats, depuis le premier si possible (saisie, import CSV ou import par l'IA).",
                          "Ce mois-ci", "Portefeuille > Journal des achats"))
    elif budget > 0 and achats["mois"] < MOIS_ACHAT_REPERE:
        c.append(_constat("vigilance", "Apports", "Apports irréguliers",
                          f"Achats enregistrés sur {achats['mois']} mois des 12 derniers ({_eur(achats['montant'])}, pour un "
                          f"budget de {_eur(12 * budget)} par an).", 45,
                          "Fixez un jour d'achat chaque mois et tenez-le, quelle que soit la météo des marchés.",
                          "En continu", "Radar > Centre d'alertes (jour d'achat du résumé mensuel)"))
    elif budget > 0:
        c.append(_constat("force", "Apports", "Apports réguliers",
                          f"Achats enregistrés sur {achats['mois']} mois des 12 derniers ({_eur(achats['montant'])}).", 40))
    if not d["allocation_personnalisee"]:
        secteur_trop_lourd = bool(repartition.get("secteurs_trop_lourds"))
        c.append(_constat("vigilance", "Allocation", "Pas d'allocation cible",
                          "L'achat du mois répartit l'enveloppe à parts égales, sans tenir compte de vos objectifs de "
                          "diversification ni de solidité" + (" (l'action sur le secteur trop lourd y remédie)." if secteur_trop_lourd else "."), 50,
                          None if secteur_trop_lourd else
                          "Définissez vos poids cibles : plafonnez les secteurs trop lourds, donnez de la place aux dividendes solides.",
                          None if secteur_trop_lourd else "Ce mois-ci", None if secteur_trop_lourd else "Radar > Définir mon allocation cible"))
    elif d["plan"].get("ecart_avant") is not None and d["plan"]["ecart_avant"] > 15:
        c.append(_constat("info", "Allocation", "Portefeuille loin de sa cible",
                          f"{_pc1(d['plan']['ecart_avant'] / 100, signe=False)} du portefeuille est mal réparti par rapport à votre "
                          f"cible ; l'achat du mois le ramène à {_pc1(d['plan']['ecart_apres'] / 100, signe=False)}.", 25))
    reserve = (solidite["rente"] - solidite["rente_crise"]) if solidite else 0.0
    if budget > 0 and d["especes"] > max(3 * budget, reserve + budget):
        c.append(_constat("vigilance", "Liquidités", "Des liquidités qui dorment",
                          f"{_eur(d['especes'])} en liquidités, soit {d['especes'] / budget:.0f} mois d'apports ; dans un PEA, elles "
                          "ne rapportent rien.", 35,
                          f"Décidez de leur rôle : une réserve pour une mauvaise année ({_eur(reserve)} suffiraient pour une crise "
                          "comme 2020) ; le reste peut suivre votre allocation cible." if reserve else
                          "Décidez de leur rôle : une réserve pour une mauvaise année, le reste selon votre allocation cible.",
                          "Ce mois-ci", "Radar > Achat du mois selon votre allocation cible"))

    # --- Performance réelle face à un ETF Monde
    perf = d["performance_vs_etf"]
    if perf and perf.get("tri") is not None and perf.get("tri_etf") is not None:
        ecart = perf["tri"] - perf["tri_etf"]
        courte = (perf.get("jours") or 0) < 3 * 365
        faits = (f"{_pc1(perf['tri'])} par an contre {_pc1(perf['tri_etf'])} pour les mêmes versements, aux mêmes dates, dans "
                 f"un ETF MSCI World (depuis le {_date_fr(perf['depuis'])}), soit {_pc1(ecart).replace(' %', ' point')} par an"
                 + (" ; sur moins de 3 ans, l'écart peut tenir au hasard" if courte else "") + ".")
        if ecart <= -ECART_ETF:
            c.append(_constat("critique", "Performance", "Votre sélection fait moins bien qu'un ETF Monde", faits, 75,
                              "Gardez ce comparatif comme juge de paix : si l'écart persiste, envisagez un cœur de portefeuille en "
                              "ETF Monde, et une poche de rente limitée aux dividendes solides.",
                              "Cette année", "Portefeuille > Ma performance réelle comparée à un ETF MSCI World"))
        elif ecart >= ECART_ETF:
            c.append(_constat("force", "Performance", "Votre sélection fait mieux qu'un ETF Monde", faits, 45))
        else:
            c.append(_constat("info", "Performance", "Au niveau d'un ETF Monde", faits, 20))
    elif d["acces_rente"] and not d["achats_12_mois"]["journal_vide"]:  # journal vide : déjà signalé plus haut
        c.append(_constat("info", "Performance", "Performance réelle non mesurée",
                          "Boursy ne peut pas encore comparer votre sélection à un ETF Monde (journal des achats incomplet).", 25,
                          "Complétez le journal des achats depuis votre premier achat pour obtenir ce comparatif.",
                          "Ce mois-ci", "Portefeuille > Journal des achats"))

    # --- PEA, devises
    if d["versements_pea"]:
        taux = d["versements_pea"] / PLAFOND_PEA
        if taux >= 0.8:
            c.append(_constat("vigilance", "PEA", "Plafond du PEA bientôt atteint",
                              f"{_eur(d['versements_pea'])} versés sur {_eur(PLAFOND_PEA)} ({_pc(taux)}).", 40,
                              "Prévoyez où iront les apports suivants (compte-titres, assurance-vie).",
                              "Cette année", "Portefeuille > Jauge du plafond PEA"))
        else:
            c.append(_constat("info", "PEA", "Marge de versements sur le PEA",
                              f"{_eur(PLAFOND_PEA - d['versements_pea'])} encore possibles ({_pc(taux)} du plafond utilisé).", 5))
    pea = d.get("pea") or {}
    taux_avant, taux_apres = _taux(TAUX_IMPOT_REVENU + TAUX_PRELEVEMENTS_SOCIAUX), _taux(TAUX_PRELEVEMENTS_SOCIAUX)
    if pea.get("premier_versement") is None:
        if d["versements_pea"] or any(a["enveloppe"] == "PEA" for a in d["actions"]):
            c.append(_constat("info", "PEA", "Date des 5 ans du PEA inconnue",
                              "Boursy ne connaît pas la date de votre premier versement sur le PEA : c'est d'elle que partent "
                              "les 5 ans qui changent la fiscalité d'un retrait.", 20,
                              "Renseignez la date de votre premier versement (sur un relevé du courtier ; ce n'est pas la date "
                              "de signature du contrat).", "Ce mois-ci", "Portefeuille > Échéances fiscales du PEA"))
    elif not pea["plus_de_5_ans"]:
        preuve = (f"Votre PEA aura 5 ans le {date_fr(pea['date_5_ans'])} (dans {pea['jours_restants']} jours). D'ici là, "
                  "un retrait clôturerait le plan")
        if pea.get("gain"):
            preuve += (f" et le gain d'environ {_eur(pea['gain'])} serait imposé à {taux_avant} (environ "
                       f"{_eur(pea['impot_avant_5_ans'])}), contre {taux_apres} après cette date (environ "
                       f"{_eur(pea['impot_apres_5_ans'])})")
        c.append(_constat("vigilance", "PEA", "PEA de moins de 5 ans", preuve + ".", 30,
                          f"Gardez votre épargne de précaution hors du PEA, pour ne pas avoir à y toucher avant le "
                          f"{date_fr(pea['date_5_ans'])}.", "En continu", "Portefeuille > Échéances fiscales du PEA"))
    else:
        c.append(_constat("force", "PEA", "PEA de plus de 5 ans",
                          f"Depuis le {date_fr(pea['date_5_ans'])} : retraits partiels possibles sans clôturer le plan, gain "
                          f"retiré exonéré d'impôt sur le revenu ({taux_apres} de prélèvements sociaux seulement).", 15))
    total_expo = d["exposition_eur"] + d["exposition_usd"]
    if total_expo > 0 and d["exposition_usd"] / total_expo >= 0.3:
        c.append(_constat("info", "Devises", "Une part importante en dollars",
                          f"{_pc(d['exposition_usd'] / total_expo)} du portefeuille en dollars : hors PEA, et soumise aux variations "
                          "de l'euro face au dollar.", 15))

    # --- Discipline : carnet et ventes
    carnet = d["carnet"]
    if carnet["a_relire"]:
        c.append(_constat("vigilance", "Discipline", "Décisions à relire",
                          f"{carnet['a_relire']} décision(s) ont passé 6 mois sans leçon écrite.", 45,
                          "Relisez-les et notez ce que vous en retenez : c'est ainsi qu'on améliore ses décisions.",
                          "Ce mois-ci", "Portefeuille > Carnet de décisions"))
    elif not carnet["total"]:
        c.append(_constat("info", "Discipline", "Carnet de décisions vide",
                          "Aucune décision notée : impossible de savoir, avec le recul, ce que vos choix ont donné.", 20,
                          "Notez chaque achat, vente ou renoncement avec sa raison : 6 mois plus tard, Boursy montre ce qu'il a donné "
                          "face à l'ETF Monde.", "En continu", "Portefeuille > Carnet de décisions"))
    ventes = d["ventes"]
    if ventes["nombre"] >= 3 and ventes["a_perte"] * 2 >= ventes["nombre"]:
        c.append(_constat("vigilance", "Discipline", "Beaucoup de ventes à perte",
                          f"{ventes['a_perte']} vente(s) à perte sur {ventes['nombre']} ({_eur(ventes['pv'])} au total).", 30,
                          "Avant de vendre, notez la raison dans le carnet et relisez-la 6 mois plus tard.",
                          "En continu", "Portefeuille > Carnet de décisions"))

    # --- Marché et radar
    vix = float(d["marche"].get("vix") or 0)
    if vix >= VIX_NERVEUX:
        c.append(_constat("info", "Marché", "Marché nerveux",
                          f"VIX à {vix:.1f}".replace(".", ",") + " : les phases de nervosité s'accompagnent souvent de cours plus bas.", 25,
                          "Maintenez l'achat prévu ce mois-ci : c'est dans ces phases que la régularité compte le plus.",
                          "Ce mois-ci", "Radar > Achat du mois"))
    if d["signaux_forts"]:
        c.append(_constat("info", "Radar", "Signaux du radar : pas des prévisions",
                          f"{len(d['signaux_forts'])} signal(aux) fort(s) aujourd'hui ({', '.join(d['signaux_forts'][:4])}). Sur 7 ans "
                          "et 120 actions, ils n'ont pas fait mieux, de façon démontrée, que les autres actions du même mois.", 15))
    mois_vides = [m for m, v in d["dividendes_par_mois"].items() if v <= 0]
    if d["rente"] and len(mois_vides) >= 6 and repartition.get("rente", 0) > 0:
        c.append(_constat("info", "Calendrier", "Versements concentrés sur quelques mois",
                          f"{len(mois_vides)} mois sans dividende. Un calendrier régulier est un confort, pas un gain : ne choisissez "
                          "pas une action pour son mois de versement.", 5))
    if not d["acces_rente"]:
        c.append(_constat("info", "Rente", "Solidité et diversification de la rente",
                          "Réservées aux offres Premium et Pro : part solide, lignes à surveiller, secteurs, crise, projection.", 10))
    ordre = {"critique": 0, "vigilance": 1, "force": 2, "info": 3}
    return sorted(c, key=lambda x: (ordre[x["niveau"]], -x["poids"]))


def plan_action(constats, maximum=7):
    """Actions des constats (critiques et vigilances d'abord), rangées par échéance."""
    avec_action = [c for c in constats if c["action"]]
    avec_action.sort(key=lambda c: ({"critique": 0, "vigilance": 1, "force": 2, "info": 3}[c["niveau"]], -c["poids"]))
    retenues = avec_action[:maximum]
    return {h: [c for c in retenues if c["quand"] == h] for h in HORIZONS}


# ==============================================================================
# RAPPORT (MOTEUR LOCAL) ET DOSSIER POUR GEMINI
# ==============================================================================
def section_rente(d):
    """Votre rente : solidité, résistance à une crise et projection prudente (chiffres des onglets Radar et Calendrier)."""
    lignes = ["#### 🛡️ Votre rente : solidité, crise et projection"]
    if not d["acces_rente"]:
        return lignes + ["- 🔒 Réservées aux offres Premium et Pro : part solide de la rente, lignes à surveiller, rente en cas de "
                         "crise et projection prudente."]
    solidite = (d["rente"] or {}).get("solidite")
    if not solidite:
        return lignes + ["- Pas encore calculée aujourd'hui : utilisez le bouton « 🛡️ Ajouter la solidité de ma rente » ci-dessous "
                         "(ou lancez l'audit 🧭 0, qui la calcule)."]
    rente, parts = solidite["rente"], solidite["parts"]
    if rente <= 0:
        return lignes + ["- Aucun dividende attendu sur vos lignes : la rente viendra de vos prochains achats."]
    lignes.append(f"- **Solidité** : {_eur(parts['solide'])} solides ({_pc(parts['solide'] / rente)}), {_eur(parts['neutre'])} neutres "
                  f"ou non classés ({_pc(parts['neutre'] / rente)}), {_eur(parts['alerte'])} à surveiller ({_pc(parts['alerte'] / rente)})"
                  + (f" : {', '.join(solidite['a_surveiller'])}" if solidite["a_surveiller"] else "") + ".")
    lignes.append(f"- **L'année d'une crise comme 2020** : environ {_eur(solidite['rente_crise'])} au lieu de {_eur(rente)} "
                  f"(−{_pc(1 - solidite['rente_crise'] / rente)}).")
    if d["budget"] > 0:
        lignes.append(f"- **Projection prudente** (euros d'aujourd'hui, {_eur(d['budget'])} par mois et dividendes réinvestis, sans "
                      f"croissance réelle) : environ {_eur(solidite['rente_prudente_horizon'])} par an dans 10 ans, "
                      f"{_eur(d['rente']['rente_20_ans'])} dans 20 ans.")
    return lignes


def rapport_markdown(d, constats):
    """Synthèse stratégique, critiques et plan d'action, en Markdown."""
    solidite = (d["rente"] or {}).get("solidite")
    critiques = [c for c in constats if c["niveau"] in ("critique", "vigilance")]
    forces = [c for c in constats if c["niveau"] == "force"]
    infos = [c for c in constats if c["niveau"] == "info"]
    plan = plan_action(constats)

    en_bref = (f"Portefeuille de **{_eur(d['valeur'])}**"
               + (f" ({_pc1((d['valeur'] - d['cout']) / d['cout'])} latent)" if d["cout"] > 0 else "")
               + f", rente de **{_eur(d['dividendes_nets'])} net par an** ({_eur(d['dividendes_nets'] / 12)} par mois)")
    if solidite and solidite["rente"] > 0:
        en_bref += f", dont {_pc(solidite['parts']['solide'] / solidite['rente'])} issus de dividendes solides"
    en_bref += "."
    if critiques:
        en_bref += f" Point principal : **{critiques[0]['titre'].lower()}**."
    if solidite and d["budget"] > 0:
        en_bref += (f" Votre moteur : {_eur(d['budget'])} d'apport par mois, pour une rente prudente d'environ "
                    f"{_eur(solidite['rente_prudente_horizon'])} par an dans 10 ans.")

    lignes = ["### 🧭 Synthèse stratégique, critiques & plan d'action", "", f"**En bref.** {en_bref}", ""]
    lignes += section_rente(d) + [""]
    lignes.append(f"#### 🟢 Ce qui va bien ({len(forces)})")
    lignes += [f"- **{c['titre']}** — {c['preuve']}" for c in forces] or ["- Rien de saillant pour l'instant."]
    lignes += ["", f"#### 🔴 Critiques et points de vigilance ({len(critiques)})"]
    lignes += [f"- {NIVEAUX[c['niveau']]} **{c['titre']}** — {c['preuve']}" for c in critiques] or ["- Aucun point critique relevé."]
    lignes += ["", "#### 🧭 Stratégie : ce que disent les études de Boursy"]
    lignes += [f"- **{titre}** : {texte}" for titre, texte in PRINCIPES]
    lignes += ["", "#### 🗓️ Plan d'action"]
    numero = 0
    for horizon in HORIZONS:
        if not plan[horizon]:
            continue
        lignes.append(f"**{horizon}**")
        for c in plan[horizon]:
            numero += 1
            lignes.append(f"{numero}. {c['action']} *Pourquoi : {c['titre'].lower()}. Où : {c['ou']}.*")
    if not numero:
        lignes.append("- Rien d'urgent : continuez vos apports réguliers.")
    if infos:
        dans_le_plan = {id(c) for h in plan.values() for c in h}
        lignes += ["", "#### 🔵 À savoir"]
        lignes += [f"- **{c['titre']}** — {c['preuve']}"
                   + (f" → {c['action']} *({c['ou']})*" if c["action"] and id(c) not in dans_le_plan else "") for c in infos]
    lignes += ["", "*⚖️ Synthèse statistique et pédagogique du moteur Boursy, à partir de vos données et des études de Boursy. "
               "Elle ne dit pas quoi acheter ni vendre : les décisions vous appartiennent (Boursy n'est pas conseiller en "
               "investissements financiers).*"]
    return "\n".join(lignes)


def dossier_texte(d, constats):
    """Le dossier complet et le diagnostic de Boursy, en texte, pour Gemini."""
    rente_ctx = d["rente"] or {}
    solidite, repartition = rente_ctx.get("solidite"), rente_ctx.get("repartition") or {}
    t = ["PORTEFEUILLE"]
    t.append(f"- Valeur {_eur(d['valeur'])}, capital investi {_eur(d['cout'])}, liquidités {_eur(d['especes'])}, "
             f"en euros {_eur(d['exposition_eur'])}, en dollars {_eur(d['exposition_usd'])}")
    for a in d["actions"]:
        t.append(f"- {a['nom']} ({a['secteur']}, {a['enveloppe']}) : {_eur(a['valeur'])} ({_pc(a['poids'])}), "
                 f"plus-value {_eur(a['pv_eur'])} ({_pc1(a['pv_pct'] / 100)})")
    t.append("RENTE")
    t.append(f"- {_eur(d['dividendes_bruts'])} brut, {_eur(d['dividendes_nets'])} net par an ; par mois : "
             + ", ".join(f"{m} {_eur(v)}" for m, v in d["dividendes_par_mois"].items() if v > 0))
    if solidite:
        p = solidite["parts"]
        t.append(f"- Solidité : {_eur(p['solide'])} solides, {_eur(p['neutre'])} neutres ou non classés, {_eur(p['alerte'])} à "
                 f"surveiller ({', '.join(solidite['a_surveiller']) or 'aucune'}) ; l'année d'une crise comme 2020 : "
                 f"{_eur(solidite['rente_crise'])}")
        t.append(f"- Projection prudente (euros d'aujourd'hui, apport {_eur(d['budget'])} par mois, dividendes réinvestis au "
                 f"rendement médian des solides de {_pc1(solidite['rendement_achats'], signe=False)}, sans croissance réelle) : "
                 f"{_eur(solidite['rente_prudente_horizon'])} par an dans 10 ans, {_eur(rente_ctx['rente_20_ans'])} dans 20 ans")
    if repartition.get("rente", 0) > 0:
        t.append("- Par grand secteur : " + ", ".join(f"{s} {_pc(p)}" for s, _m, p in repartition["par_secteur"]))
        t.append("- Par pays du siège : " + ", ".join(f"{s} {_pc(p)}" for s, _m, p in repartition["par_pays"]))
        t.append(f"- Secteurs absents (du plus au moins résistant en 2020) : {', '.join(secteurs_absents(repartition)) or 'aucun'}")
    elif not d["acces_rente"]:
        t.append("- Solidité, diversification et projection : réservées aux offres Premium et Pro (ne pas les inventer)")
    t.append("APPORTS ET ALLOCATION")
    a = d["achats_12_mois"]
    t.append(f"- Budget mensuel {_eur(d['budget'])} ; achats enregistrés sur 12 mois : {a['nombre']} achat(s), "
             f"{_eur(a['montant'])}, sur {a['mois']} mois" + (" (journal vide)" if a["journal_vide"] else ""))
    achat_du_mois = ", ".join(f"{l['qte']} {l['nom']}" for l in d["plan"].get("lignes", []) if l.get("qte")) or "aucun"
    if d["allocation_personnalisee"]:
        t.append(f"- Allocation cible définie par l'utilisateur ({d['nb_cibles']} lignes)"
                 + (f" ; écart à la cible {d['plan']['ecart_avant']:.1f} % avant l'achat du mois, {d['plan']['ecart_apres']:.1f} % après"
                    if d["plan"].get("ecart_avant") is not None else "")
                 + f" ; achat du mois (calcul arithmétique de SA propre allocation) : {achat_du_mois}")
    else:
        t.append("- Allocation cible NON définie : l'achat du mois est un calcul par défaut, à parts égales entre les valeurs du "
                 "radar ; ce n'est pas un choix de l'utilisateur, ne le présente ni comme un plan d'achat ni comme un objectif, "
                 "et l'écart à cette répartition par défaut n'a pas de sens")
    perf = d["performance_vs_etf"]
    t.append("PERFORMANCE RÉELLE")
    t.append(f"- {_pc1(perf['tri'])} par an contre {_pc1(perf['tri_etf'])} pour un ETF MSCI World aux mêmes dates (depuis le "
             f"{_date_fr(perf['depuis'])})" if perf and perf.get("tri") is not None and perf.get("tri_etf") is not None
             else "- Non mesurée (journal des achats incomplet ou offre gratuite)")
    t.append("PEA, DÉCISIONS, VENTES, MARCHÉ")
    t.append(f"- Versements nets PEA : {_eur(d['versements_pea'])} sur {_eur(PLAFOND_PEA)}" if d["versements_pea"] else "- Versements PEA : inconnus")
    pea = d.get("pea") or {}
    if pea.get("premier_versement") is None:
        t.append("- Date du premier versement PEA : non renseignée (date des 5 ans inconnue)")
    elif pea["plus_de_5_ans"]:
        t.append(f"- PEA : premier versement le {date_fr(pea['premier_versement'])}, 5 ans atteints le "
                 f"{date_fr(pea['date_5_ans'])} (retraits partiels sans clôture, gain exonéré d'impôt sur le revenu, "
                 f"{_taux(TAUX_PRELEVEMENTS_SOCIAUX)} de prélèvements sociaux)")
    else:
        t.append(f"- PEA : premier versement le {date_fr(pea['premier_versement'])}, 5 ans le {date_fr(pea['date_5_ans'])} "
                 f"(dans {pea['jours_restants']} jours ; avant, tout retrait clôture le plan et le gain est imposé à "
                 f"{_taux(TAUX_IMPOT_REVENU + TAUX_PRELEVEMENTS_SOCIAUX)}, contre {_taux(TAUX_PRELEVEMENTS_SOCIAUX)} après)")
    c = d["carnet"]
    t.append(f"- Carnet de décisions : {c['total']} décision(s), {c['a_relire']} à relire, {c['avec_lecon']} avec leçon écrite")
    v = d["ventes"]
    t.append(f"- Ventes actées : {v['nombre']} ({v['a_perte']} à perte), plus-values {_eur(v['pv'])}")
    m = d["marche"]
    t.append(f"- Marché : VIX {m.get('vix', '?')}, CAC 40 {m.get('cac', '?')}, S&P 500 {m.get('sp', '?')}, 1 € = {m.get('eurusd', '?')} $")
    t.append(f"- Signaux forts du radar aujourd'hui (non prédictifs, voir principes) : {', '.join(d['signaux_forts']) or 'aucun'}")
    t.append("DIAGNOSTIC DE BOURSY (règles explicites, chiffres vérifiés)")
    t += [f"- [{c_['niveau']}] {c_['titre']} : {c_['preuve']}" + (f" Action ({c_['quand']}, {c_['ou']}) : {c_['action']}" if c_["action"] else "")
          for c_ in constats]
    t.append("PRINCIPES ISSUS DES ÉTUDES DE BOURSY")
    t += [f"- {titre} : {texte}" for titre, texte in PRINCIPES]
    return "\n".join(t)


CONSIGNES_SYNTHESE = """Rédige une synthèse stratégique franche et concrète, en français, avec exactement ces parties :
## 1. En bref (3 à 5 lignes : où en est l'utilisateur, son principal risque, son principal levier)
## 2. Votre rente : solidité, crise et projection (reprends exactement les chiffres du dossier : part solide, neutre et à surveiller avec les lignes concernées, rente l'année d'une crise comme 2020, projection prudente à 10 et 20 ans ; si ces chiffres manquent ou sont réservés aux offres payantes, dis-le simplement)
## 3. Ce qui va bien
## 4. Critiques (de la plus grave à la moins grave, chacune avec le chiffre du dossier qui la justifie)
## 5. Stratégie (cohérence entre l'objectif de rente, les apports, la diversification et la fiscalité du PEA, en t'appuyant sur les principes issus des études)
## 6. Plan d'action : « Ce mois-ci », « Ce trimestre », « Cette année », « En continu » ; pour chaque action : quoi faire, pourquoi (chiffre du dossier) et où dans Boursy
## 7. À surveiller, et deux ou trois questions que l'utilisateur devrait se poser
Règles : n'invente aucun chiffre ni aucune donnée ; si une information manque, dis-le. Pars du diagnostic de Boursy, que tu peux approfondir ou nuancer. Aucune recommandation d'achat ou de vente d'un titre précis, ni quantité ni prix : tu peux parler de secteurs, d'allocation, de méthode, de réserve, de diversification et de fiscalité. L'achat du mois n'est jamais une recommandation : c'est un calcul arithmétique, qui ne reflète les choix de l'utilisateur que s'il a défini son allocation cible. Ne présente jamais un signal du radar comme une prévision, ni un rendement élevé comme une qualité en soi. Termine par un rappel discret : synthèse pédagogique, Boursy n'est pas conseiller en investissements financiers."""
