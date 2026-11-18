"""
Journal des signaux en direct : enregistre une fois par mois, pour chaque action du catalogue, la décision des trois
algorithmes du bilan (score actuel, score actuel + filtre de tendance, nouveau score Tendance & Dividende).

Lancé chaque soir de bourse par la tâche planifiée (.github/workflows/alertes.yml) ; n'écrit que les actions pas encore
enregistrées pour le mois en cours. Les signaux sont figés avant de connaître la suite : c'est le test qui compte.

Variables d'environnement : SUPABASE_URL, SUPABASE_SERVICE_KEY. ALERTES_DRY_RUN=1 : calcule sans rien écrire.
"""
import sys
import time
from datetime import date

from alertes_quotidiennes import _env, requete_supabase
from donnees_marche import historique_dix_ans
from catalogue_valeurs import ENRICHISSEMENT_CATALOGUE
from moteur_signaux import evaluer_signaux_a_la_date

FENETRE = 756


def historique_yahoo(symbole):
    """(dates, clôtures, dividendes, plus hauts, plus bas) sur 10 ans, séances closes uniquement ; None si indisponible."""
    try:
        return historique_dix_ans(symbole, seances_closes_seulement=True, timeout=15)
    except Exception:
        return None


def main():
    essai = _env("ALERTES_DRY_RUN") == "1"
    manquantes = [n for n in ("SUPABASE_URL", "SUPABASE_SERVICE_KEY") if not _env(n)]
    if manquantes:
        print("Configuration incomplète, secrets manquants : " + ", ".join(manquantes))
        return 1
    mois = date.today().strftime("%Y-%m")
    deja = requete_supabase("GET", f"signaux_mensuels?select=symbole&mois=eq.{mois}") or []
    symboles_deja = {ligne["symbole"] for ligne in deja}

    lignes, sans_historique = [], []
    for nom, (symbole, _devise, secteur, _cible, _div, payout, _croissance, _mois) in ENRICHISSEMENT_CATALOGUE.items():
        if "ETF" in secteur or symbole in symboles_deja or symbole in {l["symbole"] for l in lignes}:
            continue
        historique = historique_yahoo(symbole)
        time.sleep(0.3)  # rythme raisonnable vis-à-vis de Yahoo
        if historique is None or len(historique[1]) < FENETRE:
            sans_historique.append(nom)
            continue
        dates, clotures, dividendes, hauts, bas = historique
        signaux = evaluer_signaux_a_la_date(dates, clotures, hauts, bas, dividendes, len(clotures) - 1, float(payout), FENETRE)
        lignes.append({
            "mois": mois, "symbole": symbole, "nom": nom, "date_cours": signaux["date"], "prix": signaux["prix"],
            "score_actuel": signaux["score"], "decision_actuelle": signaux["decision_actuelle"],
            "decision_tendance": signaux["decision_tendance"],
            "score_nouveau": signaux["score_nouveau"], "decision_nouveau": signaux["decision_nouveau"],
        })

    if lignes and not essai:
        requete_supabase("POST", "signaux_mensuels?on_conflict=mois,symbole", lignes,
                         preference="resolution=ignore-duplicates,return=minimal")
    print(f"{mois} : {len(symboles_deja)} action(s) déjà enregistrée(s), {len(lignes)} ajoutée(s)"
          + (" (essai, rien écrit)" if essai else "") + f", {len(sans_historique)} sans historique suffisant"
          + (f" ({', '.join(sans_historique)})" if sans_historique else "") + ".")
    return 0


if __name__ == "__main__":
    sys.exit(main())
