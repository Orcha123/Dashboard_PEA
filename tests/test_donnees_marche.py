"""Tests des données de marché : lecture de Yahoo, heures de marché, calculs (python -m pytest tests)."""
import io
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import date, datetime

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import donnees_marche as D  # noqa: E402


def _instant(annee, mois, jour, heure=12):
    return int(datetime(annee, mois, jour, heure).timestamp())


class _Reponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _yahoo(monkeypatch, reponses, serveurs_en_panne=()):
    """Faux Yahoo : reponses[symbole] = résultat « chart » ; les serveurs listés sont en panne."""
    appels = []

    def faux_urlopen(requete, timeout=None):
        url = requete.full_url
        appels.append(url)
        if any(f"//{s}." in url for s in serveurs_en_panne):
            raise urllib.error.URLError("serveur en panne")
        if "/v1/finance/search" in url:
            return _Reponse(json.dumps(reponses["recherche"]).encode())
        symbole = urllib.request.unquote(url.split("/chart/")[1].split("?")[0])
        if symbole not in reponses:
            raise urllib.error.HTTPError(url, 404, "inconnu", {}, None)
        return _Reponse(json.dumps({"chart": {"result": [reponses[symbole]]}}).encode())

    monkeypatch.setattr(urllib.request, "urlopen", faux_urlopen)
    return appels


def test_heures_de_marche():
    lundi = datetime(2026, 11, 16)
    assert D.marches_ouverts(lundi.replace(hour=9, minute=0))
    assert not D.marches_ouverts(lundi.replace(hour=8, minute=59))
    assert D.marches_ouverts(lundi.replace(hour=22, minute=4))
    assert not D.marches_ouverts(lundi.replace(hour=22, minute=5))
    assert not D.marches_ouverts(datetime(2026, 11, 21, 15))  # samedi
    assert D.creneau_cours(lundi.replace(hour=10), instant=3600) == "S12"   # créneaux de 5 minutes en séance
    assert D.creneau_cours(lundi.replace(hour=23), instant=7200) == "F2"    # créneaux d'une heure sinon


def test_cours_et_historique_series_alignees(monkeypatch):
    appels = _yahoo(monkeypatch, {"AI.PA": {
        "meta": {"regularMarketPrice": 160.0},
        "indicators": {"quote": [{"close": [150.0, None, 155.0, 158.0], "high": [151.0, 999.0, None, 159.0], "low": [149.0, 1.0, 154.0, None]}]},
    }}, serveurs_en_panne=("query1",))
    prix, clotures, hauts, bas = D.cours_et_historique("AI.PA")
    assert prix == 160.0 and clotures == [150.0, 155.0, 158.0]
    assert hauts == [151.0, 155.0, 159.0] and bas == [149.0, 154.0, 158.0]  # séance sans clôture écartée, manques remplacés
    assert any("//query2." in u for u in appels)  # second serveur utilisé quand le premier est en panne
    with pytest.raises(RuntimeError):
        D.cours_et_historique("INCONNU.PA")


def test_historique_dix_ans(monkeypatch):
    jours = [_instant(2026, 11, 13), _instant(2026, 11, 16), _instant(2026, 11, 17), _instant(2026, 11, 18)]
    _yahoo(monkeypatch, {"TTE.PA": {
        "timestamp": jours,
        "indicators": {"quote": [{"close": [50.0, None, 52.0, 53.0], "high": [51.0, None, 53.0, 54.0], "low": [49.0, None, 51.0, 52.0]}]},
        "events": {"dividends": {"a": {"date": _instant(2026, 10, 1), "amount": 0.85}, "b": {"date": _instant(2026, 7, 1), "amount": 0.0}}},
    }})
    dates, clotures, dividendes, hauts, bas = D.historique_dix_ans("TTE.PA")
    assert dates == ["2026-11-13", "2026-11-17", "2026-11-18"] and clotures == [50.0, 52.0, 53.0]
    assert dividendes == [("2026-10-01", 0.85)]  # dividende nul ignoré
    # tâches du soir : la séance du jour, pas encore close, est écartée
    dates_closes = D.historique_dix_ans("TTE.PA", seances_closes_seulement=True, aujourd_hui=date(2026, 11, 18))[0]
    assert dates_closes == ["2026-11-13", "2026-11-17"]
    with pytest.raises(RuntimeError):
        D.historique_dix_ans("INCONNU.PA")


def test_dernier_cours_taux_et_indice(monkeypatch):
    _yahoo(monkeypatch, {
        "AI.PA": {"meta": {"regularMarketPrice": 160.5}},
        "ZERO.PA": {"meta": {"regularMarketPrice": 0}},
        "EURUSD=X": {"meta": {"regularMarketPrice": 1.0862}},
        "^FCHI": {"meta": {"regularMarketPrice": 8100.0}, "indicators": {"quote": [{"close": [7900.0, None, 8000.0, 8100.0]}]}},
    })
    assert D.dernier_cours("AI.PA") == 160.5
    assert D.dernier_cours("ZERO.PA") is None and D.dernier_cours("INCONNU") is None  # jamais de valeur inventée
    assert D.taux_eur_usd() == 1.0862
    niveau, variation = D.niveau_et_variation("^FCHI")
    assert niveau == 8100.0 and abs(variation - 1.25) < 1e-9  # comparé à la clôture de la veille (séances vides écartées)
    with pytest.raises(RuntimeError):
        D.niveau_et_variation("^INCONNU")


def test_tendance_ema():
    assert D.tendance_ema_2_12([100.0] * 10)[0] == "⚪ Neutre"  # trop peu de séances
    assert D.tendance_ema_2_12([100.0 + i for i in range(30)])[0] == "🟢 Tendance haussière"
    assert D.tendance_ema_2_12([100.0 - i for i in range(30)])[0] == "🔴 Tendance baissière"


def test_inspection_du_dividende(monkeypatch):
    maintenant = datetime(2026, 11, 18, 12)
    _yahoo(monkeypatch, {"KO": {
        "meta": {"regularMarketPrice": 70.123, "currency": "usd"},
        "indicators": {"quote": [{"close": [69.0, 70.0]}]},
        "events": {"dividends": {
            "1": {"date": _instant(2026, 3, 14), "amount": 0.51}, "2": {"date": _instant(2026, 6, 13), "amount": 0.51},
            "3": {"date": _instant(2025, 6, 13), "amount": 0.49},  # plus d'un an : non compté
        }},
    }})
    assert D.inspecter_dividende("KO", maintenant) == (70.12, "USD", 1.02, ["Mar", "Juin"])
    assert D.inspecter_dividende("INCONNU", maintenant) == (None, "EUR", 0.0, ["Mai"])


def test_prochain_detachement(monkeypatch):
    _yahoo(monkeypatch, {"AI.PA": {"events": {"dividends": {"1": {"date": _instant(2025, 12, 20), "amount": 3.3},
                                                            "2": {"date": _instant(2026, 5, 20), "amount": 3.2}}}},
                         "SANS.PA": {"events": {}}})
    assert D.prochain_detachement("AI.PA", date(2026, 11, 18)) == (32, date(2026, 12, 20), 3.3)
    assert D.prochain_detachement("AI.PA", date(2026, 6, 1)) == (None, None, None)  # rien dans les 90 jours
    assert D.prochain_detachement("SANS.PA", date(2026, 11, 18)) == (None, None, None)


def test_recherche(monkeypatch):
    _yahoo(monkeypatch, {"recherche": {"quotes": [
        {"quoteType": "EQUITY", "symbol": "ai.pa", "shortname": "Air Liquide", "exchDisp": "Paris"},
        {"quoteType": "EQUITY", "symbol": "VOD.L", "shortname": "Vodafone", "exchDisp": "London"},
        {"quoteType": "OPTION", "symbol": "AAPL240119C"},
        {"quoteType": "ETF", "symbol": "CW8.PA", "shortname": "Amundi MSCI World"},
    ]}})
    resultats = D.rechercher_yahoo("air", deja_vus={"cw8.pa"})
    assert [r["symbole"] for r in resultats] == ["AI.PA", "VOD.L"]  # options et déjà vus écartés
    assert resultats[0]["devise"] == "EUR" and "devise à vérifier" in resultats[1]["label"]


def test_cours_a_la_date_et_rendement_annualise():
    historique = (["2026-01-02", "2026-01-05", "2026-01-06"], [10.0, 11.0, 12.0])
    assert D.cours_a_la_date(historique, "2026-01-04") == 10.0  # week-end : dernière clôture connue
    assert D.cours_a_la_date(historique, "2026-01-06") == 12.0
    assert D.cours_a_la_date(historique, "2025-12-31") is None and D.cours_a_la_date(None, "2026-01-06") is None
    taux = D.taux_rendement_interne([("2025-01-01", -1000.0), ("2026-01-01", 1100.0)])
    assert abs(taux - 0.10) < 1e-3
    deux_versements = D.taux_rendement_interne([("2025-01-01", -1000.0), ("2025-07-01", -1000.0), ("2026-01-01", 2000.0)])
    assert abs(deux_versements) < 1e-6  # rien gagné, rien perdu
    assert D.taux_rendement_interne([("2025-01-01", -1000.0)]) is None
    assert D.taux_rendement_interne([]) is None


def test_historique_mensuel_des_dividendes(monkeypatch):
    import calendar as cal
    from datetime import date

    import donnees_marche as M

    def point(annee, mois):  # point mensuel daté du 1er à minuit, heure de Paris (la veille en UTC)
        return cal.timegm((annee, mois, 1, 0, 0, 0)) - 3600

    reponse = {
        "meta": {"gmtoffset": 3600},
        "timestamp": [point(2025, 11), point(2025, 12), point(2026, 1)],
        "indicators": {"quote": [{"close": [10.0, 11.0, 12.0]}]},
        "events": {"dividends": {"1": {"date": cal.timegm((2025, 12, 10, 8, 0, 0)), "amount": 0.5}}},
    }
    demandes = []

    def lire(serveur, symbole, plage, evenements_dividendes=False, timeout=6, intervalle="1d", periode=None):
        demandes.append((intervalle, evenements_dividendes, plage, periode[1] - periode[0]))
        return reponse

    monkeypatch.setattr(M, "lire_chart", lire)
    dates, clotures, dividendes, _hauts, _bas = M.historique_mensuel_dividendes("X.PA", aujourd_hui=date(2026, 1, 20))
    assert dates == ["2025-11-30", "2025-12-31"] and clotures == [10.0, 11.0]  # janvier 2026 : mois en cours, exclu
    assert dividendes == [("2025-12-10", 0.5)]
    assert demandes[0][:3] == ("1mo", True, None) and demandes[0][3] > 10 * 365 * 86400  # dates explicites, 11 ans

    monkeypatch.setattr(M, "lire_chart", lambda *a, **k: {"timestamp": [], "indicators": {"quote": [{"close": []}]}})
    try:
        M.historique_mensuel_dividendes("X.PA")
        assert False, "RuntimeError attendue"
    except RuntimeError:
        pass
