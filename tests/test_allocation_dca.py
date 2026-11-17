"""Tests du calcul de l'achat du mois (python -m pytest tests, ou python tests/test_allocation_dca.py)."""
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from allocation_dca import calculer_achat_du_mois, normaliser_poids  # noqa: E402
from catalogue_valeurs import symbole_a_jour  # noqa: E402


def _ligne(nom, poids, valeur, prix):
    return {"nom": nom, "poids_cible": poids, "valeur_eur": valeur, "prix_eur": prix}


def _par_nom(plan):
    return {l["nom"]: l for l in plan["lignes"]}


def test_parts_egales_portefeuille_vide():
    plan = calculer_achat_du_mois([_ligne("A", 1, 0, 100), _ligne("B", 1, 0, 50)], 450)
    l = _par_nom(plan)
    assert (l["A"]["qte"], l["B"]["qte"]) == (2, 5)
    assert abs(plan["investi"] - 450) < 1e-9 and abs(plan["reste"]) < 1e-9


def test_ligne_en_surpoids_non_renforcee():
    plan = calculer_achat_du_mois([_ligne("A", 50, 1000, 100), _ligne("B", 50, 0, 50)], 450)
    l = _par_nom(plan)
    assert l["A"]["qte"] == 0 and l["B"]["qte"] == 9
    assert plan["ecart_apres"] < plan["ecart_avant"]


def test_cours_inconnu_et_action_trop_chere():
    plan = calculer_achat_du_mois([_ligne("A", 1, 0, None), _ligne("B", 1, 0, 600), _ligne("C", 1, 0, 40)], 450)
    l = _par_nom(plan)
    assert l["A"]["qte"] == 0 and l["B"]["qte"] == 0 and l["B"]["trop_chere"]
    assert l["C"]["qte"] >= 1 and not l["C"]["trop_chere"]
    assert plan["investi"] <= 450 + 1e-9


def test_aucun_poids_positif():
    plan = calculer_achat_du_mois([_ligne("A", 0, 100, 10)], 450)
    assert plan["investi"] == 0 and plan["reste"] == 450


def test_normalisation():
    poids = normaliser_poids({"A": 2, "B": 1, "C": 0, "D": None})
    assert set(poids) == {"A", "B"} and abs(poids["A"] - 200 / 3) < 1e-9 and abs(sum(poids.values()) - 100) < 1e-9


def test_proprietes_sur_cas_aleatoires():
    rnd = random.Random(7)
    for _ in range(2000):
        lignes = [_ligne(f"L{i}", rnd.choice([0, 0.5, 1, 2, 5]), rnd.choice([0, rnd.uniform(0, 5000)]),
                         rnd.choice([None, rnd.uniform(1, 800)])) for i in range(rnd.randint(1, 8))]
        budget = rnd.uniform(0, 1500)
        plan = calculer_achat_du_mois(lignes, budget)
        assert -1e-6 <= plan["reste"] <= budget + 1e-6
        assert abs(plan["investi"] + plan["reste"] - budget) < 1e-6
        for l in plan["lignes"]:
            assert l["qte"] >= 0
            if l["prix_eur"] is None or l["poids_cible"] == 0:
                assert l["qte"] == 0
            if l["qte"] > 0:  # jamais plus d'une demi-action au-dessus de la cible
                assert l["valeur_apres"] - l["valeur_visee"] <= l["prix_eur"] / 2 + 1e-6
            if l["prix_eur"] is not None and l["poids_cible"] > 0 and l["prix_eur"] <= plan["reste"]:
                # rien d'achetable n'est laissé alors qu'il manquerait plus d'une demi-action à la ligne
                assert l["valeur_visee"] - l["valeur_apres"] < l["prix_eur"] / 2 + 1e-6


def test_symboles_renommes():
    assert symbole_a_jour("FDJ.PA") == "FDJU.PA"
    assert symbole_a_jour("fdj.pa") == "FDJU.PA"
    assert symbole_a_jour(" AI.PA ") == "AI.PA"


if __name__ == "__main__":
    for nom_test, fonction in list(globals().items()):
        if nom_test.startswith("test_") and callable(fonction):
            fonction()
            print("ok", nom_test)
