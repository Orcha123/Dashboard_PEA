"""Tests du carnet de décisions (python -m pytest tests, ou python tests/test_carnet_decisions.py)."""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import carnet_decisions as C  # noqa: E402


def _historique(debut, valeurs, dividendes=()):
    """Une séance par jour ouvré à partir de debut, avec les clôtures données."""
    dates, jour = [], date.fromisoformat(debut)
    while len(dates) < len(valeurs):
        if jour.weekday() < 5:
            dates.append(jour.isoformat())
        jour += timedelta(days=1)
    return dates, list(valeurs), list(dividendes), list(valeurs), list(valeurs)


def test_ajouter_mois():
    assert C.ajouter_mois(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert C.ajouter_mois("2026-08-31", 6) == date(2027, 2, 28)
    assert C.ajouter_mois(date(2026, 11, 17), 12) == date(2027, 11, 17)
    assert C.ajouter_mois(date(2024, 2, 29), 12) == date(2025, 2, 28)


def test_performance_avec_dividendes_et_jours_feries():
    hist = _historique("2026-01-05", [100.0] * 10 + [110.0] * 10, [("2026-01-20", 2.0)])
    # du lundi 5 janvier au vendredi 30 janvier : 100 -> 110 + 2 de dividende
    assert abs(C.performance_entre(hist, "2026-01-05", "2026-01-30") - 0.12) < 1e-12
    # un samedi prend la dernière séance close (vendredi)
    assert abs(C.performance_entre(hist, "2026-01-10", "2026-01-31") - 0.12) < 1e-12
    assert C.performance_entre(hist, "2025-12-01", "2026-01-30") is None  # avant l'historique
    assert C.performance_entre(hist, "2026-01-05", "2026-03-30") is None  # historique trop ancien pour cette date
    assert C.performance_entre(None, "2026-01-05", "2026-01-30") is None


def test_evaluation_achat_vente_et_change():
    action = _historique("2025-01-01", [100.0 + i * 0.1 for i in range(400)])
    reference = _historique("2025-01-01", [50.0 + i * 0.02 for i in range(400)])
    aujourd_hui = date.fromisoformat(action[0][-1])
    achat = C.nouvelle_decision("2025-02-03", "Alpha", "AAA.PA", "achat", "Sous mon prix cible", "Note")
    ev = C.evaluer_decision(achat, action, reference, aujourd_hui)
    six = ev["horizons"][6]
    assert six is not None and six["action"] > six["reference"] and abs(six["en_faveur"] - (six["action"] - six["reference"])) < 1e-12
    assert ev["horizons"][12] is not None and ev["depuis"]["en_faveur"] > 0
    vente = dict(achat, type="vente")
    ev_vente = C.evaluer_decision(vente, action, reference, aujourd_hui)
    assert ev_vente["horizons"][6]["en_faveur"] == -ev_vente["horizons"][6]["action"] < 0  # hausse manquée
    assert C.phrase_resultat("vente", 0.10, None).startswith("Hausse manquée de 10,0")
    assert C.phrase_resultat("attendre", -0.05, None).startswith("Baisse évitée de 5,0")
    assert "de mieux que l'ETF Monde" in C.phrase_resultat("achat", 0.12, 0.08)
    # valeur en dollars : +10 % en $, dollar qui baisse de 10 % (1 € = 1,0 $ puis 1,1 $) -> 0 % en euros
    usd = _historique("2025-01-01", [100.0] * 5 + [110.0] * 5)
    change = _historique("2025-01-01", [1.0] * 5 + [1.1] * 5)
    achat_usd = dict(achat, date="2025-01-01", devise="USD")
    ev_usd = C.evaluer_decision(achat_usd, usd, None, date.fromisoformat(usd[0][-1]), change)
    assert abs(ev_usd["depuis"]["action"]) < 1e-12 and ev_usd["depuis"]["en_faveur"] is None  # référence absente
    assert C.evaluer_decision(achat_usd, usd, None, date.fromisoformat(usd[0][-1]))["depuis"]["action"] is None  # change absent


def test_ecriture_relecture_et_bilan():
    pf = {"Alpha": {"qte": 1, "pru": 1}}
    d1 = C.ajouter_decision(pf, C.nouvelle_decision("2025-01-10", "Alpha", "AAA.PA", "achat", "Sous mon prix cible", "x" * 500))
    d2 = C.ajouter_decision(pf, C.nouvelle_decision("2026-10-01", "Beta", "BBB.PA", "vente", "Prise de bénéfices"))
    assert len(d1["note"]) == C.LONGUEUR_NOTE_MAX and pf["Alpha"] == {"qte": 1, "pru": 1}
    carnet = C.lire_carnet(pf)
    assert [d["action"] for d in carnet] == ["Beta", "Alpha"]
    aujourd_hui = date(2026, 11, 17)
    assert [d["action"] for d in C.decisions_a_relire(carnet, aujourd_hui)] == ["Alpha"]
    assert C.decisions_arrivees_a_echeance(carnet, aujourd_hui) == []  # échéance passée depuis longtemps
    assert [d["action"] for d in C.decisions_arrivees_a_echeance(carnet, date(2025, 7, 20))] == ["Alpha"]
    assert C.enregistrer_lecon(pf, d1["id"], "Bonne intuition")
    assert C.decisions_a_relire(C.lire_carnet(pf), aujourd_hui) == []
    evaluations = {d1["id"]: {"horizons": {6: {"en_faveur": 0.04}}}, d2["id"]: {"horizons": {6: None}}}
    bilan = C.bilan_par_raison(C.lire_carnet(pf), evaluations)
    assert bilan == [{"type": "achat", "raison": "Sous mon prix cible", "nombre": 1, "moyenne": 0.04, "part_favorable": 1.0}]
    assert C.supprimer_decision(pf, d2["id"]) and [d["action"] for d in C.lire_carnet(pf)] == ["Alpha"]
    assert not C.supprimer_decision(pf, "inexistant")
    try:
        C.nouvelle_decision("2026-01-01", "A", "A", "spéculation", "Autre")
        assert False
    except ValueError:
        pass


if __name__ == "__main__":
    for nom_test, fonction in list(globals().items()):
        if nom_test.startswith("test_") and callable(fonction):
            fonction()
            print("ok", nom_test)
