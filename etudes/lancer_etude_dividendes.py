"""
Lance l'étude des dividendes sur les vraies données de Yahoo Finance et écrit le rapport etudes/resultats_dividendes.md
(aussi affiché, et ajouté au résumé de la tâche GitHub quand elle tourne là).

Usage, depuis la racine du dépôt : python -m etudes.lancer_etude_dividendes
Protocole pré-enregistré : etudes/protocole_dividendes.md (aucun paramètre n'est réglé ici).
"""
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from catalogue_valeurs import ENRICHISSEMENT_CATALOGUE
from donnees_marche import SERVEURS_YAHOO, dividendes_du_resultat, lire_chart
from etudes import dividendes as D
from etudes.lancer_etude_tendances import (
    DEBUT_HISTORIQUE, clotures_par_mois, derniere_suite_complete, fourchette, mois_manquants, pct, pts,
)

CHEMIN_RAPPORT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resultats_dividendes.md")
MINIMUM_MOIS = 72


# ==============================================================================
# DONNÉES
# ==============================================================================
def serie_mensuelle(symbole, dividendes_voulus=True):
    """
    Série de l'action sur tout l'historique : clôtures mensuelles sans trou (mois en cours exclu) et dividendes.
    Essaie les points mensuels, puis les points quotidiens si des mois manquent (ou si aucun dividende n'est
    renvoyé). Garde la lecture dont la suite de mois sans trou est la plus longue. None si moins de 6 ans.
    """
    mois_en_cours = date.today().strftime("%Y-%m")
    periode = (DEBUT_HISTORIQUE, int(time.time()))
    candidates = []
    for intervalle in ("1mo", "1d"):
        resultat = None
        for serveur in SERVEURS_YAHOO:
            try:
                resultat = lire_chart(serveur, symbole, None, evenements_dividendes=dividendes_voulus, timeout=60,
                                      intervalle=intervalle, periode=periode)
                break
            except Exception:
                continue
        if resultat is None:
            continue
        par_mois = clotures_par_mois(resultat, mois_en_cours)
        mois_tries = sorted(par_mois)
        dividendes = dividendes_du_resultat(resultat) if dividendes_voulus else []
        suite = derniere_suite_complete(mois_tries)
        print(f"{symbole} ({intervalle}) : {len(mois_tries)} mois"
              + (f" de {mois_tries[0]} à {mois_tries[-1]}" if mois_tries else "")
              + f", {mois_manquants(mois_tries)} mois manquants, {len(dividendes)} dividendes"
              + (f" depuis {dividendes[0][0][:4]}" if dividendes else ""), file=sys.stderr)
        candidates.append((len(suite), len(dividendes), suite, par_mois, dividendes))
        if mois_manquants(mois_tries) == 0 and len(mois_tries) >= MINIMUM_MOIS and (dividendes or not dividendes_voulus):
            break
    if not candidates:
        return None
    _, _, suite, par_mois, dividendes = max(candidates, key=lambda c: (c[0], c[1]))
    if len(suite) < MINIMUM_MOIS:
        return None
    return D.preparer_serie(suite, [par_mois[m] for m in suite], dividendes)


def change_mensuel():
    """{"AAAA-MM": dollars pour 1 euro en fin de mois}, ou None."""
    serie = serie_mensuelle("EURUSD=X", dividendes_voulus=False)
    return dict(zip(serie["mois"], serie["clotures"])) if serie else None


# ==============================================================================
# MISE EN FORME
# ==============================================================================
def taux(x):
    return "—" if x is None else f"{x * 100:.0f} %"


def cellule(r, corrigee=False):
    if not r:
        return "—"
    texte = pts(r["moyenne"])
    if r.get("bas") is not None:
        texte += fourchette(r["bas_corrige"], r["haut_corrige"]) if corrigee else fourchette(r["bas"], r["haut"])
    return texte


def marque(ok):
    return "✅" if ok else "❌"


# ==============================================================================
# ÉTUDE
# ==============================================================================
def main():
    debut_chrono = time.time()
    actions = {nom: (sym, dev) for nom, (sym, dev, secteur, *_reste) in ENRICHISSEMENT_CATALOGUE.items() if "ETF" not in secteur}
    with ThreadPoolExecutor(max_workers=6) as executeur:
        lues = dict(zip(actions, executeur.map(lambda nom: serie_mensuelle(actions[nom][0]), actions)))
        change = change_mensuel()
    for nom in [n for n, s in lues.items() if s is None]:  # seconde chance, une par une
        lues[nom] = serie_mensuelle(actions[nom][0])
    if change is None:
        change = change_mensuel()
    series = {nom: s for nom, s in lues.items() if s}
    devises = {nom: actions[nom][1] for nom in series}
    manquantes = sorted(set(actions) - set(series))
    if not series or change is None:
        print("Données indisponibles (Yahoo) : étude impossible.")
        return 1

    premiere_annee = min(int(s["mois"][0][:4]) for s in series.values()) + D.ANNEES_HISTORIQUE
    observations = D.observations_dividendes(series, change, devises, range(premiere_annee, D.FIN_TEST + 1))
    resultats = D.mesurer(observations)
    verdicts = D.verdicts(resultats)
    decisions = D.decisions_pour_boursy(verdicts)
    baisses_par_annee = D.taux_de_baisse_par_annee(series, premiere_annee - D.ANNEES_HISTORIQUE + 1)
    annees = sorted({o["annee"] for o in observations})
    par_annee = {a: sum(1 for o in observations if o["annee"] == a) for a in annees}
    conception = [a for a in annees if a <= D.FIN_CONCEPTION]
    test = [a for a in annees if D.DEBUT_TEST <= a <= D.FIN_TEST]

    # ==========================================================================
    # RAPPORT
    # ==========================================================================
    l = []
    l.append("# Résultats : un dividende régulier dans le passé annonce-t-il un dividende fiable ?")
    l.append("")
    l.append(f"Calculé le {date.today().strftime('%d/%m/%Y')} sur les données de Yahoo Finance, selon le protocole "
             "pré-enregistré `etudes/protocole_dividendes.md` (aucun paramètre ajusté).")
    l.append("")
    debuts = sorted(s["mois"][0] for s in series.values())
    l.append(f"- Actions : {len(series)} du catalogue (hors ETF) ; historique mensuel depuis {debuts[0][5:7]}/{debuts[0][:4]} "
             f"pour la plus ancienne, {debuts[len(debuts) // 2][5:7]}/{debuts[len(debuts) // 2][:4]} en médiane"
             + (f" ; sans historique exploitable : {', '.join(manquantes)}" if manquantes else "") + ".")
    if annees:
        l.append(f"- Décisions (31 décembre) : conception {conception[0] if conception else '—'}-{conception[-1] if conception else '—'}, "
                 f"test {test[0] if test else '—'}-{test[-1] if test else '—'} ; de {min(par_annee.values())} à "
                 f"{max(par_annee.values())} actions retenues par année.")
    l.append("- Baisse du dividende : plus de 10 % sur une année civile, suppression comprise. Groupes comparés aux autres "
             "actions retenues la même année.")
    l.append("")

    l.append("## Contexte : part des actions qui ont baissé leur dividende, année par année")
    l.append("")
    l.append("| Année | Actions qui versaient un dividende l'année précédente | Baisses | Part |")
    l.append("| --- | --- | --- | --- |")
    for annee, (versantes, baisses) in sorted(baisses_par_annee.items()):
        l.append(f"| {annee} | {versantes} | {baisses} | {taux(baisses / versantes)} |")
    l.append("")

    l.append("## Mesure principale : au moins une baisse du dividende dans les 3 années suivantes")
    l.append("")
    l.append("Part des actions du groupe et des autres qui ont connu une baisse, puis écart en points avec la fourchette "
             "à 95 % corrigée pour les 15 essais (critère pré-enregistré). Période de test : décisions de "
             f"{D.DEBUT_TEST} à {D.FIN_TEST - 2} pour cette mesure.")
    l.append("")
    l.append("| Candidat | Groupe : baisse en 3 ans (test) | Autres (test) | Écart (test, corrigé) | Écart (conception) | Critère |")
    l.append("| --- | --- | --- | --- | --- | --- |")
    for candidat, libelle in D.CANDIDATS.items():
        groupe, autres, n_g, n_a = D.taux_par_groupe(observations, candidat, "baisse_3_ans", "test")
        if candidat in D.CANDIDATS_FIABILITE:
            critere = f"{marque(verdicts[candidat]['fiable'])} dividende plus fiable"
        else:
            critere = f"{marque(verdicts[candidat]['alerte'])} signal d'alerte"
        l.append(f"| {candidat} {libelle} | {taux(groupe)} ({n_g} obs.) | {taux(autres)} ({n_a} obs.) | "
                 f"{cellule(resultats.get((candidat, 'baisse_3_ans', 'test')), corrigee=True)} | "
                 f"{cellule(resultats.get((candidat, 'baisse_3_ans', 'conception')))} | {critere} |")
    l.append("")

    l.append("## Rendement total et perte maximale sur 36 mois (dividendes réinvestis, en euros)")
    l.append("")
    l.append("Écart en points entre le groupe et les autres actions de la même année ; fourchette corrigée pour la période "
             "de test. Pour la perte maximale, un écart négatif signifie des pertes plus faibles dans le groupe.")
    l.append("")
    l.append("| Candidat | Rendement 36 mois (test, corrigé) | Rendement (conception) | Verdict | Perte max. (test, corrigé) | Perte max. (conception) | Verdict |")
    l.append("| --- | --- | --- | --- | --- | --- | --- |")
    for candidat, libelle in D.CANDIDATS.items():
        v = verdicts[candidat]
        l.append(f"| {candidat} {libelle} | {cellule(resultats.get((candidat, 'rendement_36_mois', 'test')), corrigee=True)} | "
                 f"{cellule(resultats.get((candidat, 'rendement_36_mois', 'conception')))} | {v['rendement']} | "
                 f"{cellule(resultats.get((candidat, 'perte_36_mois', 'test')), corrigee=True)} | "
                 f"{cellule(resultats.get((candidat, 'perte_36_mois', 'conception')))} | "
                 f"{'perte plus faible' if v['perte_plus_faible'] else 'pas de différence démontrée'} |")
    l.append("")

    l.append("## Mesures complémentaires (période de test, fourchettes à 95 % non corrigées)")
    l.append("")
    l.append("| Candidat | Baisse l'année suivante : groupe / autres | Écart | Rendement 12 mois : écart | Croissance du dividende en 3 ans : groupe / autres | Écart |")
    l.append("| --- | --- | --- | --- | --- | --- |")
    for candidat, libelle in D.CANDIDATS.items():
        g1, a1, _, _ = D.taux_par_groupe(observations, candidat, "baisse_1_an", "test")
        gc, ac, _, _ = D.taux_par_groupe(observations, candidat, "croissance_dividende_3_ans", "test")
        l.append(f"| {candidat} {libelle} | {taux(g1)} / {taux(a1)} | {cellule(resultats.get((candidat, 'baisse_1_an', 'test')))} | "
                 f"{cellule(resultats.get((candidat, 'rendement_12_mois', 'test')))} | {pct(gc)} / {pct(ac)} | "
                 f"{cellule(resultats.get((candidat, 'croissance_dividende_3_ans', 'test')))} |")
    l.append("")

    l.append("## Verdict selon les critères pré-enregistrés")
    l.append("")
    for candidat, libelle in D.CANDIDATS.items():
        v = verdicts[candidat]
        if candidat in D.CANDIDATS_FIABILITE:
            fiab = "dividende plus fiable" if v["fiable"] else "dividende plus fiable : non démontré"
        else:
            fiab = "signal d'alerte" if v["alerte"] else "signal d'alerte : non démontré"
        l.append(f"- **{candidat} {libelle}** : {fiab} ; rendement : {v['rendement']} ; perte maximale : "
                 f"{'plus faible' if v['perte_plus_faible'] else 'pas de différence démontrée'}.")
    l.append("")
    if decisions["score"]:
        l.append(f"**Ce que le protocole prévoit pour Boursy** : un score de solidité du dividende fondé sur "
                 f"{decisions['score']} ({D.CANDIDATS[decisions['score']]}).")
    else:
        l.append("**Ce que le protocole prévoit pour Boursy** : aucun score de solidité (aucun candidat ne remplit le critère).")
    if decisions["alertes"]:
        l.append("Alerte « rendement élevé, risque de baisse » fondée sur : "
                 + ", ".join(f"{c} ({D.CANDIDATS[c]})" for c in decisions["alertes"]) + ".")
    else:
        l.append("Pas d'alerte « rendement élevé » (critère non rempli).")
    l.append("")
    l.append(f"*Calcul effectué en {time.time() - debut_chrono:.0f} secondes.*")
    rapport = "\n".join(l) + "\n"

    with open(CHEMIN_RAPPORT, "w", encoding="utf-8") as fichier:
        fichier.write(rapport)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fichier:
            fichier.write(rapport)
    print(rapport)
    return 0


if __name__ == "__main__":
    sys.exit(main())
