"""Tests de l'étude des dividendes, sur des données simulées (python -m pytest tests)."""
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from etudes import dividendes as D  # noqa: E402
from etudes import lancer_etude_dividendes as L  # noqa: E402


def _mois(premier="1995-01", dernier="2026-10"):
    resultat, annee, numero = [], int(premier[:4]), int(premier[5:7])
    while f"{annee}-{numero:02d}" <= dernier:
        resultat.append(f"{annee}-{numero:02d}")
        annee, numero = (annee + 1, 1) if numero == 12 else (annee, numero + 1)
    return resultat


def _serie(dividendes_annuels, clotures=None, premier="1995-01", mois_versement=5):
    """Série avec un dividende par an (détaché en mai) : {année: montant}."""
    mois = _mois(premier)
    clotures = clotures or [100.0] * len(mois)
    dividendes = [(f"{a}-{mois_versement:02d}-15", m) for a, m in sorted(dividendes_annuels.items()) if m > 0]
    return D.preparer_serie(mois, clotures, dividendes)


def _marche_simule(nombre, graine, probabilite_baisse):
    """Cours au hasard ; dividende annuel qui progresse, avec des baisses selon la probabilité propre à chaque action."""
    hasard = random.Random(graine)
    mois = _mois()
    series = {}
    for k in range(nombre):
        cours, clotures = 100.0, []
        for _ in mois:
            cours *= 1.0 + hasard.gauss(0.006, 0.06)
            clotures.append(max(cours, 1.0))
        montant, dividendes = 3.0, {}
        for annee in range(1995, 2027):
            montant *= 0.5 if hasard.random() < probabilite_baisse(k) else 1.0 + hasard.gauss(0.04, 0.03)
            dividendes[annee] = montant
        series[f"Action {k:02d}"] = _serie(dividendes, clotures)
    return series


# ==============================================================================
# OUTILS ET CANDIDATS
# ==============================================================================
def test_dividende_annuel_et_baisse():
    assert D.dividendes_par_annee([("2020-05-02", 1.0), ("2020-11-20", 0.5), ("2021-05-03", 1.6)]) == {2020: 1.5, 2021: 1.6}
    assert D.est_baisse(1.0, 0.89) and D.est_baisse(1.0, 0.0)
    assert not D.est_baisse(1.0, 0.91) and not D.est_baisse(0.0, 0.0) and not D.est_baisse(0.0, 1.0)


def test_caracteristiques():
    reguliere = _serie({a: 1.0 + 0.1 * (a - 2010) for a in range(2010, 2026)})
    v = D.caracteristiques(reguliere, 2020)
    assert v["R"] is True and v["hausse_5_ans"] is True
    assert abs(v["H"] - 2.0 / 100.0) < 1e-12
    assert abs(v["G"] - ((2.0 / 1.5) ** 0.2 - 1.0)) < 1e-12
    assert abs(v["Q"] - 2.0 / 1.7) < 1e-12  # médiane des rendements 2015-2019 : 1,7 %

    coupee = _serie({**{a: 1.0 for a in range(2010, 2026)}, 2017: 0.5})
    assert D.caracteristiques(coupee, 2020)["R"] is False  # baisse en 2017, dans les 5 dernières années
    assert D.caracteristiques(coupee, 2023)["R"] is True  # plus de 5 ans après
    assert D.caracteristiques(_serie({2018: 1.0, 2019: 1.0}), 2020) is None  # pas de dividende en 2020
    assert D.caracteristiques(_serie({a: 1.0 for a in range(2010, 2026)}, premier="2016-02"), 2020) is None  # trop court
    assert D.caracteristiques(reguliere, 2026) is None  # année non terminée
    assert "G" not in D.caracteristiques(_serie({a: 1.0 for a in range(2016, 2026)}), 2020)  # pas de dividende en 2015


def test_candidats_n_utilisent_que_le_passe():
    hasard = random.Random(4)
    mois = _mois()
    clotures = [100.0 + hasard.random() for _ in mois]
    dividendes = {a: 1.0 + hasard.random() for a in range(1995, 2026)}
    serie = _serie(dividendes, clotures)
    futur = _serie({**dividendes, **{a: 0.0 for a in range(2021, 2026)}},
                   [c if m <= "2020-12" else c * 5 for m, c in zip(mois, clotures)])
    assert D.caracteristiques(serie, 2020) == D.caracteristiques(futur, 2020)
    assert D.caracteristiques(serie, 2021) != D.caracteristiques(futur, 2021)


# ==============================================================================
# MESURES SUIVANTES
# ==============================================================================
def test_mesures_suivantes():
    serie = _serie({**{a: 1.0 for a in range(2010, 2026)}, 2022: 0.5, 2023: 0.5})
    m = D.mesures_suivantes(serie, None, "EUR", 2020)
    assert m["baisse_1_an"] == 0.0 and m["baisse_3_ans"] == 1.0  # baisse en 2022
    assert abs(m["croissance_dividende_3_ans"] - (-0.5)) < 1e-12
    # cours constant à 100 : seul le dividende réinvesti rapporte
    assert abs(m["rendement_36_mois"] - (1.0 + 1.0 / 100) * (1.005) * (1.005) + 1.0) < 1e-12
    assert m["perte_36_mois"] == 0.0
    tardive = D.mesures_suivantes(serie, None, "EUR", 2023)
    assert "baisse_1_an" in tardive and "baisse_3_ans" not in tardive  # 2026 n'est pas terminée
    assert D.mesures_suivantes(serie, None, "EUR", 2025) == {}


def test_rendement_en_euros_et_perte():
    mois = _mois()
    clotures = [100.0] * len(mois)
    debut = mois.index("2021-01")
    clotures[debut] = 50.0  # -50 % en janvier 2021, puis retour à 100
    serie = D.preparer_serie(mois, clotures, [])
    # le dollar passe de 1,0 à 1,25 dollar pour 1 euro en janvier 2021 : -20 % pour un investisseur en euros
    change = {m: (1.0 if m < "2021-01" else 1.25) for m in mois}
    r = D.rendements_mensuels(serie, change, "USD", "2021-01", 2)
    assert abs(r[0] - (0.5 * 1.0 / 1.25 - 1.0)) < 1e-12 and abs(r[1] - 1.0) < 1e-12
    assert D.rendements_mensuels(serie, {}, "USD", "2021-01", 2) is None  # change absent : pas de rendement inventé
    rendement, perte = D.rendement_et_perte([0.1, -0.5, 0.2])
    assert abs(perte - 0.5) < 1e-12 and abs(rendement - (1.1 * 0.5 * 1.2 - 1.0)) < 1e-12


# ==============================================================================
# GROUPES ET CRITÈRES
# ==============================================================================
def test_groupes_de_l_annee():
    series = _marche_simule(30, graine=1, probabilite_baisse=lambda k: 0.1)
    obs = D.observations_dividendes(series, None, {}, range(2005, 2025))
    de_2010 = [o for o in obs if o["annee"] == 2010]
    assert len(de_2010) == sum(1 for s in series.values() if D.caracteristiques(s, 2010))
    assert sum(o["decision_H"] == "HAUT" for o in de_2010) == round(len(de_2010) * 0.2)
    for o in de_2010:
        solide = o["valeurs"]["R"] and o["valeurs"]["hausse_5_ans"] and o["decision_H"] == "AUTRE"
        assert (o["decision_S"] == "HAUT") == solide


def test_aucun_candidat_retenu_quand_les_baisses_sont_dues_au_hasard():
    series = _marche_simule(40, graine=20261118, probabilite_baisse=lambda k: 0.12)
    obs = D.observations_dividendes(series, None, {}, range(2000, 2025))
    verdicts = D.verdicts(D.mesurer(obs))
    assert not any(v.get("fiable") or v.get("alerte") for v in verdicts.values())
    assert D.decisions_pour_boursy(verdicts) == {"score": None, "alertes": []}


def test_regularite_detectee_quand_elle_persiste():
    # la moitié des entreprises baissent rarement leur dividende, l'autre souvent
    series = _marche_simule(40, graine=7, probabilite_baisse=lambda k: 0.02 if k % 2 else 0.35)
    obs = D.observations_dividendes(series, None, {}, range(2000, 2025))
    resultats = D.mesurer(obs)
    verdicts = D.verdicts(resultats)
    assert verdicts["R"]["fiable"] and verdicts["S"]["fiable"]
    assert resultats[("R", "baisse_3_ans", "test")]["haut_corrige"] < 0
    groupe, autres, _, _ = D.taux_par_groupe(obs, "R", "baisse_3_ans", "test")
    assert groupe < autres
    assert D.decisions_pour_boursy(verdicts)["score"] == "S"


def test_baisse_durable_et_journal():
    exceptionnel = {2018: 1.0, 2019: 2.0, 2020: 1.0, 2021: 1.0}  # dividende exceptionnel en 2019
    assert D.est_baisse(2.0, 1.0) and not D.est_baisse_durable(exceptionnel, 2020)
    assert D.est_baisse_durable({2018: 1.0, 2019: 1.0, 2020: 0.5}, 2020)
    assert D.est_baisse_durable({2019: 1.0, 2020: 0.5}, 2020)  # pas de dividende en 2018 : comparaison à 2019
    serie = _serie({**{a: 1.0 for a in range(2010, 2026)}, 2019: 2.0})
    m = D.mesures_suivantes(serie, None, "EUR", 2018)
    assert m["baisse_3_ans"] == 1.0 and m["baisse_durable_3_ans"] == 0.0
    assert D.baisses_de_l_annee({"A": serie}, 2020) == [("A", 2.0, 1.0, 1.0)]


def test_taux_de_baisse_par_annee():
    series = {f"A{k}": _serie({a: (0.5 if (a == 2020 and k < 4) else 1.0) for a in range(1995, 2026)}) for k in range(10)}
    taux = D.taux_de_baisse_par_annee(series, 2000)
    assert taux[2020] == (10, 4) and taux[2019] == (10, 0)


# ==============================================================================
# LANCEUR
# ==============================================================================
def test_lecture_avec_repli_sur_les_points_quotidiens(monkeypatch):
    from datetime import datetime, timezone

    def reponse(jours, clotures, dividendes=()):
        horodatage = lambda j: int(datetime(*j, tzinfo=timezone.utc).timestamp())  # noqa: E731
        return {"meta": {"gmtoffset": 0}, "timestamp": [horodatage(j) for j in jours],
                "indicators": {"quote": [{"close": clotures}]},
                "events": {"dividends": {str(horodatage(j)): {"date": horodatage(j), "amount": m} for j, m in dividendes}}}

    trimestriel = reponse([(2000 + i // 4, 3 * (i % 4) + 1, 1) for i in range(80)], [10.0] * 80)
    jours = [(2000 + i // 12, i % 12 + 1, 15) for i in range(240)]
    quotidien = reponse(jours, [20.0] * 240, [((2005, 5, 15), 1.0), ((2006, 5, 15), 1.1)])
    lus = []

    def lire(serveur, symbole, plage, evenements_dividendes=False, timeout=6, intervalle="1d", periode=None):
        lus.append((intervalle, evenements_dividendes))
        assert plage is None and periode[0] < 0
        return trimestriel if intervalle == "1mo" else quotidien

    monkeypatch.setattr(L, "lire_chart", lire)
    serie = L.serie_mensuelle("TEST.PA")
    assert lus == [("1mo", True), ("1d", True)]
    assert len(serie["mois"]) == 240 and serie["par_annee"] == {2005: 1.0, 2006: 1.1}


def test_rapport_complet_sur_donnees_simulees(monkeypatch, tmp_path):
    series = _marche_simule(24, graine=3, probabilite_baisse=lambda k: 0.03 if k % 2 else 0.3)
    noms = sorted(series)
    catalogue = {nom: (f"SIM{k}.PA", "USD" if k % 6 == 0 else "EUR", "Simulé", 0, 0, 0, "", []) for k, nom in enumerate(noms)}
    catalogue["ETF simulé"] = ("ETFSIM.PA", "EUR", "ETF Monde PEA", 0, 0, 0, "", [])
    par_symbole = {catalogue[nom][0]: series[nom] for nom in noms}
    change = {m: 1.1 for m in _mois()}
    monkeypatch.setattr(L, "ENRICHISSEMENT_CATALOGUE", catalogue)
    monkeypatch.setattr(L, "serie_mensuelle", lambda s, dividendes_voulus=True: par_symbole.get(s))
    monkeypatch.setattr(L, "change_mensuel", lambda: change)
    monkeypatch.setattr(L, "CHEMIN_RAPPORT", str(tmp_path / "rapport.md"))
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)

    assert L.main() == 0
    rapport = (tmp_path / "rapport.md").read_text(encoding="utf-8")
    assert "Actions : 24 du catalogue" in rapport  # l'ETF est écarté
    for titre in ("## Contexte", "## Mesure principale", "## Rendement total et perte maximale",
                  "## Mesures complémentaires", "## Verdict selon les critères pré-enregistrés",
                  "**Ce que le protocole prévoit pour Boursy**"):
        assert titre in rapport, titre
    assert "| 2020 |" in rapport and "| S Solide" in rapport and "## Contrôle exploratoire" in rapport


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-q"]))
