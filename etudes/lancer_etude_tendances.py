"""
Lance l'étude des grandes tendances sur les vraies données de Yahoo Finance et écrit le rapport
etudes/resultats_tendances.md (aussi affiché, et ajouté au résumé de la tâche GitHub quand elle tourne là).

Usage, depuis la racine du dépôt : python -m etudes.lancer_etude_tendances
Protocole pré-enregistré : etudes/protocole_tendances.md (aucun paramètre n'est réglé ici).
"""
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

from catalogue_valeurs import ENRICHISSEMENT_CATALOGUE
from donnees_marche import SERVEURS_YAHOO, historique_dix_ans, lire_chart
from etudes import tendances as T

INDICES = {"^GSPC": "S&P 500", "^FCHI": "CAC 40", "^GDAXI": "DAX", "^STOXX50E": "Euro Stoxx 50",
           "^N225": "Nikkei 225", "^FTSE": "FTSE 100"}
PERIODE_TEST_INDICES = "période de test (depuis 2022)"
CHEMIN_RAPPORT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resultats_tendances.md")


def historique_quotidien(symbole):
    try:
        return historique_dix_ans(symbole, seances_closes_seulement=True, timeout=20)
    except Exception:
        return None


DEBUT_HISTORIQUE = -2208994789  # 1er janvier 1900 en secondes Unix : tout l'historique disponible


def clotures_par_mois(resultat, mois_en_cours):
    """
    {« AAAA-MM » : dernière clôture du mois} d'une réponse Yahoo (points mensuels ou quotidiens), mois en cours exclu.
    Horodatages ramenés à l'heure de la place (+6 heures de marge : un point mensuel daté du 1er à minuit, heure
    d'hiver ou d'été, reste dans son mois ; un point quotidien reste dans sa journée).
    """
    decalage = int((resultat.get("meta") or {}).get("gmtoffset") or 0) + 6 * 3600
    clotures = ((resultat.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
    par_mois = {}
    for horodatage, cloture in sorted(zip(resultat.get("timestamp") or [], clotures)):
        if cloture is None or float(cloture) <= 0:
            continue
        mois = datetime.fromtimestamp(int(horodatage) + decalage, tz=timezone.utc).strftime("%Y-%m")
        if mois < mois_en_cours:
            par_mois[mois] = float(cloture)
    return par_mois


def _rang_mois(mois):
    return int(mois[:4]) * 12 + int(mois[5:7])


def mois_manquants(mois_tries):
    """Nombre de mois absents entre le premier et le dernier mois de la liste."""
    if not mois_tries:
        return 0
    return _rang_mois(mois_tries[-1]) - _rang_mois(mois_tries[0]) + 1 - len(mois_tries)


def derniere_suite_complete(mois_tries):
    """Les mois les plus récents qui se suivent sans aucun trou (tout si la série est complète)."""
    debut = len(mois_tries) - 1
    while debut > 0 and _rang_mois(mois_tries[debut]) - _rang_mois(mois_tries[debut - 1]) == 1:
        debut -= 1
    return mois_tries[debut:]


def historique_mensuel(symbole):
    """
    (fins de mois ISO, clôtures mensuelles) sur tout l'historique disponible, mois en cours exclu ; None si absent.
    Essaie les points mensuels, puis les points quotidiens ramenés à la dernière clôture de chaque mois. Les calculs
    supposent des mois consécutifs : en cas de trou, seuls les mois qui suivent le dernier trou sont gardés.
    """
    mois_en_cours = date.today().strftime("%Y-%m")
    periode = (DEBUT_HISTORIQUE, int(time.time()))
    candidates = []
    for intervalle in ("1mo", "1d"):
        resultat = None
        for serveur in SERVEURS_YAHOO:
            try:
                resultat = lire_chart(serveur, symbole, None, timeout=60, intervalle=intervalle, periode=periode)
                break
            except Exception:
                continue
        if resultat is None:
            continue
        par_mois = clotures_par_mois(resultat, mois_en_cours)
        mois_tries = sorted(par_mois)
        trous = mois_manquants(mois_tries)
        print(f"{symbole} ({intervalle}) : {len(mois_tries)} mois"
              + (f" de {mois_tries[0]} à {mois_tries[-1]}" if mois_tries else "") + f", {trous} mois manquants",
              file=sys.stderr)
        candidates.append((len(derniere_suite_complete(mois_tries)), derniere_suite_complete(mois_tries), par_mois))
        if trous == 0 and len(mois_tries) >= 36:
            break  # série mensuelle complète : inutile de lire les points quotidiens
    if not candidates:
        return None
    _, suite, par_mois = max(candidates, key=lambda c: c[0])
    if len(suite) < 36:
        return None
    return [fin_du_mois(m) for m in suite], [par_mois[m] for m in suite]


def fin_du_mois(mois):
    annee, numero = int(mois[:4]), int(mois[5:7])
    return (date(annee + (numero == 12), numero % 12 + 1, 1) - timedelta(days=1)).isoformat()


# ==============================================================================
# MISE EN FORME
# ==============================================================================
def pct(x, decimales=1, signe=True):
    if x is None:
        return "—"
    texte = f"{x * 100:+.{decimales}f}" if signe else f"{x * 100:.{decimales}f}"
    return texte.replace(".", ",") + " %"


def pts(x):
    return "—" if x is None else f"{x * 100:+.1f}".replace(".", ",") + " pt"


def fourchette(bas, haut):
    if bas is None or haut is None:
        return ""
    return " [" + f"{bas * 100:+.1f} ; {haut * 100:+.1f}".replace(".", ",") + "]"


def demontre(bas):
    """Fourchette entièrement au-dessus de zéro."""
    return bas is not None and bas > 0


def cellule_ecart(r, corrigee=False):
    if not r:
        return "—"
    texte = pts(r["moyenne"])
    if r.get("bas") is not None:
        texte += fourchette(r["bas_corrige"], r["haut_corrige"]) if corrigee else fourchette(r["bas"], r["haut"])
    return texte + f" ({r['nombre']} obs.)"


def bloc_comparaison(titre, comparaison):
    a, b = comparaison["regle"], comparaison["conservation"]
    bas_r, haut_r = comparaison["fourchette_rendement"]
    bas_p, haut_p = comparaison["fourchette_perte"]
    ameliore, reduit = demontre(bas_r), demontre(bas_p)
    return (
        f"| {titre} | {a['mois']} | {pct(b['rendement_annualise'])} | {pct(a['rendement_annualise'])} | "
        f"{pts(comparaison['ecart_rendement'])}{fourchette(bas_r, haut_r)} | {pct(b['perte_maximale'], signe=False)} | "
        f"{pct(a['perte_maximale'], signe=False)} | {pts(comparaison['reduction_perte'])}{fourchette(bas_p, haut_p)} | "
        f"{'✅' if ameliore else '❌'} rendement · {'✅' if reduit else '❌'} risque |"
    )


ENTETE_COMPARAISON = (
    "| Période | Mois | Conservation : rendement annualisé | Règle : rendement annualisé | Écart [fourchette 95 %] | "
    "Conservation : perte max. | Règle : perte max. | Perte évitée [fourchette 95 %] | Critères |\n"
    "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"
)


# ==============================================================================
# ÉTUDE
# ==============================================================================
def main():
    debut_chrono = time.time()
    actions = {nom: (sym, dev) for nom, (sym, dev, secteur, *_reste) in ENRICHISSEMENT_CATALOGUE.items() if "ETF" not in secteur}
    with ThreadPoolExecutor(max_workers=6) as executeur:
        lus = dict(zip(actions, executeur.map(lambda nom: historique_quotidien(actions[nom][0]), actions)))
        change = historique_quotidien("EURUSD=X")
        indices = dict(zip(INDICES, executeur.map(historique_mensuel, INDICES)))
    for nom in [n for n, h in lus.items() if not h]:  # seconde chance, une par une, pour les lectures échouées
        lus[nom] = historique_quotidien(actions[nom][0])
    if change is None:
        change = historique_quotidien("EURUSD=X")
    for symbole in [s for s, d in indices.items() if not d]:
        indices[symbole] = historique_mensuel(symbole)
    historiques = {nom: h for nom, h in lus.items() if h and len(h[0]) >= 260}
    devises = {nom: actions[nom][1] for nom in historiques}
    manquantes = sorted(set(actions) - set(historiques))
    if not historiques or change is None:
        print("Données indisponibles (Yahoo) : étude impossible.")
        return 1
    premiere = min(h[0][0] for h in historiques.values())
    derniere = max(h[0][-1] for h in historiques.values())
    fins_mois = T.fins_de_mois(premiere, derniere)

    # Question A
    observations = T.observations_selection(historiques, change, devises, fins_mois)
    selection = T.mesurer_selection(observations)
    verdicts_a = T.verdict_selection(selection)

    # Question B
    series = T.series_regle_actions(historiques, change, devises, fins_mois)
    comparaisons_b = {}
    for titre, debut, fin in (("Toute la période", None, None), ("Conception (avant 2022)", None, T.DEBUT_TEST),
                              ("Test (depuis 2022)", T.DEBUT_TEST, None)):
        conservation, regle, mois = T.portefeuilles_regle_actions(series, debut, fin)
        if len(mois) >= 24:
            comparaisons_b[titre] = T.comparer_avec_fourchettes(regle, conservation)
    parts_b = {"tout": T.parts_actions_ameliorees(series), "test": T.parts_actions_ameliorees(series, T.DEBUT_TEST)}

    # Question C
    resultats_c = {}
    for symbole, nom in INDICES.items():
        donnees = indices.get(symbole)
        if not donnees:
            continue
        dates_m, clotures_m = donnees
        lignes = T.regle_indice(dates_m, clotures_m)
        periodes = {"Tout l'historique": (None, None)}
        periodes.update({titre: (deb, fin) for titre, deb, fin in T.SOUS_PERIODES_INDICES})
        periodes[PERIODE_TEST_INDICES] = (T.DEBUT_TEST, None)
        comparaisons = {}
        for titre, (deb, fin) in periodes.items():
            choisies = [l for l in lignes if (deb is None or l[0] >= deb) and (fin is None or l[0] < fin)]
            if len(choisies) >= 36:
                rendements = [r for _, r, _ in choisies]
                regle = T.appliquer_regle(rendements, [p for _, _, p in choisies])
                comparaisons[titre] = T.comparer_avec_fourchettes(regle, rendements)
                comparaisons[titre]["part_investi"] = sum(p for _, _, p in choisies) / len(choisies)
        resultats_c[symbole] = {
            "nom": nom, "debut": dates_m[0][:7], "comparaisons": comparaisons,
            "suivants": {h: T.rendements_suivants_selon_signal(dates_m, clotures_m, h) for h in T.HORIZONS},
        }

    # ==========================================================================
    # RAPPORT
    # ==========================================================================
    l = []
    l.append("# Résultats : peut-on anticiper les grandes tendances à 6 et 12 mois ?")
    l.append("")
    l.append(f"Calculé le {date.today().strftime('%d/%m/%Y')} sur les données de Yahoo Finance, selon le protocole "
             "pré-enregistré `etudes/protocole_tendances.md` (aucun paramètre ajusté).")
    l.append("")
    l.append(f"- Actions : {len(historiques)} du catalogue (hors ETF), cours du {premiere[8:10]}/{premiere[5:7]}/{premiere[:4]} "
             f"au {derniere[8:10]}/{derniere[5:7]}/{derniere[:4]}" + (f" ; sans historique : {', '.join(manquantes)}" if manquantes else "") + ".")
    l.append(f"- Décisions mensuelles de conception avant le {T.DEBUT_TEST[8:10]}/{T.DEBUT_TEST[5:7]}/{T.DEBUT_TEST[:4]}, de test ensuite.")
    l.append("")
    l.append("## A. Sélection : les actions du groupe « haut » font-elles mieux que les autres actions du même mois ?")
    l.append("")
    l.append("Écart moyen avec les autres actions du même mois, en points, avec la fourchette à 95 %. Colonne « corrigée » : "
             "fourchette élargie pour les 10 essais (critère pré-enregistré).")
    l.append("")
    l.append("| Signal | Haut, 6 mois (test) | Haut, 12 mois (test) | Haut, 12 mois (test, corrigée) | Haut, 12 mois (conception) | Bas, 12 mois (test) | Critère |")
    l.append("| --- | --- | --- | --- | --- | --- | --- |")
    for signal, libelle in T.SIGNAUX.items():
        l.append(
            f"| {signal} {libelle} | {cellule_ecart(selection.get((signal, 6, 'HAUT', 'test')))} | "
            f"{cellule_ecart(selection.get((signal, 12, 'HAUT', 'test')))} | "
            f"{cellule_ecart(selection.get((signal, 12, 'HAUT', 'test')), corrigee=True)} | "
            f"{cellule_ecart(selection.get((signal, 12, 'HAUT', 'conception')))} | "
            f"{cellule_ecart(selection.get((signal, 12, 'BAS', 'test')))} | {'✅ rempli' if verdicts_a[signal] else '❌ non rempli'} |"
        )
    l.append("")
    l.append("## B. Suivre la tendance de chaque action (investi si cours > moyenne 200 jours)")
    l.append("")
    l.append("Portefeuille à parts égales de toutes les actions, chacune gérée par la règle, contre le même portefeuille "
             "conservé. Coût de 0,25 % par entrée ou sortie, liquidités à 0 %.")
    l.append("")
    l.append(ENTETE_COMPARAISON)
    for titre, comparaison in comparaisons_b.items():
        l.append(bloc_comparaison(titre, comparaison))
    l.append("")
    for cle, titre in (("tout", "toute la période"), ("test", "période de test")):
        p = parts_b[cle]
        if p["actions"]:
            l.append(f"- Sur {titre} : la règle améliore le rendement de {pct(p['rendement'], 0, False)} des actions "
                     f"({p['actions']}) et réduit la perte maximale de {pct(p['perte'], 0, False)} d'entre elles.")
    l.append("")
    l.append("## C. Grandes tendances du marché (indices, investi si clôture mensuelle > moyenne 10 mois)")
    l.append("")
    absents = [nom for symbole, nom in INDICES.items() if symbole not in resultats_c]
    if absents:
        l.append(f"Indices écartés faute d'une série mensuelle complète chez Yahoo : {', '.join(absents)}.")
        l.append("")
    for symbole, res in resultats_c.items():
        l.append(f"### {res['nom']} (`{symbole}`, depuis {res['debut'][5:7]}/{res['debut'][:4]})")
        l.append("")
        l.append(ENTETE_COMPARAISON)
        for titre, comparaison in res["comparaisons"].items():
            l.append(bloc_comparaison(f"{titre} (investi {pct(comparaison['part_investi'], 0, False)} du temps)", comparaison))
        l.append("")
        for h, s in res["suivants"].items():
            if s:
                l.append(f"- {h} mois suivants : {pct(s['au_dessus'])} en moyenne au-dessus de la moyenne ({s['mois_au_dessus']} mois), "
                         f"{pct(s['en_dessous'])} en dessous ({s['mois_en_dessous']} mois) ; écart {pts(s['ecart'])}"
                         f"{fourchette(*s['fourchette'])}.")
        l.append("")
    l.append("## Verdict selon les critères pré-enregistrés")
    l.append("")
    retenus = [f"{s} {T.SIGNAUX[s]}" for s, ok in verdicts_a.items() if ok]
    l.append("- **A. Sélection** : " + (("signal(aux) retenu(s) : " + ", ".join(retenus)) if retenus else
                                         "aucun signal ne remplit le critère sur la période de test."))
    test_b = comparaisons_b.get("Test (depuis 2022)")
    if test_b:
        l.append(f"- **B. Tendance par action** (période de test) : rendement "
                 f"{'amélioré' if demontre(test_b['fourchette_rendement'][0]) else 'non amélioré de façon démontrée'}, "
                 f"perte maximale {'réduite' if demontre(test_b['fourchette_perte'][0]) else 'non réduite de façon démontrée'}.")
    for titre in ["Tout l'historique"] + [t for t, _, _ in T.SOUS_PERIODES_INDICES] + [PERIODE_TEST_INDICES]:
        comparaisons = [r["comparaisons"][titre] for r in resultats_c.values() if titre in r["comparaisons"]]
        if not comparaisons:
            continue
        n_rend = sum(demontre(c["fourchette_rendement"][0]) for c in comparaisons)
        n_risque = sum(demontre(c["fourchette_perte"][0]) for c in comparaisons)
        majorite = len(comparaisons) / 2
        l.append(f"- **C. Tendance des indices** ({titre.lower()}, {len(comparaisons)} indices) : rendement amélioré de façon "
                 f"démontrée sur {n_rend}, perte maximale réduite de façon démontrée sur {n_risque} — retenu pour le rendement : "
                 f"{'oui' if n_rend > majorite else 'non'} ; pour le risque : {'oui' if n_risque > majorite else 'non'}.")
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
