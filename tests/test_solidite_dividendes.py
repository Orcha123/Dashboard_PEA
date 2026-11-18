"""Tests de la solidité des dividendes affichée dans Boursy (python -m pytest tests)."""
import os
import random
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import solidite_dividendes as S  # noqa: E402
from etudes import dividendes as D  # noqa: E402


def _historique(dividendes_annuels, debut="2016-11-21", fin="2026-11-17", cours=lambda jour: 100.0):
    """Historique quotidien (jours ouvrés) au format de donnees_marche.historique_dix_ans, un dividende par an en mai."""
    dates, jour = [], date.fromisoformat(debut)
    while jour <= date.fromisoformat(fin):
        if jour.weekday() < 5:
            dates.append(jour.isoformat())
        jour += timedelta(days=1)
    clotures = [cours(j) for j in dates]
    dividendes = [(f"{a}-05-15", m) for a, m in sorted(dividendes_annuels.items()) if m > 0]
    return dates, clotures, dividendes, clotures, clotures


def test_annee_de_reference():
    assert S.annee_de_reference(date(2026, 11, 18)) == 2025
    assert S.annee_de_reference(date(2027, 1, 2)) == 2026


def test_serie_mensuelle_et_memes_valeurs_que_l_etude():
    hasard = random.Random(3)
    historique = _historique({a: 1.0 + 0.05 * (a - 2016) for a in range(2016, 2027)}, cours=lambda j: 80 + hasard.random() * 40)
    serie = S.serie_mensuelle(historique)
    assert serie["mois"][0] == "2016-11" and serie["mois"][-1] == "2026-11"
    dernier_de_decembre = max(i for i, j in enumerate(historique[0]) if j.startswith("2025-12"))
    assert D.cloture_fin_annee(serie, 2025) == historique[1][dernier_de_decembre]
    valeurs = S.caracteristiques(historique, 2025)
    attendu = D.caracteristiques(serie, 2025)
    assert valeurs["retenue"] and {k: valeurs[k] for k in attendu} == attendu
    assert valeurs["dividendes"] == {a: 1.0 + 0.05 * (a - 2016) for a in range(2020, 2026)}


def test_mois_manquants_ecartes():
    historique = _historique({a: 1.0 for a in range(2016, 2027)})
    sans_mars_2019 = tuple([x for x, j in zip(serie, historique[0]) if not j.startswith("2019-03")] if i in (0, 1, 3, 4) else serie
                           for i, serie in enumerate(historique))
    assert S.serie_mensuelle(sans_mars_2019)["mois"][0] == "2019-04"


def test_actions_non_classees():
    assert S.caracteristiques(None, 2025) == {"retenue": False, "raison": "historique indisponible"}
    court = S.caracteristiques(_historique({a: 1.0 for a in range(2021, 2027)}, debut="2021-03-01"), 2025)
    assert not court["retenue"] and "historique trop court" in court["raison"]
    sans_dividende = S.caracteristiques(_historique({a: 1.0 for a in range(2016, 2025)}), 2025)
    assert not sans_dividende["retenue"] and sans_dividende["raison"] == "pas de dividende en 2025"
    verdict = S.statut(sans_dividende, {"H": 0.05}, 2025)
    assert verdict["libelle"] == "— Non classée" and verdict["explication"] == "pas de dividende en 2025"


def test_seuils_comme_dans_l_etude():
    valeurs = {f"A{k}": {"retenue": True, "H": 0.01 * k, "Q": 1.0 + 0.1 * k} for k in range(1, 21)}
    valeurs["B"] = {"retenue": False}
    seuils = S.seuils(valeurs)
    assert abs(seuils["H"] - 0.17) < 1e-12 and abs(seuils["Q"] - 2.7) < 1e-12  # les 4 plus élevés sur 20
    assert S.seuils({k: v for k, v in list(valeurs.items())[:9]}) == {}  # moins de 10 actions : pas de classement


def test_statuts():
    seuils = {"H": 0.06, "Q": 1.5}
    base = {"retenue": True, "R": True, "hausse_5_ans": True, "H": 0.03, "Q": 1.0, "dividendes": {}}
    assert S.statut(base, seuils, 2025)["libelle"] == "🛡️ Solide"
    eleve = S.statut(dict(base, H=0.07), seuils, 2025)
    assert not eleve["solide"] and eleve["libelle"] == "⚠️ Risque de baisse du dividende"
    assert "20 % les plus élevés" in eleve["explication"]
    anormal = S.statut(dict(base, Q=1.8), seuils, 2025)  # solide, mais rendement anormal : les deux sont dits
    assert anormal["solide"] and anormal["libelle"] == "🛡️ Solide, mais ⚠️ à surveiller"
    coupe = S.statut(dict(base, R=False), seuils, 2025)
    assert coupe["libelle"] == "Neutre" and "baisse ou interruption" in coupe["explication"]
    en_recul = S.statut(dict(base, hausse_5_ans=False), seuils, 2025)
    assert en_recul["libelle"] == "Neutre" and "moins élevé qu'en 2020" in en_recul["explication"]
    assert not S.statut(base, {}, 2025)["solide"]  # sans classement du catalogue, pas de verdict « solide »


def test_evolution_du_dividende():
    valeurs = {"dividendes": {2020: 1.0, 2021: 1.1, 2022: 0.0, 2023: 1.2, 2024: 1.25, 2025: 1.3}}
    assert S.evolution_dividende(valeurs, 2025) == "1,00 → 1,10 → 0,00 → 1,20 → 1,25 → 1,30"
    assert S.evolution_dividende(None, 2025) == "—" and S.evolution_dividende({"retenue": False}, 2025) == "—"


# ==============================================================================
# PROJECTION PRUDENTE
# ==============================================================================
def test_constantes_issues_de_l_etude():
    # pire année mesurée (départ 2019, donc 2020) : c'est le choc de crise
    assert S.CHOC_CRISE == {"solide": 0.867 - 1.0, "neutre": 0.762 - 1.0, "alerte": 0.478 - 1.0}
    assert all(set(m) == {1, 3, 5, 10} for m in S.EVOLUTION_REVENU.values())


def test_facteur_relatif():
    assert S.facteur_relatif("solide", 7) == 1.0
    assert all(S.facteur_relatif("neutre", n) == 1.0 for n in (1, 5, 20))  # jamais compté mieux que les solides
    assert abs(S.facteur_relatif("alerte", 1) - 0.992 / 1.118) < 1e-12
    assert abs(S.facteur_relatif("alerte", 10) - 1.448 / 2.046) < 1e-12
    assert S.facteur_relatif("alerte", 20) == S.facteur_relatif("alerte", 10)  # au-delà de 10 ans : écart des 10 ans
    entre = S.facteur_relatif("alerte", 2)
    assert S.facteur_relatif("alerte", 3) < entre < S.facteur_relatif("alerte", 1)


def test_projection_sans_apport():
    projection = S.projeter_rente([(1000.0, "solide"), (1000.0, "alerte")], annees=10)
    assert [n for n, _, _ in projection] == list(range(1, 11))
    annee_1 = projection[0]
    assert abs(annee_1[1] - (1000.0 + 1000.0 * S.facteur_relatif("alerte", 1))) < 1e-9
    assert abs(annee_1[2] - (1000.0 * 0.867 + 1000.0 * S.facteur_relatif("alerte", 1) * 0.478)) < 1e-9
    assert projection[-1][1] < annee_1[1]  # sans apport, la part « à surveiller » s'érode


def test_projection_avec_apports_et_reinvestissement():
    sans = S.projeter_rente([(1000.0, "solide")], apport_annuel=1200.0, rendement_achats=0.04, annees=3)
    assert [round(r, 6) for _, r, _ in sans] == [1048.0, 1096.0, 1144.0]  # +48 € de rente par an d'apports
    avec = S.projeter_rente([(1000.0, "solide")], apport_annuel=1200.0, rendement_achats=0.04, reinvestir=True, annees=2)
    assert round(avec[0][1], 6) == 1088.0  # 1000 + 4 % x (1200 + 1000)
    assert round(avec[1][1], 6) == round(1088.0 + 0.04 * (1200.0 + 1088.0), 6)
    assert S.projeter_rente([], apport_annuel=1200.0, rendement_achats=0.05, annees=1) == [(1, 60.0, 60.0 * 0.867)]


def test_euros_courants_et_categories():
    assert abs(S.en_euros_courants(100.0, 10) - 100.0 * 1.02 ** 10) < 1e-9
    assert S.categorie_projection({"alertes": ["x"], "solide": True}) == "alerte"
    assert S.categorie_projection({"alertes": [], "solide": True}) == "solide"
    assert S.categorie_projection({"alertes": [], "solide": False}) == "neutre"
    assert S.categorie_projection(None) == "neutre"  # non classée


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-q"]))
