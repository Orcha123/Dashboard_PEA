"""
Tests de l'application complète, sans réseau (python -m pytest tests).

L'application est lancée par Streamlit en mode test (AppTest) à travers tests/banc_application.py, qui remplace
Yahoo Finance et Supabase par des versions factices. Ces tests servent de filet de sécurité : après chaque
modification, et en particulier pendant le découpage d'app.py en modules, ils vérifient que chaque profil affiche
tous les onglets sans erreur et que les principales actions fonctionnent toujours.
"""
import os

import pytest
from streamlit.testing.v1 import AppTest

BANC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "banc_application.py")
ONGLETS = ["1. Radar", "2. Portefeuille", "3. Calendrier", "4. Coach", "5. Arbitrages"]
VOLETS_COMMUNS = ["Achat du mois selon votre allocation cible", "Définir mon allocation cible", "Bilan des signaux",
                  "Journal des achats", "Carnet de décisions", "Mentions Légales"]


def lancer(profil, monkeypatch):
    monkeypatch.setenv("BOURSY_PROFIL_TEST", profil)
    application = AppTest.from_file(BANC, default_timeout=240)
    application.run()
    verifier_sans_erreur(application)
    return application


def verifier_sans_erreur(application):
    assert not application.exception, [e.value for e in application.exception]


def textes(application):
    """Tout le texte affiché : titres, paragraphes et HTML des tableaux, légendes, encadrés."""
    morceaux = [m.value for m in application.markdown] + [c.value for c in application.caption]
    morceaux += [a.value for a in application.info] + [a.value for a in application.success] + [a.value for a in application.warning]
    return "\n".join(str(m) for m in morceaux)


@pytest.mark.parametrize("profil", ["visiteur", "gratuit", "pro"])
def test_chaque_profil_affiche_tout_sans_erreur(profil, monkeypatch):
    application = lancer(profil, monkeypatch)
    libelles_onglets = [t.label for t in application.tabs]
    for onglet in ONGLETS:
        assert any(onglet in l for l in libelles_onglets), (onglet, libelles_onglets)
    libelles_volets = [e.label for e in application.expander]
    for volet in VOLETS_COMMUNS:
        assert any(volet in l for l in libelles_volets), (volet, libelles_volets)
    contenu = textes(application)
    assert "Tableau 1" in contenu and "Ce que valent ces signaux" in contenu
    assert ("Enregistrer une nouvelle vente" in " ".join(libelles_volets)) == (profil == "pro")  # onglet 5 réservé au Pro


def test_noter_une_decision_dans_le_carnet(monkeypatch):
    application = lancer("pro", monkeypatch)
    application.selectbox(key="cd_type").select("attendre")
    application.run()
    application.text_area(key="cd_note").input("Le cours a trop monté, j'attends un repli.")
    application.button(key="btn_noter_decision").click()
    application.run()
    verifier_sans_erreur(application)
    carnet = application.session_state["portefeuille"]["_carnet_decisions"]
    assert len(carnet) == 1 and carnet[0]["type"] == "attendre" and carnet[0]["note"].startswith("Le cours a trop monté")
    assert "Ce que sont devenues mes décisions (1)" in textes(application)


def test_enregistrer_une_allocation_cible(monkeypatch):
    application = lancer("pro", monkeypatch)
    application.button(key="btn_allocation_egale").click()
    application.run()
    application.button(key="btn_enregistrer_allocation").click()
    application.run()
    verifier_sans_erreur(application)
    cibles = application.session_state["portefeuille"]["_allocation_cible"]
    assert cibles and abs(sum(c["poids"] for c in cibles) - 100.0) < 0.1
    assert "Allocation cible : la vôtre" in textes(application)


def test_enregistrer_un_achat_avec_sa_raison(monkeypatch):
    application = lancer("pro", monkeypatch)
    action = application.selectbox(key="ja_action").value
    quantite_avant = int((application.session_state["portefeuille"].get(action) or {}).get("qte", 0))
    application.number_input(key="ja_qte").set_value(2)
    application.selectbox(key="ja_raison").select("Sous mon prix cible")
    application.run()
    application.button(key="btn_enregistrer_achat").click()
    application.run()
    verifier_sans_erreur(application)
    portefeuille = application.session_state["portefeuille"]
    assert int(portefeuille[action]["qte"]) == quantite_avant + 2
    assert portefeuille["_journal_achats"][-1]["action"] == action
    assert portefeuille["_carnet_decisions"][-1]["raison"] == "Sous mon prix cible"


def test_abonnement_pro_verifie_sur_stripe(monkeypatch):
    """Compte sans abonnement enregistré, mais abonnement Pro actif sur Stripe : les fonctions Pro s'ouvrent."""
    monkeypatch.setenv("BOURSY_PROFIL_TEST", "gratuit")
    monkeypatch.setenv("BOURSY_STRIPE_TEST", "pro")
    application = AppTest.from_file(BANC, default_timeout=240)
    application.secrets["STRIPE_SECRET_KEY"] = "sk_test_cle"
    application.run()
    verifier_sans_erreur(application)
    assert application.session_state["niveau_abonnement"] == "pro"
    assert any("Enregistrer une nouvelle vente" in e.label for e in application.expander)
