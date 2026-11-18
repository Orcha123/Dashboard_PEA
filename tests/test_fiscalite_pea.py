"""Tests des échéances fiscales du PEA (python -m pytest tests)."""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import fiscalite_pea as F  # noqa: E402

AUJOURD_HUI = date(2026, 11, 18)


def test_date_des_5_ans_et_anciennete():
    assert F.date_des_5_ans(date(2022, 3, 15)) == date(2027, 3, 15)
    assert F.date_des_5_ans(date(2024, 2, 29)) == date(2029, 3, 1)  # jamais un jour trop tôt
    assert F.anciennete(date(2022, 3, 15), AUJOURD_HUI) == (4, 8)
    assert F.anciennete(date(2022, 11, 19), AUJOURD_HUI) == (3, 11)  # le jour anniversaire n'est pas encore passé
    assert F.texte_anciennete(4, 8) == "4 ans et 8 mois" and F.texte_anciennete(1, 0) == "1 an"
    assert F.texte_anciennete(0, 3) == "3 mois" and F.date_fr(date(2027, 3, 1)) == "1er mars 2027"


def test_etat_avant_5_ans_avec_impot_d_un_retrait():
    etat = F.etat_pea({"_pea": {"premier_versement": "2022-03-15"}}, AUJOURD_HUI, versements=40000.0, valeur=50000.0)
    assert etat["date_5_ans"] == date(2027, 3, 15) and etat["plus_de_5_ans"] is False
    assert etat["jours_restants"] == (date(2027, 3, 15) - AUJOURD_HUI).days
    assert etat["gain"] == 10000.0
    assert abs(etat["impot_avant_5_ans"] - 3140.0) < 1e-6  # 12,8 % + 18,6 %
    assert abs(etat["impot_apres_5_ans"] - 1860.0) < 1e-6 and abs(etat["ecart_impot"] - 1280.0) < 1e-6
    assert abs(etat["part_plafond"] - 40000 / 150000) < 1e-9 and etat["reste_versable"] == 110000.0
    assert not etat["plafond_proche"] and etat["suggestion"] is None


def test_etat_apres_5_ans_plafond_proche_et_perte():
    etat = F.etat_pea({"_pea": {"premier_versement": "2019-06-01"}}, AUJOURD_HUI, versements=130000.0, valeur=120000.0)
    assert etat["plus_de_5_ans"] is True and etat["jours_restants"] == 0
    assert etat["plafond_proche"] and etat["gain"] == 0.0 and etat["impot_avant_5_ans"] == 0.0  # pas d'impôt sur une perte


def test_date_inconnue_suggestion_du_journal():
    portefeuille = {"_journal_achats": [
        {"date": "2023-05-10", "devise": "EUR"}, {"date": "2021-09-02", "devise": "USD"}, {"date": "2022-01-20"}]}
    etat = F.etat_pea(portefeuille, AUJOURD_HUI)
    assert etat["premier_versement"] is None and etat["date_5_ans"] is None
    assert etat["suggestion"] == date(2022, 1, 20)  # plus ancien achat en euros
    assert F.etat_pea({"_pea": {"premier_versement": "2030-01-01"}}, AUJOURD_HUI)["premier_versement"] is None  # futur
    assert F.etat_pea({"_pea": "n'importe quoi"}, AUJOURD_HUI)["premier_versement"] is None


def test_versements_nets_estimes():
    ventes = [{"plus_value_eur": 500.0, "devise": "€"}, {"plus_value_eur": 900.0, "devise": "$"}, {"plus_value_eur": -100.0}]
    assert F.versements_nets_estimes(10000.0, ventes, 600.0) == 10000.0 - (400.0 + 600.0)
    assert F.versements_nets_estimes(10000.0, [{"plus_value_eur": -3000.0}], 0.0) == 10000.0  # pertes : rien à retirer
    assert F.versements_nets_estimes(500.0, [], 900.0) == 0.0


def test_rappel_du_mois():
    def etat(premier):
        return F.etat_pea({"_pea": {"premier_versement": premier}}, AUJOURD_HUI)

    assert F.rappel_du_mois(etat("2022-01-10"), AUJOURD_HUI) == {"type": "bientot", "date_5_ans": date(2027, 1, 10), "jours": 53}
    assert F.rappel_du_mois(etat("2021-11-10"), AUJOURD_HUI)["type"] == "atteint"
    assert F.rappel_du_mois(etat("2022-06-10"), AUJOURD_HUI) is None  # trop loin
    assert F.rappel_du_mois(etat("2020-06-10"), AUJOURD_HUI) is None  # atteint depuis longtemps
    assert F.rappel_du_mois(F.etat_pea({}, AUJOURD_HUI), AUJOURD_HUI) is None


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-q"]))
