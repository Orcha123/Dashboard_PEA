"""Tests des comptes et de l'abonnement protégé (python -m pytest tests)."""
import os
import sys
import types
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import comptes as C  # noqa: E402


def _utilisateur(identifiant="u1", courriel="Moi@Exemple.fr"):
    return types.SimpleNamespace(id=identifiant, email=courriel)


def test_administrateur():
    assert C.est_compte_admin(_utilisateur(), admin_user_id="u1")
    assert not C.est_compte_admin(_utilisateur(), admin_user_id="u2", admin_email="moi@exemple.fr")  # l'identifiant prime
    assert C.est_compte_admin(_utilisateur(), admin_email=" moi@exemple.FR ")  # repli sur l'e-mail, sans casse
    assert not C.est_compte_admin(_utilisateur(), admin_email="autre@exemple.fr")
    assert not C.est_compte_admin(_utilisateur())  # rien de configuré : personne n'est administrateur
    assert not C.est_compte_admin(None, admin_user_id="u1")
    assert not C.est_compte_admin(_utilisateur(courriel=None), admin_email="moi@exemple.fr")


def test_decision_sans_verdict_stripe():
    # Stripe absent ou injoignable : la table protégée fait foi, rien n'est réécrit
    assert C.decider_niveau({"niveau": "pro", "fin_programmee": "31/12/2026", "stripe_customer_id": "cus_A"}, None) == {
        "niveau": "pro", "fin": "31/12/2026", "client_id": "cus_A", "a_enregistrer": False}
    assert C.decider_niveau({}, None)["niveau"] == "gratuit"
    assert C.decider_niveau({"niveau": "platine"}, None)["niveau"] == "gratuit"  # niveau inconnu : gratuit
    assert C.decider_niveau(None, None)["niveau"] == "gratuit"
    # verdict illisible : ignoré, comme s'il n'y en avait pas
    assert C.decider_niveau({"niveau": "premium"}, {"niveau": "illimité"}) == {
        "niveau": "premium", "fin": None, "client_id": None, "a_enregistrer": False}


def test_decision_avec_verdict_stripe():
    ligne = {"niveau": "premium", "fin_programmee": None, "stripe_customer_id": "cus_A"}
    # même situation : rien à réécrire
    assert C.decider_niveau(ligne, {"niveau": "premium", "fin": None, "client_id": "cus_A"})["a_enregistrer"] is False
    # passage à Pro : réécrit
    decision = C.decider_niveau(ligne, {"niveau": "pro", "fin": None, "client_id": "cus_A"})
    assert decision == {"niveau": "pro", "fin": None, "client_id": "cus_A", "a_enregistrer": True}
    # résiliation programmée : réécrit avec la date
    assert C.decider_niveau(ligne, {"niveau": "premium", "fin": "31/12/2026", "client_id": "cus_A"})["a_enregistrer"] is True
    # désabonné sur Stripe : retour au gratuit, même si la table disait Pro ; le client connu est conservé
    decision = C.decider_niveau({"niveau": "pro", "stripe_customer_id": "cus_A"}, {"niveau": "gratuit", "fin": None, "client_id": None})
    assert decision == {"niveau": "gratuit", "fin": None, "client_id": "cus_A", "a_enregistrer": True}


class _Base:
    """Client Supabase factice : enregistre les appels de la forme table(...).méthode(...).eq(...).execute()."""

    def __init__(self, lignes=None, panne=False):
        self.lignes, self.panne, self.appels = lignes or [], panne, []
        self.auth = types.SimpleNamespace(admin=types.SimpleNamespace(delete_user=lambda uid: self.appels.append(("delete_user", uid))))

    def table(self, nom):
        base = self

        class _Requete:
            def __getattr__(self, methode):
                def _appel(*args, **kwargs):
                    base.appels.append((nom, methode, args))
                    return self
                return _appel

            def execute(self):
                if base.panne:
                    raise RuntimeError("base indisponible")
                return types.SimpleNamespace(data=list(base.lignes))

        return _Requete()


def test_lecture_de_la_table_protegee():
    base = _Base([{"niveau": "pro", "stripe_customer_id": "cus_A", "fin_programmee": None}])
    assert C.lire_abonnement_protege(base, "u1")["niveau"] == "pro"
    assert ("abonnements", "eq", ("user_id", "u1")) in base.appels  # sa propre ligne seulement
    assert C.lire_abonnement_protege(_Base([]), "u1") == {}
    assert C.lire_abonnement_protege(_Base(panne=True), "u1") is None
    assert C.lire_abonnement_protege(None, "u1") is None and C.lire_abonnement_protege(base, None) is None


def test_ecriture_reservee_au_client_serveur():
    assert C.enregistrer_abonnement_protege(None, "u1", "pro", "cus_A", None) is False  # pas de clé de service
    base = _Base()
    assert C.enregistrer_abonnement_protege(base, "u1", "platine", "cus_A", None) is False  # niveau inconnu refusé
    instant = datetime(2026, 11, 18, 10, 0)
    assert C.enregistrer_abonnement_protege(base, "u1", "pro", "cus_A", "31/12/2026", instant) is True
    ecriture = next(args[0] for nom, methode, args in base.appels if methode == "upsert")
    assert ecriture == {"user_id": "u1", "niveau": "pro", "stripe_customer_id": "cus_A", "fin_programmee": "31/12/2026",
                        "verifie_le": instant.isoformat()}
    assert C.enregistrer_abonnement_protege(_Base(panne=True), "u1", "pro", None, None) is False


def test_suppression_du_compte():
    base = _Base()
    assert C.supprimer_compte(base, "u1") == (True, "")
    appels_tables = [a for a in base.appels if len(a) == 3]
    assert [nom for nom, methode, args in appels_tables if methode == "delete"] == ["portfolio_history", "user_data", "abonnements"]
    assert all(args == ("user_id", "u1") for nom, methode, args in appels_tables if methode == "eq")  # ce compte seulement
    assert base.appels[-1] == ("delete_user", "u1")  # le compte de connexion en dernier
    ok, message = C.supprimer_compte(None, "u1")
    assert not ok and "pas disponible" in message
    ok, message = C.supprimer_compte(_Base(panne=True), "u1")
    assert not ok and "n'a pas pu aboutir" in message
