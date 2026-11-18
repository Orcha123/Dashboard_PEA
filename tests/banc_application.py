"""
Banc d'essai de l'application complète, lancé par les tests automatiques (tests/test_application.py).

Aucun appel réseau : Yahoo Finance est remplacé par des cours simulés (toujours les mêmes pour un symbole donné) et,
pour un compte connecté, Supabase par une base factice en mémoire. Le profil est choisi par la variable
d'environnement BOURSY_PROFIL_TEST :
- « visiteur » : mode local, sans compte ;
- « gratuit » : compte connecté, sans abonnement ;
- « pro » : compte connecté, abonnement Pro dans la table protégée.
Avec BOURSY_STRIPE_TEST=pro (et le secret STRIPE_SECRET_KEY), un faux Stripe répond qu'un abonnement Pro est actif.
"""
import io
import json
import os
import random
import runpy
import sys
import time
import types
import urllib.error
import urllib.parse
import urllib.request

import streamlit as st

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)


class _Reponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _serie(symbole, nombre):
    """Cours simulés sur 10 ans (2 520 séances), toujours identiques pour un même symbole."""
    hasard = random.Random(symbole)
    prix = hasard.uniform(15, 320)
    derive = hasard.uniform(-0.0002, 0.0007)
    clotures, hauts, bas = [], [], []
    for _ in range(2520):
        prix *= 1 + derive + hasard.gauss(0, 0.013)
        clotures.append(round(prix, 2))
        hauts.append(round(prix * (1 + abs(hasard.gauss(0, 0.006))), 2))
        bas.append(round(prix * (1 - abs(hasard.gauss(0, 0.006))), 2))
    return clotures[-nombre:], hauts[-nombre:], bas[-nombre:]


def _faux_urlopen(requete, timeout=None):
    url = requete.full_url if hasattr(requete, "full_url") else str(requete)
    if "api.stripe.com" in url and os.environ.get("BOURSY_STRIPE_TEST") == "pro":
        if "/customers?" in url:
            return _Reponse(json.dumps({"data": [{"id": "cus_TEST"}]}).encode())
        if "/subscriptions?" in url:
            return _Reponse(json.dumps({"data": [{"status": "active", "items": {"data": [{"price": {
                "id": "price_x", "unit_amount": 890, "recurring": {"interval": "month"}}}]}}]}).encode())
        return _Reponse(json.dumps({"data": []}).encode())
    if "finance.yahoo.com" not in url:
        raise urllib.error.URLError("réseau coupé (banc d'essai)")
    adresse = urllib.parse.urlparse(url)
    parametres = urllib.parse.parse_qs(adresse.query)
    if "/v1/finance/search" in adresse.path:
        return _Reponse(json.dumps({"quotes": [{"quoteType": "EQUITY", "symbol": "RACE.MI", "shortname": "Ferrari N.V.", "exchDisp": "Milan"}]}).encode())
    symbole = urllib.parse.unquote(adresse.path.rsplit("/", 1)[-1])
    nombre = {"1d": 1, "5d": 5, "3mo": 64, "1y": 252, "2y": 504, "3y": 756, "10y": 2520}.get(parametres.get("range", ["1y"])[0], 252)
    clotures, hauts, bas = _serie(symbole, nombre)
    if symbole == "EURUSD=X":
        clotures = [1.0862] * nombre
    jours, instant = [], time.time()
    while len(jours) < nombre:
        if time.gmtime(instant).tm_wday < 5:
            jours.append(int(instant))
        instant -= 86400
    resultat = {
        "meta": {"regularMarketPrice": clotures[-1], "currency": "USD" if "." not in symbole and not symbole.startswith("^") else "EUR",
                 "chartPreviousClose": clotures[0]},
        "timestamp": list(reversed(jours)),
        "indicators": {"quote": [{"close": clotures, "high": hauts, "low": bas}]},
    }
    if "div" in parametres.get("events", [""])[0]:
        maintenant = time.time()
        resultat["events"] = {"dividends": {str(int(maintenant - j * 86400)): {"date": int(maintenant - j * 86400), "amount": round(clotures[-1] * 0.012, 2)}
                                            for j in (40, 130, 220, 310)}}
    return _Reponse(json.dumps({"chart": {"result": [resultat]}}).encode())


urllib.request.urlopen = _faux_urlopen

PROFIL = os.environ.get("BOURSY_PROFIL_TEST", "visiteur")
if PROFIL in ("gratuit", "pro"):
    class _RequeteFactice:
        def __init__(self, table):
            self.table = table

        def __getattr__(self, nom):  # select, eq, order, upsert, insert, update, delete, range...
            return lambda *args, **kwargs: self

        def execute(self):
            if self.table == "abonnements" and PROFIL == "pro":
                return types.SimpleNamespace(data=[{"niveau": "pro", "stripe_customer_id": None, "fin_programmee": None}])
            return types.SimpleNamespace(data=[])

    class _ClientFactice:
        auth = types.SimpleNamespace(sign_out=lambda: None, verify_otp=lambda params: None, update_user=lambda attrs: None)

        def table(self, nom):
            return _RequeteFactice(nom)

    st.session_state.setdefault("_supabase_client", _ClientFactice())
    st.session_state.setdefault("user", types.SimpleNamespace(id="u-test", email="test@exemple.test"))

runpy.run_path(os.path.join(RACINE, "app.py"), run_name="__main__")
