import urllib.request
import urllib.error
import urllib.parse
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import streamlit as st
from supabase import create_client
import importlib
import catalogue_valeurs
import moteur_signaux
import allocation_dca
import carnet_decisions
import resume_mensuel
import paiements_stripe
import comptes
import courriels
import donnees_marche
import habillage
import pages_legales
import etudes.dividendes
import solidite_dividendes
import onglets.calendrier
import onglets.ventes
import onglets.radar
import onglets.coach_ia
import onglets.portefeuille
import onglets.super_pack
# Après une mise à jour du dépôt, Streamlit Cloud relance app.py sans toujours recharger les modules locaux déjà
# chargés : un app.py récent avec un ancien moteur_signaux provoquait une ImportError jusqu'au redémarrage.
# Les recharger à chaque exécution (quelques millisecondes) garantit qu'ils sont de la même version que app.py.
importlib.reload(catalogue_valeurs)
importlib.reload(moteur_signaux)
importlib.reload(allocation_dca)
importlib.reload(carnet_decisions)
importlib.reload(resume_mensuel)
importlib.reload(paiements_stripe)
importlib.reload(comptes)
importlib.reload(courriels)
importlib.reload(donnees_marche)
importlib.reload(habillage)
importlib.reload(pages_legales)
importlib.reload(etudes.dividendes)
importlib.reload(solidite_dividendes)  # après etudes.dividendes, dont il dépend
importlib.reload(onglets.calendrier)
importlib.reload(onglets.ventes)
importlib.reload(onglets.radar)
importlib.reload(onglets.coach_ia)
importlib.reload(onglets.portefeuille)
importlib.reload(onglets.super_pack)
from catalogue_valeurs import ENRICHISSEMENT_CATALOGUE, NOMS_RENOMMES, symbole_a_jour  # catalogue partagé avec la tâche planifiée
from allocation_dca import calculer_achat_du_mois, preparer_lignes_dca  # DCA guidé par l'allocation cible
from paiements_stripe import creer_session_portail, ids_prix, verifier_abonnement  # abonnements Stripe (testés)
from comptes import decider_niveau  # comptes et abonnement protégé (testés)
from courriels import ADRESSE_APPLICATION, composer_email_alertes_radar, envoyer_smtp  # envoi des e-mails
from habillage import afficher_html, appliquer_habillage, nombres_fr  # styles et format français
from pages_legales import afficher_pages_legales  # AMF, CGV, rétractation, mentions légales, confidentialité
from donnees_marche import (  # Yahoo Finance, heures de marché, calculs sur les historiques (testés)
    RAFRAICHISSEMENT_SEANCE_SECONDES,
    clotures_trois_mois,
    cours_et_historique,
    creneau_cours,
    heure_paris,
    historique_dix_ans,
    inspecter_dividende,
    marches_ouverts,
    niveau_et_variation,
    rechercher_yahoo,
    taux_eur_usd,
    tendance_ema_2_12,
)
from resume_mensuel import composer_email_resume  # résumé mensuel du DCA par e-mail (aperçu)
from moteur_signaux import (  # moteur de calcul partagé avec la tâche planifiée
    calculer_rsi,
    calculer_stochastique,
    calculer_atr_pct,
    calculer_bollinger,
    calculer_macd,
    analyser_signal_ema_2_12,
    calculer_score_radar,
    calculer_regression_lineaire,
    rejouer_signaux,
)

# ==============================================================================
# CONFIGURATION DE LA PAGE & DESIGN ARGON UI
# ==============================================================================
st.set_page_config(
    page_title="Boursy - Suite Boursière PEA, US & Dividendes",
    page_icon="📈",
    layout="wide",
)

CLES_TECHNIQUES_PF = ("Espèces", "_historique_ventes", "_quota_ia", "_niveau_abo", "_div_encaisses_cumul", "_stripe_customer_id", "_alertes_auto", "_alertes_envoyees", "_journal_achats", "_allocation_cible", "_resume_mensuel", "_jour_dca", "_resume_envoye", "_carnet_decisions")


def _lire_secret(nom, defaut=""):
    """Lit un secret Streamlit sans jamais lever d'erreur (fichier de secrets absent, clé manquante...)."""
    try:
        return str(st.secrets.get(nom, defaut)).strip().strip('"').strip("'")
    except Exception:
        return defaut


# Adresses lues dans les Secrets Streamlit : aucune adresse personnelle n'est écrite dans le code source.
# - ADMIN_EMAIL   : e-mail du compte administrateur (repli si ADMIN_USER_ID n'est pas renseigné).
# - CONTACT_EMAIL : adresse de contact affichée dans les mentions légales (par défaut : ADMIN_EMAIL).
ADMIN_EMAIL = _lire_secret("ADMIN_EMAIL")
CONTACT_EMAIL = _lire_secret("CONTACT_EMAIL") or ADMIN_EMAIL


def est_compte_admin(user):
    """
    Reconnaît le compte administrateur à partir d'un utilisateur AUTHENTIFIÉ (jamais d'une simple saisie).
    - Recommandé : ajoutez le secret ADMIN_USER_ID (UUID de votre compte, visible dans Supabase > Authentication > Users).
    - Sinon, repli sur l'adresse e-mail du compte connecté (secret ADMIN_EMAIL). Règle dans comptes.py.
    """
    return comptes.est_compte_admin(user, _lire_secret("ADMIN_USER_ID"), ADMIN_EMAIL)


# Habillage (habillage.css) et nombres au format français : habillage.py
appliquer_habillage()

# ==============================================================================
# CONNEXION SUPABASE, STRIPE & EMAILS D'ALERTE
# ==============================================================================
def init_supabase():
    """
    Un client Supabase PAR session utilisateur.
    (Avec @st.cache_resource, un seul client était partagé par tous les visiteurs : chaque connexion
    écrasait le jeton de la précédente et une déconnexion déconnectait tout le monde.)
    """
    if "_supabase_client" not in st.session_state:
        try:
            url = str(st.secrets["SUPABASE_URL"]).strip().rstrip("/")
            key = str(st.secrets["SUPABASE_KEY"]).strip()
            st.session_state["_supabase_client"] = create_client(url, key)
        except Exception:
            st.session_state["_supabase_client"] = None
    return st.session_state["_supabase_client"]

supabase = init_supabase()

# --- ABONNEMENTS STRIPE : la logique (qui a droit à Premium ou Pro) est dans paiements_stripe.py, couverte par des
# tests ; ici, seulement la lecture des secrets ---
def _config_stripe():
    """Clé secrète et identifiants de prix Stripe (secrets Streamlit)."""
    return (_lire_secret("STRIPE_SECRET_KEY"), ids_prix(_lire_secret("STRIPE_PRICE_PREMIUM")),
            ids_prix(_lire_secret("STRIPE_PRICE_PRO")))


def creer_session_portail_stripe(id_client):
    """Adresse d'une session du portail client Stripe (gestion de l'abonnement sans e-mail) ; None si impossible."""
    adresse_retour = _lire_secret("APP_URL")
    if not adresse_retour:
        try:
            adresse_retour = str(st.context.url or "").split("?")[0]
        except Exception:
            adresse_retour = ""
    return creer_session_portail(id_client, _lire_secret("STRIPE_SECRET_KEY"), adresse_retour)


def verifier_abonnement_stripe(email_client, user_id=None, id_client_memorise=None):
    """Niveau vérifié en direct sur Stripe (voir paiements_stripe.verifier_abonnement) ; None si rien n'est conclu."""
    cle_stripe, prix_premium, prix_pro = _config_stripe()
    return verifier_abonnement(email_client, cle_stripe, prix_premium, prix_pro, user_id, id_client_memorise)


# ==============================================================================
# ABONNEMENT PROTÉGÉ : TABLE « abonnements », LISIBLE PAR L'UTILISATEUR, MODIFIABLE PAR LE SERVEUR SEUL
# ==============================================================================
# Le niveau d'abonnement ne vient plus jamais de user_data (que chaque utilisateur peut modifier sur sa ligne).
# Il est lu dans la table « abonnements » (sécurité par ligne : lecture de sa propre ligne uniquement) et n'y est
# écrit qu'avec la clé de service, après vérification sur Stripe.

@st.cache_resource
def init_supabase_serveur():
    """Client Supabase « serveur » (clé service_role), réservé à l'écriture de la table abonnements. None si absent."""
    url = _lire_secret("SUPABASE_URL").rstrip("/")
    cle_service = _lire_secret("SUPABASE_SERVICE_KEY")
    if not url or not cle_service:
        return None
    try:
        return create_client(url, cle_service)
    except Exception:
        return None


def lire_abonnement_protege(user):
    """Ligne de l'utilisateur dans la table abonnements (dict), {} s'il n'en a pas, None si la lecture échoue."""
    return comptes.lire_abonnement_protege(st.session_state.get("_supabase_client"), getattr(user, "id", None))


def enregistrer_abonnement_protege(user_id, niveau, client_id, fin):
    """Écrit le niveau vérifié sur Stripe dans la table abonnements (clé de service). False si impossible."""
    return comptes.enregistrer_abonnement_protege(init_supabase_serveur(), user_id, niveau, client_id, fin)


def supprimer_compte_utilisateur(user):
    """Efface définitivement le compte (clé de service nécessaire). Renvoie (succès, message d'erreur éventuel)."""
    return comptes.supprimer_compte(init_supabase_serveur(), getattr(user, "id", None))


def etablir_niveau_abonnement(user, verifier_stripe=True):
    """
    Fixe le niveau d'abonnement de la session à partir de sources fiables uniquement :
    compte administrateur, puis Stripe (si configuré et joignable), sinon la table protégée « abonnements ».
    La décision est prise par comptes.decider_niveau (testée). Retourne "gratuit", "premium" ou "pro".
    """
    if user is None:
        return "gratuit"
    st.session_state["_stripe_sync_session_ok"] = True
    if est_compte_admin(user):
        st.session_state.update(est_abonne_pro=True, niveau_abonnement="pro", abo_fin_periode=None)
        return "pro"
    ligne = lire_abonnement_protege(user) or {}
    verdict = (verifier_abonnement_stripe(str(user.email or "").lower(), user.id, ligne.get("stripe_customer_id"))
               if verifier_stripe else None)
    decision = decider_niveau(ligne, verdict)
    if decision["a_enregistrer"]:
        enregistrer_abonnement_protege(user.id, decision["niveau"], decision["client_id"], decision["fin"])
    st.session_state["_stripe_client_id"] = decision["client_id"]
    st.session_state.update(est_abonne_pro=(decision["niveau"] != "gratuit"), niveau_abonnement=decision["niveau"],
                            abo_fin_periode=decision["fin"])
    return decision["niveau"]


# --- E-MAILS : composition et envoi dans courriels.py ; identifiants lus ici dans les secrets ---
MESSAGE_SMTP_ABSENT = "Pour activer l'envoi d'emails, ajoutez `SMTP_EMAIL` et `SMTP_PASSWORD` dans vos Secrets Streamlit."


def _identifiants_smtp():
    return _lire_secret("SMTP_EMAIL"), _lire_secret("SMTP_PASSWORD")


def envoyer_email_alerte(destinataire, liste_alertes):
    smtp_user, smtp_pass = _identifiants_smtp()
    if not smtp_user or not smtp_pass:
        return False, MESSAGE_SMTP_ABSENT
    try:
        message = composer_email_alertes_radar(smtp_user, destinataire, liste_alertes, _lire_secret("APP_URL") or ADRESSE_APPLICATION)
        envoyer_smtp(message, smtp_user, smtp_pass, timeout=10)
        return True, f"✅ Email d'alerte envoyé avec succès à {destinataire} !"
    except Exception as e:
        return False, f"Erreur SMTP : {e}"


def envoyer_apercu_resume_mensuel(destinataire, resume):
    """Envoie tout de suite le résumé mensuel (marqué « Aperçu ») : le vrai envoi du mois n'est pas touché."""
    smtp_user, smtp_pass = _identifiants_smtp()
    if not smtp_user or not smtp_pass:
        return False, MESSAGE_SMTP_ABSENT
    try:
        message = composer_email_resume(resume, smtp_user, destinataire, _lire_secret("APP_URL") or ADRESSE_APPLICATION, apercu=True)
        envoyer_smtp(message, smtp_user, smtp_pass, timeout=10)
        return True, f"✅ Aperçu du résumé envoyé à {destinataire}."
    except Exception as e:
        return False, f"Erreur SMTP : {e}"

# ==============================================================================
# TAUX DE CHANGE & MÉTÉO DES MARCHÉS (CAC 40, S&P 500, VIX)
# ==============================================================================
# Lectures Yahoo et heures de marché : donnees_marche.py. Ici, seulement la mise en cache par créneau de cours
# (toutes les 5 minutes en séance, toutes les heures sinon) et les replis propres à la session.


@st.cache_data(ttl=7200, max_entries=64)
def heure_maj_cours(creneau):
    """Heure (Paris) à laquelle les cours du créneau ont été lus pour la première fois."""
    return heure_paris().strftime("%H:%M")


@st.cache_data(ttl=1800, max_entries=32)
def _taux_change_yahoo(creneau):
    """Taux EUR/USD lu sur Yahoo. Lève une erreur en cas d'échec : un échec n'est ainsi jamais mis en cache."""
    return taux_eur_usd()


def facteur_cout_usd(position):
    """
    Facteur de conversion $ -> € du COÛT D'ACHAT d'une ligne en dollars.
    Utilise le taux €/$ du jour de l'achat s'il a été saisi pour la ligne ("taux_achat" : 1 € = x $), ce qui fait
    apparaître l'effet de change dans la plus-value. Sinon, repli sur le taux du jour (effet de change nul).
    """
    try:
        taux_a = float(position.get("taux_achat") or 0.0) if isinstance(position, dict) else 0.0
    except Exception:
        taux_a = 0.0
    return 1.0 / (taux_a if taux_a > 0 else TAUX_USD_EUR)


def construire_position(nom_action, qte, pru):
    """Position {qte, pru} qui conserve le taux €/$ d'achat déjà enregistré pour cette ligne, s'il existe."""
    position = {"qte": qte, "pru": pru}
    pf_courant = st.session_state.get("portefeuille")
    ancienne = pf_courant.get(nom_action) if isinstance(pf_courant, dict) else None
    if isinstance(ancienne, dict) and ancienne.get("taux_achat"):
        position["taux_achat"] = ancienne["taux_achat"]
    return position


def recuperer_taux_change():
    """Taux EUR/USD ; en cas d'échec Yahoo, dernier taux connu de la session (sinon 1,08), retenté au prochain affichage."""
    try:
        taux = _taux_change_yahoo(creneau_cours())
        st.session_state["_dernier_taux_change_ok"] = taux
        return taux
    except Exception:
        return float(st.session_state.get("_dernier_taux_change_ok", 1.08))

# Défini dès maintenant : sauvegarder_dans_cloud() en a besoin dès la connexion et au retour de paiement Stripe
TAUX_USD_EUR = recuperer_taux_change()

def recuperer_indice_meteo(symbole):
    """Niveau et variation du jour d'un indice ; (None, 0.0) en cas d'échec, sans mise en cache de l'échec."""
    try:
        return _indice_meteo_yahoo(symbole, creneau_cours())
    except Exception:
        return None, 0.0


@st.cache_data(ttl=1800, max_entries=64)
def _indice_meteo_yahoo(symbole, creneau):
    return niveau_et_variation(symbole)

# ==============================================================================
# VALEURS PAR DÉFAUT & CATALOGUE INTERNATIONAL (PEA & US)
# ==============================================================================
WATCHLIST_DEFAUT = {
    "TotalEnergies": {"symbole": "TTE.PA", "prix_cible": 58.0, "secteur": "Énergie", "div_eur": 3.22, "payout_ratio": 0.42, "croissance_5a": "+6.1%", "mois_div": ["Jan", "Avr", "Juil", "Oct"], "devise": "EUR"},
    "Air Liquide": {"symbole": "AI.PA", "prix_cible": 165.0, "secteur": "Chimie/Industrie", "div_eur": 3.20, "payout_ratio": 0.55, "croissance_5a": "+8.5%", "mois_div": ["Mai"], "devise": "EUR"},
    "Vinci": {"symbole": "DG.PA", "prix_cible": 105.0, "secteur": "Concessions/BTP", "div_eur": 4.50, "payout_ratio": 0.52, "croissance_5a": "+7.5%", "mois_div": ["Avr", "Nov"], "devise": "EUR"},
    "AXA": {"symbole": "CS.PA", "prix_cible": 35.0, "secteur": "Assurance", "div_eur": 1.98, "payout_ratio": 0.55, "croissance_5a": "+9.2%", "mois_div": ["Mai"], "devise": "EUR"},
    "Sanofi": {"symbole": "SAN.PA", "prix_cible": 90.0, "secteur": "Santé", "div_eur": 3.76, "payout_ratio": 0.58, "croissance_5a": "+4.8%", "mois_div": ["Mai"], "devise": "EUR"},
    "Rubis": {"symbole": "RUI.PA", "prix_cible": 25.0, "secteur": "Énergie/Stockage", "div_eur": 1.98, "payout_ratio": 0.62, "croissance_5a": "+3.5%", "mois_div": ["Juin"], "devise": "EUR"},
    "Pernod Ricard": {"symbole": "RI.PA", "prix_cible": 70.0, "secteur": "Spiritueux", "div_eur": 4.70, "payout_ratio": 0.55, "croissance_5a": "+6.0%", "mois_div": ["Juil", "Nov"], "devise": "EUR"},
    "Schneider Electric": {"symbole": "SU.PA", "prix_cible": 210.0, "secteur": "Industrie/Tech", "div_eur": 3.50, "payout_ratio": 0.48, "croissance_5a": "+8.8%", "mois_div": ["Mai"], "devise": "EUR"},
    "LVMH": {"symbole": "MC.PA", "prix_cible": 620.0, "secteur": "Luxe", "div_eur": 13.00, "payout_ratio": 0.45, "croissance_5a": "+12.0%", "mois_div": ["Avr", "Déc"], "devise": "EUR"},
    "Engie": {"symbole": "ENGI.PA", "prix_cible": 16.0, "secteur": "Énergie/Utilities", "div_eur": 1.43, "payout_ratio": 0.65, "croissance_5a": "+5.0%", "mois_div": ["Mai"], "devise": "EUR"},
    "Microsoft": {"symbole": "MSFT", "prix_cible": 400.0, "secteur": "Tech US", "div_eur": 3.32, "payout_ratio": 0.25, "croissance_5a": "+10.2%", "mois_div": ["Mar", "Juin", "Sep", "Déc"], "devise": "USD"},
    "Apple": {"symbole": "AAPL", "prix_cible": 200.0, "secteur": "Tech US", "div_eur": 1.00, "payout_ratio": 0.16, "croissance_5a": "+5.5%", "mois_div": ["Fév", "Mai", "Août", "Nov"], "devise": "USD"},
    "Coca-Cola": {"symbole": "KO", "prix_cible": 62.0, "secteur": "Consommation US", "div_eur": 1.94, "payout_ratio": 0.70, "croissance_5a": "+4.5%", "mois_div": ["Avr", "Juil", "Oct", "Déc"], "devise": "USD"},
    "Realty Income": {"symbole": "O", "prix_cible": 55.0, "secteur": "Immobilier US (REIT)", "div_eur": 3.16, "payout_ratio": 0.74, "croissance_5a": "+3.8%", "mois_div": ["Jan", "Fév", "Mar", "Avr", "Mai", "Juin", "Juil", "Août", "Sep", "Oct", "Nov", "Déc"], "devise": "USD"},
}

PORTEFEUILLE_DEFAUT = {
    "TotalEnergies": {"qte": 25, "pru": 54.0},
    "Air Liquide": {"qte": 10, "pru": 155.0},
    "Rubis": {"qte": 30, "pru": 24.5},
    "AXA": {"qte": 25, "pru": 29.0},
}

CATALOGUE_ACTIONS = {
    "Air Liquide (EUR)": ("AI.PA", "EUR", "Chimie/Industrie"),
    "Amundi (EUR)": ("AMUN.PA", "EUR", "Finance/Gestion"),
    "ASML Holding (EUR)": ("ASML.AS", "EUR", "Semi-conducteurs EUR"),
    "AXA (EUR)": ("CS.PA", "EUR", "Assurance"),
    "BNP Paribas (EUR)": ("BNP.PA", "EUR", "Banque"),
    "Bouygues (EUR)": ("EN.PA", "EUR", "BTP/Télécoms"),
    "Crédit Agricole (EUR)": ("ACA.PA", "EUR", "Banque"),
    "Danone (EUR)": ("BN.PA", "EUR", "Agroalimentaire"),
    "Engie (EUR)": ("ENGI.PA", "EUR", "Énergie/Utilities"),
    "EssilorLuxottica (EUR)": ("EL.PA", "EUR", "Santé/Optique"),
    "GTT - Gaztransport (EUR)": ("GTT.PA", "EUR", "Ingénierie/GNL"),
    "Hermès (EUR)": ("RMS.PA", "EUR", "Luxe"),
    "L'Oréal (EUR)": ("OR.PA", "EUR", "Cosmétiques"),
    "Legrand (EUR)": ("LR.PA", "EUR", "Équipement Élec."),
    "LVMH (EUR)": ("MC.PA", "EUR", "Luxe"),
    "Michelin (EUR)": ("ML.PA", "EUR", "Automobile"),
    "Pernod Ricard (EUR)": ("RI.PA", "EUR", "Spiritueux"),
    "Publicis (EUR)": ("PUB.PA", "EUR", "Communication"),
    "Rubis (EUR)": ("RUI.PA", "EUR", "Énergie/Stockage"),
    "Saint-Gobain (EUR)": ("SGO.PA", "EUR", "Matériaux"),
    "Sanofi (EUR)": ("SAN.PA", "EUR", "Santé"),
    "Schneider Electric (EUR)": ("SU.PA", "EUR", "Industrie/Tech"),
    "Société Générale (EUR)": ("GLE.PA", "EUR", "Banque"),
    "Stellantis (EUR)": ("STLAP.PA", "EUR", "Automobile"),
    "TotalEnergies (EUR)": ("TTE.PA", "EUR", "Énergie"),
    "Veolia (EUR)": ("VIE.PA", "EUR", "Environnement"),
    "Vinci (EUR)": ("DG.PA", "EUR", "Concessions/BTP"),
    "AbbVie (USD)": ("ABBV", "USD", "Santé US"),
    "Alphabet - Google (USD)": ("GOOGL", "USD", "Tech US"),
    "Amazon (USD)": ("AMZN", "USD", "Tech/E-Commerce US"),
    "Apple (USD)": ("AAPL", "USD", "Tech US"),
    "Broadcom (USD)": ("AVGO", "USD", "Semi-conducteurs US"),
    "Chevron (USD)": ("CVX", "USD", "Énergie US"),
    "Coca-Cola (USD)": ("KO", "USD", "Consommation US"),
    "Costco (USD)": ("COST", "USD", "Distribution US"),
    "ExxonMobil (USD)": ("XOM", "USD", "Énergie US"),
    "Home Depot (USD)": ("HD", "USD", "Distribution US"),
    "Johnson & Johnson (USD)": ("JNJ", "USD", "Santé US"),
    "JPMorgan Chase (USD)": ("JPM", "USD", "Banque US"),
    "Mastercard (USD)": ("MA", "USD", "Paiements US"),
    "McDonald's (USD)": ("MCD", "USD", "Restauration US"),
    "Meta Platforms (USD)": ("META", "USD", "Tech US"),
    "Microsoft (USD)": ("MSFT", "USD", "Tech US"),
    "NVIDIA (USD)": ("NVDA", "USD", "IA & Semi-conducteurs US"),
    "PepsiCo (USD)": ("PEP", "USD", "Consommation US"),
    "Procter & Gamble (USD)": ("PG", "USD", "Consommation US"),
    "Realty Income - Mensuel (USD)": ("O", "USD", "Immobilier US (REIT)"),
    "Visa (USD)": ("V", "USD", "Paiements US"),
    "Walmart (USD)": ("WMT", "USD", "Distribution US"),
}

# ==============================================================================
# INITIALISATION DE LA SESSION & SYNCHRONISATION CLOUD
# ==============================================================================
if "user" not in st.session_state:
    st.session_state["user"] = None
if "watchlist" not in st.session_state:
    st.session_state["watchlist"] = WATCHLIST_DEFAUT.copy()
if "portefeuille" not in st.session_state:
    st.session_state["portefeuille"] = PORTEFEUILLE_DEFAUT.copy()
if isinstance(st.session_state.get("portefeuille"), dict) and "_historique_ventes" in st.session_state["portefeuille"]:
    st.session_state["historique_ventes"] = list(st.session_state["portefeuille"].get("_historique_ventes", []))
if "budget_dca" not in st.session_state:
    st.session_state["budget_dca"] = 450.0
if "est_abonne_pro" not in st.session_state:
    st.session_state["est_abonne_pro"] = False
if "niveau_abonnement" not in st.session_state:
    st.session_state["niveau_abonnement"] = "gratuit"
if "reponse_ia_coach" not in st.session_state:
    st.session_state["reponse_ia_coach"] = ""
if "historique_chat_ia" not in st.session_state:
    st.session_state["historique_chat_ia"] = []
if "historique_ventes" not in st.session_state:
    st.session_state["historique_ventes"] = []
date_jour_str = datetime.now().strftime("%Y-%m-%d")
if st.session_state.get("quota_ia_date") != date_jour_str:
    st.session_state["quota_ia_date"] = date_jour_str
    st.session_state["quota_ia_utilise"] = 0

def synchroniser_widgets_portefeuille(portefeuille_cloud, watchlist_courante):
    if isinstance(portefeuille_cloud, dict):
        if isinstance(portefeuille_cloud.get("_historique_ventes"), list):
            st.session_state["historique_ventes"] = list(portefeuille_cloud["_historique_ventes"])
        if "_div_encaisses_cumul" in portefeuille_cloud:
            st.session_state["dividendes_encaisses_cumul"] = float(portefeuille_cloud.get("_div_encaisses_cumul", 0.0))
        # Restauration anti-triche (F5) du quota IA journalier depuis le Cloud
        quota_str = str(portefeuille_cloud.get("_quota_ia", ""))
        if "|" in quota_str:
            q_date, q_nb = quota_str.split("|", 1)
            if q_date == datetime.now().strftime("%Y-%m-%d") and q_nb.isdigit():
                st.session_state["quota_ia_date"] = q_date
                st.session_state["quota_ia_utilise"] = max(int(st.session_state.get("quota_ia_utilise", 0)), int(q_nb))

    actions_pf_cloud = [k for k in portefeuille_cloud.keys() if k not in CLES_TECHNIQUES_PF]
    toutes_les_actions = set(list(watchlist_courante.keys()) + list(PORTEFEUILLE_DEFAUT.keys()) + actions_pf_cloud)

    for nom_act in toutes_les_actions:
        if nom_act in CLES_TECHNIQUES_PF:
            continue
        if nom_act in portefeuille_cloud and isinstance(portefeuille_cloud[nom_act], dict):
            st.session_state[f"qte_{nom_act}"] = int(portefeuille_cloud[nom_act].get("qte", 0))
            st.session_state[f"pru_{nom_act}"] = float(portefeuille_cloud[nom_act].get("pru", 0.0))
            try:
                st.session_state[f"txa_{nom_act}"] = min(5.0, max(0.0, float(portefeuille_cloud[nom_act].get("taux_achat") or 0.0)))
            except Exception:
                st.session_state[f"txa_{nom_act}"] = 0.0
        else:
            st.session_state[f"txa_{nom_act}"] = 0.0
            st.session_state[f"qte_{nom_act}"] = 0
            cible_def = float(watchlist_courante.get(nom_act, {}).get("prix_cible", 50.0))
            st.session_state[f"pru_{nom_act}"] = cible_def

    if "Espèces" in portefeuille_cloud and isinstance(portefeuille_cloud["Espèces"], dict):
        st.session_state["pru_Espèces"] = float(portefeuille_cloud["Espèces"].get("pru", 0.0))
        st.session_state["qte_Espèces"] = 1
    else:
        st.session_state["pru_Espèces"] = 0.0
        st.session_state["qte_Espèces"] = 0

def sauvegarder_dans_cloud():
    if supabase and st.session_state.get("user"):
        try:
            user_id_str = str(st.session_state["user"].id)
            email_str = str(st.session_state["user"].email)
            watchlist_actuelle = st.session_state.get("watchlist", WATCHLIST_DEFAUT)
            date_du_jour = datetime.now().strftime("%Y-%m-%d")

            # Copie indicative du niveau établi par etablir_niveau_abonnement() : n'est plus lue pour donner des droits
            est_pro_val = True if est_compte_admin(st.session_state["user"]) else bool(st.session_state.get("est_abonne_pro", False))

            hist_ventes_actuel = list(st.session_state.get("historique_ventes", []))

            # Protection anti-écrasement : conserve les ventes, le quota IA et le niveau d'abonnement sur Supabase
            if not hist_ventes_actuel and not st.session_state.get("_ventes_videes_volontairement", False):
                try:
                    res_ex = supabase.table("user_data").select("portefeuille").eq("user_id", user_id_str).execute()
                    if res_ex.data and len(res_ex.data) > 0:
                        pf_ex = res_ex.data[0].get("portefeuille") or {}
                        if isinstance(pf_ex, dict):
                            if isinstance(pf_ex.get("_historique_ventes"), list):
                                hist_ventes_actuel = list(pf_ex["_historique_ventes"])
                                st.session_state["historique_ventes"] = hist_ventes_actuel
                            q_str_ex = str(pf_ex.get("_quota_ia", ""))
                            if "|" in q_str_ex:
                                q_d_ex, q_n_ex = q_str_ex.split("|", 1)
                                if q_d_ex == date_du_jour and q_n_ex.isdigit():
                                    st.session_state["quota_ia_utilise"] = max(int(st.session_state.get("quota_ia_utilise", 0)), int(q_n_ex))
                except Exception:
                    pass

            pf_a_sauver = dict(st.session_state.get("portefeuille", {}))
            # Anciennes données d'abonnement : elles vivent désormais dans la table protégée « abonnements »
            for cle_obsolete in ("_niveau_abo", "_stripe_customer_id"):
                pf_a_sauver.pop(cle_obsolete, None)
                st.session_state["portefeuille"].pop(cle_obsolete, None)
            pf_a_sauver["_historique_ventes"] = hist_ventes_actuel
            pf_a_sauver["_quota_ia"] = f"{date_du_jour}|{int(st.session_state.get('quota_ia_utilise', 0))}"
            if pf_a_sauver.get("_alertes_auto") or pf_a_sauver.get("_resume_mensuel"):
                # Suivi écrit chaque soir par la tâche planifiée : repris de la base pour ne pas l'écraser
                try:
                    res_al = supabase.table("user_data").select("portefeuille").eq("user_id", user_id_str).execute()
                    pf_al = (res_al.data[0].get("portefeuille") or {}) if res_al.data else {}
                    if isinstance(pf_al, dict) and isinstance(pf_al.get("_alertes_envoyees"), list):
                        pf_a_sauver["_alertes_envoyees"] = pf_al["_alertes_envoyees"]
                        st.session_state["portefeuille"]["_alertes_envoyees"] = pf_al["_alertes_envoyees"]
                    if isinstance(pf_al, dict) and isinstance(pf_al.get("_resume_envoye"), str):
                        pf_a_sauver["_resume_envoye"] = pf_al["_resume_envoye"]
                        st.session_state["portefeuille"]["_resume_envoye"] = pf_al["_resume_envoye"]
                except Exception:
                    pass
            pf_a_sauver["_div_encaisses_cumul"] = round(float(st.session_state.get("dividendes_encaisses_cumul", pf_a_sauver.get("_div_encaisses_cumul", 0.0))), 2)
            st.session_state["portefeuille"]["_historique_ventes"] = hist_ventes_actuel
            st.session_state["portefeuille"]["_quota_ia"] = pf_a_sauver["_quota_ia"]
            st.session_state["portefeuille"]["_div_encaisses_cumul"] = pf_a_sauver["_div_encaisses_cumul"]

            payload = {
                "user_id": user_id_str,
                "email": email_str,
                "budget_dca": float(st.session_state.get("budget_dca", 450.0)),
                "watchlist": dict(watchlist_actuelle),
                "portefeuille": pf_a_sauver,
                "est_abonne_pro": est_pro_val,
                "updated_at": datetime.now().isoformat()
            }
            supabase.table("user_data").upsert(payload).execute()

            # Calcul et sauvegarde du Snapshot du jour dans portfolio_history
            cap_investi = 0.0
            val_totale = 0.0
            rente_tot = 0.0
            prix_tr = st.session_state.get("prix_temps_reel", {})
            snapshot_fiable = True  # Faux dès qu'une ligne détenue n'a pas de cours réel : pas de snapshot faussé

            for nom_a, pos_a in pf_a_sauver.items():
                if (nom_a in CLES_TECHNIQUES_PF and nom_a != "Espèces") or not isinstance(pos_a, dict):
                    continue
                q_a = float(pos_a.get("qte", 0.0))
                p_a = float(pos_a.get("pru", 0.0))
                if q_a <= 0:
                    continue
                if nom_a == "Espèces":
                    cap_investi += p_a
                    val_totale += p_a
                else:
                    info_a = watchlist_actuelle.get(nom_a, WATCHLIST_DEFAUT.get(nom_a, {}))
                    fact_a = (1.0 / TAUX_USD_EUR) if info_a.get("devise") == "USD" else 1.0
                    fact_cout_a = facteur_cout_usd(pos_a) if info_a.get("devise") == "USD" else 1.0
                    if nom_a in prix_tr:
                        cours_a = float(prix_tr[nom_a])
                    else:
                        cours_a = p_a
                        snapshot_fiable = False
                    div_a = float(info_a.get("div_eur", 0.0))
                    cap_investi += q_a * p_a * fact_cout_a
                    val_totale += q_a * cours_a * fact_a
                    rente_tot += q_a * div_a * fact_a
            if val_totale > 0 and snapshot_fiable:
                snapshot_payload = {
                    "user_id": user_id_str,
                    "date": date_du_jour,
                    "capital_investi": round(cap_investi, 2),
                    "valorisation_pea": round(val_totale, 2),
                    "rente_annuelle": round(rente_tot, 2)
                }
                supabase.table("portfolio_history").delete().eq("user_id", user_id_str).eq("date", date_du_jour).execute()
                supabase.table("portfolio_history").insert(snapshot_payload).execute()
                st.session_state.pop("_historique_snapshots", None)  # la courbe réelle sera relue avec ce nouveau point

            if snapshot_fiable:
                st.sidebar.success("✅ Sauvegardé & Snapshot du jour mis à jour !")
            else:
                st.sidebar.success("✅ Sauvegardé ! (Snapshot du jour non mis à jour : cours indisponible pour au moins une ligne.)")
            return True
        except Exception as e:
            st.sidebar.error(f"Erreur Supabase : {e}")
            return False
    else:
        st.sidebar.warning("⚠️ Connectez-vous dans l'Espace Membre pour sauvegarder dans le Cloud.")
        return False


# ==============================================================================
# BARRE LATÉRALE : ESPACE MEMBRE, DCA, GESTION D'ACTIFS & CONSOLE ADMIN
# ==============================================================================
st.sidebar.header("👤 Espace Membre")

# --- RÉINITIALISATION DU MOT DE PASSE : page ouverte depuis le lien reçu par e-mail ---
# Le modèle d'e-mail « Reset Password » de Supabase doit pointer vers {{ .SiteURL }}?type=recovery&token_hash={{ .TokenHash }}
# (voir README) : le jeton arrive ainsi dans l'adresse, lisible par le serveur Streamlit.
_type_lien = str(st.query_params.get("type", ""))
_jeton_lien = str(st.query_params.get("token_hash", ""))
if supabase is not None and ((_type_lien == "recovery" and _jeton_lien) or st.session_state.get("_reinit_mdp_actif")):
    st.title("🔑 Choisir un nouveau mot de passe")
    if not st.session_state.get("_reinit_mdp_actif"):
        try:
            reponse_jeton = supabase.auth.verify_otp({"token_hash": _jeton_lien, "type": "recovery"})
            if not getattr(reponse_jeton, "session", None):
                raise ValueError("jeton refusé")
            st.session_state["_reinit_mdp_actif"] = True
            st.session_state["user"] = None  # session de récupération : personne n'est connecté à l'application
        except Exception:
            st.error(
                "Ce lien de réinitialisation est invalide ou a expiré : il ne sert qu'une fois et pendant une durée limitée. "
                "Redemandez-en un depuis « Mot de passe oublié » dans le menu de gauche."
            )
            if st.button("Revenir à l'accueil", type="primary"):
                st.query_params.clear()
                st.rerun()
            st.stop()

    with st.form("form_nouveau_mot_de_passe"):
        nouveau_mdp = st.text_input("Nouveau mot de passe (6 caractères minimum)", type="password")
        confirmation_mdp = st.text_input("Confirmer le nouveau mot de passe", type="password")
        valider_mdp = st.form_submit_button("Enregistrer mon nouveau mot de passe", type="primary")
    if valider_mdp:
        if len(nouveau_mdp) < 6:
            st.error("Le mot de passe doit contenir au moins 6 caractères.")
        elif nouveau_mdp != confirmation_mdp:
            st.error("Les deux mots de passe ne sont pas identiques.")
        else:
            try:
                supabase.auth.update_user({"password": nouveau_mdp})
                try:
                    supabase.auth.sign_out()
                except Exception:
                    pass
                st.session_state.pop("_reinit_mdp_actif", None)
                st.session_state["_notif_mdp_change"] = True
                st.query_params.clear()
                st.rerun()
            except Exception as erreur_mdp:
                st.error(f"Le mot de passe n'a pas pu être modifié : {erreur_mdp}")
    st.stop()

if st.session_state.pop("_notif_compte_supprime", False):
    st.sidebar.success("✅ Votre compte et toutes vos données ont été supprimés.")

if st.session_state.pop("_notif_mdp_change", False):
    st.sidebar.success("✅ Mot de passe modifié. Connectez-vous avec votre nouveau mot de passe.")

if supabase is None:
    st.sidebar.warning("⚠️ Base de données non connectée. Mode local actif.")
else:
    if st.session_state["user"] is None:
        choix_auth = st.sidebar.radio("Navigation compte :", ["Se connecter", "Créer un compte", "Mot de passe oublié"])
        email_input = st.sidebar.text_input("Adresse Email").strip()

        if choix_auth == "Se connecter":
            password_input = st.sidebar.text_input("Mot de passe", type="password")
            if st.sidebar.button("🔓 Connexion", type="primary", width="stretch"):
                res = None
                try:
                    res = supabase.auth.sign_in_with_password({"email": email_input, "password": password_input})
                except Exception:
                    st.sidebar.error("Identifiants incorrects ou compte inexistant.")

                # Le compte n'est marqué « connecté » qu'une fois ses données chargées : si le chargement échoue,
                # personne n'est connecté et le portefeuille de démonstration ne peut pas écraser les données du Cloud.
                if res is not None and getattr(res, "user", None) is not None:
                  try:
                    data = supabase.table("user_data").select("*").eq("user_id", res.user.id).execute()
                    st.session_state["user"] = res.user
                    if data.data:
                        profil = data.data[0]
                        wl_cloud = profil.get("watchlist")
                        st.session_state["watchlist"] = wl_cloud if wl_cloud is not None else WATCHLIST_DEFAUT.copy()
                        pf_raw = profil.get("portefeuille")
                        portefeuille_cloud = pf_raw if pf_raw is not None else PORTEFEUILLE_DEFAUT.copy()
                        st.session_state["portefeuille"] = portefeuille_cloud
                        st.session_state["budget_dca"] = float(profil.get("budget_dca") or 450.0)

                        synchroniser_widgets_portefeuille(portefeuille_cloud, st.session_state["watchlist"])
                        etablir_niveau_abonnement(res.user)
                    else:
                        etablir_niveau_abonnement(res.user)
                        sauvegarder_dans_cloud()
                    st.rerun()
                  except Exception:
                    st.session_state["user"] = None
                    st.session_state["watchlist"] = WATCHLIST_DEFAUT.copy()
                    st.session_state["portefeuille"] = PORTEFEUILLE_DEFAUT.copy()
                    st.session_state["est_abonne_pro"] = False
                    st.session_state["niveau_abonnement"] = "gratuit"
                    try:
                        supabase.auth.sign_out()
                    except Exception:
                        pass
                    st.sidebar.error("⚠️ Connexion réussie, mais vos données n'ont pas pu être chargées. Vous n'êtes pas connecté : réessayez dans un instant.")

        elif choix_auth == "Créer un compte":
            password_input = st.sidebar.text_input("Choisir un mot de passe (6 car. min.)", type="password")
            if st.sidebar.button("✨ S'inscrire gratuitement", type="primary", width="stretch"):
                try:
                    res = supabase.auth.sign_up({"email": email_input, "password": password_input})
                    # Connexion uniquement si Supabase a ouvert une VRAIE session. Sans session (e-mail à confirmer,
                    # ou adresse déjà inscrite : Supabase renvoie alors un utilisateur factice), on ne connecte personne.
                    if res.user and getattr(res, "session", None):
                        st.session_state["user"] = res.user
                        st.session_state["watchlist"] = WATCHLIST_DEFAUT.copy()
                        st.session_state["portefeuille"] = PORTEFEUILLE_DEFAUT.copy()
                        etablir_niveau_abonnement(res.user)
                        sauvegarder_dans_cloud()
                        st.sidebar.success("Compte créé avec succès !")
                        st.rerun()
                    elif res.user:
                        st.sidebar.info(
                            "📧 Presque terminé ! Cliquez sur le lien de confirmation reçu par e-mail, puis connectez-vous. "
                            "Si un compte existe déjà avec cette adresse, utilisez « Se connecter » ou « Mot de passe oublié »."
                        )
                except Exception as e:
                    st.sidebar.error(f"Erreur d'inscription : {e}")

        else:
            st.sidebar.caption("Recevez un lien sécurisé de réinitialisation par email :")
            if st.sidebar.button("📧 Envoyer le lien", width="stretch"):
                if not email_input or "@" not in email_input:
                    st.sidebar.warning("⚠️ Veuillez saisir une adresse email valide.")
                else:
                    try:
                        supabase.auth.reset_password_for_email(email_input)
                        st.sidebar.success("✅ Email envoyé ! Vérifiez votre boîte de réception.")
                    except Exception as e:
                        st.sidebar.error(f"Erreur : {e}")
    else:
        email_courant = str(st.session_state["user"].email)
        est_admin_connecte = est_compte_admin(st.session_state["user"])
        if est_admin_connecte:
            st.session_state["est_abonne_pro"] = True
            st.session_state["niveau_abonnement"] = "pro"

        param_paiement = str(st.query_params.get("paiement", "")).lower()
        if param_paiement in ("succes", "premium", "pro"):
            # Le palier (premium / pro) est celui constaté sur Stripe, jamais celui indiqué dans l'URL
            if etablir_niveau_abonnement(st.session_state["user"]) in ("premium", "pro"):
                sauvegarder_dans_cloud()
                st.query_params.clear()
                st.balloons()
                st.sidebar.success("🎉 Paiement validé ! Votre abonnement est actif.")

        st.sidebar.success(f"Connecté : **{email_courant}**")

        if st.sidebar.button("🔄 Charger mes données", type="primary", width="stretch"):
            try:
                reponse = supabase.table("user_data").select("*").eq("user_id", st.session_state["user"].id).execute()
                if reponse.data:
                    profil = reponse.data[0]
                    wl_cloud = profil.get("watchlist")
                    st.session_state["watchlist"] = wl_cloud if wl_cloud is not None else WATCHLIST_DEFAUT.copy()
                    pf_raw = profil.get("portefeuille")
                    portefeuille_cloud = pf_raw if pf_raw is not None else PORTEFEUILLE_DEFAUT.copy()
                    st.session_state["portefeuille"] = portefeuille_cloud
                    st.session_state["budget_dca"] = float(profil.get("budget_dca") or 450.0)
                    synchroniser_widgets_portefeuille(portefeuille_cloud, st.session_state["watchlist"])
                    etablir_niveau_abonnement(st.session_state["user"], verifier_stripe=False)
                    st.sidebar.success("✅ Données synchronisées !")
                    st.rerun()
            except Exception as e:
                st.sidebar.error(f"Erreur : {e}")

        # --- MON COMPTE : SUPPRESSION DÉFINITIVE (droit à l'effacement, RGPD article 17) ---
        with st.sidebar.expander("⚙️ Mon compte"):
            st.caption("Supprimer votre compte efface définitivement votre portefeuille, votre historique et votre accès. Pensez à exporter vos données (bouton CSV) avant.")
            niveau_compte = st.session_state.get("niveau_abonnement", "gratuit") if st.session_state.get("est_abonne_pro") else "gratuit"
            if est_admin_connecte:
                st.info("Le compte administrateur ne peut pas être supprimé depuis l'application.")
            elif niveau_compte in ("premium", "pro") and not st.session_state.get("abo_fin_periode"):
                st.warning(
                    "Votre abonnement est encore actif : résiliez-le d'abord avec « ⚙️ Gérer mon abonnement / Factures » "
                    "(menu 💎 Offres & Abonnement), pour ne plus être prélevé, puis revenez ici."
                )
            else:
                confirmation_suppr = st.text_input("Tapez SUPPRIMER pour confirmer", key="txt_confirmer_suppression")
                if st.button("🗑️ Supprimer définitivement mon compte", width="stretch", disabled=(confirmation_suppr.strip() != "SUPPRIMER")):
                    # Vérification au moment du clic (Stripe ou table protégée) : un abonnement encore actif bloque la
                    # suppression, même si l'affichage précédent ne le savait pas encore
                    if etablir_niveau_abonnement(st.session_state["user"]) in ("premium", "pro") and not st.session_state.get("abo_fin_periode"):
                        ok_suppr, msg_suppr = False, ("Votre abonnement est encore actif : résiliez-le d'abord avec « ⚙️ Gérer mon "
                                                      "abonnement / Factures », pour ne plus être prélevé, puis revenez ici.")
                    else:
                        ok_suppr, msg_suppr = supprimer_compte_utilisateur(st.session_state["user"])
                    if ok_suppr:
                        try:
                            supabase.auth.sign_out()
                        except Exception:
                            pass
                        for cle_session in list(st.session_state.keys()):
                            del st.session_state[cle_session]
                        st.session_state["_notif_compte_supprime"] = True
                        st.rerun()
                    else:
                        st.error(msg_suppr)

        col_btn1, col_btn2 = st.sidebar.columns(2)
        if col_btn1.button("💾 Sauver", width="stretch"):
            if sauvegarder_dans_cloud():
                st.toast("✅ Profil & Snapshot sauvegardés dans le Cloud !")
        if col_btn2.button("🚪 Sortir", width="stretch"):
            supabase.auth.sign_out()
            st.session_state["user"] = None
            st.session_state["est_abonne_pro"] = False
            st.session_state["niveau_abonnement"] = "gratuit"
            st.session_state.pop("_stripe_sync_session_ok", None)
            st.session_state.pop("_historique_snapshots", None)
            st.session_state.pop("abo_fin_periode", None)
            for cle_stripe_session in ("_stripe_client_id", "_url_portail_session", "_portail_session_echec"):
                st.session_state.pop(cle_stripe_session, None)
            st.rerun()

# Symboles Yahoo changés depuis l'ajout d'une valeur au radar (ex. FDJ.PA devenu FDJU.PA) : corrigés en mémoire,
# puis enregistrés avec le radar à la prochaine sauvegarde
for info_radar in st.session_state["watchlist"].values():
    if isinstance(info_radar, dict) and info_radar.get("symbole"):
        info_radar["symbole"] = symbole_a_jour(info_radar["symbole"])
WATCHLIST = st.session_state["watchlist"]
WATCHLIST_DEFAUT.update(st.session_state["watchlist"])
TAUX_USD_EUR = recuperer_taux_change()
st.session_state["taux_change"] = TAUX_USD_EUR

if st.sidebar.button("🔄 Actualiser les cours Bourse", width="stretch"):
    st.cache_data.clear()
    st.toast("⚡ Cours boursiers, indices et taux EUR/USD actualisés !")
    st.rerun()

# --- RAFRAÎCHISSEMENT AUTOMATIQUE : la page se relit seule toutes les 5 minutes pendant les heures de bourse ---
st.session_state["_dernier_affichage_complet"] = time.time()
rafraichissement_auto = st.sidebar.toggle(
    "⏱️ Rafraîchir les cours automatiquement",
    value=True,
    key="tog_rafraichissement_auto",
    help="Pendant les heures de bourse, la page se met à jour seule toutes les 5 minutes. "
         "Désactivez l'option si vous préférez actualiser à la main.",
)


@st.fragment(run_every=RAFRAICHISSEMENT_SEANCE_SECONDES if (rafraichissement_auto and marches_ouverts()) else None)
def _minuteur_rafraichissement():
    # Ce minuteur ne dessine rien. À chaque échéance, il relance l'affichage complet si la page n'a pas déjà été
    # réaffichée entre-temps (par une action de l'utilisateur, par exemple).
    ecoule = time.time() - float(st.session_state.get("_dernier_affichage_complet", 0.0))
    if ecoule >= RAFRAICHISSEMENT_SEANCE_SECONDES - 10:
        st.rerun()


_minuteur_rafraichissement()

# --- PARAMÈTRES DCA ---
st.sidebar.markdown("---")
st.sidebar.header("⚙️ Paramètres DCA")
nouveau_budget = st.sidebar.number_input(
    "Enveloppe Mensuelle (€)",
    min_value=50.0,
    max_value=10000.0,
    value=float(st.session_state["budget_dca"]),
    step=50.0,
)
if nouveau_budget != st.session_state["budget_dca"]:
    st.session_state["budget_dca"] = nouveau_budget
    sauvegarder_dans_cloud()

BUDGET_MENSUEL = st.session_state["budget_dca"]

# --- AJOUT / GESTION DES ACTIONS (CATALOGUE + TICKER LIBRE) ---
st.sidebar.markdown("---")
st.sidebar.subheader("🔍 Ajouter / Gérer les actions")

# --- MÉGA-CATALOGUE ENRICHI (+100 VALEURS PEA, SBF 120, EUROPE, ETF & US) ---

for nom_e, (sym_e, dev_e, sec_e, cib_e, div_e, pay_e, cr_e, mois_e) in ENRICHISSEMENT_CATALOGUE.items():
    CATALOGUE_ACTIONS[f"{nom_e} ({dev_e})"] = (sym_e, dev_e, sec_e)
    if nom_e not in WATCHLIST_DEFAUT:
        WATCHLIST_DEFAUT[nom_e] = {
            "symbole": sym_e,
            "prix_cible": cib_e,
            "secteur": sec_e,
            "div_eur": div_e,
            "payout_ratio": pay_e,
            "croissance_5a": cr_e,
            "mois_div": mois_e,
            "devise": dev_e,
        }
# Valeur renommée encore enregistrée sous son ancien nom dans un portefeuille : même fiche que le nouveau nom
for ancien_nom_v, nouveau_nom_v in NOMS_RENOMMES.items():
    if ancien_nom_v in st.session_state.get("portefeuille", {}) and ancien_nom_v not in WATCHLIST_DEFAUT and nouveau_nom_v in WATCHLIST_DEFAUT:
        WATCHLIST_DEFAUT[ancien_nom_v] = dict(WATCHLIST_DEFAUT[nouveau_nom_v])

WATCHLIST_DEFAUT.update(st.session_state["watchlist"])

def recuperer_donnees(symbole):
    """Cours + historique 3 ans. Un échec Yahoo renvoie (None, None, None, None) sans être mis en cache."""
    try:
        return _recuperer_donnees_yahoo(symbole, creneau_cours())
    except Exception:
        return None, None, None, None


@st.cache_data(ttl=3600, max_entries=1500)
def _recuperer_donnees_yahoo(symbole, creneau):
    return cours_et_historique(symbole, "3y")

def historique_long(symbole):
    """(dates ISO, clôtures, dividendes [(date ISO, montant)], plus hauts, plus bas) sur 10 ans ; None si indisponible."""
    try:
        return _historique_long_yahoo(str(symbole).strip())
    except Exception:
        return None


@st.cache_data(ttl=21600, max_entries=300)
def _historique_long_yahoo(symbole):
    return historique_dix_ans(symbole)


@st.cache_data(ttl=86400, max_entries=4)
def _solidite_catalogue(annee, jour):
    """
    Étude des dividendes appliquée à tout le catalogue (hors ETF) au 31 décembre de l'année : valeurs de l'étude par
    symbole et seuils des 20 % les plus élevés. Erreur (non mise en cache) si moins de la moitié des historiques est lue.
    """
    symboles = sorted({sym for sym, _devise, secteur, *_reste in ENRICHISSEMENT_CATALOGUE.values() if "ETF" not in secteur})
    with ThreadPoolExecutor(max_workers=8) as executeur:
        historiques = dict(zip(symboles, executeur.map(historique_long, symboles)))
    if sum(1 for h in historiques.values() if h) < len(symboles) / 2:
        raise RuntimeError("Historiques de dividendes indisponibles")
    valeurs = {sym: solidite_dividendes.caracteristiques(h, annee) for sym, h in historiques.items()}
    return valeurs, solidite_dividendes.seuils(valeurs)


@st.cache_resource
def _analyses_solidite_faites():
    """Jours où l'analyse du catalogue a déjà été calculée (partagé entre utilisateurs) : elle s'affiche alors d'emblée."""
    return set()


def analyse_solidite_dividendes(symboles, calculer=False):
    """
    Solidité des dividendes (étude pré-enregistrée) : {"annee", "seuils", "catalogue": {symbole: (valeurs, statut)},
    "demandes": {symbole: (valeurs, statut)}, "noms": {symbole: (nom, secteur, devise)}}.
    None si l'analyse du jour n'a pas encore été lancée (et calculer=False) ou si Yahoo est indisponible.
    """
    aujourd_hui = heure_paris().date()
    annee = solidite_dividendes.annee_de_reference(aujourd_hui)
    cle = (annee, aujourd_hui.isoformat())
    if not calculer and cle not in _analyses_solidite_faites():
        return None
    try:
        valeurs_catalogue, seuils_catalogue = _solidite_catalogue(*cle)
    except Exception:
        return None
    _analyses_solidite_faites().add(cle)

    def avec_statut(valeurs):
        return valeurs, solidite_dividendes.statut(valeurs, seuils_catalogue, annee)

    catalogue = {sym: avec_statut(v) for sym, v in valeurs_catalogue.items()}
    demandes = {}
    for symbole in symboles:
        symbole = str(symbole).strip()
        demandes[symbole] = catalogue.get(symbole) or avec_statut(solidite_dividendes.caracteristiques(historique_long(symbole), annee))
    noms = {sym: (nom, secteur, devise) for nom, (sym, devise, secteur, *_reste) in ENRICHISSEMENT_CATALOGUE.items()}
    return {"annee": annee, "seuils": seuils_catalogue, "catalogue": catalogue, "demandes": demandes, "noms": noms}


def bilan_signaux_symbole(symbole, payout_r):
    """Observations mensuelles du radar rejoué sur le passé pour une action ; None si l'historique est indisponible."""
    try:
        return _bilan_signaux_symbole(str(symbole).strip(), round(float(payout_r), 4))
    except Exception:
        return None


@st.cache_data(ttl=21600, max_entries=300)
def _bilan_signaux_symbole(symbole, payout_r):
    """
    Rejoue les algorithmes une fois par mois sur l'historique (moteur_signaux.rejouer_signaux) : à chaque date, seuls les
    cours et les dividendes connus à cette date sont utilisés. Mesure ensuite la performance des 1, 3 et 6 mois suivants.
    """
    historique = historique_long(symbole)
    if historique is None or len(historique) < 5:
        raise RuntimeError(f"Historique indisponible : {symbole}")
    return rejouer_signaux(historique, payout_r)


@st.cache_data(ttl=3600)
def lire_signaux_mensuels():
    """Toutes les lignes du journal des signaux en direct (table signaux_mensuels) ; None si la lecture est impossible."""
    client_serveur = init_supabase_serveur()
    if client_serveur is None:
        raise RuntimeError("Clé de service absente")
    lignes, debut = [], 0
    while True:
        lot = client_serveur.table("signaux_mensuels").select("*").order("mois").range(debut, debut + 999).execute().data or []
        lignes.extend(lot)
        if len(lot) < 1000:
            return lignes
        debut += 1000


@st.cache_data(ttl=1800)
def inspecter_dividende_yahoo_live(symbole):
    """Cours, devise réelle, dividende annuel et mois de versement lus sur Yahoo (voir donnees_marche.inspecter_dividende)."""
    return inspecter_dividende(symbole)

@st.cache_data(ttl=1800)
def rechercher_actions_yahoo_live(requete):
    """Recherche hybride : Méga-Catalogue local instantané + API Yahoo Finance."""
    if not requete or len(requete.strip()) < 2:
        return []
    q_clean = requete.strip()
    q_low = q_clean.lower()
    resultats = []
    symboles_vus = set()

    for lib_cat, (sym_c, dev_c, sec_c) in CATALOGUE_ACTIONS.items():
        nom_c = lib_cat.rsplit(" (", 1)[0]
        if q_low in nom_c.lower() or q_low in sym_c.lower() or q_low in sec_c.lower():
            resultats.append({
                "label": f"⭐ {nom_c} ({sym_c} — Catalogue | {dev_c})",
                "nom": nom_c,
                "symbole": sym_c,
                "devise": dev_c,
                "secteur": sec_c,
            })
            symboles_vus.add(sym_c.upper())

    resultats.extend(rechercher_yahoo(q_clean, symboles_vus))
    return resultats

mode_ajout = st.sidebar.radio(
    "Mode de recherche :",
    ["📚 Catalogue (+100 valeurs)", "🌐 Recherche Yahoo Live"],
    horizontal=True,
)

if mode_ajout == "📚 Catalogue (+100 valeurs)":
    filtre_texte_cat = st.sidebar.text_input("🔎 Filtrer le catalogue (ex: Thales, GTT, ETF, Luxe...)", "").strip().lower()
    cles_catalogue = sorted(CATALOGUE_ACTIONS.keys())
    if filtre_texte_cat:
        cles_catalogue = [
            k for k in cles_catalogue
            if filtre_texte_cat in k.lower()
            or filtre_texte_cat in CATALOGUE_ACTIONS[k][0].lower()
            or filtre_texte_cat in CATALOGUE_ACTIONS[k][2].lower()
        ]

    choix_menu_yf = st.sidebar.selectbox(
        f"Sélectionner ({len(cles_catalogue)} valeurs dispo) :",
        ["-- Choisir une action --"] + cles_catalogue,
    )
    if choix_menu_yf != "-- Choisir une action --":
        symbole_sel, devise_sel, secteur_def = CATALOGUE_ACTIONS[choix_menu_yf]
        nom_propre = choix_menu_yf.rsplit(" (", 1)[0]
        info_pre = WATCHLIST.get(nom_propre, WATCHLIST_DEFAUT.get(nom_propre, {}))

        with st.sidebar.form("form_catalogue_yf"):
            st.markdown(f"**{nom_propre}** (`{symbole_sel}`) — **{devise_sel}**")
            nouveau_secteur = st.text_input("Secteur", value=info_pre.get("secteur", secteur_def))
            nouveau_cible = st.number_input(f"Prix cible ({devise_sel})", min_value=0.0, value=float(info_pre.get("prix_cible", 100.0)), step=1.0)
            nouveau_div = st.number_input(f"Dividende annuel ({devise_sel})", min_value=0.0, value=float(info_pre.get("div_eur", 2.5)), step=0.1)
            nouveau_payout = st.number_input("Payout Ratio (ex: 0.50)", min_value=0.0, max_value=2.0, value=float(info_pre.get("payout_ratio", 0.50)), step=0.05)
            nouveau_croiss = st.text_input("Croissance Div. 5A", value=info_pre.get("croissance_5a", "+6.0%"))
            liste_mois_possibles = ["Jan", "Fév", "Mar", "Avr", "Mai", "Juin", "Juil", "Août", "Sep", "Oct", "Nov", "Déc"]
            def_mois = ["Mar", "Juin", "Sep", "Déc"] if devise_sel == "USD" else ["Mai"]
            mois_actuels = [m for m in info_pre.get("mois_div", def_mois) if m in liste_mois_possibles] or def_mois
            nouveau_mois = st.multiselect("Mois de versement :", liste_mois_possibles, default=mois_actuels)

            st.markdown("---")
            st.caption("💼 **Optionnel : Ajouter aussi dans mon Portefeuille**")
            qte_init_pf = int(st.session_state["portefeuille"].get(nom_propre, {}).get("qte", 0)) if isinstance(st.session_state["portefeuille"].get(nom_propre), dict) else 0
            pru_init_pf = float(st.session_state["portefeuille"].get(nom_propre, {}).get("pru", float(info_pre.get("prix_cible", 100.0)))) if isinstance(st.session_state["portefeuille"].get(nom_propre), dict) else float(info_pre.get("prix_cible", 100.0))
            qte_ajout_pf = st.number_input("Quantité détenue (0 = Radar seul)", min_value=0, value=qte_init_pf, step=1)
            pru_ajout_pf = st.number_input(f"Mon PRU unitaire ({devise_sel})", min_value=0.0, value=pru_init_pf, step=0.5)

            if st.form_submit_button("➕ Ajouter au Radar & Portefeuille", type="primary"):
                nouvel_objet_act = {
                    "symbole": symbole_sel,
                    "prix_cible": nouveau_cible,
                    "secteur": nouveau_secteur,
                    "div_eur": nouveau_div,
                    "payout_ratio": nouveau_payout,
                    "croissance_5a": nouveau_croiss,
                    "mois_div": nouveau_mois,
                    "devise": devise_sel,
                }
                st.session_state["watchlist"][nom_propre] = nouvel_objet_act
                WATCHLIST_DEFAUT[nom_propre] = nouvel_objet_act
                if qte_ajout_pf > 0:
                    st.session_state["portefeuille"][nom_propre] = construire_position(nom_propre, int(qte_ajout_pf), float(pru_ajout_pf))
                    st.session_state[f"qte_{nom_propre}"] = int(qte_ajout_pf)
                    st.session_state[f"pru_{nom_propre}"] = float(pru_ajout_pf)
                sauvegarder_dans_cloud()
                st.rerun()
else:
    col_yq1, col_yq2 = st.sidebar.columns([3, 1.2])
    with col_yq1:
        requete_yahoo = st.text_input("🌐 Nom ou Ticker Yahoo", placeholder="Ex: Ferrari, Novo, MC.PA...").strip()
    with col_yq2:
        st.markdown("<div style='margin-top:28px;'></div>", unsafe_allow_html=True)
        st.button("🔎 Chercher", width="stretch")

    resultats_yahoo = rechercher_actions_yahoo_live(requete_yahoo) if len(requete_yahoo) >= 2 else []

    nom_defaut_y, sym_defaut_y, dev_defaut_y, sec_defaut_y = requete_yahoo, requete_yahoo.upper(), "EUR", "Action Internationale"
    if resultats_yahoo:
        choix_res_y = st.sidebar.selectbox("Résultats trouvés :", [r["label"] for r in resultats_yahoo])
        item_y = next((r for r in resultats_yahoo if r["label"] == choix_res_y), resultats_yahoo[0])
        nom_defaut_y = item_y["nom"]
        sym_defaut_y = item_y["symbole"]
        dev_defaut_y = item_y["devise"]
        sec_defaut_y = item_y["secteur"]

    info_connue_y = WATCHLIST_DEFAUT.get(nom_defaut_y, {})
    prix_detecte, dev_detectee, div_detecte, mois_detectes = inspecter_dividende_yahoo_live(sym_defaut_y) if sym_defaut_y else (None, "EUR", 0.0, ["Mai"])
    # La devise lue sur Yahoo fait foi dès que le cours a été trouvé. Seuls l'euro et le dollar sont gérés :
    # une autre devise (GBP, CHF, DKK...) serait comptée à 1 pour 1 et fausserait toute la valorisation.
    devise_non_geree = bool(prix_detecte) and dev_detectee not in ("EUR", "USD")
    if prix_detecte and not devise_non_geree:
        dev_defaut_y = dev_detectee

    cible_auto = float(info_connue_y.get("prix_cible", round(prix_detecte * 0.95, 2) if prix_detecte else 100.0))
    # Aucun dividende trouvé = 0 (action de croissance, ETF capitalisant...) : on n'invente plus de rendement
    div_auto = float(info_connue_y.get("div_eur", div_detecte))
    payout_auto = float(info_connue_y.get("payout_ratio", 0.50))

    if devise_non_geree:
        st.sidebar.error(
            f"⚠️ `{sym_defaut_y}` est cotée en **{dev_detectee}**. Seules les valeurs cotées en euros (€) ou en dollars ($) "
            "sont gérées pour l'instant : choisissez une cotation en EUR ou en USD de cette action."
        )
    elif prix_detecte:
        txt_div_detecte = f"Div. détecté : **{div_auto:.2f} {dev_defaut_y}**" if div_auto > 0 else "Aucun dividende détecté"
        st.sidebar.success(nombres_fr(f"⚡ Cours live : **{prix_detecte:.2f} {dev_defaut_y}** | {txt_div_detecte}"))

    nom_libre = st.sidebar.text_input("Nom de l'action", value=nom_defaut_y, key=f"yl_nom_{sym_defaut_y}").strip()
    sym_libre = st.sidebar.text_input("Ticker Yahoo (ex: OR.PA, ASML.AS, NVDA)", value=sym_defaut_y, key=f"yl_sym_{sym_defaut_y}").strip().upper()
    dev_libre = st.sidebar.selectbox("Devise de cotation :", ["EUR", "USD"], index=0 if dev_defaut_y == "EUR" else 1, key=f"yl_dev_{sym_defaut_y}")
    sec_libre = st.sidebar.text_input("Secteur", value=sec_defaut_y, key=f"yl_sec_{sym_defaut_y}")
    cible_libre = st.sidebar.number_input(f"Prix cible ({dev_libre})", min_value=0.0, value=cible_auto, step=1.0, key=f"yl_cib_{sym_defaut_y}")
    div_libre = st.sidebar.number_input(f"Dividende annuel ({dev_libre})", min_value=0.0, value=div_auto, step=0.1, key=f"yl_div_{sym_defaut_y}")
    payout_libre = st.sidebar.number_input("Payout Ratio (ex: 0.50)", min_value=0.0, max_value=2.0, value=payout_auto, step=0.05, key=f"yl_pay_{sym_defaut_y}")
    liste_mois_possibles = ["Jan", "Fév", "Mar", "Avr", "Mai", "Juin", "Juil", "Août", "Sep", "Oct", "Nov", "Déc"]
    mois_def_y = [m for m in info_connue_y.get("mois_div", mois_detectes) if m in liste_mois_possibles] or ["Mai"]
    mois_libre = st.sidebar.multiselect("Mois de versement :", liste_mois_possibles, default=mois_def_y, key=f"yl_mois_{sym_defaut_y}")

    st.sidebar.markdown("---")
    st.sidebar.caption("💼 **Optionnel : Ajouter aussi dans mon Portefeuille**")
    qte_libre_pf = st.sidebar.number_input("Quantité détenue (0 = Radar seul)", min_value=0, value=0, step=1, key=f"yl_qte_{sym_defaut_y}")
    pru_libre_pf = st.sidebar.number_input(f"Mon PRU unitaire ({dev_libre})", min_value=0.0, value=float(prix_detecte if prix_detecte else cible_auto), step=0.5, key=f"yl_pru_{sym_defaut_y}")

    if st.sidebar.button("🚀 Valider & Ajouter cette Action", type="primary", width="stretch"):
        sym_final = sym_libre or sym_defaut_y or requete_yahoo.upper()
        # Les noms sont affichés dans des tableaux HTML : on en retire les chevrons pour qu'ils restent du simple texte
        nom_final = re.sub(r"[<>]", "", nom_libre or nom_defaut_y or sym_final).strip() or sym_final
        if not sym_final:
            st.sidebar.error("⚠️ Veuillez saisir un nom ou un ticker Yahoo.")
        else:
            test_p, _, _, _ = recuperer_donnees(sym_final)
            # Devise réelle du ticker FINAL (il a pu être modifié à la main dans le formulaire)
            prix_verif, dev_reelle, _, _ = inspecter_dividende_yahoo_live(sym_final)
            if test_p is None:
                st.sidebar.error(f"❌ Ticker `{sym_final}` introuvable sur Yahoo Finance. Vérifiez le suffixe (ex: `.PA` pour Paris).")
            elif prix_verif and dev_reelle not in ("EUR", "USD"):
                st.sidebar.error(f"❌ `{sym_final}` est cotée en **{dev_reelle}** : seules les valeurs en euros (€) ou en dollars ($) peuvent être ajoutées.")
            else:
                if prix_verif:
                    dev_libre = dev_reelle
                nouvel_act_l = {
                    "symbole": sym_final,
                    "prix_cible": cible_libre,
                    "secteur": sec_libre,
                    "div_eur": div_libre,
                    "payout_ratio": payout_libre,
                    "croissance_5a": info_connue_y.get("croissance_5a", "+5.0%"),
                    "mois_div": mois_libre,
                    "devise": dev_libre,
                }
                st.session_state["watchlist"][nom_final] = nouvel_act_l
                WATCHLIST_DEFAUT[nom_final] = nouvel_act_l
                if qte_libre_pf > 0:
                    st.session_state["portefeuille"][nom_final] = construire_position(nom_final, int(qte_libre_pf), float(pru_libre_pf))
                    st.session_state[f"qte_{nom_final}"] = int(qte_libre_pf)
                    st.session_state[f"pru_{nom_final}"] = float(pru_libre_pf)
                sauvegarder_dans_cloud()
                st.toast(f"✅ {nom_final} ({sym_final}) ajoutée avec succès !")
                st.rerun()

with st.sidebar.expander("🗑️ Supprimer une action du radar"):
    if WATCHLIST:
        action_a_suppr = st.selectbox("Choisir l'action à retirer :", list(WATCHLIST.keys()), key="sel_suppr_radar")
        if st.button("Supprimer définitivement", key="btn_suppr_radar"):
            if action_a_suppr in st.session_state["watchlist"]:
                del st.session_state["watchlist"][action_a_suppr]
            if action_a_suppr in st.session_state["portefeuille"]:
                del st.session_state["portefeuille"][action_a_suppr]
            st.session_state[f"qte_{action_a_suppr}"] = 0
            sauvegarder_dans_cloud()
            st.rerun()

# --- GESTION SAAS 3 NIVEAUX (GRATUIT 0€ / PREMIUM 4,90€ / PRO 8,90€) & PORTAIL STRIPE ---
st.sidebar.markdown("---")
st.sidebar.header("💎 Offres & Abonnement")

est_admin = est_compte_admin(st.session_state.get("user"))

# Synchronisation automatique Stripe (détecte les désabonnements et les changements 4,90€ <-> 8,90€)
if st.session_state.get("user") is not None and not est_admin:
    if not st.session_state.get("_stripe_sync_session_ok", False):
        niveau_avant = st.session_state.get("niveau_abonnement", "gratuit") if st.session_state.get("est_abonne_pro") else "gratuit"
        if etablir_niveau_abonnement(st.session_state["user"]) == "gratuit" and niveau_avant in ("premium", "pro"):
            st.sidebar.info("ℹ️ Votre abonnement est arrivé à échéance. Votre compte est repassé en forfait Gratuit.")

choix_simu_admin = "👑 Vue Pro Max (8,90 €)"
if est_admin:
    with st.sidebar.expander("👑 Console Administrateur SaaS", expanded=False):
        choix_simu_admin = st.radio(
            "Tester l'affichage d'un forfait :",
            ["👑 Vue Pro Max (8,90 €)", "⚡ Simuler Premium (4,90 €)", "🌱 Simuler Gratuit (0 €)"],
            index=0,
            key="rad_simu_admin_saas",
        )
        if supabase:
            try:
                res_users = supabase.table("user_data").select("user_id").execute()
                liste_u = res_users.data if res_users.data else []
                res_abos = supabase.table("abonnements").select("niveau").execute()
                nb_payants = sum(1 for a in (res_abos.data or []) if a.get("niveau") in ("premium", "pro"))
                st.caption(f"👥 **{len(liste_u)} inscrit(s)** | 💎 **{nb_payants} Abonné(s) actif(s)**")
            except Exception:
                pass
            if init_supabase_serveur() is None:
                st.warning(
                    "Secret `SUPABASE_SERVICE_KEY` absent : les abonnements vérifiés sur Stripe ne peuvent pas être "
                    "enregistrés dans la table protégée (ils restent valables le temps de la session)."
                )

if est_admin:
    if "Gratuit" in choix_simu_admin:
        niveau_acces = "gratuit"
    elif "Premium" in choix_simu_admin:
        niveau_acces = "premium"
    else:
        niveau_acces = "pro"
else:
    # Niveau fixé uniquement par etablir_niveau_abonnement() (Stripe ou table protégée), jamais par le portefeuille
    if st.session_state.get("est_abonne_pro", False) and st.session_state.get("niveau_abonnement") in ("premium", "pro"):
        niveau_acces = st.session_state["niveau_abonnement"]
    else:
        niveau_acces = "gratuit"

mode_gratuit = (niveau_acces == "gratuit")
est_premium_ou_pro = (niveau_acces in ("premium", "pro"))
est_pro_max = (niveau_acces == "pro")

quota_ia_max = 1 if mode_gratuit else (3 if niveau_acces == "premium" else 15)

def _construire_url_stripe(*cles_possibles, avec_reference=True):
    url_b = ""
    for k_s in cles_possibles:
        val_s = _lire_secret(k_s)
        if val_s:
            url_b = val_s
            break
    if not url_b:
        return "https://buy.stripe.com/"
    if st.session_state.get("user") is not None:
        em_q = urllib.parse.quote(str(st.session_state["user"].email))
        sep = "&" if "?" in url_b else "?"
        url_f = f"{url_b}{sep}prefilled_email={em_q}"
        if avec_reference:
            # Relie le paiement au compte Boursy, même si l'adresse saisie chez Stripe est différente
            url_f += f"&client_reference_id={urllib.parse.quote(str(st.session_state['user'].id))}"
        return url_f
    return url_b

url_stripe_premium = _construire_url_stripe("STRIPE_PREMIUM_URL", "STRIPE_PRENIUM_URL", "STRIPE_CHECKOUT_URL", "STRIPE_PRO_URL")
url_stripe_pro = _construire_url_stripe("STRIPE_PRO_URL", "STRIPE_CHECKOUT_URL", "STRIPE_PREMIUM_URL", "STRIPE_PRENIUM_URL")
url_portail_stripe = _construire_url_stripe("STRIPE_PORTAL_URL", "STRIPE_BILLING_URL", avec_reference=False)
def afficher_bouton_portail_stripe():
    """
    Bouton « Gérer mon abonnement » : ouvre directement le portail Stripe de l'abonné (session créée à la demande).
    Repli sur le lien de connexion du portail (secret STRIPE_PORTAL_URL) si la session ne peut pas être créée.
    """
    if st.sidebar.button("⚙️ Gérer mon abonnement / Factures", width="stretch", key="btn_portail_stripe"):
        url_session = creer_session_portail_stripe(st.session_state.get("_stripe_client_id"))
        st.session_state["_url_portail_session"] = url_session or (url_portail_stripe if portail_configure else None)
        st.session_state["_portail_session_echec"] = url_session is None
    url_a_ouvrir = st.session_state.get("_url_portail_session")
    if url_a_ouvrir:
        st.sidebar.link_button("➡️ Ouvrir mon espace de facturation Stripe", url_a_ouvrir, type="primary", width="stretch")
        if st.session_state.get("_portail_session_echec"):
            st.sidebar.caption("Accès direct indisponible : Stripe vous enverra un lien de connexion par e-mail.")
    elif st.session_state.get("_portail_session_echec"):
        st.sidebar.warning("Le portail de facturation n'est pas joignable pour le moment. Réessayez dans un instant.")


portail_configure = (url_portail_stripe and not url_portail_stripe.startswith("https://buy.stripe.com/?") and url_portail_stripe != "https://buy.stripe.com/")

if mode_gratuit:
    actions_autorisees = list(WATCHLIST.keys())[:2]
    st.sidebar.info("🌱 **Forfait Gratuit (0 €)** : 2 valeurs max & 1 audit IA/jour.")
    st.sidebar.link_button("⚡ Passer à Premium — 4,90 €/mois", url_stripe_premium, width="stretch")
    st.sidebar.link_button("👑 Passer à Pro Max — 8,90 €/mois", url_stripe_pro, type="primary", width="stretch")
elif niveau_acces == "premium":
    actions_autorisees = list(WATCHLIST.keys())
    st.sidebar.warning(f"⚡ **Abonné Premium (4,90 €/mois)** : {len(WATCHLIST)} valeurs débloquées & 3 audits IA/jour.")
    if st.session_state.get("abo_fin_periode"):
        st.sidebar.caption(f"⏳ *Résiliation programmée — accès actif jusqu'au {st.session_state['abo_fin_periode']}.*")
    st.sidebar.link_button("👑 Débloquer Pro Max (8,90 €/mois)", url_stripe_pro, type="primary", width="stretch")
    afficher_bouton_portail_stripe()
else:
    actions_autorisees = list(WATCHLIST.keys())
    st.sidebar.success(f"👑 **Abonné Pro Max (8,90 €/mois)** : Accès intégral ({len(WATCHLIST)} valeurs & 15 audits IA/jour).")
    if st.session_state.get("abo_fin_periode"):
        st.sidebar.caption(f"⏳ *Résiliation programmée — accès actif jusqu'au {st.session_state['abo_fin_periode']}.*")
    afficher_bouton_portail_stripe()
def afficher_verrou_saas(titre_module, palier_requis="👑 Offre Pro (8,90 €/mois)", description=""):
    """Affiche une bannière Argon élégante pour les fonctionnalités verrouillées."""
    couleur_v = "#f39c12" if "4,90" in palier_requis else "#9b59b6"
    afficher_html(f"""
    <div class="argon-card" style="text-align:left; border-left: 4px solid {couleur_v}; margin: 12px 0; padding: 14px 18px;">
        <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">
            <span style="font-weight:900; font-size:0.98em;">🔒 {titre_module}</span>
            <span class="b-purple" style="background:rgba(155,89,182,0.18); color:{couleur_v};">Réservé {palier_requis}</span>
        </div>
        <div style="font-size:0.86em; opacity:0.88; margin-top:6px; line-height:1.45;">
            {description} Passez au forfait <b>{palier_requis}</b> depuis le menu de gauche (<b>💎 Offres & Abonnement</b>) pour débloquer instantanément ce module.
        </div>
    </div>
    """)
# ==============================================================================
# MOTEUR ALGORITHMIQUE ÉLEVÉ & INDICATEURS TECHNIQUES AVANCÉS
# ==============================================================================


# ==============================================================================
# EN-TÊTE PRINCIPAL, MÉTÉO DES MARCHÉS & BANNIÈRE D'ACCUEIL
# ==============================================================================
_seance_ouverte = marches_ouverts()
_heure_maj = heure_maj_cours(creneau_cours())
if _seance_ouverte:
    _texte_puce_cours = f"Cours différés (jusqu'à 15 min) · mis à jour à {_heure_maj}"
    _style_point_cours = ""
else:
    _texte_puce_cours = f"Marchés fermés · derniers cours connus, relevés à {_heure_maj}"
    _style_point_cours = " style='background:#95a5a6; box-shadow:0 0 0 4px rgba(149,165,166,0.18);'"
afficher_html(f"""
<div class="bz-hero">
    <div class="bz-logo">
        <svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="#ffffff" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 17 9 11 13 15 21 7"></polyline><polyline points="15 7 21 7 21 13"></polyline></svg>
    </div>
    <div>
        <div class="bz-nom">Boursy</div>
        <div class="bz-slogan">Votre copilote PEA, actions US &amp; dividendes</div>
        <div class="bz-slogan" style="font-size:0.76em; opacity:0.62;">Information statistique et pédagogique · ne constitue pas un conseil en investissement</div>
    </div>
    <div class="bz-hero-droite">
        <span class="bz-puce"><span class="bz-point"{_style_point_cours}></span>{_texte_puce_cours}</span>
    </div>
</div>
""")

cac_pts, cac_var = recuperer_indice_meteo("^FCHI")
sp_pts, sp_var = recuperer_indice_meteo("^GSPC")
vix_pts, vix_var = recuperer_indice_meteo("^VIX")

# --- CALCUL DU SIGNAL EMA 2/12 POUR LES INDICES MÉTÉO ---
@st.cache_data(ttl=1800)
def calculer_ema_meteo_indice(symbole):
    """Tendance EMA 2/12 d'un indice sur 3 mois ; « Neutre » si Yahoo ne répond pas."""
    try:
        return tendance_ema_2_12(clotures_trois_mois(symbole))
    except Exception:
        return "⚪ Neutre", "#95a5a6"

statut_ema_cac, col_ema_cac = calculer_ema_meteo_indice("^FCHI")
statut_ema_sp, col_ema_sp = calculer_ema_meteo_indice("^GSPC")

cac_str = f"{cac_pts:,.0f} pts ({cac_var:+.2f}%)" if cac_pts else "En attente"
sp_str = f"{sp_pts:,.0f} pts ({sp_var:+.2f}%)" if sp_pts else "En attente"
vix_val = vix_pts if vix_pts else 18.0
etat_vix = "🟢 Marché Calme" if vix_val < 16 else ("🔥 Forte nervosité" if vix_val >= 24 else "🟡 Volatilité Normale")
c_cac = "#2ecc71" if cac_var >= 0 else "#e74c3c"
c_sp = "#2ecc71" if sp_var >= 0 else "#e74c3c"
c_vix = "#2ecc71" if vix_val < 16 else ("#e74c3c" if vix_val >= 24 else "#f39c12")

html_meteo = f"""
<div class="meteo-bar">
    <div class="meteo-item" style="border-left-color: {c_cac};">
        <div>
            <div style="font-size:0.75em; font-weight:800; opacity:0.7;">🇫🇷 CAC 40 (PARIS)</div>
            <div style="font-weight:900; font-size:1.05em;">{cac_str}</div>
            <div style="font-size:0.76em; margin-top:3px; font-weight:700; color:{col_ema_cac};">EMA 2/12 : {statut_ema_cac}</div>
        </div>
        <span style="color:{c_cac}; font-weight:800; font-size:1.2em;">{'▲' if cac_var >= 0 else '▼'}</span>
    </div>
    <div class="meteo-item" style="border-left-color: {c_sp};">
        <div>
            <div style="font-size:0.75em; font-weight:800; opacity:0.7;">🇺🇸 S&P 500 (NEW YORK)</div>
            <div style="font-weight:900; font-size:1.05em;">{sp_str}</div>
            <div style="font-size:0.76em; margin-top:3px; font-weight:700; color:{col_ema_sp};">EMA 2/12 : {statut_ema_sp}</div>
        </div>
        <span style="color:{c_sp}; font-weight:800; font-size:1.2em;">{'▲' if sp_var >= 0 else '▼'}</span>
    </div>
    <div class="meteo-item" style="border-left-color: {c_vix};">
        <div>
            <div style="font-size:0.75em; font-weight:800; opacity:0.7;">🌡️ INDICE VIX (NERVOSITÉ)</div>
            <div style="font-weight:900; font-size:1.05em;">{vix_val:.1f} — {etat_vix}</div>
        </div>
    </div>
    <div class="meteo-item" style="border-left-color: #9b59b6;">
        <div>
            <div style="font-size:0.75em; font-weight:800; opacity:0.7;">💱 PARITÉ EUR / USD</div>
            <div style="font-weight:900; font-size:1.05em;">1 € = {TAUX_USD_EUR:.4f} $</div>
        </div>
    </div>
</div>
"""
afficher_html(html_meteo)

# --- BADGE DE SYNCHRONISATION CLOUD EN TEMPS RÉEL ---
try:
    from zoneinfo import ZoneInfo
    heure_sync = datetime.now(ZoneInfo("Europe/Paris")).strftime("%H:%M")
except Exception:
    heure_sync = datetime.now().strftime("%H:%M")

est_connecte = st.session_state.get("user") is not None
couleur_sync = "#2ecc71" if est_connecte else "#f39c12"
texte_sync = f"☁️ Cloud synchronisé ({heure_sync})" if est_connecte else f"💾 Mode local ({heure_sync})"

st.sidebar.markdown(
    f"""
    <div style="background: rgba(46, 204, 113, 0.08); border: 1px solid {couleur_sync}55;
                border-radius: 8px; padding: 7px 12px; margin-bottom: 12px;
                display: flex; align-items: center; justify-content: space-between; font-size: 0.8em;">
        <span style="font-weight: 700; color: {couleur_sync};">● {texte_sync}</span>
        <span style="opacity: 0.7; font-size: 0.9em;">Sécurisé</span>
    </div>
    """,
    unsafe_allow_html=True
)

if st.session_state["user"] is None:
    html_landing_banner = """
    <div style="background: linear-gradient(135deg, rgba(46,204,113,0.14) 0%, rgba(52,152,219,0.14) 100%); border: 1px solid rgba(46,204,113,0.35); border-radius: 14px; padding: 18px 24px; margin-bottom: 22px; font-family: sans-serif;">
        <div style="font-size: 1.15em; font-weight: 900; margin-bottom: 8px;">🚀 Bienvenue sur Boursy : Pilotez votre PEA, vos Actions US & vos Dividendes</div>
        <div style="font-size: 0.94em; opacity: 0.92; line-height: 1.6;">
            • 🎯 <b>Radar Algorithmique (/100) :</b> RSI, Stochastique, Bandes de Bollinger, ATR, MACD & Canal de Régression 3 ans.<br>
            • 🌍 <b>Suivi Multidevises (EUR / USD), Répartition Sectorielle & Courbe Boursière :</b> Conversion automatique en Euros (€).<br>
            • 🤖 <b>Coach IA 2.0 & Calendrier 12 Mois :</b> Audits patrimoniaux, jauge d'objectifs de rente et simulateur Boule de Neige.<br>
            👉 <i>Connectez-vous ou créez votre compte gratuit dans le menu de gauche (<b>👤 Espace Membre</b>) !</i>
        </div>
    </div>
    """
    afficher_html(html_landing_banner)

# ==============================================================================
# TRAITEMENT DU MOTEUR BOURSIER SUR LA WATCHLIST (MULTI-THREADING ULTRA-RAPIDE)
# ==============================================================================
resultats_analysed = []
donnees_t1, donnees_t2, donnees_t3, donnees_t4 = [], [], [], []
alertes_detectees = []
historiques_prix = {}
droites_regression_dict = {}
prix_temps_reel = {}
variations_jour = {}

items_wl_valides = [
    (nom_w, info_w)
    for nom_w, info_w in list(st.session_state["watchlist"].items())
    if nom_w not in CLES_TECHNIQUES_PF and isinstance(info_w, dict) and info_w.get("symbole")
]

def _charger_ticker_parallele(item_tuple):
    nom_t, info_t = item_tuple
    return nom_t, info_t, recuperer_donnees(info_t["symbole"])

with ThreadPoolExecutor(max_workers=10) as executor:
    resultats_bruts_yahoo = list(executor.map(_charger_ticker_parallele, items_wl_valides))

for nom, info, (prix_actuel, closes, hauts, bas) in resultats_bruts_yahoo:
    if prix_actuel is None or not closes:
        continue

    prix_temps_reel[nom] = prix_actuel
    historiques_prix[nom] = closes
    # Variation du jour : cours actuel comparé à la clôture de la séance précédente
    if len(closes) >= 2 and closes[-2] > 0:
        variations_jour[nom] = (prix_actuel - closes[-2]) / closes[-2]
    st.session_state["prix_temps_reel"] = prix_temps_reel

    if nom not in actions_autorisees:
        continue

    devise = info.get("devise", "EUR")
    symbole_devise = "$" if devise == "USD" else "€"
    facteur_devise = (1.0 / TAUX_USD_EUR) if devise == "USD" else 1.0

    div_origine = float(info.get("div_eur", 0.0))
    div_en_eur = div_origine * facteur_devise
    prix_en_eur = prix_actuel * facteur_devise
    rendement_actuel = (div_origine / prix_actuel) if prix_actuel > 0 else 0.0

    prix_cible = float(info.get("prix_cible", 0.0))
    rsi = calculer_rsi(closes, 14)
    stoch_k = calculer_stochastique(closes, hauts, bas, 14)
    atr_pct = calculer_atr_pct(closes, hauts, bas, 14)
    borne_inf, borne_sup = calculer_bollinger(closes, 20)
    macd_val, macd_sig = calculer_macd(closes)
    statut_ema_2_12, pts_ema = analyser_signal_ema_2_12(closes)
    val_reg, ecart_reg_pct, droite_reg, std_res = calculer_regression_lineaire(closes)
    droites_regression_dict[nom] = (closes, droite_reg, std_res, symbole_devise)

    support_30j = min(bas[-30:]) if len(bas) >= 30 else min(bas)
    resistance_30j = max(hauts[-30:]) if len(hauts) >= 30 else max(hauts)
    distance_cible_pct = ((prix_actuel - prix_cible) / prix_cible) * 100 if prix_cible > 0 else 0.0

    payout_r = float(info.get("payout_ratio", 0.60))
    score, est_surevalue, decision = calculer_score_radar(
        prix_actuel, prix_cible, payout_r, rendement_actuel, ecart_reg_pct, pts_ema, rsi, stoch_k,
        borne_inf, borne_sup, macd_val, macd_sig, statut_ema_2_12,
    )

    if (prix_cible > 0 and prix_actuel <= prix_cible) or "SIGNAL FORT" in decision:
        motif_al = "Sous le Prix Cible 🎯" if (prix_cible > 0 and prix_actuel <= prix_cible) else "Signal technique fort 🟢"
        alertes_detectees.append({
            "Actif": f"{nom} ({devise})",
            "Prix": f"{prix_actuel:.2f} {symbole_devise}",
            "Cible": f"{prix_cible:.2f} {symbole_devise}",
            "Score": score,
            "Motif": motif_al,
        })

    dist_str = f"🟢 {distance_cible_pct:+.1f}%" if distance_cible_pct <= 0 else (f"🟡 {distance_cible_pct:+.1f}%" if distance_cible_pct <= 5 else f"⚪ {distance_cible_pct:+.1f}%")

    donnees_t1.append({
        "NomBrut": nom,
        "Actif": f"{nom} ({devise})",
        "Prix": f"{prix_actuel:.2f} {symbole_devise}",
        "PrixEUR": f"{prix_en_eur:.2f} €",
        "Prix Cible": f"{prix_cible:.2f} {symbole_devise}" if prix_cible > 0 else "N/A",
        "Écart Cible (%)": dist_str if prix_cible > 0 else "N/A",
        "RSI": round(rsi, 1),
        "Stoch": round(stoch_k, 0),
        "MACD": "🟢 Haussier" if macd_val > macd_sig else "🔴 Baissier",
        "EMA 2/12": statut_ema_2_12,
        "Score": score,
        "Décision": decision,
    })

    if ecart_reg_pct <= -10.0:
        statut_val_str = "🟢 FORTE DÉCOTE"
        ordre_statut_val = 0
    elif ecart_reg_pct < 0.0:
        statut_val_str = "🟡 SOUS-ÉVALUÉE"
        ordre_statut_val = 1
    else:
        statut_val_str = "⚪ PRIX NORMAL / CHER"
        ordre_statut_val = 2

    donnees_t2.append({
        "NomBrut": nom,
        "Actif": f"{nom} ({devise})",
        "Prix": f"{prix_actuel:.2f} {symbole_devise}",
        "Tendance 3A": f"{val_reg:.2f} {symbole_devise}",
        "Écart %": f"{ecart_reg_pct:+.1f}%",
        "EcartNum": float(ecart_reg_pct),
        "OrdreStatut": ordre_statut_val,
        "Statut Value": statut_val_str,
    })

    donnees_t3.append({
        "Actif": f"{nom} ({devise})",
        "Div/Act": f"{div_origine:.2f} {symbole_devise} ({div_en_eur:.2f} €)",
        "Rendement": f"{rendement_actuel*100:.2f}%",
        "Payout": f"{payout_r*100:.0f}%",
        "Croissance 5a": info.get("croissance_5a", "N/A"),
        "Sûreté": "🛡️ ULTRA SÛR" if payout_r <= 0.55 else ("✅ SOLIDE" if payout_r <= 0.72 else "🟡 À SURVEILLER"),
    })

    statut_boll = "🟢 Bas de Bollinger" if prix_actuel <= borne_inf * 1.02 else ("🔴 Haut de Bollinger" if prix_actuel >= borne_sup * 0.98 else "⚪ Milieu de Canal")
    donnees_t4.append({
        "Actif": f"{nom} ({devise})",
        "Prix": f"{prix_actuel:.2f} {symbole_devise}",
        "Support 30J": f"{support_30j:.2f} {symbole_devise}",
        "Résistance 30J": f"{resistance_30j:.2f} {symbole_devise}",
        "Bollinger (20J)": f"[{borne_inf:.1f} - {borne_sup:.1f}] ({statut_boll})",
        "Stochastique": f"{stoch_k:.0f}% ({'🟢 Survente' if stoch_k <= 20 else ('🔴 Surachat' if stoch_k >= 80 else 'Neutre')})",
        "Volatilité ATR": f"{atr_pct:.2f}% / jour",
    })

    if score >= 45 and not est_surevalue and "🔴" not in statut_ema_2_12:
        resultats_analysed.append({
            "nom": nom,
            "devise": devise,
            "score": score,
            "rendement": rendement_actuel,
            "prix_origine": prix_actuel,
            "prix_eur": prix_en_eur,
            "div_eur": div_en_eur,
        })

donnees_t2.sort(key=lambda x: (x["OrdreStatut"], x["EcartNum"]))

candidats_tries = sorted(resultats_analysed, key=lambda x: x["score"], reverse=True)

# ==============================================================================
# DCA GUIDÉ PAR L'ALLOCATION CIBLE : chaque mois, l'enveloppe va aux lignes les plus en retard sur la cible choisie.
# Remplace l'ancienne répartition sur les 2 meilleurs scores du radar, dont le bilan des signaux n'a pas montré
# d'avantage. Calcul dans allocation_dca.py.
# ==============================================================================
# Lignes, poids cibles et cours : même préparation que le résumé mensuel envoyé par e-mail (allocation_dca.py)
portefeuille_dca = st.session_state["portefeuille"] if isinstance(st.session_state.get("portefeuille"), dict) else {}
lignes_dca, allocation_personnalisee, defaut_sur_lignes_detenues = preparer_lignes_dca(
    portefeuille_dca,
    [n for n in actions_autorisees if n not in CLES_TECHNIQUES_PF],
    WATCHLIST_DEFAUT,
    prix_temps_reel,
    TAUX_USD_EUR,
    decisions={d["NomBrut"]: d["Décision"] for d in donnees_t1},
    seulement_radar=mode_gratuit,
)

plan_dca = calculer_achat_du_mois(lignes_dca, BUDGET_MENSUEL)
montant_investi_dca = plan_dca["investi"]
budget_courant = plan_dca["reste"]
achats_dca = [l for l in plan_dca["lignes"] if l["qte"] > 0]
montant_tot_div_dca = sum(l["qte"] * l["div_eur"] for l in achats_dca)
libelle_allocation_dca = "Selon votre allocation cible" if allocation_personnalisee else "Parts égales (allocation par défaut)"
detail_defaut_dca = ("parts égales entre les lignes que vous détenez" if defaut_sur_lignes_detenues
                     else "parts égales entre les valeurs de votre radar (vous ne détenez encore aucune ligne)")

# ==============================================================================
# NAVIGATION PAR ONGLETS
# ==============================================================================
onglet_radar, onglet_portefeuille, onglet_dividendes, onglet_ia, onglet_ventes = st.tabs([
    "🔍 1. Radar, DCA & Alertes",
    "💼 2. Portefeuille & Trajectoire Boursière",
    "📅 3. Calendrier 12 Mois & Boule de Neige",
    "🤖 4. Coach & Audit IA 2.0 (Gemini)",
    "💰 5. Arbitrages & Plus-Values Actées",
])


# ------------------------------------------------------------------------------
# ONGLET 1 : RADAR ALGORITHMIQUE, DCA GUIDÉ PAR L'ALLOCATION CIBLE & ALERTES EMAIL
# ------------------------------------------------------------------------------
with onglet_radar:
    onglets.radar.afficher(
        ADMIN_EMAIL=ADMIN_EMAIL,
        BUDGET_MENSUEL=BUDGET_MENSUEL,
        CLES_TECHNIQUES_PF=CLES_TECHNIQUES_PF,
        TAUX_USD_EUR=TAUX_USD_EUR,
        WATCHLIST=WATCHLIST,
        WATCHLIST_DEFAUT=WATCHLIST_DEFAUT,
        actions_autorisees=actions_autorisees,
        afficher_verrou_saas=afficher_verrou_saas,
        alertes_detectees=alertes_detectees,
        allocation_personnalisee=allocation_personnalisee,
        analyse_solidite_dividendes=analyse_solidite_dividendes,
        bilan_signaux_symbole=bilan_signaux_symbole,
        budget_courant=budget_courant,
        candidats_tries=candidats_tries,
        detail_defaut_dca=detail_defaut_dca,
        donnees_t1=donnees_t1,
        donnees_t2=donnees_t2,
        donnees_t3=donnees_t3,
        donnees_t4=donnees_t4,
        droites_regression_dict=droites_regression_dict,
        envoyer_apercu_resume_mensuel=envoyer_apercu_resume_mensuel,
        envoyer_email_alerte=envoyer_email_alerte,
        est_premium_ou_pro=est_premium_ou_pro,
        est_pro_max=est_pro_max,
        historique_long=historique_long,
        libelle_allocation_dca=libelle_allocation_dca,
        lire_signaux_mensuels=lire_signaux_mensuels,
        mode_gratuit=mode_gratuit,
        montant_investi_dca=montant_investi_dca,
        montant_tot_div_dca=montant_tot_div_dca,
        plan_dca=plan_dca,
        prix_temps_reel=prix_temps_reel,
        sauvegarder_dans_cloud=sauvegarder_dans_cloud,
    )
# ------------------------------------------------------------------------------
# ONGLET 2 : PORTEFEUILLE, RÉPARTITION SECTORIELLE & TRAJECTOIRE BOURSIÈRE
# ------------------------------------------------------------------------------
with onglet_portefeuille:
    resultat_portefeuille = onglets.portefeuille.afficher(
        BUDGET_MENSUEL=BUDGET_MENSUEL,
        CATALOGUE_ACTIONS=CATALOGUE_ACTIONS,
        CLES_TECHNIQUES_PF=CLES_TECHNIQUES_PF,
        TAUX_USD_EUR=TAUX_USD_EUR,
        WATCHLIST_DEFAUT=WATCHLIST_DEFAUT,
        _lire_secret=_lire_secret,
        afficher_verrou_saas=afficher_verrou_saas,
        construire_position=construire_position,
        est_premium_ou_pro=est_premium_ou_pro,
        est_pro_max=est_pro_max,
        facteur_cout_usd=facteur_cout_usd,
        historique_long=historique_long,
        historiques_prix=historiques_prix,
        mode_gratuit=mode_gratuit,
        prix_temps_reel=prix_temps_reel,
        recuperer_donnees=recuperer_donnees,
        sauvegarder_dans_cloud=sauvegarder_dans_cloud,
        supabase=supabase,
        variations_jour=variations_jour,
    )
actions_actives_pf = resultat_portefeuille["actions_actives_pf"]
cout_total_achat = resultat_portefeuille["cout_total_achat"]
dividendes_bruts_totaux_eur = resultat_portefeuille["dividendes_bruts_totaux_eur"]
dividendes_nets_totaux_eur = resultat_portefeuille["dividendes_nets_totaux_eur"]
exposition_eur = resultat_portefeuille["exposition_eur"]
exposition_usd = resultat_portefeuille["exposition_usd"]
lignes_triees = resultat_portefeuille["lignes_triees"]
noter_dans_carnet = resultat_portefeuille["noter_dans_carnet"]
plus_value_globale = resultat_portefeuille["plus_value_globale"]
plus_value_pct = resultat_portefeuille["plus_value_pct"]
portefeuille_utilisateur = resultat_portefeuille["portefeuille_utilisateur"]
repartition_secteurs = resultat_portefeuille["repartition_secteurs"]
valeur_totale_portefeuille = resultat_portefeuille["valeur_totale_portefeuille"]
versements_nets_pea = resultat_portefeuille["versements_nets_pea"]


# ------------------------------------------------------------------------------
# ONGLET 3 : JAUGE D'OBJECTIF DE RENTE, CALENDRIER 12 MOIS & BOULE DE NEIGE
# ------------------------------------------------------------------------------
with onglet_dividendes:
    onglets.calendrier.afficher(
        BUDGET_MENSUEL=BUDGET_MENSUEL,
        CLES_TECHNIQUES_PF=CLES_TECHNIQUES_PF,
        TAUX_USD_EUR=TAUX_USD_EUR,
        WATCHLIST_DEFAUT=WATCHLIST_DEFAUT,
        actions_actives_pf=actions_actives_pf,
        afficher_verrou_saas=afficher_verrou_saas,
        cout_total_achat=cout_total_achat,
        est_pro_max=est_pro_max,
        lignes_triees=lignes_triees,
        mode_gratuit=mode_gratuit,
        portefeuille_utilisateur=portefeuille_utilisateur,
        sauvegarder_dans_cloud=sauvegarder_dans_cloud,
        valeur_totale_portefeuille=valeur_totale_portefeuille,
    )
# ------------------------------------------------------------------------------
# ONGLET 4 : COACH & AUDIT IA 2.0 (AVEC PHRASE FLASH + AUTO-DISCOVERY GEMINI)
# ------------------------------------------------------------------------------
with onglet_ia:
    onglets.coach_ia.afficher(
        BUDGET_MENSUEL=BUDGET_MENSUEL,
        CLES_TECHNIQUES_PF=CLES_TECHNIQUES_PF,
        TAUX_USD_EUR=TAUX_USD_EUR,
        WATCHLIST_DEFAUT=WATCHLIST_DEFAUT,
        _lire_secret=_lire_secret,
        achats_dca=achats_dca,
        afficher_verrou_saas=afficher_verrou_saas,
        allocation_personnalisee=allocation_personnalisee,
        budget_courant=budget_courant,
        cac_str=cac_str,
        candidats_tries=candidats_tries,
        cout_total_achat=cout_total_achat,
        dividendes_bruts_totaux_eur=dividendes_bruts_totaux_eur,
        dividendes_nets_totaux_eur=dividendes_nets_totaux_eur,
        donnees_t1=donnees_t1,
        donnees_t2=donnees_t2,
        donnees_t3=donnees_t3,
        donnees_t4=donnees_t4,
        est_pro_max=est_pro_max,
        etat_vix=etat_vix,
        exposition_eur=exposition_eur,
        exposition_usd=exposition_usd,
        libelle_allocation_dca=libelle_allocation_dca,
        lignes_triees=lignes_triees,
        mode_gratuit=mode_gratuit,
        montant_investi_dca=montant_investi_dca,
        montant_tot_div_dca=montant_tot_div_dca,
        niveau_acces=niveau_acces,
        plus_value_pct=plus_value_pct,
        portefeuille_utilisateur=portefeuille_utilisateur,
        prix_temps_reel=prix_temps_reel,
        quota_ia_max=quota_ia_max,
        repartition_secteurs=repartition_secteurs,
        sauvegarder_dans_cloud=sauvegarder_dans_cloud,
        sp_str=sp_str,
        valeur_totale_portefeuille=valeur_totale_portefeuille,
        vix_val=vix_val,
    )


# ------------------------------------------------------------------------------
# ONGLET 5 : ARBITRAGES, VENTES & CALENDRIER 12 MOIS ARGON DES PLUS-VALUES ACTÉES (EXCLUSIF PRO 8,90 €)
# ------------------------------------------------------------------------------
with onglet_ventes:
    onglets.ventes.afficher(
        CLES_TECHNIQUES_PF=CLES_TECHNIQUES_PF,
        TAUX_USD_EUR=TAUX_USD_EUR,
        WATCHLIST_DEFAUT=WATCHLIST_DEFAUT,
        afficher_verrou_saas=afficher_verrou_saas,
        construire_position=construire_position,
        est_pro_max=est_pro_max,
        facteur_cout_usd=facteur_cout_usd,
        noter_dans_carnet=noter_dans_carnet,
        plus_value_globale=plus_value_globale,
        portefeuille_utilisateur=portefeuille_utilisateur,
        sauvegarder_dans_cloud=sauvegarder_dans_cloud,
        supabase=supabase,
        valeur_totale_portefeuille=valeur_totale_portefeuille,
    )
# ==============================================================================
# SUPER-PACK PRO V2 : PEA/CTO, YIELD ON COST, DUEL ETF, BOOST COUPON & STATION 360°
# ==============================================================================
try:
    onglets.super_pack.afficher(
        CLES_TECHNIQUES_PF=CLES_TECHNIQUES_PF,
        TAUX_USD_EUR=TAUX_USD_EUR,
        WATCHLIST_DEFAUT=WATCHLIST_DEFAUT,
        actions_autorisees=actions_autorisees,
        afficher_verrou_saas=afficher_verrou_saas,
        donnees_t1=donnees_t1,
        est_premium_ou_pro=est_premium_ou_pro,
        est_pro_max=est_pro_max,
        facteur_cout_usd=facteur_cout_usd,
        historiques_prix=historiques_prix,
        mode_gratuit=mode_gratuit,
        onglet_dividendes=onglet_dividendes,
        onglet_portefeuille=onglet_portefeuille,
        onglet_radar=onglet_radar,
        recuperer_donnees=recuperer_donnees,
        versements_nets_pea=versements_nets_pea,
    )
except Exception as e_pack:
    st.warning(f"Initialisation du Super-Pack Pro V2 ({e_pack})")


# ==============================================================================
# PIED DE PAGE : MENTIONS LÉGALES, CGV, DROIT DE RÉTRACTATION & CONFORMITÉ AMF (NON-CIF) — textes dans pages_legales.py
# ==============================================================================
# Identité de l'éditeur (obligatoire, loi LCEN) : à renseigner dans les secrets Streamlit
afficher_pages_legales(_lire_secret("EDITEUR_NOM"), _lire_secret("EDITEUR_SIRET"), _lire_secret("EDITEUR_ADRESSE"), CONTACT_EMAIL)
