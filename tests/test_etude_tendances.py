"""Tests de l'étude des grandes tendances, sur des cours simulés (python -m pytest tests)."""
import math
import os
import random
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from etudes import lancer_etude_tendances as L  # noqa: E402
from etudes import tendances as T  # noqa: E402


def _jours_ouvres(debut, nombre):
    dates, jour = [], date.fromisoformat(debut)
    while len(dates) < nombre:
        if jour.weekday() < 5:
            dates.append(jour.isoformat())
        jour += timedelta(days=1)
    return dates


def _historique(dates, clotures, dividendes=()):
    return list(dates), list(clotures), list(dividendes), list(clotures), list(clotures)


def _marches_simules(nombre_actions, seances, graine, derive_par_action=None, volatilite=0.015):
    """Cours quotidiens simulés : marche aléatoire, avec une dérive annuelle propre à chaque action si demandée."""
    hasard = random.Random(graine)
    dates = _jours_ouvres("2012-01-02", seances)
    historiques = {}
    for k in range(nombre_actions):
        derive = (derive_par_action[k] if derive_par_action else 0.0) / 252.0
        cours, clotures = 100.0, []
        for _ in dates:
            cours *= math.exp(derive + volatilite * hasard.gauss(0.0, 1.0))
            clotures.append(cours)
        historiques[f"Action {k:02d}"] = _historique(dates, clotures)
    return historiques, dates


# ==============================================================================
# OUTILS
# ==============================================================================
def test_fins_de_mois():
    assert T.fins_de_mois("2024-01-15", "2024-04-30") == ["2024-01-31", "2024-02-29", "2024-03-31", "2024-04-30"]
    assert T.fins_de_mois("2024-01-31", "2024-03-30") == ["2024-01-31", "2024-02-29"]


def test_rangs_centiles_avec_egalites():
    rangs = T.rangs_centiles({"a": 1.0, "b": 2.0, "c": 2.0, "d": 5.0})
    assert rangs == {"a": 0.0, "b": 0.5, "c": 0.5, "d": 1.0}


def test_statistiques():
    stats = T.statistiques([0.10, -0.50, 0.20])
    assert abs(stats["perte_maximale"] - 0.50) < 1e-12
    assert abs(stats["rendement_annualise"] - (1.1 * 0.5 * 1.2) ** 4 + 1.0) < 1e-12
    assert stats["mois"] == 3


def test_cout_a_chaque_changement_de_position():
    # départ investi : pas de coût en janvier ; sortie en février ; rien en mars ; retour en avril
    regle = T.appliquer_regle([0.01, 0.02, -0.03, 0.01], [1, 0, 0, 1], cout=0.0025)
    assert [round(r, 10) for r in regle] == [0.01, -0.0025, 0.0, 0.0075]


def test_fourchettes_deterministes_et_nulles_si_regle_identique():
    hasard = random.Random(1)
    rendements = [hasard.gauss(0.005, 0.04) for _ in range(120)]
    regle = T.appliquer_regle(rendements, [1 if hasard.random() < 0.7 else 0 for _ in rendements])
    assert T.comparer_avec_fourchettes(regle, rendements) == T.comparer_avec_fourchettes(regle, rendements)
    identique = T.comparer_avec_fourchettes(rendements, rendements)
    assert identique["fourchette_rendement"] == (0.0, 0.0) and identique["fourchette_perte"] == (0.0, 0.0)


# ==============================================================================
# AUCUNE DONNÉE FUTURE
# ==============================================================================
def test_signaux_n_utilisent_que_le_passe():
    historiques, dates = _marches_simules(1, 1500, graine=3)
    historique = historiques["Action 00"]
    jour = "2015-06-30"
    coupe = sum(1 for d in dates if d <= jour)
    tronque = tuple(serie[:coupe] for serie in historique[:2]) + ([],) + tuple(serie[:coupe] for serie in historique[3:])
    complet = T.signaux_a_la_date(historique, None, "EUR", jour)
    assert set(complet) >= {"S1", "S2", "S3", "S4", "rendement_dividende"}
    assert complet == T.signaux_a_la_date(tronque, None, "EUR", jour)


def test_regles_de_tendance_n_utilisent_que_le_passe():
    hasard = random.Random(5)
    clotures = [100.0]
    for _ in range(199):
        clotures.append(clotures[-1] * (1.0 + hasard.gauss(0.005, 0.05)))
    dates = [f"{2000 + i // 12}-{i % 12 + 1:02d}-28" for i in range(200)]
    avant = T.regle_indice(dates, clotures)
    modifie = clotures[:120] + [c * 3.0 for c in clotures[120:]]
    apres = T.regle_indice(dates, modifie)
    # lignes[j] : position décidée avec les clôtures jusqu'au rang j + 9 ; clôtures modifiées à partir du rang 120
    assert [p for _, _, p in avant[:111]] == [p for _, _, p in apres[:111]]
    assert avant[111][2] != apres[111][2]  # le test voit bien la modification dès qu'elle est connue

    historiques, jours = _marches_simules(1, 1200, graine=8)
    fins = T.fins_de_mois(jours[0], jours[-1])
    series = T.series_regle_actions(historiques, None, {}, fins)["Action 00"]
    (d, c, div, h, b) = historiques["Action 00"]
    coupe = sum(1 for j in d if j <= "2014-12-31")
    choc = {"Action 00": (d, c[:coupe] + [x * 0.3 for x in c[coupe:]], div, h, b)}
    series_choc = T.series_regle_actions(choc, None, {}, fins)["Action 00"]
    positions = [p for f, _, p in series if f <= "2015-01-31"]
    assert positions == [p for f, _, p in series_choc if f <= "2015-01-31"]


# ==============================================================================
# QUESTION A : SÉLECTION
# ==============================================================================
def test_aucun_signal_retenu_sur_des_marches_sans_previsibilite():
    historiques, dates = _marches_simules(30, 2600, graine=20261118)
    fins = T.fins_de_mois(dates[0], dates[-1])
    observations = T.observations_selection(historiques, None, {}, fins)
    resultats = T.mesurer_selection(observations)
    assert not any(T.verdict_selection(resultats).values())
    for signal in T.SIGNAUX:
        r = resultats[(signal, 12, "HAUT", "tout")]
        assert r["bas_corrige"] < 0 < r["haut_corrige"], (signal, r)
    # groupes de 20 % : 6 actions sur 30 en haut et en bas chaque mois
    du_mois = [o for o in observations if o["date"] == fins[-20]]
    assert sum(o.get("decision_S1") == "HAUT" for o in du_mois) == 6
    assert sum(o.get("decision_S1") == "BAS" for o in du_mois) == 6


def test_momentum_detecte_quand_les_tendances_persistent():
    derives = [-0.30 + 0.60 * k / 29 for k in range(30)]
    historiques, dates = _marches_simules(30, 2600, graine=7, derive_par_action=derives, volatilite=0.01)
    fins = T.fins_de_mois(dates[0], dates[-1])
    resultats = T.mesurer_selection(T.observations_selection(historiques, None, {}, fins))
    assert resultats[("S1", 12, "HAUT", "tout")]["bas_corrige"] > 0
    assert resultats[("S1", 12, "BAS", "tout")]["haut_corrige"] < 0


# ==============================================================================
# QUESTIONS B ET C : RÈGLES DE TENDANCE
# ==============================================================================
def test_regle_de_tendance_reduit_la_perte_d_un_krach_lent():
    clotures = [100.0 * 1.01 ** i for i in range(60)]
    clotures += [clotures[-1] * 0.95 ** i for i in range(1, 25)]
    clotures += [clotures[-1] * 1.01 ** i for i in range(1, 61)]
    dates = [f"{1990 + i // 12}-{i % 12 + 1:02d}-28" for i in range(len(clotures))]
    lignes = T.regle_indice(dates, clotures)
    regle = T.appliquer_regle([r for _, r, _ in lignes], [p for _, _, p in lignes])
    comparaison = T.comparer_avec_fourchettes(regle, [r for _, r, _ in lignes])
    assert comparaison["conservation"]["perte_maximale"] > 0.65
    assert comparaison["regle"]["perte_maximale"] < 0.25
    assert comparaison["reduction_perte"] > 0.4


def test_rendements_suivants_selon_signal():
    clotures = [100.0 * 1.01 ** i for i in range(60)] + [100.0 * 1.01 ** 59 * 0.98 ** i for i in range(1, 61)]
    dates = [f"{1990 + i // 12}-{i % 12 + 1:02d}-28" for i in range(len(clotures))]
    s = T.rendements_suivants_selon_signal(dates, clotures, 6)
    assert s["mois_au_dessus"] + s["mois_en_dessous"] == len(clotures) - 6 - 9
    assert s["au_dessus"] > s["en_dessous"] and s["ecart"] > 0


def test_portefeuilles_et_parts_actions():
    historiques, dates = _marches_simules(12, 1500, graine=11)
    fins = T.fins_de_mois(dates[0], dates[-1])
    series = T.series_regle_actions(historiques, None, {}, fins)
    conservation, regle, mois = T.portefeuilles_regle_actions(series)
    assert len(conservation) == len(regle) == len(mois) > 50
    assert mois == sorted(mois)
    parts = T.parts_actions_ameliorees(series)
    assert parts["actions"] == 12 and 0.0 <= parts["rendement"] <= 1.0 and 0.0 <= parts["perte"] <= 1.0


# ==============================================================================
# LANCEUR : RAPPORT COMPLET SANS RÉSEAU
# ==============================================================================
def test_rapport_complet_sur_donnees_simulees(monkeypatch, tmp_path):
    historiques, dates = _marches_simules(12, 2600, graine=13)
    noms = sorted(historiques)
    catalogue = {nom: (f"SIM{k}.PA", "EUR", "Simulé", 0, 0, 0, "", []) for k, nom in enumerate(noms)}
    catalogue["ETF simulé"] = ("ETFSIM.PA", "EUR", "ETF Monde PEA", 0, 0, 0, "", [])
    par_symbole = {catalogue[nom][0]: historiques[nom] for nom in noms}
    change = _historique(dates, [1.1] * len(dates))
    hasard = random.Random(2)
    mensuel = [100.0]
    for _ in range(239):
        mensuel.append(mensuel[-1] * (1.0 + hasard.gauss(0.006, 0.045)))
    fins_mensuelles = T.fins_de_mois("1995-01-01", "2014-12-31")

    monkeypatch.setattr(L, "ENRICHISSEMENT_CATALOGUE", catalogue)
    monkeypatch.setattr(L, "historique_quotidien", lambda s: change if s == "EURUSD=X" else par_symbole.get(s))
    monkeypatch.setattr(L, "historique_mensuel", lambda s: (fins_mensuelles, mensuel) if s in ("^GSPC", "^FCHI") else None)
    monkeypatch.setattr(L, "CHEMIN_RAPPORT", str(tmp_path / "rapport.md"))
    monkeypatch.setattr(T, "TIRAGES_BOOTSTRAP", 100)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)

    assert L.main() == 0
    rapport = (tmp_path / "rapport.md").read_text(encoding="utf-8")
    assert "Actions : 12 du catalogue" in rapport  # l'ETF est écarté
    for titre in ("## A. Sélection", "## B. Suivre la tendance", "## C. Grandes tendances", "### S&P 500", "### CAC 40",
                  "## Verdict selon les critères pré-enregistrés"):
        assert titre in rapport, titre
    assert "### DAX" not in rapport  # indice indisponible : absent, rien d'inventé
    assert "**A. Sélection** : aucun signal" in rapport


def test_mise_en_forme():
    assert L.fin_du_mois("2024-02") == "2024-02-29" and L.fin_du_mois("2023-12") == "2023-12-31"
    assert L.pct(0.1234) == "+12,3 %" and L.pct(0.5, 0, False) == "50 %" and L.pct(None) == "—"
    assert L.fourchette(-0.012, 0.034) == " [-1,2 ; +3,4]" and L.fourchette(None, 0.1) == ""
    assert L.demontre(0.001) and not L.demontre(0.0) and not L.demontre(None)


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-q"]))
