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


def _bouton(application, debut_du_libelle):
    return next(b for b in application.button if b.label.startswith(debut_du_libelle))


def test_suppression_du_compte_protegee(monkeypatch):
    # Abonné Pro actif : il doit d'abord résilier, la suppression n'est pas proposée
    application = lancer("pro", monkeypatch)
    application.run()
    assert any("Votre abonnement est encore actif" in a.value for a in application.warning)
    assert not [b for b in application.button if b.label.startswith("🗑️ Supprimer définitivement")]
    # Compte gratuit, sans clé de service : message clair, le compte reste connecté
    application = lancer("gratuit", monkeypatch)
    assert _bouton(application, "🗑️ Supprimer définitivement").disabled  # tant que SUPPRIMER n'est pas tapé
    application.text_input(key="txt_confirmer_suppression").input("SUPPRIMER")
    application.run()
    _bouton(application, "🗑️ Supprimer définitivement").click()
    application.run()
    verifier_sans_erreur(application)
    assert any("pas disponible" in e.value for e in application.error)
    assert application.session_state["user"] is not None


def test_suppression_refusee_si_abonnement_souscrit_entre_temps(monkeypatch):
    """La session croit le compte gratuit, mais un abonnement vient d'être souscrit (autre onglet) : refus au clic."""
    monkeypatch.setenv("BOURSY_PROFIL_TEST", "gratuit")
    monkeypatch.delenv("BOURSY_STRIPE_TEST", raising=False)
    application = AppTest.from_file(BANC, default_timeout=240)
    application.secrets["STRIPE_SECRET_KEY"] = "sk_test_cle"
    application.run()
    assert application.session_state["niveau_abonnement"] == "gratuit"
    application.text_input(key="txt_confirmer_suppression").input("SUPPRIMER")
    application.run()
    monkeypatch.setenv("BOURSY_STRIPE_TEST", "pro")  # paiement Stripe fait entre-temps
    _bouton(application, "🗑️ Supprimer définitivement").click()
    application.run()
    verifier_sans_erreur(application)
    assert any("abonnement est encore actif" in e.value for e in application.error)
    assert application.session_state["user"] is not None


def test_rapport_d_alertes_par_email(monkeypatch):
    import smtplib
    envois = []

    class FauxSMTP:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def login(self, *args):
            pass

        def sendmail(self, expediteur, destinataire, corps):
            envois.append((destinataire, corps))

    monkeypatch.setattr(smtplib, "SMTP_SSL", FauxSMTP)
    monkeypatch.setenv("BOURSY_PROFIL_TEST", "pro")
    application = AppTest.from_file(BANC, default_timeout=240)
    application.secrets["SMTP_EMAIL"] = "envoi@exemple.test"
    application.secrets["SMTP_PASSWORD"] = "secret"
    application.run()
    _bouton(application, "📧 M'envoyer ce rapport d'alertes").click()
    application.run()
    verifier_sans_erreur(application)
    assert [d for d, _ in envois] == ["test@exemple.test"]
    assert any("envoyé avec succès" in s.value for s in application.success)


def test_encaisser_un_dividende_dans_les_especes(monkeypatch):
    """Onglet 3 : le guichet crédite le dividende dans la poche Espèces."""
    application = lancer("pro", monkeypatch)
    especes_avant = float((application.session_state["portefeuille"].get("Espèces") or {}).get("pru", 0.0))
    application.number_input(key="input_mt_enc_div").set_value(12.5)
    application.run()
    _bouton(application, "💶 Créditer mes Espèces").click()
    application.run()
    verifier_sans_erreur(application)
    assert abs(application.session_state["portefeuille"]["Espèces"]["pru"] - (especes_avant + 12.5)) < 1e-9
    assert application.session_state["dividendes_encaisses_cumul"] == 12.5


def test_enregistrer_une_vente_avec_sa_raison(monkeypatch):
    """Onglet 5 : la vente réduit la ligne, entre dans l'historique et sa raison arrive dans le carnet."""
    application = lancer("pro", monkeypatch)
    action = application.selectbox(key="sel_action_vente").value
    quantite_avant = int(application.session_state["portefeuille"][action]["qte"])
    application.selectbox(key=f"input_raison_v_{action}").select("Rééquilibrage")
    application.run()
    _bouton(application, "🚀 Valider la vente").click()
    application.run()
    verifier_sans_erreur(application)
    assert int(application.session_state["portefeuille"][action]["qte"]) == quantite_avant - 1
    assert application.session_state["historique_ventes"][0]["action"] == action
    decision = application.session_state["portefeuille"]["_carnet_decisions"][-1]
    assert (decision["type"], decision["action"], decision["raison"]) == ("vente", action, "Rééquilibrage")
