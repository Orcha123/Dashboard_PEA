"""
Banc d'essai de l'application complète, lancé par les tests automatiques (tests/test_application.py).

Aucun appel réseau : Yahoo Finance est remplacé par des cours simulés (toujours les mêmes pour un symbole donné) et,
pour un compte connecté, Supabase par une base factice en mémoire. Le profil est choisi par la variable
d'environnement BOURSY_PROFIL_TEST :
- « visiteur » : mode local, sans compte ;
- « gratuit » : compte connecté, sans abonnement ;
- « pro » : compte connecté, abonnement Pro dans la table protégée.
Avec BOURSY_STRIPE_TEST=pro (et le secret STRIPE_SECRET_KEY), un faux Stripe répond qu'un abonnement Pro est actif.
Avec BOURSY_DIVIDENDES_10_ANS=1, les historiques sur 10 ans contiennent 10 ans de dividendes trimestriels.
Avec BOURSY_GEMINI_TEST=<fichier>, un faux Gemini écrit dans ce fichier le texte que l'application lui envoie.
"""
import calendar
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
    """Cours simulés sur 10 ans (2 520 séances, ou plus si demandé), toujours identiques pour un même symbole."""
    hasard = random.Random(symbole)
    prix = hasard.uniform(15, 320)
    derive = hasard.uniform(-0.0002, 0.0007)
    clotures, hauts, bas = [], [], []
    for _ in range(max(2520, nombre)):
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
    if "generativelanguage.googleapis.com" in url and os.environ.get("BOURSY_GEMINI_TEST"):
        # faux Gemini : enregistre le texte reçu dans le fichier indiqué et répond une phrase fixe
        if ":generateContent" in url:
            with open(os.environ["BOURSY_GEMINI_TEST"], "w", encoding="utf-8") as fichier:
                fichier.write(json.loads(requete.data)["contents"][0]["parts"][0]["text"])
            return _Reponse(json.dumps({"candidates": [{"content": {"parts": [{"text": "Réponse Gemini simulée"}]}}]}).encode())
        return _Reponse(json.dumps({"models": [{"name": "models/gemini-2.5-flash", "supportedGenerationMethods": ["generateContent"]}]}).encode())
    if "finance.yahoo.com" not in url:
        raise urllib.error.URLError("réseau coupé (banc d'essai)")
    adresse = urllib.parse.urlparse(url)
    parametres = urllib.parse.parse_qs(adresse.query)
    if "/v1/finance/search" in adresse.path:
        return _Reponse(json.dumps({"quotes": [{"quoteType": "EQUITY", "symbol": "RACE.MI", "shortname": "Ferrari N.V.", "exchDisp": "Milan"}]}).encode())
    symbole = urllib.parse.unquote(adresse.path.rsplit("/", 1)[-1])
    mensuel = parametres.get("interval", ["1d"])[0] == "1mo"
    if mensuel:
        # une clôture par mois sur 11 ans (points datés du 1er du mois), tirée de la même série quotidienne
        clotures, hauts, bas = (serie[::-21][:132][::-1] for serie in _serie(symbole, 2520 + 21 * 12))
        nombre = len(clotures)
        annee_m, mois_m = time.gmtime().tm_year, time.gmtime().tm_mon
        jours = []
        for _ in range(nombre):
            jours.append(int(calendar.timegm((annee_m, mois_m, 1, 0, 0, 0))))
            annee_m, mois_m = (annee_m - 1, 12) if mois_m == 1 else (annee_m, mois_m - 1)
    else:
        nombre = {"1d": 1, "5d": 5, "3mo": 64, "1y": 252, "2y": 504, "3y": 756, "10y": 2520}.get(parametres.get("range", ["1y"])[0], 252)
        clotures, hauts, bas = _serie(symbole, nombre)
        jours, instant = [], time.time()
        while len(jours) < nombre:
            if time.gmtime(instant).tm_wday < 5:
                jours.append(int(instant))
            instant -= 86400
    if symbole == "EURUSD=X":
        clotures = [1.0862] * nombre
    resultat = {
        "meta": {"regularMarketPrice": clotures[-1], "currency": "USD" if "." not in symbole and not symbole.startswith("^") else "EUR",
                 "chartPreviousClose": clotures[0]},
        "timestamp": list(reversed(jours)),
        "indicators": {"quote": [{"close": clotures, "high": hauts, "low": bas}]},
    }
    if "div" in parametres.get("events", [""])[0]:
        maintenant = time.time()
        if (nombre == 2520 or mensuel) and os.environ.get("BOURSY_DIVIDENDES_10_ANS"):
            # 10 ans de dividendes trimestriels qui progressent de 5 % par an ; un tiers des valeurs l'a divisé par deux
            # il y a 2 ans environ (pour la solidité des dividendes)
            hasard_div = random.Random("dividendes " + symbole)
            base, coupe = clotures[-1] * hasard_div.uniform(0.003, 0.02), hasard_div.random() < 1 / 3
            versements = {}
            for trimestre in range(1, 40):
                instant_div = int(maintenant - trimestre * 91.25 * 86400)
                montant_div = base * 1.05 ** (-trimestre / 4) * (0.5 if coupe and 6 <= trimestre <= 9 else 1.0)
                versements[str(instant_div)] = {"date": instant_div, "amount": round(montant_div, 4)}
            resultat["events"] = {"dividends": versements}
        else:
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
