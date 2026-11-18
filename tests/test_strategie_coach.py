"""Tests du dossier, du diagnostic et du plan d'action du coach (python -m pytest tests)."""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import strategie_coach as S  # noqa: E402
from diversification_rente import repartition_rente  # noqa: E402

AUJOURD_HUI = date(2026, 11, 18)
FICHES = {
    "TotalEnergies": {"symbole": "TTE.PA", "secteur": "Énergie", "mois_div": ["Jan", "Avr", "Juil", "Oct"]},
    "Rubis": {"symbole": "RUI.PA", "secteur": "Énergie/Stockage", "mois_div": ["Juin"]},
    "Sanofi": {"symbole": "SAN.PA", "secteur": "Santé", "mois_div": ["Mai"]},
}


def _rente(lignes_rente, solidite=True):
    rente = sum(r for *_x, r in lignes_rente)
    contexte = {"lignes": lignes_rente, "repartition": repartition_rente(lignes_rente), "solidite": None}
    if solidite:
        contexte["solidite"] = {
            "rente": rente, "parts": {"solide": rente * 0.2, "neutre": 0.0, "alerte": rente * 0.8},
            "a_surveiller": ["TotalEnergies"], "rente_crise": rente * 0.6, "horizon": 10,
            "rente_prudente_horizon": 2400.0, "apport_annuel": 5400.0, "rendement_achats": 0.034,
        }
        contexte["rente_20_ans"] = 5500.0
    return contexte


def _dossier(**changements):
    lignes_rente = [("TotalEnergies", "TTE.PA", "Énergie", 300.0), ("Rubis", "RUI.PA", "Énergie/Stockage", 200.0),
                    ("Sanofi", "SAN.PA", "Santé", 100.0)]
    parametres = dict(
        lignes_portefeuille=[
            {"nom_act": "TotalEnergies", "val_eur": 5000.0, "pv_eur": 500.0, "pv_pct": 11.0, "env_label": "PEA", "est_especes": False},
            {"nom_act": "Rubis", "val_eur": 3000.0, "pv_eur": -200.0, "pv_pct": -6.0, "env_label": "PEA", "est_especes": False},
            {"nom_act": "Sanofi", "val_eur": 2000.0, "pv_eur": 100.0, "pv_pct": 5.0, "env_label": "PEA", "est_especes": False},
            {"nom_act": "Espèces", "val_eur": 4000.0, "est_especes": True},
        ],
        valeur_totale=14000.0, cout_total=13600.0, budget_mensuel=450.0, dividendes_bruts=600.0, dividendes_nets=600.0,
        rente=_rente(lignes_rente), acces_rente=True, plan_dca={"ecart_avant": 20.0, "ecart_apres": 12.0, "lignes": []},
        allocation_personnalisee=False, portefeuille={}, ventes=[], performance_vs_etf=None, versements_pea=10000.0,
        exposition_eur=10000.0, exposition_usd=0.0, marche={"vix": 18.0}, signaux_forts=["Rubis"], fiches=FICHES,
        taux_usd_eur=1.1, aujourd_hui=AUJOURD_HUI,
    )
    parametres.update(changements)
    return S.construire_dossier(**parametres)


def _titres(constats, niveau=None):
    return [c["titre"] for c in constats if niveau is None or c["niveau"] == niveau]


def test_dossier():
    d = _dossier()
    assert d["especes"] == 4000.0 and [a["nom"] for a in d["actions"]] == ["TotalEnergies", "Rubis", "Sanofi"]
    assert d["actions"][0]["secteur"] == "Énergie" and abs(d["actions"][0]["poids"] - 5000 / 14000) < 1e-9
    assert d["dividendes_par_mois"]["Jan"] == 75.0 and d["dividendes_par_mois"]["Juin"] == 200.0
    assert d["achats_12_mois"]["journal_vide"] and d["carnet"]["total"] == 0
    assert _dossier(acces_rente=False)["rente"] is None  # réservé Premium et Pro


def test_critiques_principales():
    constats = S.diagnostiquer(_dossier())
    critiques = _titres(constats, "critique")
    assert critiques[0] == "Une grosse part de votre rente est à risque"  # 80 % à surveiller
    assert "Rente trop dépendante d'un secteur : Énergie" in critiques  # 83 % de la rente
    secteur = next(c for c in constats if c["titre"].startswith("Rente trop dépendante"))
    assert "Santé" not in secteur["action"] and "Immobilier" in secteur["action"]  # secteurs absents seulement
    assert "Rente sensible à une crise" in _titres(constats, "vigilance")  # -40 %
    assert "Peu de lignes de rente" in _titres(constats, "vigilance")
    assert "Des liquidités qui dorment" in _titres(constats, "vigilance")  # 4 000 € > 3 mois d'apports
    pas_de_cible = next(c for c in constats if c["titre"] == "Pas d'allocation cible")
    assert pas_de_cible["action"] is None  # l'action sur le secteur trop lourd la couvre
    assert "Vos apports sont le moteur de la rente" in _titres(constats, "force")
    assert [c["niveau"] for c in constats] == sorted((c["niveau"] for c in constats),
                                                     key=["critique", "vigilance", "force", "info"].index)


def test_performance_pea_discipline_et_marche():
    moins_bien = {"tri": 0.04, "tri_etf": 0.09, "depuis": "2021-03-01", "jours": 2000}
    constats = S.diagnostiquer(_dossier(performance_vs_etf=moins_bien, versements_pea=130000.0, marche={"vix": 30.0},
                                        portefeuille={"_carnet_decisions": [{"date": "2025-01-10", "action": "Rubis", "type": "achat"}],
                                                      "_journal_achats": [{"date": "2026-10-05", "qte": 2, "prix": 30.0}]},
                                        ventes=[{"plus_value_eur": -50}, {"plus_value_eur": -10}, {"plus_value_eur": 20}],
                                        exposition_usd=6000.0))
    titres = _titres(constats)
    assert "Votre sélection fait moins bien qu'un ETF Monde" in _titres(constats, "critique")
    for attendu in ("Plafond du PEA bientôt atteint", "Décisions à relire", "Beaucoup de ventes à perte", "Apports irréguliers"):
        assert attendu in _titres(constats, "vigilance"), attendu
    for attendu in ("Marché nerveux", "Une part importante en dollars", "Signaux du radar : pas des prévisions"):
        assert attendu in titres, attendu
    perf = next(c for c in constats if c["theme"] == "Performance")
    assert "−5,0 point" in perf["preuve"] or "-5,0 point" in perf["preuve"]
    mieux = S.diagnostiquer(_dossier(performance_vs_etf={"tri": 0.12, "tri_etf": 0.08, "depuis": "2025-06-01", "jours": 500}))
    gagnant = next(c for c in mieux if c["theme"] == "Performance")
    assert gagnant["niveau"] == "force" and "hasard" in gagnant["preuve"]  # moins de 3 ans


def test_offre_gratuite_sans_rente():
    constats = S.diagnostiquer(_dossier(acces_rente=False))
    assert not any(c["theme"] in ("Solidité", "Diversification", "Crise") for c in constats)
    assert "Solidité et diversification de la rente" in _titres(constats, "info")


def test_plan_d_action():
    constats = S.diagnostiquer(_dossier())
    plan = S.plan_action(constats)
    assert list(plan) == list(S.HORIZONS)
    actions = [c for h in plan.values() for c in h]
    assert 0 < len(actions) <= 7 and all(c["action"] and c["ou"] for c in actions)
    assert plan["Ce mois-ci"][0]["titre"] == "Rente trop dépendante d'un secteur : Énergie"
    assert S.plan_action(constats, maximum=2) and sum(len(h) for h in S.plan_action(constats, maximum=2).values()) == 2


def test_rapport_et_dossier_pour_gemini():
    d = _dossier()
    constats = S.diagnostiquer(d)
    rapport = S.rapport_markdown(d, constats)
    for partie in ("**En bref.**", "Ce qui va bien", "Critiques et points de vigilance", "Stratégie : ce que disent les études",
                   "Plan d'action", "**Ce mois-ci**", "n'est pas conseiller en investissements financiers"):
        assert partie in rapport, partie
    assert "Votre rente : solidité, crise et projection" in rapport and "Projection prudente" in rapport
    assert "L'année d'une crise comme 2020" in rapport
    assert "Réservées aux offres Premium et Pro" in S.rapport_markdown(_dossier(acces_rente=False), constats)
    sans_solidite = _dossier(rente=_rente([("Sanofi", "SAN.PA", "Santé", 100.0)], solidite=False))
    assert "Ajouter la solidité de ma rente" in S.rapport_markdown(sans_solidite, S.diagnostiquer(sans_solidite))
    texte = S.dossier_texte(d, constats)
    assert "Allocation cible NON définie" in texte and "écart à cette répartition par défaut n'a pas de sens" in texte
    avec_cible = _dossier(allocation_personnalisee=True, portefeuille={"_allocation_cible": [{"nom": "Sanofi", "poids": 50}]})
    assert "Allocation cible définie par l'utilisateur (1 lignes)" in S.dossier_texte(avec_cible, S.diagnostiquer(avec_cible))
    for partie in ("PORTEFEUILLE", "RENTE", "APPORTS ET ALLOCATION", "PERFORMANCE RÉELLE", "DIAGNOSTIC DE BOURSY",
                   "PRINCIPES ISSUS DES ÉTUDES", "TotalEnergies (Énergie, PEA)", "[critique] Une grosse part de votre rente est à risque"):
        assert partie in texte, partie
    assert "Aucune recommandation d'achat ou de vente d'un titre précis" in S.CONSIGNES_SYNTHESE
    assert "## 2. Votre rente : solidité, crise et projection" in S.CONSIGNES_SYNTHESE
    assert "L'achat du mois n'est jamais une recommandation" in S.CONSIGNES_SYNTHESE


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-q"]))
