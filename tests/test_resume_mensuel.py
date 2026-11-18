"""Tests du résumé mensuel (python -m pytest tests, ou python tests/test_resume_mensuel.py)."""
import email
import io
import json
import os
import smtplib
import sys
import urllib.request
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import resume_mensuel as R  # noqa: E402


def test_prochaine_date_et_fenetre():
    assert R.prochaine_date_dca(date(2026, 11, 17), 20) == date(2026, 11, 20)
    assert R.prochaine_date_dca(date(2026, 11, 17), 17) == date(2026, 11, 17)
    assert R.prochaine_date_dca(date(2026, 11, 17), 5) == date(2026, 12, 5)
    assert R.prochaine_date_dca(date(2026, 12, 30), 2) == date(2027, 1, 2)
    assert R.prochaine_date_dca(date(2026, 2, 10), 31) == date(2026, 2, 28)  # jour ramené à 28
    assert R.jour_dca_valide("abc") == 1 and R.jour_dca_valide(0) == 1
    # fenêtre de 3 jours avant l'achat, un seul envoi par mois d'achat
    assert R.doit_envoyer_resume(date(2026, 11, 17), 20, None) == (True, date(2026, 11, 20))
    assert R.doit_envoyer_resume(date(2026, 11, 16), 20, None)[0] is False
    assert R.doit_envoyer_resume(date(2026, 11, 18), 20, "2026-11")[0] is False
    assert R.doit_envoyer_resume(date(2026, 11, 18), 20, "2026-10")[0] is True
    # achat le 1er : envoyé fin du mois précédent, compté pour le mois de l'achat
    assert R.doit_envoyer_resume(date(2026, 11, 28), 1, "2026-11") == (True, date(2026, 12, 1))


WATCHLIST = {
    "Alpha": {"symbole": "AAA.PA", "devise": "EUR", "prix_cible": 60.0, "div_eur": 3.0, "mois_div": ["Déc"]},
    "Beta": {"symbole": "BBB", "devise": "USD", "prix_cible": 50.0, "div_eur": 2.0, "mois_div": ["Mar", "Juin", "Sep", "Déc"]},
    "Gamma <script>": {"symbole": "GGG.PA", "devise": "EUR", "prix_cible": 10.0, "div_eur": 0.0, "mois_div": []},
}
PORTEFEUILLE = {
    "Alpha": {"qte": 10, "pru": 40.0},
    "Beta": {"qte": 5, "pru": 45.0},
    "Espèces": {"qte": 1, "pru": 120.0},
    "_allocation_cible": [{"nom": "Alpha", "poids": 50}, {"nom": "Beta", "poids": 30}, {"nom": "Gamma <script>", "poids": 20}],
    "_resume_mensuel": True, "_jour_dca": 5,
}
COURS = {"Alpha": 50.0, "Beta": 55.0, "Gamma <script>": 9.0}


def test_contenu_du_resume():
    resume = R.construire_resume(PORTEFEUILLE, WATCHLIST, 450.0, COURS, 1.10, date(2026, 12, 5))
    plan = resume["plan"]
    assert resume["allocation_personnalisee"]
    assert abs(plan["investi"] + plan["reste"] - 450.0) < 1e-9
    # 10 x 50 € + 5 x 55 $ / 1,10 + 120 € de liquidités
    assert abs(resume["valeur_portefeuille"] - (500.0 + 250.0 + 120.0)) < 1e-9
    assert abs(resume["rente_annuelle"] - (30.0 + 10.0 / 1.10)) < 1e-9
    noms_div = [n for n, _ in resume["dividendes_mois"]]
    assert noms_div == ["Alpha", "Beta"]  # décembre : Alpha (annuel) et Beta (trimestriel)
    assert abs(dict(resume["dividendes_mois"])["Beta"] - 10.0 / 1.10 / 4) < 1e-9
    assert [v["nom"] for v in resume["sous_cible"]] == ["Alpha", "Gamma <script>"]  # du plus grand écart au plus petit


def test_email():
    resume = R.construire_resume(PORTEFEUILLE, WATCHLIST, 450.0, COURS, 1.10, date(2026, 12, 5))
    message = R.composer_email_resume(resume, "envoi@exemple.test", "moi@exemple.test", "https://boursy.example")
    corps = message.get_payload()[0].get_payload(decode=True).decode()
    sujet = str(email.header.make_header(email.header.decode_header(message["Subject"])))
    assert "5 décembre" in sujet and "proposés" in sujet
    assert "Gamma &lt;script&gt;" in corps and "<script>" not in corps
    assert "Répartition selon votre allocation cible" in corps and "Dividendes attendus en décembre" in corps
    assert "https://boursy.example" in corps
    apercu = R.composer_email_resume(resume, "a@b.c", "d@e.f", apercu=True)
    assert "[Aperçu]" in str(email.header.make_header(email.header.decode_header(apercu["Subject"])))


def test_tache_du_soir_avec_faux_services():
    import alertes_quotidiennes as A

    envois, patchs = [], []
    base = {
        "u1": {"user_id": "u1", "email": "pro@exemple.test", "watchlist": WATCHLIST, "budget_dca": 450,
               "portefeuille": dict(PORTEFEUILLE, _jour_dca=date.today().day if date.today().day <= 28 else 28)},
        "u2": {"user_id": "u2", "email": "premium@exemple.test", "watchlist": WATCHLIST, "budget_dca": 450,
               "portefeuille": dict(PORTEFEUILLE, _jour_dca=date.today().day if date.today().day <= 28 else 28)},
        "u3": {"user_id": "u3", "email": "sans@exemple.test", "watchlist": WATCHLIST, "budget_dca": 450,
               "portefeuille": dict(PORTEFEUILLE, _resume_mensuel=False)},
    }
    prix_yahoo = {"AAA.PA": 50.0, "BBB": 55.0, "GGG.PA": 9.0, "EURUSD=X": 1.10}

    class Reponse(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def faux_urlopen(req, timeout=None):
        url = req.full_url
        if "yahoo" in url:
            symbole = urllib.request.unquote(url.split("/chart/")[1].split("?")[0])
            if symbole not in prix_yahoo:
                raise OSError("indisponible")
            return Reponse(json.dumps({"chart": {"result": [{"meta": {"regularMarketPrice": prix_yahoo[symbole]}}]}}).encode())
        if req.get_method() == "PATCH":
            patchs.append((url.split("user_id=eq.")[1], json.loads(req.data)))
            return Reponse(b"")
        if "/abonnements" in url:
            return Reponse(json.dumps([{"user_id": "u1", "niveau": "pro"}, {"user_id": "u2", "niveau": "premium"},
                                       {"user_id": "u3", "niveau": "pro"}]).encode())
        if "user_id=eq." in url:
            return Reponse(json.dumps([{"portefeuille": base[url.split("user_id=eq.")[1]]["portefeuille"]}]).encode())
        return Reponse(json.dumps(list(base.values())).encode())

    class FauxSMTP:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def login(self, *a):
            pass

        def sendmail(self, de, a, corps):
            envois.append(a)

    anciens = (urllib.request.urlopen, smtplib.SMTP_SSL, dict(os.environ))
    try:
        urllib.request.urlopen, smtplib.SMTP_SSL = faux_urlopen, FauxSMTP
        os.environ.update(SUPABASE_URL="https://faux.supabase.test", SUPABASE_SERVICE_KEY="cle",
                          SMTP_EMAIL="envoi@exemple.test", SMTP_PASSWORD="x", ALERTES_DRY_RUN="")
        A._cache_cours.clear()
        assert R.main() == 0
        assert envois == ["pro@exemple.test"], envois  # seulement le compte Pro qui l'a activé
        mois = date.today().strftime("%Y-%m")
        assert len(patchs) == 1 and patchs[0][0] == "u1" and patchs[0][1]["portefeuille"]["_resume_envoye"] == mois
        assert patchs[0][1]["portefeuille"]["Alpha"] == {"qte": 10, "pru": 40.0}  # le reste du portefeuille est intact
        # 2e soir : déjà envoyé ce mois-ci
        base["u1"]["portefeuille"]["_resume_envoye"] = mois
        envois.clear()
        patchs.clear()
        assert R.main() == 0 and not envois and not patchs
        # cours indisponibles : reporté, rien d'envoyé ni d'écrit
        base["u1"]["portefeuille"].pop("_resume_envoye")
        A._cache_cours.clear()
        prix_yahoo.clear()
        assert R.main() == 0 and not envois and not patchs
        # essai : rien d'envoyé ni d'écrit
        prix_yahoo.update({"AAA.PA": 50.0, "BBB": 55.0, "GGG.PA": 9.0, "EURUSD=X": 1.10})
        A._cache_cours.clear()
        os.environ["ALERTES_DRY_RUN"] = "1"
        assert R.main() == 0 and not envois and not patchs
        # secrets manquants
        os.environ["SMTP_PASSWORD"] = ""
        assert R.main() == 1
    finally:
        urllib.request.urlopen, smtplib.SMTP_SSL = anciens[0], anciens[1]
        os.environ.clear()
        os.environ.update(anciens[2])
        A._cache_cours.clear()


def test_solidite_de_la_rente_dans_le_resume():
    categories = {"AAA.PA": "solide", "BBB": "alerte"}
    resume = R.construire_resume(PORTEFEUILLE, WATCHLIST, 450.0, COURS, 1.10, date(2026, 12, 5),
                                 categorie_de=categories.get, rendement_achats=0.03)
    solidite = resume["solidite_rente"]
    assert abs(solidite["parts"]["solide"] - 30.0) < 1e-9 and abs(solidite["parts"]["alerte"] - 10.0 / 1.10) < 1e-9
    assert solidite["a_surveiller"] == ["Beta"] and solidite["apport_annuel"] == 12 * 450.0
    corps = R.composer_email_resume(resume, "a@b.c", "d@e.f").get_payload()[0].get_payload(decode=True).decode()
    assert "Solidité de votre rente" in corps and "à surveiller" in corps and "Beta" in corps
    assert "crise comme 2020" in corps and "Projection prudente dans 10 ans" in corps
    # sans classement (historiques indisponibles), l'e-mail part sans cette section
    sans = R.construire_resume(PORTEFEUILLE, WATCHLIST, 450.0, COURS, 1.10, date(2026, 12, 5))
    assert sans["solidite_rente"] is None
    assert "Solidité de votre rente" not in R.composer_email_resume(sans, "a@b.c", "d@e.f").get_payload()[0].get_payload(decode=True).decode()


def test_preparer_solidite_pour_la_tache_du_soir():
    from datetime import timedelta

    def historique(symbole):
        if symbole == "INCONNU":
            return None
        jours, jour = [], date(2016, 11, 21)
        while jour <= date(2026, 11, 17):
            if jour.weekday() < 5:
                jours.append(jour.isoformat())
            jour += timedelta(days=1)
        cours = [40.0 + (sum(map(ord, symbole)) % 60)] * len(jours)
        return jours, cours, [(f"{a}-05-15", 1.0 + 0.05 * (a - 2016)) for a in range(2016, 2027)], cours, cours

    categorie_de, rendement = R.preparer_solidite(date(2026, 11, 18), historique)
    assert categorie_de("TTE.PA") in ("solide", "alerte") and 0.0 < rendement < 0.2
    assert categorie_de("INCONNU") == "neutre"  # hors catalogue et sans historique : non classée
    assert R.preparer_solidite(date(2026, 11, 18), lambda symbole: None) == (None, 0.0)


def test_decisions_a_relire_dans_le_resume():
    carnet = [
        {"id": "1", "date": "2026-06-01", "action": "Alpha", "type": "achat", "raison": "Sous mon prix cible", "note": "Cible <atteinte>"},
        {"id": "2", "date": "2026-06-02", "action": "Beta", "type": "vente", "raison": "Prise de bénéfices", "lecon": "déjà relue"},
        {"id": "3", "date": "2026-01-10", "action": "Alpha", "type": "attendre", "raison": "Trop cher"},
    ]
    pf = dict(PORTEFEUILLE, _carnet_decisions=carnet)
    resume = R.construire_resume(pf, WATCHLIST, 450.0, COURS, 1.10, date(2026, 12, 5), aujourd_hui=date(2026, 12, 3))
    assert [d["id"] for d in resume["decisions_a_relire"]] == ["1"]  # leçon déjà écrite, ou échéance trop ancienne : exclues
    corps = R.composer_email_resume(resume, "a@b.c", "d@e.f").get_payload()[0].get_payload(decode=True).decode()
    assert "Décisions à relire" in corps and "Cible &lt;atteinte&gt;" in corps and "01/06/2026" in corps
    sans = R.construire_resume(PORTEFEUILLE, WATCHLIST, 450.0, COURS, 1.10, date(2026, 12, 5), aujourd_hui=date(2026, 12, 3))
    assert "Décisions à relire" not in R.composer_email_resume(sans, "a@b.c", "d@e.f").get_payload()[0].get_payload(decode=True).decode()


if __name__ == "__main__":
    for nom_test, fonction in list(globals().items()):
        if nom_test.startswith("test_") and callable(fonction):
            fonction()
            print("ok", nom_test)
