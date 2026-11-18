"""
Suivi de la solidité des dividendes en conditions réelles (protocole : etudes/protocole_suivi_dividendes.md).

Une fois par an, au premier soir de bourse de janvier (nouvel essai chaque soir jusqu'à fin mars si les données
manquent), enregistre dans la table protégée suivi_solidite le classement de chaque action au 31 décembre de l'année
écoulée (solide, neutre, à surveiller ou non classée, avec les définitions de l'étude), et son dividende de l'année.
Les actions suivies les deux années précédentes le restent, même si elles ont quitté le catalogue : c'est ce qui
supprime le biais du survivant de l'étude. Une année enregistrée n'est jamais réécrite.

Lancé chaque soir de bourse par la tâche planifiée (.github/workflows/alertes.yml) ; hors de janvier à mars, ne fait
rien (aucun appel réseau). Variables : SUPABASE_URL, SUPABASE_SERVICE_KEY ; ALERTES_DRY_RUN=1 : calcule sans écrire.
"""
import sys
from datetime import date

import solidite_dividendes as S
from alertes_quotidiennes import _env, requete_supabase
from catalogue_valeurs import ENRICHISSEMENT_CATALOGUE

MOIS_ENREGISTREMENT = (1, 2, 3)


def lire_historique(symbole):
    """Historique sur 10 ans (dividendes compris), séances closes uniquement ; None si indisponible."""
    from donnees_marche import historique_dix_ans

    try:
        return historique_dix_ans(symbole, seances_closes_seulement=True, timeout=20)
    except Exception:
        return None


def lignes_du_classement(annee, actions_suivies, lire=None):
    """
    Lignes à enregistrer pour le classement au 31/12 de l'année : actions du catalogue (hors ETF) et actions déjà
    suivies ({symbole: nom}). Lève RuntimeError si le catalogue ne peut pas être classé (Yahoo indisponible).
    """
    lire = lire or lire_historique
    noms = {sym: nom for nom, (sym, _devise, secteur, *_reste) in ENRICHISSEMENT_CATALOGUE.items() if "ETF" not in secteur}
    valeurs_catalogue, seuils = S.analyser_catalogue(lire, annee, symboles=sorted(noms))
    lignes = []
    for symbole in sorted(set(valeurs_catalogue) | set(actions_suivies)):
        valeurs = valeurs_catalogue.get(symbole)
        if valeurs is None:
            valeurs = S.caracteristiques(lire(symbole), annee)
        verdict = S.statut(valeurs, seuils, annee)
        dividendes = valeurs.get("dividendes") or {}
        lignes.append({
            "annee": annee,
            "symbole": symbole,
            "nom": noms.get(symbole) or actions_suivies.get(symbole) or "",
            "dans_catalogue": symbole in noms,
            "categorie": S.categorie_projection(verdict) if valeurs.get("retenue") else "non classée",
            "alertes": " ; ".join(verdict["alertes"]),
            "rendement": valeurs.get("H"),
            "dividende": dividendes.get(annee),  # None : historique illisible
            "dividende_precedent": dividendes.get(annee - 1),
            "seuil_rendement": seuils.get("H"),
        })
    return lignes


def main(aujourd_hui=None, lire=None):
    aujourd_hui = aujourd_hui or date.today()
    if aujourd_hui.month not in MOIS_ENREGISTREMENT:
        print("Suivi de la solidité des dividendes : enregistrement annuel de janvier à mars, rien à faire aujourd'hui.")
        return 0
    essai = _env("ALERTES_DRY_RUN") == "1"
    manquantes = [n for n in ("SUPABASE_URL", "SUPABASE_SERVICE_KEY") if not _env(n)]
    if manquantes:
        print("Configuration incomplète, secrets manquants : " + ", ".join(manquantes))
        return 1
    annee = aujourd_hui.year - 1
    deja = requete_supabase("GET", f"suivi_solidite?select=symbole&annee=eq.{annee}&limit=1") or []
    if deja:
        print(f"Classement au 31/12/{annee} déjà enregistré : rien à faire.")
        return 0
    precedents = requete_supabase(
        "GET", f"suivi_solidite?select=symbole,nom&annee=gte.{annee - 2}&annee=lt.{annee}") or []
    actions_suivies = {l["symbole"]: l.get("nom") or "" for l in precedents}
    try:
        lignes = lignes_du_classement(annee, actions_suivies, lire)
    except RuntimeError:
        print("Historiques indisponibles (Yahoo) : nouvel essai au prochain soir de bourse.")
        return 0
    if not essai:
        # une seule requête : toutes les lignes de l'année sont écrites, ou aucune
        requete_supabase("POST", "suivi_solidite?on_conflict=annee,symbole", lignes,
                         preference="resolution=ignore-duplicates,return=minimal")
    comptes = {}
    for l in lignes:
        comptes[l["categorie"]] = comptes.get(l["categorie"], 0) + 1
    print(f"Classement au 31/12/{annee} : {len(lignes)} action(s)" + (" (essai, rien écrit)" if essai else " enregistrée(s)")
          + " : " + ", ".join(f"{n} {c}" for c, n in sorted(comptes.items()))
          + f" ; {sum(1 for l in lignes if not l['dans_catalogue'])} hors catalogue, suivie(s) depuis les années précédentes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
