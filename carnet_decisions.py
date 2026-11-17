"""
Carnet de décisions de Boursy (module sans Streamlit).

À chaque décision (acheter, vendre, ou attendre au lieu d'acheter), l'utilisateur note en une phrase pourquoi, avec
une raison choisie dans une liste courte. Plus tard, Boursy montre ce qu'est devenue la valeur, dividendes compris,
face à l'ETF MSCI World (CW8) sur la même période, pour voir quels raisonnements ont tenu. Les décisions sont
enregistrées dans le portefeuille (clé technique « _carnet_decisions »).

Lecture des résultats :
- achat : la valeur a-t-elle fait mieux que l'ETF Monde, qu'on aurait pu acheter à la place ?
- vente, ou attendre au lieu d'acheter : quelle hausse a été manquée, ou quelle baisse évitée, en ne détenant pas la
  valeur ?
"""
import bisect
import time
from datetime import date, timedelta

CLE_CARNET = "_carnet_decisions"
SYMBOLE_REFERENCE = "CW8.PA"  # ETF Amundi MSCI World, déjà utilisé comme référence dans l'application
NOM_REFERENCE = "ETF Monde (CW8)"
HORIZONS_MOIS = (1, 3, 6, 12)
HORIZON_RELECTURE_MOIS = 6
LONGUEUR_NOTE_MAX = 300

TYPES_DECISION = {
    "achat": "Achat",
    "vente": "Vente",
    "attendre": "Attendre, ne pas acheter",
}
RAISONS = {
    "achat": ["Renforcement DCA (allocation cible)", "Sous mon prix cible", "Signal du radar", "Rendement du dividende",
              "Conviction long terme", "Actualité de l'entreprise", "Autre"],
    "vente": ["Prise de bénéfices", "Thèse invalidée", "Rééquilibrage", "Valorisation trop élevée", "Besoin de liquidités",
              "Autre"],
    "attendre": ["Trop cher", "Attendre une baisse", "Doute sur l'entreprise", "Pas de liquidités", "Autre"],
}


# ==============================================================================
# LECTURE ET ÉCRITURE DU CARNET (dans le dictionnaire du portefeuille)
# ==============================================================================
def lire_carnet(portefeuille):
    """Décisions enregistrées, les plus récentes d'abord."""
    brut = portefeuille.get(CLE_CARNET) if isinstance(portefeuille, dict) else None
    decisions = [d for d in (brut if isinstance(brut, list) else []) if isinstance(d, dict) and d.get("action") and d.get("date")]
    return sorted(decisions, key=lambda d: (str(d.get("date")), str(d.get("id"))), reverse=True)


def nouvelle_decision(jour, action, symbole, type_decision, raison, note="", devise="EUR", source="carnet", qte=None, prix=None):
    if type_decision not in TYPES_DECISION:
        raise ValueError(f"Type de décision inconnu : {type_decision}")
    decision = {
        "id": f"{time.time():.6f}",
        "date": str(jour)[:10],
        "action": str(action),
        "symbole": str(symbole or "").strip(),
        "type": type_decision,
        "raison": str(raison or "Autre"),
        "note": str(note or "").strip()[:LONGUEUR_NOTE_MAX],
        "devise": "USD" if devise == "USD" else "EUR",
        "source": source,
    }
    if qte:
        decision["qte"] = int(qte)
    if prix:
        decision["prix"] = float(prix)
    return decision


def ajouter_decision(portefeuille, decision):
    carnet = portefeuille.get(CLE_CARNET) if isinstance(portefeuille.get(CLE_CARNET), list) else []
    carnet.append(decision)
    portefeuille[CLE_CARNET] = carnet
    return decision


def supprimer_decision(portefeuille, id_decision):
    carnet = portefeuille.get(CLE_CARNET) if isinstance(portefeuille.get(CLE_CARNET), list) else []
    portefeuille[CLE_CARNET] = [d for d in carnet if not (isinstance(d, dict) and d.get("id") == id_decision)]
    return len(carnet) != len(portefeuille[CLE_CARNET])


def enregistrer_lecon(portefeuille, id_decision, texte):
    """« Ce que j'en retiens », écrit en relisant la décision."""
    for decision in portefeuille.get(CLE_CARNET) or []:
        if isinstance(decision, dict) and decision.get("id") == id_decision:
            decision["lecon"] = str(texte or "").strip()[:LONGUEUR_NOTE_MAX]
            decision["lecon_date"] = date.today().isoformat()
            return True
    return False


# ==============================================================================
# CALCULS
# ==============================================================================
def ajouter_mois(jour, nombre_mois):
    """Même jour, nombre_mois plus tard (ramené au dernier jour du mois si besoin)."""
    if isinstance(jour, str):
        jour = date.fromisoformat(jour[:10])
    mois_total = jour.month - 1 + nombre_mois
    annee, mois = jour.year + mois_total // 12, mois_total % 12 + 1
    dernier_jour = (date(annee + (mois == 12), mois % 12 + 1, 1) - timedelta(days=1)).day
    return date(annee, mois, min(jour.day, dernier_jour))


def _rang_au(dates, jour_iso):
    """Dernière séance close au plus tard ce jour-là (None si avant le début de l'historique)."""
    rang = bisect.bisect_right(dates, jour_iso) - 1
    return rang if rang >= 0 else None


def performance_entre(historique, debut, fin):
    """
    Performance entre deux dates, dividendes détachés compris (cours de clôture de la dernière séance close à chaque
    date). None si l'historique ne couvre pas la période.
    """
    if not historique:
        return None
    dates, clotures, dividendes = historique[0], historique[1], historique[2]
    debut_iso, fin_iso = str(debut)[:10], str(fin)[:10]
    if not dates or fin_iso > dates[-1] and (date.fromisoformat(fin_iso) - date.fromisoformat(dates[-1])).days > 7:
        return None
    rang_debut, rang_fin = _rang_au(dates, debut_iso), _rang_au(dates, fin_iso)
    if rang_debut is None or rang_fin is None or rang_fin < rang_debut or clotures[rang_debut] <= 0:
        return None
    if (date.fromisoformat(debut_iso) - date.fromisoformat(dates[rang_debut])).days > 7:
        return None  # trou dans l'historique : pas de cours proche de la date de décision
    detaches = sum(m for d, m in dividendes if dates[rang_debut] < d <= dates[rang_fin])
    return (clotures[rang_fin] + detaches) / clotures[rang_debut] - 1.0


def _en_euros(performance, devise, historique_change, debut, fin):
    """Performance d'une valeur en dollars convertie en euros (historique de EURUSD=X : dollars pour 1 euro)."""
    if performance is None or devise != "USD":
        return performance
    variation_dollar = performance_entre(historique_change, debut, fin) if historique_change else None
    if variation_dollar is None:
        return None
    return (1.0 + performance) / (1.0 + variation_dollar) - 1.0


def en_faveur(type_decision, perf_action, perf_reference):
    """
    Ce que la décision a rapporté, en points :
    - achat : écart avec l'ETF Monde (positif si la valeur a fait mieux) ;
    - vente ou attente : baisse évitée (positif) ou hausse manquée (négatif) en ne détenant pas la valeur.
    """
    if perf_action is None:
        return None
    if type_decision == "achat":
        return None if perf_reference is None else perf_action - perf_reference
    return -perf_action


def phrase_resultat(type_decision, perf_action, perf_reference):
    """Lecture en une phrase, sans jugement de valeur."""
    if perf_action is None:
        return "Historique indisponible"
    pts = lambda x: f"{abs(x) * 100:.1f}".replace(".", ",")
    if type_decision == "achat":
        if perf_reference is None:
            return f"Valeur {perf_action * 100:+.1f} % ; ETF Monde indisponible".replace(".", ",")
        ecart = perf_action - perf_reference
        return (f"{pts(ecart)} pt(s) de mieux que l'ETF Monde" if ecart >= 0
                else f"{pts(ecart)} pt(s) de moins que l'ETF Monde")
    return (f"Hausse manquée de {pts(perf_action)} %" if perf_action > 0
            else f"Baisse évitée de {pts(perf_action)} %")


def evaluer_decision(decision, historique_action, historique_reference, aujourd_hui, historique_change=None):
    """
    Résultats d'une décision : depuis la décision (dernière séance close) et à chaque horizon atteint.
    Renvoie {"depuis": {...}, "horizons": {mois: {...} ou None}} ; chaque résultat contient action, reference,
    en_faveur (en fraction, ou None) et fin (date ISO).
    """
    jour = date.fromisoformat(str(decision["date"])[:10])
    devise = decision.get("devise", "EUR")

    def _mesure(fin):
        perf = _en_euros(performance_entre(historique_action, jour, fin), devise, historique_change, jour, fin)
        reference = performance_entre(historique_reference, jour, fin)
        return {"action": perf, "reference": reference, "en_faveur": en_faveur(decision["type"], perf, reference),
                "fin": fin.isoformat()}

    fin_depuis = aujourd_hui
    if historique_action and historique_action[0]:
        fin_depuis = min(aujourd_hui, date.fromisoformat(historique_action[0][-1]))
    resultat = {"depuis": _mesure(fin_depuis) if fin_depuis > jour else None, "horizons": {}}
    for mois in HORIZONS_MOIS:
        echeance = ajouter_mois(jour, mois)
        resultat["horizons"][mois] = _mesure(echeance) if echeance <= aujourd_hui else None
    return resultat


def decisions_a_relire(decisions, aujourd_hui, mois=HORIZON_RELECTURE_MOIS):
    """Décisions qui ont passé leur échéance de relecture et dont la leçon n'est pas encore écrite."""
    return [d for d in decisions if not d.get("lecon") and ajouter_mois(str(d["date"])[:10], mois) <= aujourd_hui]


def decisions_arrivees_a_echeance(decisions, aujourd_hui, mois=HORIZON_RELECTURE_MOIS, fenetre_jours=31):
    """Décisions sans leçon dont l'échéance tombe dans les fenetre_jours derniers jours (rappel du résumé mensuel)."""
    return [d for d in decisions_a_relire(decisions, aujourd_hui, mois)
            if (aujourd_hui - ajouter_mois(str(d["date"])[:10], mois)).days < fenetre_jours]


def bilan_par_raison(decisions, evaluations, horizon_mois=HORIZON_RELECTURE_MOIS):
    """
    Par type et par raison : nombre de décisions arrivées à l'horizon, résultat moyen en leur faveur (fraction) et part
    de décisions favorables. Seules les décisions qui ont atteint l'horizon comptent, pour comparer des durées égales.
    """
    groupes = {}
    for decision in decisions:
        mesure = (evaluations.get(decision.get("id")) or {}).get("horizons", {}).get(horizon_mois)
        if not mesure or mesure.get("en_faveur") is None:
            continue
        groupes.setdefault((decision["type"], decision.get("raison", "Autre")), []).append(mesure["en_faveur"])
    return sorted(
        ({"type": t, "raison": r, "nombre": len(v), "moyenne": sum(v) / len(v), "part_favorable": sum(1 for x in v if x > 0) / len(v)}
         for (t, r), v in groupes.items()),
        key=lambda g: (list(TYPES_DECISION).index(g["type"]), -g["nombre"], g["raison"]),
    )
