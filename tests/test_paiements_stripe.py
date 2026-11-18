"""Tests des règles d'abonnement Stripe : qui a droit à Premium ou à Pro (python -m pytest tests)."""
import io
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import paiements_stripe as S  # noqa: E402


def _abonnement(statut="active", prix_id="price_inconnu", centimes=490, intervalle="month", nombre=1, **autres):
    return dict({"status": statut, "items": {"data": [{"price": {"id": prix_id, "unit_amount": centimes,
                                                                    "recurring": {"interval": intervalle, "interval_count": nombre}}}]}},
                **autres)


def test_palier_par_identifiant_de_prix():
    assert S.palier_depuis_abonnement(_abonnement(prix_id="price_pro", centimes=1), {"price_premium"}, {"price_pro"}) == "pro"
    # l'identifiant prime sur le montant
    assert S.palier_depuis_abonnement(_abonnement(prix_id="price_premium", centimes=99900), {"price_premium"}, {"price_pro"}) == "premium"
    assert S.ids_prix(" price_a, price_b ,,") == {"price_a", "price_b"}


def test_palier_par_montant_ramene_au_mois():
    assert S.palier_depuis_abonnement(_abonnement(centimes=490)) == "premium"
    assert S.palier_depuis_abonnement(_abonnement(centimes=890)) == "pro"
    assert S.palier_depuis_abonnement(_abonnement(centimes=8900, intervalle="year")) == "pro"       # 7,42 €/mois
    assert S.palier_depuis_abonnement(_abonnement(centimes=4900, intervalle="year")) == "premium"   # 4,08 €/mois
    assert S.palier_depuis_abonnement(_abonnement(centimes=1500, intervalle="month", nombre=3)) == "premium"  # 5 €/mois
    # jamais Pro par défaut : montant absent, nul ou illisible
    assert S.palier_depuis_abonnement(_abonnement(centimes=None)) == "premium"
    assert S.palier_depuis_abonnement(_abonnement(centimes="abc")) == "premium"
    assert S.palier_depuis_abonnement({"items": {"data": []}}) == "premium"


def test_fin_programmee():
    fin = int(datetime(2026, 12, 31, 12).timestamp())
    assert S.fin_programmee(_abonnement()) is None
    assert S.fin_programmee(_abonnement(cancel_at_period_end=True, current_period_end=fin)) == "31/12/2026"
    abonnement = _abonnement(cancel_at_period_end=True)
    abonnement["items"]["data"][0]["current_period_end"] = fin  # API récente : fin portée par la ligne
    assert S.fin_programmee(abonnement) == "31/12/2026"


class _Reponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _stripe_factice(monkeypatch, clients, abonnements, sessions=(), panne=False):
    """Faux Stripe : clients par e-mail, abonnements par client, sessions de paiement."""
    appels = []

    def faux_urlopen(requete, timeout=None):
        url = requete.full_url
        appels.append(url)
        assert requete.headers.get("Authorization") == "Bearer sk_test_cle"
        if panne:
            raise urllib.error.URLError("réseau indisponible")
        if "/customers?" in url:
            courriel = urllib.request.unquote(url.split("email=")[1].split("&")[0])
            return _Reponse(json.dumps({"data": [{"id": c} for c in clients.get(courriel, [])]}).encode())
        if "/subscriptions?" in url:
            client = url.split("customer=")[1].split("&")[0]
            if client not in abonnements:
                raise urllib.error.HTTPError(url, 404, "inconnu", {}, None)
            return _Reponse(json.dumps({"data": abonnements[client]}).encode())
        if "/checkout/sessions" in url:
            return _Reponse(json.dumps({"data": list(sessions)}).encode())
        raise AssertionError(url)

    monkeypatch.setattr(urllib.request, "urlopen", faux_urlopen)
    return appels


def test_verification_complete(monkeypatch):
    _stripe_factice(monkeypatch, {"a@b.fr": ["cus_A"]}, {"cus_A": [_abonnement("canceled", centimes=890), _abonnement(centimes=490)]})
    assert S.verifier_abonnement("a@b.fr", "sk_test_cle") == {"niveau": "premium", "fin": None, "client_id": "cus_A"}
    # aucune clé : rien n'est conclu ; e-mail inconnu sans paiement : gratuit
    assert S.verifier_abonnement("a@b.fr", "") is None
    assert S.verifier_abonnement("x@y.fr", "sk_test_cle", user_id="u1") == {"niveau": "gratuit", "fin": None, "client_id": None}


def test_pro_prioritaire_et_client_memorise(monkeypatch):
    _stripe_factice(monkeypatch, {"a@b.fr": ["cus_A"]},
                    {"cus_A": [_abonnement(centimes=490)], "cus_M": [_abonnement("trialing", prix_id="price_pro")]})
    resultat = S.verifier_abonnement("a@b.fr", "sk_test_cle", {"price_premium"}, {"price_pro"}, id_client_memorise="cus_M")
    assert resultat["niveau"] == "pro" and resultat["client_id"] == "cus_M"
    # un identifiant mémorisé qui n'a pas la forme « cus_... » est ignoré
    assert S.verifier_abonnement("a@b.fr", "sk_test_cle", id_client_memorise="pas_un_client")["client_id"] == "cus_A"


def test_paiement_avec_une_autre_adresse(monkeypatch):
    sessions = [{"status": "complete", "client_reference_id": "u1", "customer": {"id": "cus_R"}},
                {"status": "complete", "client_reference_id": "autre", "customer": "cus_X"}]
    _stripe_factice(monkeypatch, {}, {"cus_R": [_abonnement(centimes=890)], "cus_X": [_abonnement(centimes=890)]}, sessions)
    assert S.verifier_abonnement("autre@adresse.fr", "sk_test_cle", user_id="u1")["client_id"] == "cus_R"
    assert S.verifier_abonnement("autre@adresse.fr", "sk_test_cle", user_id="u2")["niveau"] == "gratuit"


def test_client_supprime_et_panne(monkeypatch):
    _stripe_factice(monkeypatch, {"a@b.fr": ["cus_supprime"]}, {})
    assert S.verifier_abonnement("a@b.fr", "sk_test_cle")["niveau"] == "gratuit"  # 404 : aucun abonnement
    _stripe_factice(monkeypatch, {"a@b.fr": ["cus_A"]}, {}, panne=True)
    assert S.verifier_abonnement("a@b.fr", "sk_test_cle") is None  # panne : rien n'est conclu


def test_session_du_portail(monkeypatch):
    envoye = {}

    def faux_urlopen(requete, timeout=None):
        envoye["url"], envoye["corps"] = requete.full_url, requete.data.decode()
        return _Reponse(json.dumps({"url": "https://billing.stripe.com/p/session/abc"}).encode())

    monkeypatch.setattr(urllib.request, "urlopen", faux_urlopen)
    assert S.creer_session_portail("cus_A", "sk_test_cle", "https://boursy.example") == "https://billing.stripe.com/p/session/abc"
    assert "customer=cus_A" in envoye["corps"] and "return_url=https" in envoye["corps"]
    assert S.creer_session_portail("pas_un_client", "sk_test_cle") is None
    assert S.creer_session_portail("cus_A", "") is None
