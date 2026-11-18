"""Tests du suivi de la solidité des dividendes en conditions réelles (python -m pytest tests)."""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import journal_solidite as J  # noqa: E402
import solidite_dividendes as S  # noqa: E402

JOURS = []
_jour = date(2016, 11, 21)
while _jour <= date(2027, 1, 8):
    if _jour.weekday() < 5:
        JOURS.append(_jour.isoformat())
    _jour += timedelta(days=1)


def _historique(symbole):
    """Historique simulé : dividende annuel en mai, en hausse ; un tiers des actions le divise par deux en 2024."""
    rang = sum(map(ord, symbole))
    cours = [30.0 + rang % 70] * len(JOURS)
    dividendes = [(f"{a}-05-15", (0.5 if (rang % 3 == 0 and a == 2024) else 1.0) * (1.0 + 0.04 * (a - 2016))) for a in range(2016, 2027)]
    return JOURS, cours, dividendes, cours, cours


class FauxSupabase:
    def __init__(self, deja=(), precedents=()):
        self.deja, self.precedents, self.appels, self.ecrits = list(deja), list(precedents), [], []

    def __call__(self, methode, chemin, corps=None, preference=""):
        self.appels.append((methode, chemin))
        if methode == "POST":
            self.ecrits.extend(corps)
            return None
        if "annee=eq." in chemin:
            return self.deja
        return self.precedents


def _environnement(monkeypatch, faux):
    monkeypatch.setenv("SUPABASE_URL", "https://faux.supabase.test")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "cle")
    monkeypatch.setenv("ALERTES_DRY_RUN", "")
    monkeypatch.setattr(J, "requete_supabase", faux)


def test_rien_hors_de_janvier_a_mars(monkeypatch):
    faux = FauxSupabase()
    _environnement(monkeypatch, faux)
    assert J.main(aujourd_hui=date(2026, 11, 18), lire=_historique) == 0
    assert faux.appels == []  # aucun appel réseau


def test_enregistrement_de_janvier(monkeypatch):
    faux = FauxSupabase(precedents=[{"symbole": "ANCIEN.PA", "nom": "Ancienne valeur"}])
    _environnement(monkeypatch, faux)
    assert J.main(aujourd_hui=date(2027, 1, 5), lire=_historique) == 0
    assert ("POST", "suivi_solidite?on_conflict=annee,symbole") in faux.appels
    lignes = {l["symbole"]: l for l in faux.ecrits}
    assert len(lignes) == len(S.symboles_catalogue()) + 1 and all(l["annee"] == 2026 for l in faux.ecrits)
    ancienne = lignes["ANCIEN.PA"]  # a quitté le catalogue : toujours suivie, avec son nom
    assert ancienne["dans_catalogue"] is False and ancienne["nom"] == "Ancienne valeur"
    totale = lignes["TTE.PA"]
    assert totale["dans_catalogue"] and totale["nom"] == "TotalEnergies"
    assert abs(totale["dividende"] - (1.0 + 0.04 * 10)) < 1e-9 and totale["seuil_rendement"] > 0
    assert {l["categorie"] for l in faux.ecrits} <= {"solide", "neutre", "alerte", "non classée"}
    assert any(l["categorie"] == "solide" for l in faux.ecrits) and any(l["categorie"] == "neutre" for l in faux.ecrits)


def test_pas_de_reecriture_ni_d_ecriture_sans_donnees(monkeypatch):
    faux = FauxSupabase(deja=[{"symbole": "TTE.PA"}])
    _environnement(monkeypatch, faux)
    assert J.main(aujourd_hui=date(2027, 2, 1), lire=_historique) == 0 and not faux.ecrits  # année déjà enregistrée
    faux = FauxSupabase()
    _environnement(monkeypatch, faux)
    assert J.main(aujourd_hui=date(2027, 1, 5), lire=lambda symbole: None) == 0 and not faux.ecrits  # Yahoo indisponible
    monkeypatch.setenv("ALERTES_DRY_RUN", "1")
    assert J.main(aujourd_hui=date(2027, 1, 5), lire=_historique) == 0 and not faux.ecrits  # essai
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "")
    assert J.main(aujourd_hui=date(2027, 1, 5), lire=_historique) == 1


def test_evaluation_du_suivi():
    def ligne(annee, symbole, categorie, dividende):
        return {"annee": annee, "symbole": symbole, "categorie": categorie, "dividende": dividende}

    lignes = [
        ligne(2026, "A", "solide", 1.0), ligne(2026, "B", "solide", 1.0), ligne(2026, "C", "alerte", 2.0),
        ligne(2026, "D", "neutre", 1.0), ligne(2026, "E", "non classée", 0.0), ligne(2026, "F", "solide", 1.0),
        ligne(2027, "A", "solide", 1.05), ligne(2027, "B", "neutre", 0.8), ligne(2027, "C", "neutre", 1.0),
        ligne(2027, "D", "neutre", 1.0), ligne(2027, "F", "solide", None),  # F illisible en 2027
        ligne(2028, "A", "solide", 1.1), ligne(2028, "B", "solide", 0.85), ligne(2028, "C", "alerte", 1.0),
        ligne(2028, "D", "neutre", 0.5), ligne(2029, "A", "solide", 1.1), ligne(2029, "B", "solide", 0.9),
        ligne(2029, "C", "alerte", 1.0), ligne(2029, "D", "neutre", 0.5),
    ]
    r = S.evaluer_suivi(lignes)
    un_an = r["cohortes"][2026][1]
    assert un_an["comptes"] == {"solide": (1, 2), "alerte": (1, 1), "neutre": (0, 1)} and un_an["illisibles"] == 1
    trois_ans = r["cohortes"][2026][3]
    assert trois_ans["comptes"] == {"solide": (1, 2), "alerte": (1, 1), "neutre": (1, 1)}  # D coupe en 2028
    assert 3 not in r["cohortes"][2027] and 3 not in r["cohortes"][2029] and 1 not in r["cohortes"][2029]
    assert r["total"][1]["solide"] == (1, 5)  # 2026 : A, B (baisse) ; 2027 : A ; 2028 : A, B
    assert S.evaluer_suivi([]) == {"cohortes": {}, "total": {1: {}, 3: {}}}


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-q"]))
