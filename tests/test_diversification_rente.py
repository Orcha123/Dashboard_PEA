"""Tests de la diversification de la rente (python -m pytest tests)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import diversification_rente as R  # noqa: E402
from catalogue_valeurs import ENRICHISSEMENT_CATALOGUE  # noqa: E402


def test_chaque_action_du_catalogue_a_un_grand_secteur_et_un_pays():
    for nom, (symbole, _devise, secteur, *_reste) in ENRICHISSEMENT_CATALOGUE.items():
        assert R.grand_secteur(secteur, symbole) != "Autre", (nom, secteur)
        assert R.pays_du_siege(symbole) != "Inconnu", (nom, symbole)
    assert set(R.BAISSES_CRISES) == {R.grand_secteur(v[2], v[0]) for v in ENRICHISSEMENT_CATALOGUE.values()} - {"ETF (déjà diversifiés)"}


def test_regroupements_delicats():
    assert R.grand_secteur("Santé/Assurance US", "UNH") == "Santé"  # pas « finance »
    assert R.grand_secteur("Énergie EUR", "ENEL.MI") == "Services publics" and R.grand_secteur("Énergie EUR", "SHELL.AS") == "Énergie"
    assert R.grand_secteur("Industrie/Tech") == "Industrie et construction" and R.grand_secteur("Logiciels/Tech") == "Technologie"
    assert R.grand_secteur("BTP/Télécoms") == "Industrie et construction"  # Bouygues
    assert R.grand_secteur("Luxe/Auto EUR") == "Luxe et spiritueux"  # Ferrari
    assert R.grand_secteur("Secteur inconnu") == "Autre" and R.grand_secteur(None) == "Autre"


def test_pays_du_siege():
    assert R.pays_du_siege("MC.PA") == "France" and R.pays_du_siege("SAP.DE") == "Allemagne"
    assert R.pays_du_siege("AIR.PA") == "Pays-Bas" and R.pays_du_siege("STLAP.PA") == "Pays-Bas"  # sièges néerlandais
    assert R.pays_du_siege("SHELL.AS") == "Royaume-Uni" and R.pays_du_siege("KO") == "États-Unis"
    assert R.pays_du_siege("XYZ.ZZ") == "Inconnu" and R.pays_du_siege("") == "Inconnu"


def test_repartition_de_la_rente():
    lignes = [
        ("LVMH", "MC.PA", "Luxe", 400.0),
        ("Hermès", "RMS.PA", "Luxe", 100.0),
        ("Allianz", "ALV.DE", "Assurance EUR", 200.0),
        ("Airbus", "AIR.PA", "Aéronautique/Défense", 100.0),
        ("Coca-Cola", "KO", "Consommation US", 100.0),
        ("ETF Monde", "CW8.PA", "ETF Monde PEA", 100.0),
        ("Sans dividende", "ASML.AS", "Semi-conducteurs EUR", 0.0),
    ]
    r = R.repartition_rente(lignes)
    assert r["rente"] == 1000.0
    assert r["par_secteur"][0] == ("Luxe et spiritueux", 500.0, 0.5)
    assert [s for s, _, _ in r["secteurs_trop_lourds"]] == ["Luxe et spiritueux"]
    assert [(n, p) for n, _, p in r["lignes_trop_lourdes"]] == [("LVMH", 0.4)]  # Allianz : 20 %, pas au-dessus
    assert dict((p, m) for p, m, _ in r["par_pays"]) == {"France": 500.0, "Allemagne": 200.0, "Pays-Bas": 100.0,
                                                         "États-Unis": 100.0, "ETF (déjà diversifiés)": 100.0}
    assert [(x["nom"], x["pays"]) for x in r["retenues"]] == [("Allianz", "Allemagne"), ("Airbus", "Pays-Bas")]
    assert abs(r["retenue_totale"] - (200.0 * 0.26375 + 100.0 * 0.15)) < 1e-9
    assert r["hors_pea"] == [("Coca-Cola", "États-Unis")]


def test_rente_bien_repartie_ou_vide():
    lignes = [(f"A{k}", f"A{k}.PA", s, 100.0) for k, s in enumerate(["Santé", "Énergie", "Banque", "Télécoms", "Luxe", "Immobilier"])]
    r = R.repartition_rente(lignes)
    assert not r["secteurs_trop_lourds"] and not r["lignes_trop_lourdes"] and not r["retenues"]
    vide = R.repartition_rente([])
    assert vide["rente"] == 0.0 and vide["par_secteur"] == [] and vide["lignes_trop_lourdes"] == []


def test_lignes_de_rente():
    portefeuille = {"LVMH": {"qte": 2, "pru": 600}, "Coca-Cola": {"qte": 10, "pru": 50}, "Vendue": {"qte": 0, "pru": 10},
                    "Inconnue": {"qte": 5, "pru": 10}, "_allocation_cible": [], "Espèces": {"qte": 1, "pru": 100}}
    fiches = {"LVMH": {"symbole": "MC.PA ", "secteur": "Luxe", "div_eur": 13.0, "devise": "EUR"},
              "Coca-Cola": {"symbole": "KO", "secteur": "Consommation US", "div_eur": 2.0, "devise": "USD"},
              "Vendue": {"symbole": "V.PA", "secteur": "Luxe", "div_eur": 1.0, "devise": "EUR"}}
    lignes = R.lignes_de_rente(portefeuille, fiches, 1.25)
    assert lignes == [("LVMH", "MC.PA", "Luxe", 26.0), ("Coca-Cola", "KO", "Consommation US", 10 * 2.0 / 1.25)]
    assert R.lignes_de_rente(portefeuille, fiches, 1.25, noms=["Coca-Cola"]) == [lignes[1]]


def test_phrase_de_crise():
    assert "1 des 6 valeurs de ce secteur a baissé ou suspendu son dividende" in R.phrase_crise("Énergie")
    assert "plutôt bien tenu" in R.phrase_crise("Énergie")
    assert "4 des 4 valeurs de ce secteur ont baissé ou suspendu leur dividende" in R.phrase_crise("Automobile")
    assert "une seule mauvaise année" in R.phrase_crise("Automobile")
    assert R.phrase_crise("Autre") == ""


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-q"]))
