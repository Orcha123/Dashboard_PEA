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
    # Radar, tableaux 3 et 4 : descriptifs et alignés sur les études (ni niveau d'achat, ni « timing », ni « ultra sûr »)
    for absent in ("Niveau technique de référence", "niveau de prix technique", "TIMING", "Rebond probable", "Ultra Sûr",
                   "meilleur équilibre"):
        assert absent not in contenu, absent
    assert ("ils ne prévoient pas la suite" in contenu) == (profil == "pro")
    if profil == "pro":
        assert "estimé sur ce tableau" in contenu and "YoC 5A (hypothèse)" in contenu
        tableau_4 = next(m.value for m in application.markdown if "RENDEMENT TRÈS ÉLEVÉ" in str(m.value))
        fin = tableau_4[tableau_4.index("RENDEMENT TRÈS ÉLEVÉ"):]
        for profil_rente in ("PROFIL COMPLET", "BON RENDEMENT", "CROISSANCE DU DIVIDENDE", "PROFIL MODÉRÉ"):
            assert profil_rente not in fin, profil_rente  # les rendements les plus élevés sont en bas, signalés


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


def test_bilan_des_signaux(monkeypatch):
    """Onglet 1 : le bilan rejoue les signaux sur l'historique et affiche ses tableaux."""
    application = lancer("pro", monkeypatch)
    _bouton(application, "🔬 Calculer le bilan").click()
    application.run()
    verifier_sans_erreur(application)
    contenu = textes(application)
    assert "Toutes les observations" in contenu and "Comparaison des trois algorithmes" in contenu


def test_solidite_des_dividendes(monkeypatch):
    """Onglet 1 : l'analyse de la solidité des dividendes classe le radar et liste les dividendes solides du catalogue."""
    import streamlit as st

    # Les caches de Streamlit sont partagés entre les tests : ceux d'avant ont lu des historiques sans dividendes anciens
    st.cache_data.clear()
    st.cache_resource.clear()
    monkeypatch.setenv("BOURSY_DIVIDENDES_10_ANS", "1")
    try:
        application = lancer("pro", monkeypatch)
        _bouton(application, "🛡️ Analyser la solidité").click()
        application.run()
        verifier_sans_erreur(application)
        contenu = textes(application)
        assert "Votre radar : situation au 31/12/" in contenu and "Les dividendes solides du catalogue" in contenu
        verdicts = [v for tableau in application.dataframe for v in tableau.value.get("Verdict", [])]
        assert any("Solide" in v for v in verdicts) and any("Neutre" in v for v in verdicts)
        assert any("Risque de baisse" in v for v in verdicts)
        # l'analyse du jour s'affiche ensuite d'emblée, sans nouveau calcul demandé
        suivante = lancer("pro", monkeypatch)
        assert "Les dividendes solides du catalogue" in textes(suivante)
        # le tableau 4 du radar reprend alors le seuil de l'étude et le verdict de chaque action
        assert "seuil de l'étude" in textes(suivante) and "Étude : 🛡️ Solide" in textes(suivante)
    finally:
        st.cache_data.clear()
        st.cache_resource.clear()


def test_projection_prudente_de_la_rente(monkeypatch):
    """Onglet 3 : la projection prudente classe les lignes du portefeuille et projette la rente sur 20 ans."""
    import streamlit as st

    st.cache_data.clear()
    st.cache_resource.clear()
    monkeypatch.setenv("BOURSY_DIVIDENDES_10_ANS", "1")
    try:
        application = lancer("pro", monkeypatch)
        _bouton(application, "🛡️ Calculer la projection prudente").click()
        application.run()
        verifier_sans_erreur(application)
        contenu = textes(application)
        assert "Point de départ" in contenu and "Pourquoi pas la croissance passée" in contenu
        tableau = next(t.value for t in application.dataframe if "Rente prudente (euros d'aujourd'hui)" in t.value.columns)
        assert len(tableau) == 6 and tableau["Horizon"].iloc[-1].startswith("Dans 20 ans")
        # sans apport ni réinvestissement, la rente ne grossit pas
        application.number_input(key="nb_apport_rente_prudente").set_value(0)
        application.toggle(key="tg_reinvestir_rente_prudente").set_value(False)
        application.run()
        verifier_sans_erreur(application)
        tableau = next(t.value for t in application.dataframe if "Rente prudente (euros d'aujourd'hui)" in t.value.columns)
        montants = [int(v.split(" €")[0].replace(" ", "")) for v in tableau["Rente prudente (euros d'aujourd'hui)"]]
        assert montants == sorted(montants, reverse=True)
    finally:
        st.cache_data.clear()
        st.cache_resource.clear()


def test_diversification_de_la_rente(monkeypatch):
    """Onglet 3 : la rente est répartie par secteur et par pays, avec les alertes et les retenues à la source."""
    application = lancer("pro", monkeypatch)
    tableaux = [t.value for t in application.dataframe]
    secteurs = next(t for t in tableaux if "Secteur" in t.columns and "Baisses en 2020 (catalogue)" in t.columns)
    pays = next(t for t in tableaux if "Pays" in t.columns and "Dans un PEA" in t.columns)
    assert len(secteurs) >= 1 and len(pays) >= 1
    assert all(p.endswith("%") for p in secteurs["Part"])
    contenu = textes(application)
    assert "Repères usuels de diversification" in contenu
    assert ("Rente bien répartie" in contenu) or ("au-dessus du repère" in contenu)
    gratuit = lancer("gratuit", monkeypatch)
    assert not any("Baisses en 2020 (catalogue)" in t.value.columns for t in gratuit.dataframe)  # réservé Premium et Pro


def test_suivi_de_la_solidite_en_conditions_reelles(monkeypatch):
    """Onglet 1 : le suivi en conditions réelles s'affiche ; sans clé de service, il le dit au lieu de planter."""
    application = lancer("pro", monkeypatch)
    application.toggle(key="tog_suivi_solidite").set_value(True)
    application.run()
    verifier_sans_erreur(application)
    assert any("Le suivi n'est pas lisible" in i.value for i in application.info)


class _FauxSMTP:
    envois = []

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def login(self, *args):
        pass

    def sendmail(self, expediteur, destinataire, corps):
        _FauxSMTP.envois.append((destinataire, corps))


def test_resume_mensuel_reglages_et_apercu(monkeypatch):
    """Onglet 1 : activer le résumé mensuel, choisir son jour d'achat, recevoir un aperçu."""
    import email
    import email.header
    import smtplib
    _FauxSMTP.envois = []
    monkeypatch.setattr(smtplib, "SMTP_SSL", _FauxSMTP)
    monkeypatch.setenv("BOURSY_PROFIL_TEST", "pro")
    application = AppTest.from_file(BANC, default_timeout=240)
    application.secrets["SMTP_EMAIL"] = "envoi@exemple.test"
    application.secrets["SMTP_PASSWORD"] = "secret"
    application.run()
    next(t for t in application.toggle if t.label.startswith("📅 Recevoir chaque mois")).set_value(True)
    application.run()
    application.number_input(key="num_jour_dca").set_value(20)
    application.run()
    _bouton(application, "👁️ M'envoyer un aperçu").click()
    application.run()
    verifier_sans_erreur(application)
    portefeuille = application.session_state["portefeuille"]
    assert portefeuille["_resume_mensuel"] is True and portefeuille["_jour_dca"] == 20
    assert len(_FauxSMTP.envois) == 1
    message = email.message_from_string(_FauxSMTP.envois[0][1])
    sujet = str(email.header.make_header(email.header.decode_header(message["Subject"])))
    assert sujet.startswith("[Aperçu]") and "20 " in sujet
    corps = message.get_payload()[0].get_payload(decode=True).decode()
    assert "Solidité de votre rente" in corps and "crise comme 2020" in corps


def test_coach_ia_achat_du_mois(monkeypatch):
    """Onglet 4 : sans clé Gemini, le moteur local rédige l'audit « Achat DCA du Mois »."""
    application = lancer("pro", monkeypatch)
    _bouton(application, "🛒 2. Achat DCA du Mois").click()
    application.run()
    verifier_sans_erreur(application)
    assert "Achat DCA du Mois" in application.session_state["reponse_ia_coach"]
    assert application.session_state["quota_ia_utilise"] == 1


def test_coach_ia_audit_de_la_rente(monkeypatch):
    """Onglet 4 : l'audit de la rente reprend solidité, diversification et projection ; le gratuit voit le verrou."""
    import streamlit as st

    st.cache_data.clear()
    st.cache_resource.clear()
    monkeypatch.setenv("BOURSY_DIVIDENDES_10_ANS", "1")
    try:
        application = lancer("pro", monkeypatch)
        _bouton(application, "💵 5. Ma Rente").click()
        application.run()
        verifier_sans_erreur(application)
        rapport = application.session_state["reponse_ia_coach"]
        for titre in ("Ma Rente : Solidité, Diversification & Projection Prudente", "Solidité de votre rente",
                      "Diversification de votre rente", "Projection prudente", "crise comme 2020", "Palier des 100"):
            assert titre in rapport, titre
        assert "5,5 %" not in rapport and "5.5 %" not in rapport  # plus de rendement supposé
        _bouton(application, "🛡️ 4. Stress-Test").click()
        application.run()
        stress = application.session_state["reponse_ia_coach"]
        assert "n'est pas à l'abri" in stress and "Diversification de votre rente" in stress
        assert "dépend du nombre d'actions détenues" not in stress
        gratuit = lancer("gratuit", monkeypatch)
        _bouton(gratuit, "💵 5. Ma Rente").click()
        gratuit.run()
        verifier_sans_erreur(gratuit)
        assert "Réservées aux offres" in gratuit.session_state["reponse_ia_coach"]
    finally:
        st.cache_data.clear()
        st.cache_resource.clear()


def test_coach_ia_gemini_recoit_la_rente(monkeypatch, tmp_path):
    """Onglet 4 : avec Gemini, le texte envoyé contient la solidité, la diversification, la projection et l'étude."""
    import streamlit as st

    st.cache_data.clear()
    st.cache_resource.clear()
    texte_envoye = tmp_path / "gemini.txt"
    monkeypatch.setenv("BOURSY_DIVIDENDES_10_ANS", "1")
    monkeypatch.setenv("BOURSY_GEMINI_TEST", str(texte_envoye))
    monkeypatch.setenv("BOURSY_PROFIL_TEST", "pro")
    try:
        application = AppTest.from_file(BANC, default_timeout=240)
        application.secrets["GEMINI_API_KEY"] = "cle-de-test"
        application.run()
        _bouton(application, "💵 5. Ma Rente").click()
        application.run()
        verifier_sans_erreur(application)
        assert application.session_state["reponse_ia_coach"] == "Réponse Gemini simulée"
        envoye = texte_envoye.read_text(encoding="utf-8")
        for morceau in ("Répartition de la rente par grand secteur", "Solidité de la rente", "crise comme 2020",
                        "Projection prudente", "Résultats de l'étude des dividendes de Boursy",
                        "Ne présente jamais un rendement élevé comme une qualité en soi"):
            assert morceau in envoye, morceau
    finally:
        st.cache_data.clear()
        st.cache_resource.clear()


def _synthese_affichee(application):
    return next((str(m.value) for m in application.markdown if "Synthèse stratégique, critiques & plan d'action" in str(m.value)), "")


def test_coach_synthese_strategique_et_audit_0(monkeypatch, tmp_path):
    """Onglet 4 : synthèse et plan d'action en tête (sans crédit d'audit), audit 0 local puis par Gemini."""
    import streamlit as st

    st.cache_data.clear()
    st.cache_resource.clear()
    monkeypatch.setenv("BOURSY_DIVIDENDES_10_ANS", "1")
    try:
        application = lancer("pro", monkeypatch)
        synthese = _synthese_affichee(application)
        for partie in ("**En bref.**", "Critiques et points de vigilance", "Plan d'action", "Stratégie : ce que disent les études"):
            assert partie in synthese, partie
        assert "Diagnostic de Boursy" in textes(application)
        _bouton(application, "🛡️ Ajouter la solidité de ma rente").click()
        application.run()
        verifier_sans_erreur(application)
        assert "issus de dividendes solides" in _synthese_affichee(application)
        reperes = next(str(m.value) for m in application.markdown if "DIVIDENDE SOLIDE AU MEILLEUR RENDEMENT" in str(m.value))
        for repere in ("RENDEMENTS ÉLEVÉS À SURVEILLER", "SECTEUR ABSENT DE VOTRE RENTE", "ACHAT DU MOIS", "au 31/12/"):
            assert repere in reperes, repere
        assert any("Indicateurs techniques du radar (non prédictifs)" in e.label for e in application.expander)
        affichage_coach = " ".join(str(m.value) for m in application.markdown)
        assert "Simulation : 1 titre de plus" not in affichage_coach and "RENDEMENT LE PLUS ÉLEVÉ" not in affichage_coach
        assert "Votre rente : solidité, crise et projection" in _synthese_affichee(application)
        assert not any(b.label.startswith("🛡️ Ajouter la solidité") for b in application.button)  # bouton inutile désormais
        _bouton(application, "🧭 0. Synthèse").click()
        application.run()
        verifier_sans_erreur(application)
        assert application.session_state["reponse_ia_coach"].startswith("### 🧭 Synthèse stratégique")

        texte_envoye = tmp_path / "gemini.txt"
        monkeypatch.setenv("BOURSY_GEMINI_TEST", str(texte_envoye))
        monkeypatch.setenv("BOURSY_PROFIL_TEST", "pro")
        avec_gemini = AppTest.from_file(BANC, default_timeout=240)
        avec_gemini.secrets["GEMINI_API_KEY"] = "cle-de-test"
        avec_gemini.run()
        _bouton(avec_gemini, "🧭 0. Synthèse").click()
        avec_gemini.run()
        verifier_sans_erreur(avec_gemini)
        assert avec_gemini.session_state["reponse_ia_coach"] == "Réponse Gemini simulée"
        envoye = texte_envoye.read_text(encoding="utf-8")
        for partie in ("PORTEFEUILLE", "APPORTS ET ALLOCATION", "PERFORMANCE RÉELLE", "DIAGNOSTIC DE BOURSY",
                       "PRINCIPES ISSUS DES ÉTUDES", "## 2. Votre rente : solidité", "## 6. Plan d'action", "n'invente aucun chiffre"):
            assert partie in envoye, partie
    finally:
        st.cache_data.clear()
        st.cache_resource.clear()


def test_coach_synthese_offre_gratuite(monkeypatch):
    application = lancer("gratuit", monkeypatch)
    synthese = _synthese_affichee(application)
    assert "Plan d'action" in synthese and "Réservées aux offres Premium et Pro" in synthese
    reperes = next(str(m.value) for m in application.markdown if "DIVIDENDE SOLIDE AU MEILLEUR RENDEMENT" in str(m.value))
    assert "🔒 Offres Premium et Pro" in reperes
    assert not any(b.label.startswith("🛡️ Ajouter la solidité") for b in application.button)


def test_plafond_pea_identique_dans_le_portefeuille_et_le_super_pack(monkeypatch):
    """Le Super-Pack reprend les versements nets PEA calculés par l'onglet Portefeuille (même marge restante)."""
    import re
    application = lancer("pro", monkeypatch)
    contenu = textes(application)
    marge_portefeuille = re.search(r"Marge de versement restante : <b>([^<]+) €</b>", contenu)
    marge_super_pack = re.search(r"Reste à verser sur PEA : <b>([^<]+) €</b>", contenu)
    assert marge_portefeuille and marge_super_pack
    assert marge_portefeuille.group(1) == marge_super_pack.group(1)
