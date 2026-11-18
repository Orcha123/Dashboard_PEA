import urllib.request
import urllib.error
import urllib.parse
import io
import json
import math
import re
import html as html_lib
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import pandas as pd
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
import onglets.calendrier
import onglets.ventes
import onglets.radar
import onglets.coach_ia
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
importlib.reload(onglets.calendrier)
importlib.reload(onglets.ventes)
importlib.reload(onglets.radar)
importlib.reload(onglets.coach_ia)
from catalogue_valeurs import ENRICHISSEMENT_CATALOGUE, NOMS_RENOMMES, symbole_a_jour  # catalogue partagé avec la tâche planifiée
from allocation_dca import calculer_achat_du_mois, preparer_lignes_dca  # DCA guidé par l'allocation cible
from paiements_stripe import creer_session_portail, ids_prix, verifier_abonnement  # abonnements Stripe (testés)
from comptes import decider_niveau  # comptes et abonnement protégé (testés)
from courriels import ADRESSE_APPLICATION, composer_email_alertes_radar, envoyer_smtp  # envoi des e-mails
from habillage import afficher_html, appliquer_habillage, markdown_fr, nombres_fr  # styles et format français
from pages_legales import afficher_pages_legales  # AMF, CGV, rétractation, mentions légales, confidentialité
from donnees_marche import (  # Yahoo Finance, heures de marché, calculs sur les historiques (testés)
    RAFRAICHISSEMENT_SEANCE_SECONDES,
    clotures_trois_mois,
    cours_a_la_date,
    cours_et_historique,
    creneau_cours,
    heure_paris,
    historique_dix_ans,
    inspecter_dividende,
    marches_ouverts,
    niveau_et_variation,
    rechercher_yahoo,
    taux_eur_usd,
    taux_rendement_interne,
    tendance_ema_2_12,
)
from carnet_decisions import (  # carnet de décisions : pourquoi j'achète, pourquoi je vends
    HORIZON_RELECTURE_MOIS,
    HORIZONS_MOIS,
    LONGUEUR_NOTE_MAX,
    NOM_REFERENCE,
    RAISONS,
    SYMBOLE_REFERENCE,
    TYPES_DECISION,
    ajouter_decision,
    ajouter_mois,
    bilan_par_raison,
    decisions_a_relire,
    enregistrer_lecon,
    evaluer_decision,
    lire_carnet,
    nouvelle_decision,
    phrase_resultat,
    supprimer_decision,
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
    st.subheader("💼 Gestionnaire de Portefeuille Multidevises & Fiscalité")

    # Intègre toutes les actions du catalogue pour pouvoir les sélectionner librement
    for lib_cat, (sym_c, dev_c, sec_c) in CATALOGUE_ACTIONS.items():
        nom_c = lib_cat.rsplit(" (", 1)[0]
        if nom_c not in WATCHLIST_DEFAUT:
            WATCHLIST_DEFAUT[nom_c] = {
                "symbole": sym_c,
                "prix_cible": 100.0,
                "secteur": sec_c,
                "div_eur": 2.0,
                "payout_ratio": 0.50,
                "croissance_5a": "+5.0%",
                "mois_div": ["Mar", "Juin", "Sep", "Déc"] if dev_c == "USD" else ["Mai"],
                "devise": dev_c,
            }

    with st.expander("✏️ Saisir ou modifier mes actions détenues (Quantité & PRU)", expanded=False):
        st.markdown("#### 💶 Poche Liquidités (Espèces disponibles)")
        esp_dict_actuel = st.session_state["portefeuille"].get("Espèces", {})
        pru_esp_defaut = float(esp_dict_actuel.get("pru", 0.0)) if isinstance(esp_dict_actuel, dict) else 0.0
        montant_especes = st.number_input("Montant Espèces (€)", min_value=0.0, value=float(st.session_state.get("pru_Espèces", pru_esp_defaut)), step=50.0, key="pru_Espèces")

        nouveau_portefeuille_temp = {}
        for cle_t in ("_historique_ventes", "_quota_ia", "_niveau_abo", "_div_encaisses_cumul", "_stripe_customer_id", "_alertes_auto", "_alertes_envoyees", "_journal_achats", "_allocation_cible", "_resume_mensuel", "_jour_dca", "_resume_envoye", "_carnet_decisions"):
            if cle_t in st.session_state["portefeuille"]:
                nouveau_portefeuille_temp[cle_t] = st.session_state["portefeuille"][cle_t]
        if st.session_state.get("historique_ventes"):
            nouveau_portefeuille_temp["_historique_ventes"] = list(st.session_state["historique_ventes"])
        if montant_especes > 0:
            nouveau_portefeuille_temp["Espèces"] = {"qte": 1, "pru": montant_especes}
            st.session_state["qte_Espèces"] = 1

        st.markdown("---")
        st.markdown("#### 🎯 Choisir les actions à afficher dans mon portefeuille")

        actions_deja_detenues = [k for k in st.session_state["portefeuille"].keys() if k not in CLES_TECHNIQUES_PF]
        for k_det in actions_deja_detenues:
            if k_det not in WATCHLIST_DEFAUT:
                WATCHLIST_DEFAUT[k_det] = {
                    "symbole": k_det.upper(), "prix_cible": float(st.session_state["portefeuille"][k_det].get("pru", 50.0)),
                    "secteur": "Action Portefeuille", "div_eur": 0.0, "payout_ratio": 0.50,
                    "croissance_5a": "+5.0%", "mois_div": ["Mai"], "devise": "EUR",
                }
        actions_radar = [k for k in st.session_state["watchlist"].keys() if k not in CLES_TECHNIQUES_PF]
        selection_par_defaut = sorted(list(set(actions_deja_detenues + actions_radar)))

        actions_choisies_pf = st.multiselect(
            "Sélectionnez ou recherchez vos actions (ex: Engie, TotalEnergies, Air Liquide, Rubis, AXA...) :",
            options=sorted([k for k in WATCHLIST_DEFAUT.keys() if k not in CLES_TECHNIQUES_PF]),
            default=[a for a in selection_par_defaut if a in WATCHLIST_DEFAUT],
        )

        st.markdown("#### 📈 Mes Positions Actions (Saisissez le PRU dans la devise de l'action : € ou $)")
        cols_saisie = st.columns(3)

        for idx, nom_act in enumerate(actions_choisies_pf):
            info_act = WATCHLIST_DEFAUT[nom_act]
            col_active = cols_saisie[idx % 3]
            devise_a = info_act.get("devise", "EUR")
            with col_active:
                st.markdown(f"**{nom_act}** *({devise_a})*")
                pos_existante = st.session_state["portefeuille"].get(nom_act, {})
                qte_defaut = int(pos_existante.get("qte", 0)) if isinstance(pos_existante, dict) else 0
                pru_defaut = float(pos_existante.get("pru", float(info_act["prix_cible"]))) if isinstance(pos_existante, dict) else float(info_act["prix_cible"])

                qte_saisie = st.number_input(f"Quantité ({nom_act})", min_value=0, value=int(st.session_state.get(f"qte_{nom_act}", qte_defaut)), key=f"qte_{nom_act}")
                pru_saisi = st.number_input(f"PRU Unitaire ({devise_a})", min_value=0.0, value=float(st.session_state.get(f"pru_{nom_act}", pru_defaut)), step=0.5, key=f"pru_{nom_act}")

                taux_achat_saisi = 0.0
                if devise_a == "USD":
                    try:
                        taux_achat_defaut = float(pos_existante.get("taux_achat") or 0.0) if isinstance(pos_existante, dict) else 0.0
                    except Exception:
                        taux_achat_defaut = 0.0
                    taux_achat_saisi = st.number_input(
                        "Taux €/$ à l'achat (1 € = ? $)",
                        min_value=0.0,
                        max_value=5.0,
                        value=min(5.0, max(0.0, float(st.session_state.get(f"txa_{nom_act}", taux_achat_defaut)))),
                        step=0.01,
                        format="%.4f",
                        key=f"txa_{nom_act}",
                        help="Taux de change moyen de vos achats (ex. 1,0850). Il sert à convertir votre PRU en euros, pour que "
                             "la plus-value tienne compte de l'effet de change. Laissez 0 pour utiliser le taux du jour.",
                    )

                if qte_saisie > 0:
                    nouveau_portefeuille_temp[nom_act] = {"qte": qte_saisie, "pru": pru_saisi}
                    if taux_achat_saisi > 0:
                        nouveau_portefeuille_temp[nom_act]["taux_achat"] = round(float(taux_achat_saisi), 4)
                    if nom_act not in st.session_state["watchlist"]:
                        st.session_state["watchlist"][nom_act] = info_act.copy()
                st.markdown("---")

        st.session_state["portefeuille"] = nouveau_portefeuille_temp
        if st.button("💾 Enregistrer mon portefeuille & créer un Snapshot Cloud", type="primary", width="stretch"):
            sauvegarder_dans_cloud()
            st.rerun()

    # ======================================================================
    # JOURNAL DES ACHATS : CHAQUE ACHAT MET À JOUR LA QUANTITÉ ET LE PRU (FRAIS INCLUS)
    # ======================================================================
    def _nombre_lu(valeur):
        """Lit un nombre écrit à la française ou à l'anglaise ('1 234,56 €', '1,234.56') ; None si illisible."""
        if valeur is None:
            return None
        if isinstance(valeur, (int, float)):
            return None if (isinstance(valeur, float) and math.isnan(valeur)) else float(valeur)
        texte = str(valeur)
        for parasite in (" ", " ", " ", "€", "$", "EUR", "USD"):
            texte = texte.replace(parasite, "")
        texte = texte.strip()
        if not texte:
            return None
        if "," in texte and "." in texte:
            # Le séparateur le plus à droite est celui des décimales
            texte = texte.replace(".", "").replace(",", ".") if texte.rfind(",") > texte.rfind(".") else texte.replace(",", "")
        else:
            texte = texte.replace(",", ".")
        try:
            return float(texte)
        except ValueError:
            return None

    def _calculer_position_apres_achat(position, est_usd, qte, prix, frais_eur, taux_operation):
        """Nouvelle position après un achat : PRU moyen pondéré frais inclus, et taux €/$ moyen pour les lignes en dollars."""
        position = position if isinstance(position, dict) else {}
        qte_avant = float(position.get("qte", 0) or 0)
        pru_avant = float(position.get("pru", 0) or 0)
        frais_devise = frais_eur * taux_operation if est_usd else frais_eur
        cout_devise = qte_avant * pru_avant + qte * prix + frais_devise
        qte_apres = qte_avant + qte
        nouvelle = {"qte": int(round(qte_apres)), "pru": round(cout_devise / qte_apres, 4) if qte_apres > 0 else 0.0}
        if est_usd:
            taux_avant = float(position.get("taux_achat") or 0) or float(TAUX_USD_EUR)
            cout_eur = (qte_avant * pru_avant) / taux_avant + (qte * prix) / taux_operation + frais_eur
            nouvelle["taux_achat"] = round(cout_devise / cout_eur, 4) if cout_eur > 0 else round(taux_operation, 4)
        return nouvelle

    def _synchroniser_saisie_position(nom_action, position):
        """Aligne les champs « Quantité / PRU / Taux » du volet de saisie sur la position (ou les vide si elle disparaît)."""
        st.session_state[f"qte_{nom_action}"] = int(position.get("qte", 0)) if position else 0
        if position:
            st.session_state[f"pru_{nom_action}"] = float(position.get("pru", 0.0))
        st.session_state[f"txa_{nom_action}"] = float((position or {}).get("taux_achat") or 0.0)

    def noter_dans_carnet(type_decision, nom_action, jour, raison, note, source, qte=None, prix=None):
        """Ajoute une décision au carnet si l'utilisateur a indiqué une raison ou une note (sinon ne fait rien)."""
        note = str(note or "").strip()
        if (not raison or raison == "—") and not note:
            return None
        info_carnet = WATCHLIST_DEFAUT.get(nom_action, {})
        return ajouter_decision(st.session_state["portefeuille"], nouvelle_decision(
            jour, nom_action, symbole_a_jour(info_carnet.get("symbole", "")), type_decision,
            raison if raison and raison != "—" else "Autre", note, info_carnet.get("devise", "EUR"), source, qte, prix,
        ))

    def appliquer_achat(nom_action, date_achat, qte, prix, frais_eur, taux_operation=0.0, source="saisie"):
        """Ajoute un achat au journal et met à jour la ligne du portefeuille. Renvoie la nouvelle position."""
        est_usd = WATCHLIST_DEFAUT.get(nom_action, {}).get("devise") == "USD"
        taux_operation = float(taux_operation) if (est_usd and taux_operation and float(taux_operation) > 0) else (float(TAUX_USD_EUR) if est_usd else 1.0)
        pf = st.session_state["portefeuille"]
        position_avant = pf.get(nom_action) if isinstance(pf.get(nom_action), dict) else {}
        nouvelle = _calculer_position_apres_achat(position_avant, est_usd, qte, prix, frais_eur, taux_operation)
        pf[nom_action] = nouvelle
        journal = pf.get("_journal_achats") if isinstance(pf.get("_journal_achats"), list) else []
        journal.append({
            "id": f"{time.time():.6f}",
            "date": str(date_achat)[:10],
            "action": nom_action,
            "qte": int(qte),
            "prix": float(prix),
            "frais_eur": float(frais_eur),
            "devise": "USD" if est_usd else "EUR",
            "taux_change": round(taux_operation, 4) if est_usd else None,
            "source": source,
            "avant": {k: position_avant.get(k) for k in ("qte", "pru", "taux_achat") if position_avant.get(k) is not None},
            "apres": dict(nouvelle),
        })
        pf["_journal_achats"] = journal
        _synchroniser_saisie_position(nom_action, nouvelle)
        if nom_action not in st.session_state["watchlist"] and nom_action in WATCHLIST_DEFAUT:
            st.session_state["watchlist"][nom_action] = WATCHLIST_DEFAUT[nom_action].copy()
        return nouvelle

    def _achat_annulable(entree):
        """Un achat n'est annulable que si la ligne n'a pas changé depuis (ni achat, ni vente, ni modification manuelle)."""
        position = st.session_state["portefeuille"].get(entree.get("action"))
        apres = entree.get("apres") or {}
        return (
            isinstance(position, dict)
            and int(position.get("qte", 0)) == int(apres.get("qte", -1))
            and abs(float(position.get("pru", 0)) - float(apres.get("pru", -1))) < 0.005
        )

    def _enregistrer_achat_saisi():
        nom_action = st.session_state.get("ja_action")
        qte = int(st.session_state.get("ja_qte", 0) or 0)
        prix = float(st.session_state.get(f"ja_prix_{nom_action}", 0.0) or 0.0)
        frais = float(st.session_state.get("ja_frais", 0.0) or 0.0)
        if not nom_action or qte <= 0 or prix <= 0:
            st.session_state["_notif_journal"] = ("erreur", "Indiquez une action, une quantité et un prix supérieurs à zéro.")
            return
        position = appliquer_achat(nom_action, st.session_state.get("ja_date", datetime.now().date()), qte, prix, frais,
                                   st.session_state.get(f"ja_taux_{nom_action}", 0.0))
        decision_notee = noter_dans_carnet("achat", nom_action, st.session_state.get("ja_date", datetime.now().date()),
                                           st.session_state.get("ja_raison"), st.session_state.get("ja_note"), "journal", qte, prix)
        st.session_state["ja_note"] = ""
        st.session_state["ja_raison"] = "—"
        sauvegarder_dans_cloud()
        st.session_state["_notif_journal"] = ("ok", f"✅ Achat enregistré : +{qte} {nom_action}. Nouvelle ligne : {position['qte']} titre(s), PRU {position['pru']:.2f}."
                                              + (" Raison notée dans le carnet de décisions." if decision_notee else ""))

    def _annuler_achat(id_achat):
        pf = st.session_state["portefeuille"]
        journal = list(pf.get("_journal_achats") or [])
        entree = next((e for e in journal if e.get("id") == id_achat), None)
        if entree is None or not _achat_annulable(entree):
            st.session_state["_notif_journal"] = ("erreur", "Cet achat ne peut plus être annulé : la ligne a changé depuis.")
            return
        nom_action = entree["action"]
        avant = entree.get("avant") or {}
        if int(avant.get("qte", 0) or 0) > 0:
            pf[nom_action] = {k: avant[k] for k in ("qte", "pru", "taux_achat") if avant.get(k) is not None}
            _synchroniser_saisie_position(nom_action, pf[nom_action])
        else:
            pf.pop(nom_action, None)
            _synchroniser_saisie_position(nom_action, None)
        pf["_journal_achats"] = [e for e in journal if e.get("id") != id_achat]
        sauvegarder_dans_cloud()
        st.session_state["_notif_journal"] = ("ok", f"🔄 Achat annulé : la ligne {nom_action} est revenue à son état précédent.")

    def _lire_date(valeur):
        texte_date = str(valeur or "").strip()
        if re.match(r"^\d{4}-\d{2}-\d{2}", texte_date):
            return pd.to_datetime(texte_date[:10], format="%Y-%m-%d", errors="coerce")
        return pd.to_datetime(texte_date, dayfirst=True, errors="coerce")

    def _analyser_operations(operations, taux_dollar):
        """
        Contrôle des opérations lues dans un fichier CSV ou par l'IA. Chaque opération est un dict
        {date, libelle, qte, prix, frais, sens}. Renvoie (achats importables, aperçu ligne par ligne).
        """
        journal_actuel = st.session_state["portefeuille"].get("_journal_achats")
        journal_actuel = journal_actuel if isinstance(journal_actuel, list) else []
        signatures = {f"{e.get('date')}|{e.get('action')}|{int(e.get('qte', 0))}|{float(e.get('prix', 0)):.4f}" for e in journal_actuel}
        lignes_valides, apercu = [], []
        for operation in operations:
            libelle = str(operation.get("libelle", "") or "")
            date_lue = _lire_date(operation.get("date"))
            qte_lue = _nombre_lu(operation.get("qte"))
            prix_lu = _nombre_lu(operation.get("prix"))
            frais_lus = _nombre_lu(operation.get("frais")) or 0.0
            sens_lu = _normaliser(operation.get("sens", "") or "")
            action_lue = _reconnaitre_action(libelle)
            if any(m in sens_lu for m in ("vente", "sell", "cession")):
                statut = "Ignorée : vente (à saisir dans l'onglet Arbitrages)"
            elif pd.isna(date_lue) or not qte_lue or not prix_lu or prix_lu <= 0:
                statut = "Ignorée : date, quantité ou prix illisible"
            elif action_lue is None:
                statut = "Ignorée : action non reconnue (ajoutez-la d'abord à votre radar)"
            elif date_lue.date() > datetime.now().date():
                statut = "Ignorée : date dans le futur"
            else:
                ligne = {
                    "date": date_lue.date().isoformat(), "action": action_lue, "qte": int(round(abs(qte_lue))),
                    "prix": float(prix_lu), "frais": abs(float(frais_lus)), "taux": float(taux_dollar),
                }
                signature = f"{ligne['date']}|{ligne['action']}|{ligne['qte']}|{ligne['prix']:.4f}"
                if ligne["qte"] <= 0:
                    statut = "Ignorée : quantité nulle"
                elif signature in signatures:
                    statut = "Ignorée : déjà dans le journal"
                else:
                    signatures.add(signature)
                    lignes_valides.append(ligne)
                    statut = "✅ À importer"
            apercu.append({
                "Date": date_lue.strftime("%d/%m/%Y") if not pd.isna(date_lue) else "?",
                "Valeur lue": libelle,
                "Action reconnue": action_lue or "—",
                "Quantité": qte_lue,
                "Prix": prix_lu,
                "Statut": statut,
            })
        return lignes_valides, apercu

    def _extraire_json_gemini(parties):
        """Envoie un texte ou une image à Gemini et renvoie (liste JSON extraite, message d'erreur éventuel)."""
        cle_gemini_journal = next((v for v in (_lire_secret(n) for n in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GEMINI_KEY")) if v), "")
        if not cle_gemini_journal:
            return None, "⚠️ Clé `GEMINI_API_KEY` absente de vos Secrets Streamlit."
        corps_requete = json.dumps({"contents": [{"parts": parties}]}).encode("utf-8")
        for modele in ("gemini-2.5-flash", "gemini-2.0-flash", "gemini-flash-latest"):
            try:
                requete = urllib.request.Request(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{modele}:generateContent?key={urllib.parse.quote(cle_gemini_journal)}",
                    data=corps_requete, headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(requete, timeout=40) as reponse:
                    texte_ia = json.loads(reponse.read().decode("utf-8"))["candidates"][0]["content"]["parts"][0]["text"]
                debut, fin = texte_ia.find("["), texte_ia.rfind("]")
                if debut != -1 and fin > debut:
                    donnees = json.loads(texte_ia[debut:fin + 1])
                    if isinstance(donnees, list):
                        return donnees, None
            except Exception:
                continue
        return None, "L'IA n'a pas pu lire cet historique. Réessayez avec une capture plus nette, ou copiez-collez le texte."

    CONSIGNE_HISTORIQUE_IA = (
        "Extrais chaque opération d'achat ou de vente d'actions ou d'ETF de cet historique de PEA ou de compte-titres. "
        "Réponds UNIQUEMENT avec un tableau JSON valide de la forme : "
        '[{"date": "2025-03-15", "nom": "Air Liquide", "sens": "achat", "qte": 5, "prix": 160.50, "frais": 1.95}]. '
        "date = date d'exécution au format AAAA-MM-JJ ; sens = achat ou vente ; qte = nombre de titres ; "
        "prix = prix unitaire d'exécution ; frais = frais de courtage en euros (0 s'ils ne sont pas indiqués). "
        "Ignore les dividendes, versements, virements, taxes et droits de garde. "
        "Utilise les noms standards si tu reconnais l'entreprise (ex : TotalEnergies, Air Liquide, AXA, LVMH, Sanofi, "
        "Engie, Vinci, BNP Paribas, Schneider Electric, Microsoft, Apple, Realty Income)."
    )

    def _importer_achats(lignes_a_importer):
        for ligne in sorted(lignes_a_importer, key=lambda l: l["date"]):
            appliquer_achat(ligne["action"], ligne["date"], ligne["qte"], ligne["prix"], ligne["frais"], ligne["taux"], source="import")
        sauvegarder_dans_cloud()
        # Nouveaux champs de dépôt (clés différentes) : le fichier ou le texte importé disparaît de l'écran
        st.session_state["_compteur_import_achats"] = int(st.session_state.get("_compteur_import_achats", 0)) + 1
        st.session_state.pop("_operations_ia", None)
        st.session_state["_notif_journal"] = ("ok", f"✅ {len(lignes_a_importer)} achat(s) importé(s). Quantités et PRU mis à jour.")

    def _sans_accents(texte):
        import unicodedata
        return "".join(c for c in unicodedata.normalize("NFD", str(texte)) if unicodedata.category(c) != "Mn")

    def _normaliser(texte):
        return re.sub(r"[^a-z0-9]+", " ", _sans_accents(texte).lower()).strip()

    def _reconnaitre_action(texte):
        """Retrouve une action connue à partir d'un libellé ou d'un symbole de courtier ; None si aucune ne correspond."""
        cherche = _normaliser(texte)
        if not cherche:
            return None
        meilleure, longueur = None, 0
        for nom_c, info_c in WATCHLIST_DEFAUT.items():
            if nom_c in CLES_TECHNIQUES_PF or not isinstance(info_c, dict):
                continue
            nom_n = _normaliser(nom_c)
            symbole = str(info_c.get("symbole", ""))
            if cherche in (nom_n, _normaliser(symbole)) or (len(symbole.split(".")[0]) >= 2 and cherche == _normaliser(symbole.split(".")[0])):
                return nom_c
            nom_court = _normaliser(re.sub(r"\(.*?\)", "", nom_c))
            for candidat in {nom_n, nom_court}:
                if len(candidat) >= 4 and (candidat in cherche or (len(cherche) >= 4 and cherche in candidat)) and len(candidat) > longueur:
                    meilleure, longueur = nom_c, len(candidat)
        return meilleure

    with st.expander("🧾 Journal des achats : enregistrer un achat (PRU recalculé automatiquement)", expanded=False):
        notif_journal = st.session_state.pop("_notif_journal", None)
        if notif_journal:
            (st.success if notif_journal[0] == "ok" else st.error)(nombres_fr(notif_journal[1]))
        st.caption(
            "Chaque achat enregistré met à jour la quantité et le PRU de la ligne, frais de courtage inclus. "
            "Vos lignes déjà saisies servent de point de départ."
        )

        options_achat = sorted([k for k in WATCHLIST_DEFAUT.keys() if k not in CLES_TECHNIQUES_PF])
        lignes_detenues = [k for k, v in st.session_state["portefeuille"].items() if k not in CLES_TECHNIQUES_PF and isinstance(v, dict)]
        index_defaut = options_achat.index(lignes_detenues[0]) if lignes_detenues and lignes_detenues[0] in options_achat else 0
        col_ja1, col_ja2 = st.columns([2, 1])
        with col_ja1:
            action_achat = st.selectbox("Action achetée :", options_achat, index=index_defaut, key="ja_action")
        with col_ja2:
            st.date_input("Date de l'achat :", value=datetime.now().date(), max_value=datetime.now().date(), key="ja_date", format="DD/MM/YYYY")

        est_usd_achat = WATCHLIST_DEFAUT.get(action_achat, {}).get("devise") == "USD"
        symbole_achat = "$" if est_usd_achat else "€"
        cours_reference = float(prix_temps_reel.get(action_achat, WATCHLIST_DEFAUT.get(action_achat, {}).get("prix_cible", 0.0)) or 0.0)
        col_ja3, col_ja4, col_ja5 = st.columns(3)
        with col_ja3:
            st.number_input("Quantité achetée :", min_value=0, value=0, step=1, key="ja_qte")
        with col_ja4:
            st.number_input(f"Prix unitaire ({symbole_achat}) :", min_value=0.0, value=round(cours_reference, 2), step=0.5, key=f"ja_prix_{action_achat}")
        with col_ja5:
            st.number_input("Frais de courtage (€) :", min_value=0.0, value=0.0, step=0.5, key="ja_frais")
        if est_usd_achat:
            st.number_input("Taux €/$ de l'achat (1 € = ? $) :", min_value=0.0, max_value=5.0, value=round(float(TAUX_USD_EUR), 4),
                            step=0.01, format="%.4f", key=f"ja_taux_{action_achat}")

        qte_apercu = int(st.session_state.get("ja_qte", 0) or 0)
        prix_apercu = float(st.session_state.get(f"ja_prix_{action_achat}", 0.0) or 0.0)
        if qte_apercu > 0 and prix_apercu > 0:
            taux_apercu = float(st.session_state.get(f"ja_taux_{action_achat}", TAUX_USD_EUR) or TAUX_USD_EUR) if est_usd_achat else 1.0
            position_actuelle = st.session_state["portefeuille"].get(action_achat)
            position_apercu = _calculer_position_apres_achat(position_actuelle, est_usd_achat, qte_apercu, prix_apercu,
                                                             float(st.session_state.get("ja_frais", 0.0) or 0.0), taux_apercu)
            qte_actuelle_ap = int(position_actuelle.get("qte", 0)) if isinstance(position_actuelle, dict) else 0
            pru_actuel_ap = float(position_actuelle.get("pru", 0.0)) if isinstance(position_actuelle, dict) else 0.0
            afficher_html(f"""
            <div style="background:rgba(128,128,128,0.05); border:1px dashed #3498db; padding:10px 14px; border-radius:8px; margin:6px 0 10px 0; font-size:0.88em;">
                🔎 <b>Aperçu :</b> {qte_actuelle_ap} ➔ <b>{position_apercu['qte']} titre(s)</b> |
                PRU {pru_actuel_ap:.2f} ➔ <b>{position_apercu['pru']:.2f} {symbole_achat}</b> (frais inclus) |
                Montant de l'achat : <b>{qte_apercu * prix_apercu:,.2f} {symbole_achat}</b>
            </div>
            """)
        col_ja6, col_ja7 = st.columns([1, 2])
        with col_ja6:
            st.selectbox("📓 Pourquoi cet achat ? (facultatif)", ["—"] + RAISONS["achat"], key="ja_raison",
                         help="Noté dans le carnet de décisions : six mois plus tard, Boursy vous montrera ce qu'est devenue la valeur.")
        with col_ja7:
            st.text_input("En une phrase (facultatif) :", max_chars=LONGUEUR_NOTE_MAX, key="ja_note",
                          placeholder="Ex. : sous mon prix cible depuis 3 semaines, dividende confirmé.")
        st.button("➕ Enregistrer cet achat", type="primary", width="stretch", on_click=_enregistrer_achat_saisi, key="btn_enregistrer_achat")

        journal_achats = st.session_state["portefeuille"].get("_journal_achats") if isinstance(st.session_state["portefeuille"].get("_journal_achats"), list) else []
        if journal_achats:
            st.markdown("#### 📜 Historique des achats")
            montant_total_achats = sum(
                (e["qte"] * e["prix"]) / (e.get("taux_change") or TAUX_USD_EUR) + e.get("frais_eur", 0.0) if e.get("devise") == "USD"
                else e["qte"] * e["prix"] + e.get("frais_eur", 0.0)
                for e in journal_achats
            )
            st.caption(nombres_fr(f"{len(journal_achats)} achat(s) enregistré(s), pour un total de {montant_total_achats:,.2f} € frais inclus."))
            entrees_triees = sorted(journal_achats, key=lambda e: (e.get("date", ""), e.get("id", "")), reverse=True)
            for entree in entrees_triees[:30]:
                sym_e = "$" if entree.get("devise") == "USD" else "€"
                date_e = str(entree.get("date", ""))
                date_fr_e = f"{date_e[8:10]}/{date_e[5:7]}/{date_e[0:4]}" if len(date_e) == 10 else date_e
                col_h1, col_h2 = st.columns([5, 1])
                with col_h1:
                    markdown_fr(
                        f"**{date_fr_e}** — **{entree['action']}** : +{entree['qte']} à {entree['prix']:.2f} {sym_e}"
                        + (f" (frais {entree.get('frais_eur', 0.0):.2f} €)" if entree.get("frais_eur") else "")
                        + (" · *importé*" if entree.get("source") == "import" else "")
                    )
                with col_h2:
                    annulable = _achat_annulable(entree)
                    st.button("↩️ Annuler", key=f"annuler_achat_{entree['id']}", on_click=_annuler_achat, args=(entree["id"],),
                              disabled=not annulable, width="stretch",
                              help=None if annulable else "La ligne a changé depuis cet achat (autre achat, vente ou modification) : il ne peut plus être annulé.")
            if len(entrees_triees) > 30:
                st.caption(f"… et {len(entrees_triees) - 30} achat(s) plus ancien(s).")

        # --- IMPORT D'UN HISTORIQUE D'ACHATS (CSV EXPORTÉ DEPUIS LE COURTIER) ---
        st.markdown("#### 📥 Importer un historique d'achats (fichier CSV de votre courtier)")
        if not est_premium_ou_pro:
            afficher_verrou_saas(
                "Import d'un historique d'achats depuis votre courtier (CSV)",
                "⚡ Offre Premium (4,90 €/mois) ou 👑 Pro (8,90 €/mois)",
                "Importez en une fois tous vos achats passés : quantités et PRU sont recalculés automatiquement."
            )
        else:
            st.caption(
                "Exportez l'historique de vos opérations depuis votre courtier au format CSV, puis déposez-le ici. "
                "Indiquez quelle colonne contient quoi : seuls les achats d'actions reconnues sont importés. "
                "Pas d'export CSV ? Utilisez l'import par l'IA juste en dessous (offre Pro)."
            )
            fichier_achats = st.file_uploader("Fichier CSV des opérations", type=["csv", "txt"], key=f"up_csv_achats_{st.session_state.get('_compteur_import_achats', 0)}")
            if fichier_achats is not None:
                tableau_csv = None
                for encodage in ("utf-8-sig", "latin-1"):
                    try:
                        tableau_csv = pd.read_csv(io.BytesIO(fichier_achats.getvalue()), sep=None, engine="python", encoding=encodage, dtype=str)
                        break
                    except Exception:
                        continue
                if tableau_csv is None or tableau_csv.empty:
                    st.error("Ce fichier n'a pas pu être lu. Vérifiez qu'il s'agit bien d'un export CSV (texte séparé par des points-virgules ou des virgules).")
                else:
                    colonnes_csv = [str(c) for c in tableau_csv.columns]
                    tableau_csv.columns = colonnes_csv

                    def _colonne_probable(mots):
                        for c in colonnes_csv:
                            if any(m in _normaliser(c) for m in mots):
                                return colonnes_csv.index(c) + 1
                        return 0

                    choix_aucune = ["(aucune)"] + colonnes_csv
                    col_m1, col_m2, col_m3 = st.columns(3)
                    with col_m1:
                        col_date = st.selectbox("Colonne Date :", choix_aucune, index=_colonne_probable(["date"]), key="map_date")
                        col_valeur = st.selectbox("Colonne Valeur (nom ou symbole) :", choix_aucune,
                                                  index=_colonne_probable(["libelle", "valeur", "titre", "instrument", "produit", "nom", "symbole", "ticker", "action"]), key="map_valeur")
                    with col_m2:
                        col_qte = st.selectbox("Colonne Quantité :", choix_aucune, index=_colonne_probable(["quantite", "qte", "nombre", "quantity"]), key="map_qte")
                        col_prix = st.selectbox("Colonne Prix unitaire :", choix_aucune, index=_colonne_probable(["cours", "prix", "price"]), key="map_prix")
                    with col_m3:
                        col_frais = st.selectbox("Colonne Frais (facultatif, en €) :", choix_aucune, index=_colonne_probable(["frais", "commission", "courtage"]), key="map_frais")
                        col_sens = st.selectbox("Colonne Sens (facultatif : achat / vente) :", choix_aucune,
                                                index=_colonne_probable(["sens", "operation", "nature", "type"]), key="map_sens")
                    taux_import = st.number_input("Taux €/$ appliqué aux achats en dollars de ce fichier (1 € = ? $) :", min_value=0.0, max_value=5.0,
                                                  value=round(float(TAUX_USD_EUR), 4), step=0.01, format="%.4f", key="map_taux")

                    if "(aucune)" in (col_date, col_valeur, col_qte, col_prix):
                        st.info("Indiquez au minimum les colonnes Date, Valeur, Quantité et Prix unitaire.")
                    else:
                        lignes_valides, apercu_import = _analyser_operations([
                            {
                                "date": rangee.get(col_date),
                                "libelle": rangee.get(col_valeur),
                                "qte": rangee.get(col_qte),
                                "prix": rangee.get(col_prix),
                                "frais": rangee.get(col_frais) if col_frais != "(aucune)" else 0.0,
                                "sens": rangee.get(col_sens) if col_sens != "(aucune)" else "",
                            }
                            for _, rangee in tableau_csv.iterrows()
                        ], taux_import)
                        st.dataframe(pd.DataFrame(apercu_import), width="stretch", hide_index=True)
                        if lignes_valides:
                            st.button(f"📥 Importer {len(lignes_valides)} achat(s)", type="primary", width="stretch",
                                      on_click=_importer_achats, args=(lignes_valides,), key="btn_importer_achats")
                        else:
                            st.warning("Aucun achat importable dans ce fichier.")

        # --- IMPORT D'UN HISTORIQUE D'OPÉRATIONS PAR L'IA (CAPTURE D'ÉCRAN OU COPIER-COLLER) ---
        st.markdown("#### 🤖 Importer un historique par capture d'écran ou copier-coller (IA Gemini)")
        if not est_pro_max:
            afficher_verrou_saas(
                "Import d'un historique d'opérations par l'IA (capture d'écran ou copier-coller)",
                "👑 Offre Pro (8,90 €/mois)",
                "Pas d'export CSV ? L'IA lit une capture d'écran de votre historique d'opérations et remplit le journal, dates comprises."
            )
        else:
            st.caption(
                "Faites une capture d'écran de la page « Historique des opérations » ou « Mouvements » de votre courtier, "
                "ou copiez-collez son texte. L'IA en extrait les achats datés ; vous vérifiez l'aperçu avant d'importer."
            )
            compteur_import = st.session_state.get("_compteur_import_achats", 0)
            mode_historique_ia = st.radio("Source :", ["📋 Copier-coller le texte", "📸 Capture d'écran (PNG / JPG)"],
                                          horizontal=True, key="rad_historique_ia")
            parties_ia = None
            if mode_historique_ia.startswith("📋"):
                texte_historique = st.text_area(
                    "Collez ici l'historique de vos opérations :", height=120, key=f"txt_historique_ia_{compteur_import}",
                    placeholder="Ex. : 15/03/2025  Achat  5 AIR LIQUIDE  160,50 €  frais 1,95 €",
                )
                if st.button("🤖 Extraire les opérations de ce texte", key="btn_historique_ia_texte"):
                    if texte_historique.strip():
                        parties_ia = [{"text": f"{CONSIGNE_HISTORIQUE_IA}\n\nHistorique :\n{texte_historique}"}]
                    else:
                        st.warning("Collez d'abord le texte de votre historique.")
            else:
                image_historique = st.file_uploader("Capture d'écran de l'historique", type=["png", "jpg", "jpeg", "webp"],
                                                    key=f"up_historique_ia_{compteur_import}")
                if image_historique is not None and st.button("🤖 Analyser cette capture", key="btn_historique_ia_image"):
                    import base64
                    parties_ia = [
                        {"text": CONSIGNE_HISTORIQUE_IA},
                        {"inline_data": {"mime_type": image_historique.type or "image/jpeg",
                                         "data": base64.b64encode(image_historique.getvalue()).decode("utf-8")}},
                    ]
            if parties_ia is not None:
                with st.spinner("🧠 Lecture de votre historique d'opérations..."):
                    operations_lues, erreur_lecture = _extraire_json_gemini(parties_ia)
                if erreur_lecture:
                    st.error(erreur_lecture)
                else:
                    st.session_state["_operations_ia"] = operations_lues

            if st.session_state.get("_operations_ia"):
                taux_historique_ia = st.number_input(
                    "Taux €/$ appliqué aux achats en dollars de cet historique (1 € = ? $) :", min_value=0.0, max_value=5.0,
                    value=round(float(TAUX_USD_EUR), 4), step=0.01, format="%.4f", key="taux_historique_ia",
                )
                lignes_ia, apercu_ia = _analyser_operations([
                    {"date": o.get("date"), "libelle": o.get("nom"), "qte": o.get("qte"), "prix": o.get("prix"),
                     "frais": o.get("frais", 0.0), "sens": o.get("sens", "")}
                    for o in st.session_state["_operations_ia"] if isinstance(o, dict)
                ], taux_historique_ia)
                st.success(f"✅ {len(apercu_ia)} opération(s) lue(s), dont {len(lignes_ia)} achat(s) importable(s). Vérifiez l'aperçu avant d'importer.")
                st.dataframe(pd.DataFrame(apercu_ia), width="stretch", hide_index=True)
                if lignes_ia:
                    st.button(f"📥 Importer {len(lignes_ia)} achat(s)", type="primary", width="stretch",
                              on_click=_importer_achats, args=(lignes_ia,), key="btn_importer_historique_ia")
                else:
                    st.warning("Aucun achat importable dans cet historique.")

    # ======================================================================
    # CARNET DE DÉCISIONS : POURQUOI J'ACHÈTE, POURQUOI JE VENDS, ET CE QUE C'EST DEVENU (carnet_decisions.py)
    # ======================================================================
    def _noter_decision_carnet():
        type_d = st.session_state.get("cd_type", "achat")
        nom_d = st.session_state.get("cd_action")
        note_d = str(st.session_state.get("cd_note") or "").strip()
        if not nom_d:
            st.session_state["_notif_carnet"] = ("erreur", "Choisissez une valeur.")
            return
        info_d = WATCHLIST_DEFAUT.get(nom_d, {})
        ajouter_decision(st.session_state["portefeuille"], nouvelle_decision(
            st.session_state.get("cd_date", datetime.now().date()), nom_d, symbole_a_jour(info_d.get("symbole", "")), type_d,
            st.session_state.get(f"cd_raison_{type_d}", "Autre"), note_d, info_d.get("devise", "EUR"), "carnet",
        ))
        st.session_state["cd_note"] = ""
        sauvegarder_dans_cloud()
        st.session_state["_notif_carnet"] = ("ok", f"📓 Décision notée : {TYPES_DECISION[type_d].lower()} — {nom_d}.")

    def _enregistrer_lecon_carnet(id_decision):
        if enregistrer_lecon(st.session_state["portefeuille"], id_decision, st.session_state.get(f"cd_lecon_{id_decision}", "")):
            sauvegarder_dans_cloud()
            st.session_state["_notif_carnet"] = ("ok", "💡 Leçon enregistrée.")

    def _supprimer_decision_carnet(id_decision):
        if supprimer_decision(st.session_state["portefeuille"], id_decision):
            sauvegarder_dans_cloud()
            st.session_state["_notif_carnet"] = ("ok", "🗑️ Décision supprimée du carnet.")

    def _date_fr(jour_iso):
        jour_iso = str(jour_iso)[:10]
        return f"{jour_iso[8:10]}/{jour_iso[5:7]}/{jour_iso[0:4]}" if len(jour_iso) == 10 else jour_iso

    def _pct_carnet(valeur):
        return "—" if valeur is None else f"{valeur * 100:+.1f} %"

    carnet_actuel = lire_carnet(st.session_state["portefeuille"])
    # Titre fixe : un titre qui change (nombre de décisions) refermerait le volet après chaque enregistrement
    with st.expander("📓 Carnet de décisions : pourquoi j'achète, pourquoi je vends", expanded=False):
        notif_carnet = st.session_state.pop("_notif_carnet", None)
        if notif_carnet:
            (st.success if notif_carnet[0] == "ok" else st.error)(notif_carnet[1])
        st.caption(
            "Notez en une phrase pourquoi vous achetez, vendez ou préférez attendre. Plus tard, Boursy vous montre ce qu'est "
            f"devenue la valeur, dividendes compris, face à l'{NOM_REFERENCE} sur la même période : de quoi voir quels "
            "raisonnements ont tenu. Les achats et les ventes enregistrés avec une raison y arrivent automatiquement."
        )

        st.markdown("#### ✍️ Noter une décision")
        aujourd_hui_carnet = datetime.now().date()
        options_carnet = sorted([k for k in WATCHLIST_DEFAUT.keys() if k not in CLES_TECHNIQUES_PF])
        col_cd1, col_cd2, col_cd3 = st.columns([1.3, 2, 1])
        with col_cd1:
            type_carnet = st.selectbox("Décision :", list(TYPES_DECISION), format_func=TYPES_DECISION.get, key="cd_type")
        with col_cd2:
            st.selectbox("Valeur :", options_carnet, key="cd_action")
        with col_cd3:
            st.date_input("Date :", value=aujourd_hui_carnet, max_value=aujourd_hui_carnet, key="cd_date", format="DD/MM/YYYY")
        st.selectbox("Raison principale :", RAISONS[type_carnet], key=f"cd_raison_{type_carnet}")
        st.text_area("Pourquoi, en une ou deux phrases :", max_chars=LONGUEUR_NOTE_MAX, key="cd_note", height=80,
                     placeholder="Ex. : je n'achète pas ce mois-ci, le cours a pris 25 % en deux mois ; j'attends un repli.")
        st.button("📓 Noter dans le carnet", type="primary", width="stretch", on_click=_noter_decision_carnet, key="btn_noter_decision")

        if carnet_actuel:
            # Historiques (mis en cache 6 heures) : valeurs du carnet, ETF de référence et change €/$ pour les valeurs en dollars
            symboles_carnet = sorted({symbole_a_jour(d.get("symbole")) for d in carnet_actuel if d.get("symbole")})
            symboles_a_charger = symboles_carnet + [SYMBOLE_REFERENCE] + (["EURUSD=X"] if any(d.get("devise") == "USD" for d in carnet_actuel) else [])
            with ThreadPoolExecutor(max_workers=6) as executeur_carnet:
                historiques_carnet = dict(zip(symboles_a_charger, executeur_carnet.map(historique_long, symboles_a_charger)))
            evaluations_carnet = {
                d["id"]: evaluer_decision(d, historiques_carnet.get(symbole_a_jour(d.get("symbole"))),
                                          historiques_carnet.get(SYMBOLE_REFERENCE), aujourd_hui_carnet, historiques_carnet.get("EURUSD=X"))
                for d in carnet_actuel
            }

            a_relire_carnet = decisions_a_relire(carnet_actuel, aujourd_hui_carnet)
            if a_relire_carnet:
                st.info(
                    f"🔔 {len(a_relire_carnet)} décision(s) ont plus de {HORIZON_RELECTURE_MOIS} mois et attendent votre relecture : "
                    + ", ".join(f"{d['action']} ({_date_fr(d['date'])})" for d in a_relire_carnet[:5])
                    + (" …" if len(a_relire_carnet) > 5 else "") + ". Choisissez-les plus bas, dans « Relire une décision »."
                )

            st.markdown(f"#### 🔎 Ce que sont devenues mes décisions ({len(carnet_actuel)})")
            html_carnet = (
                "<table class='r-table'><thead><tr><th>Date</th><th style='text-align:left;'>Valeur et décision</th>"
                "<th style='text-align:left;'>Pourquoi</th><th>Depuis : valeur · ETF Monde</th>"
                f"<th>Résultat à {HORIZON_RELECTURE_MOIS} mois</th></tr></thead><tbody>"
            )
            for d in carnet_actuel[:40]:
                ev_d = evaluations_carnet[d["id"]]
                depuis_d = ev_d["depuis"]
                mesure_6 = ev_d["horizons"].get(HORIZON_RELECTURE_MOIS)
                if mesure_6:
                    resultat_6 = phrase_resultat(d["type"], mesure_6["action"], mesure_6["reference"])
                    couleur_6 = "#2ecc71" if (mesure_6["en_faveur"] or 0) >= 0 else "#e74c3c"
                    cellule_6 = f"<span style='color:{couleur_6}; font-weight:700;'>{html_lib.escape(resultat_6)}</span>"
                else:
                    cellule_6 = (f"<span style='opacity:0.7;'>le {_date_fr(ajouter_mois(d['date'], HORIZON_RELECTURE_MOIS).isoformat())}</span>")
                pourquoi_d = html_lib.escape(d.get("note") or "—")
                if d.get("lecon"):
                    pourquoi_d += f"<br><span style='font-size:0.85em; opacity:0.8;'>💡 {html_lib.escape(d['lecon'])}</span>"
                html_carnet += (
                    f"<tr><td style='white-space:nowrap;'>{_date_fr(d['date'])}</td>"
                    f"<td class='r-name' style='text-align:left;'><b>{html_lib.escape(d['action'])}</b><br>"
                    f"<span style='font-size:0.85em; opacity:0.8;'>{TYPES_DECISION.get(d['type'], d['type'])} · {html_lib.escape(d.get('raison', ''))}</span></td>"
                    f"<td style='text-align:left; max-width:320px;'>{pourquoi_d}</td>"
                    f"<td style='white-space:nowrap;'>{_pct_carnet(depuis_d['action'] if depuis_d else None)} · {_pct_carnet(depuis_d['reference'] if depuis_d else None)}</td>"
                    f"<td>{cellule_6}</td></tr>"
                )
            html_carnet += "</tbody></table>"
            afficher_html(html_carnet)
            st.caption(
                "Achat : écart avec l'ETF Monde, qu'on aurait pu acheter à la place. Vente ou attente : hausse manquée ou baisse "
                "évitée en ne détenant pas la valeur. Performances de clôture à clôture, dividendes compris, converties en "
                "euros pour les valeurs en dollars."
                + (f" Seules les 40 décisions les plus récentes sont affichées ({len(carnet_actuel)} au total)." if len(carnet_actuel) > 40 else "")
            )

            st.markdown("#### 💡 Relire une décision")
            ordre_relecture = a_relire_carnet + [d for d in carnet_actuel if d not in a_relire_carnet]
            decisions_par_id = {d["id"]: d for d in ordre_relecture}
            ids_a_relire = {d["id"] for d in a_relire_carnet}
            id_relu = st.selectbox(
                "Décision :", list(decisions_par_id), key="cd_relue",
                format_func=lambda i: f"{_date_fr(decisions_par_id[i]['date'])} · {TYPES_DECISION.get(decisions_par_id[i]['type'], '')} · "
                                      f"{decisions_par_id[i]['action']}" + (" 🔔" if i in ids_a_relire else ""),
            )
            decision_relue = decisions_par_id.get(id_relu)
            if decision_relue:
                ev_relue = evaluations_carnet[decision_relue["id"]]
                markdown_fr(
                    f"**{TYPES_DECISION.get(decision_relue['type'])} — {decision_relue['action']}** le {_date_fr(decision_relue['date'])} · "
                    f"*{decision_relue.get('raison', '')}*" + (f" : « {decision_relue['note']} »" if decision_relue.get("note") else "")
                )
                lignes_relue = []
                for mois_r in HORIZONS_MOIS:
                    mesure_r = ev_relue["horizons"].get(mois_r)
                    lignes_relue.append({
                        "Horizon": f"{mois_r} mois",
                        "Valeur": _pct_carnet(mesure_r["action"]) if mesure_r else f"le {_date_fr(ajouter_mois(decision_relue['date'], mois_r).isoformat())}",
                        NOM_REFERENCE: _pct_carnet(mesure_r["reference"]) if mesure_r else "—",
                        "Résultat": phrase_resultat(decision_relue["type"], mesure_r["action"], mesure_r["reference"]) if mesure_r else "pas encore",
                    })
                st.dataframe(pd.DataFrame(lignes_relue).map(nombres_fr), width="stretch", hide_index=True)
                st.text_area("Ce que j'en retiens :", value=decision_relue.get("lecon", ""), max_chars=LONGUEUR_NOTE_MAX, height=80,
                             key=f"cd_lecon_{decision_relue['id']}",
                             placeholder="Ex. : acheter sous mon prix cible a bien marché ; je garde cette règle.")
                col_cl1, col_cl2 = st.columns(2)
                with col_cl1:
                    st.button("💾 Enregistrer ma leçon", width="stretch", key=f"cd_btn_lecon_{decision_relue['id']}",
                              on_click=_enregistrer_lecon_carnet, args=(decision_relue["id"],))
                with col_cl2:
                    with st.popover("🗑️ Supprimer cette décision", width="stretch"):
                        st.caption("La décision et la leçon notée seront effacées du carnet.")
                        st.button("Confirmer la suppression", type="primary", width="stretch", key=f"cd_btn_suppr_{decision_relue['id']}",
                                  on_click=_supprimer_decision_carnet, args=(decision_relue["id"],))

            bilan_carnet = bilan_par_raison(carnet_actuel, evaluations_carnet)
            st.markdown(f"#### 📊 Quels raisonnements ont tenu ? (à {HORIZON_RELECTURE_MOIS} mois)")
            if not bilan_carnet:
                st.caption(f"Le bilan apparaîtra quand vos premières décisions auront {HORIZON_RELECTURE_MOIS} mois.")
            else:
                html_bilan_carnet = (
                    "<table class='r-table'><thead><tr><th style='text-align:left;'>Décision et raison</th><th>Décisions</th>"
                    "<th>Résultat moyen</th><th>Part favorable</th></tr></thead><tbody>"
                )
                for g in bilan_carnet:
                    couleur_g = "#2ecc71" if g["moyenne"] >= 0 else "#e74c3c"
                    html_bilan_carnet += (
                        f"<tr><td class='r-name' style='text-align:left;'>{TYPES_DECISION.get(g['type'])} · {html_lib.escape(g['raison'])}</td>"
                        f"<td>{g['nombre']}</td><td style='color:{couleur_g}; font-weight:800;'>{g['moyenne'] * 100:+.1f} pt</td>"
                        f"<td>{g['part_favorable'] * 100:.0f} %</td></tr>"
                    )
                html_bilan_carnet += "</tbody></table>"
                afficher_html(html_bilan_carnet)
                st.caption(
                    "Résultat moyen : pour un achat, l'écart avec l'ETF Monde ; pour une vente ou une attente, la baisse évitée "
                    "(positive) ou la hausse manquée (négative). Avec moins d'une dizaine de décisions par raison, ces chiffres "
                    "tiennent de l'anecdote : ils servent à se poser des questions, pas à conclure."
                )

    portefeuille_utilisateur = st.session_state["portefeuille"]
    valeur_totale_portefeuille = 0.0
    cout_total_achat = 0.0
    plus_value_globale = 0.0
    plus_value_pct = 0.0
    dividendes_bruts_totaux_eur = 0.0
    dividendes_nets_totaux_eur = 0.0
    repartition_secteurs = {}
    exposition_eur = 0.0
    exposition_usd = 0.0
    lignes_triees = []

    actions_actives_pf = [
        k for k, v in portefeuille_utilisateur.items()
        if k not in ("_historique_ventes", "_quota_ia", "_niveau_abo", "_div_encaisses_cumul") and isinstance(v, dict) and float(v.get("qte", 0)) > 0
    ]

    if not actions_actives_pf:
        st.warning("Votre portefeuille est vide. Ouvrez le volet ci-dessus pour renseigner vos lignes.")
    else:
        if mode_gratuit:
            st.info("🌱 **Forfait Gratuit (0 €)** : Suivi limité à 2 lignes d'actions. Passez à **Premium (4,90 €/mois)** ou **Pro (8,90 €/mois)** pour débloquer un nombre illimité de lignes et l'export CSV !")

        # Fiscalité automatique selon l'enveloppe : PEA (EUR) = 100% en réinvestissement interne, CTO (USD) = 70% net (-30% Flat Tax)
        taux_net_eur = 1.0
        taux_net_usd = 0.70

        lignes_detaillees = []
        variation_jour_totale_eur = 0.0
        lignes_sans_cours = []
        nb_actions_comptees_gratuit = 0

        for nom_act, data_pos in portefeuille_utilisateur.items():
            if nom_act in ("_historique_ventes", "_quota_ia", "_niveau_abo", "_div_encaisses_cumul") or not isinstance(data_pos, dict):
                continue

            if nom_act == "Espèces":
                val_especes = float(data_pos.get("pru", 0.0))
                if val_especes <= 0:
                    continue
                valeur_totale_portefeuille += val_especes
                cout_total_achat += val_especes
                exposition_eur += val_especes
                repartition_secteurs["Liquidités (€)"] = val_especes
                lignes_detaillees.append({
                    "est_especes": True,
                    "nom_act": "Espèces",
                    "env_label": "Liquidités",
                    "devise": "EUR",
                    "sym": "€",
                    "qte": 1,
                    "pru": val_especes,
                    "prix_jour": val_especes,
                    "val_eur": val_especes,
                    "cout_eur": val_especes,
                    "pv_eur": 0.0,
                    "pv_pct": 0.0,
                    "div_brut_l": 0.0,
                    "div_net_l": 0.0,
                })
                continue

            if nom_act not in WATCHLIST_DEFAUT:
                continue

            qte = float(data_pos.get("qte", 0.0))
            if qte <= 0:
                continue

            if mode_gratuit and nb_actions_comptees_gratuit >= 2:
                continue
            nb_actions_comptees_gratuit += 1

            pru = float(data_pos.get("pru", 0.0))
            info_act = WATCHLIST_DEFAUT[nom_act]
            devise = info_act.get("devise", "EUR")
            sym = "$" if devise == "USD" else "€"
            env_label = "CTO US" if devise == "USD" else "PEA"
            facteur = (1.0 / TAUX_USD_EUR) if devise == "USD" else 1.0
            if nom_act in prix_temps_reel:
                prix_jour = float(prix_temps_reel[nom_act])
            else:
                # Cours indisponible : la ligne est valorisée à son PRU (plus-value nulle) et signalée, jamais au prix cible
                prix_jour = pru if pru > 0 else float(info_act.get("prix_cible", 0.0))
                lignes_sans_cours.append(nom_act)

            val_ligne_eur = qte * prix_jour * facteur
            # Coût d'achat converti au taux €/$ du jour de l'achat s'il est renseigné (sinon taux du jour)
            facteur_cout = facteur_cout_usd(data_pos) if devise == "USD" else 1.0
            cout_ligne_eur = qte * pru * facteur_cout
            pv_eur = val_ligne_eur - cout_ligne_eur
            pv_pct = (pv_eur / cout_ligne_eur * 100) if cout_ligne_eur > 0 else 0.0
            div_brut_eur = qte * float(info_act["div_eur"]) * facteur
            div_net_eur = div_brut_eur * (taux_net_usd if devise == "USD" else taux_net_eur)

            # Variation du jour de la ligne (en € et en %), si le cours et la clôture précédente sont connus
            var_jour_pct_l = variations_jour.get(nom_act) if nom_act in prix_temps_reel else None
            var_jour_eur_l = (val_ligne_eur * var_jour_pct_l / (1.0 + var_jour_pct_l)) if (var_jour_pct_l is not None and var_jour_pct_l > -1.0) else 0.0
            variation_jour_totale_eur += var_jour_eur_l

            valeur_totale_portefeuille += val_ligne_eur
            cout_total_achat += cout_ligne_eur
            dividendes_bruts_totaux_eur += div_brut_eur
            dividendes_nets_totaux_eur += div_net_eur

            if devise == "USD":
                exposition_usd += val_ligne_eur
            else:
                exposition_eur += val_ligne_eur

            secteur = info_act["secteur"]
            repartition_secteurs[secteur] = repartition_secteurs.get(secteur, 0.0) + val_ligne_eur

            lignes_detaillees.append({
                "est_especes": False,
                "nom_act": nom_act,
                "env_label": env_label,
                "devise": devise,
                "sym": sym,
                "qte": int(qte),
                "pru": pru,
                "prix_jour": prix_jour,
                "val_eur": val_ligne_eur,
                "cout_eur": cout_ligne_eur,
                "pv_eur": pv_eur,
                "pv_pct": pv_pct,
                "div_brut_l": div_brut_eur,
                "div_net_l": div_net_eur,
                "var_jour_pct": (var_jour_pct_l * 100.0) if var_jour_pct_l is not None else None,
                "var_jour_eur": var_jour_eur_l,
            })

        lignes_triees = sorted(lignes_detaillees, key=lambda x: x["val_eur"], reverse=True)

        if lignes_sans_cours:
            st.warning(
                "⚠️ Cours indisponible pour : **" + ", ".join(lignes_sans_cours) + "**. "
                "Ces lignes sont valorisées à leur PRU (plus-value affichée à 0) en attendant le retour des cours. "
                "Cliquez sur « 🔄 Actualiser les cours Bourse » pour réessayer."
            )

        lignes_export_csv = []
        for l_item in lignes_triees:
            poids_item = (l_item["val_eur"] / valeur_totale_portefeuille * 100) if valeur_totale_portefeuille > 0 else 0.0
            lignes_export_csv.append({
                "Actif": l_item["nom_act"],
                "Enveloppe": l_item["env_label"],
                "Devise": l_item["devise"],
                "Quantite": l_item["qte"],
                "PRU_Devise": round(l_item["pru"], 2),
                "Cours_Actuel_Devise": round(l_item["prix_jour"], 2),
                "Valorisation_EUR": round(l_item["val_eur"], 2),
                "Poids_Portefeuille_Pct": round(poids_item, 2),
                "Plus_Value_EUR": round(l_item["pv_eur"], 2),
                "Dividende_Brut_EUR": round(l_item["div_brut_l"], 2),
                "Dividende_Net_EUR": round(l_item["div_net_l"], 2),
            })

        plus_value_globale = valeur_totale_portefeuille - cout_total_achat
        plus_value_pct = (plus_value_globale / cout_total_achat * 100) if cout_total_achat > 0 else 0.0
        yoc_global = (dividendes_bruts_totaux_eur / cout_total_achat * 100) if cout_total_achat > 0 else 0.0
        part_usd_pct = (exposition_usd / valeur_totale_portefeuille * 100) if valeur_totale_portefeuille > 0 else 0.0
        part_eur_pct = 100.0 - part_usd_pct
        c_pv = "#2ecc71" if plus_value_globale >= 0 else "#e74c3c"
        valeur_veille_pf = valeur_totale_portefeuille - variation_jour_totale_eur
        variation_jour_totale_pct = (variation_jour_totale_eur / valeur_veille_pf * 100.0) if valeur_veille_pf > 0 else 0.0
        c_jour = "#2ecc71" if variation_jour_totale_eur >= 0 else "#e74c3c"

        html_kpi_port = f"""
        <div class="argon-grid bz-5">
            <div class="argon-card">
                <div class="argon-title">💼 Valorisation Totale (€)</div>
                <div class="argon-val">{valeur_totale_portefeuille:,.2f} €</div>
                <div class="argon-sub">Capital investi : <b>{cout_total_achat:,.2f} €</b></div>
            </div>
            <div class="argon-card">
                <div class="argon-title">⚡ Variation du Jour</div>
                <div class="argon-val" style="color:{c_jour};">{variation_jour_totale_eur:+,.2f} €</div>
                <div class="argon-sub" style="color:{c_jour};">Depuis la clôture précédente : <b>{variation_jour_totale_pct:+.2f}%</b></div>
            </div>
            <div class="argon-card">
                <div class="argon-title">📈 Plus/Moins-Value Latente</div>
                <div class="argon-val" style="color:{c_pv};">{plus_value_globale:+,.2f} €</div>
                <div class="argon-sub" style="color:{c_pv};">Performance : <b>{plus_value_pct:+.2f}%</b></div>
            </div>
            <div class="argon-card">
                <div class="argon-title">💰 Rente Brute vs Nette</div>
                <div class="argon-val" style="color:#2ecc71;">{dividendes_nets_totaux_eur:,.2f} € net/an</div>
                <div class="argon-sub">Brut : <b>{dividendes_bruts_totaux_eur:,.2f} €</b> (YoC : {yoc_global:.2f}%)</div>
            </div>
            <div class="argon-card">
                <div class="argon-title">🌍 Exposition Devises</div>
                <div class="argon-val">{part_eur_pct:.0f}% € / {part_usd_pct:.0f}% $</div>
                <div class="argon-sub">PEA : {exposition_eur:,.0f} € | US : {exposition_usd:,.0f} €</div>
            </div>
        </div>
        """
        afficher_html(html_kpi_port)

        col_titre_p, col_btn_csv = st.columns([3, 1])
        with col_titre_p:
            st.subheader("💼 Portefeuille et Performance")
        with col_btn_csv:
            if est_premium_ou_pro:
                df_export = pd.DataFrame(lignes_export_csv)
                csv_bytes = df_export.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig")
                st.download_button(
                    label="📥 Exporter Bilan CSV (Excel)",
                    data=csv_bytes,
                    file_name=f"Boursy_Portefeuille_{datetime.now().strftime('%Y-%m-%d')}.csv",
                    mime="text/csv",
                    width="stretch",
                )
            else:
                st.button("🔒 Export CSV (Offre Premium/Pro)", disabled=True, width="stretch")

        html_port = "<table class='r-table'><thead><tr><th style='text-align: left;'>Actif (Enveloppe)</th><th>Qté</th><th>PRU ➔ Cours</th><th>Valorisation (€)</th><th>+/- Value (€ & %)</th><th>Div. Brut / Net (€)</th><th style='width:140px;'>Poids (%)</th></tr></thead><tbody>"

        for l_item in lignes_triees:
            poids = (l_item["val_eur"] / valeur_totale_portefeuille * 100) if valeur_totale_portefeuille > 0 else 0.0
            if l_item["est_especes"]:
                html_port += f"""
                <tr>
                    <td class='r-name'>💶 Espèces (Liquidités)</td>
                    <td>-</td>
                    <td>-</td>
                    <td><b>{l_item['val_eur']:,.2f} €</b></td>
                    <td><span class='b-neutral'>0.00 €</span></td>
                    <td>-</td>
                    <td>
                        <div style="font-weight:800;">{poids:.1f}%</div>
                        <div class="score-bg"><div style="width:{min(100, poids)}%; background:#95a5a6; height:100%;"></div></div>
                    </td>
                </tr>
                """
            else:
                b_pv = "b-green" if l_item["pv_eur"] >= 0 else "b-red"
                vj_l = l_item.get("var_jour_pct")
                badge_jour_l = (
                    f"<br><span style='font-size:0.80em; font-weight:700; color:{'#2ecc71' if vj_l >= 0 else '#e74c3c'};'>"
                    f"{'▲' if vj_l >= 0 else '▼'} {vj_l:+.2f}% aujourd'hui</span>"
                    if vj_l is not None else ""
                )
                html_port += f"""
                <tr>
                    <td class="r-name">{l_item['nom_act']} <span class="b-neutral" style="font-size:0.75em;">{l_item['env_label']}</span></td>
                    <td><b>{l_item['qte']}</b></td>
                    <td style="white-space:nowrap;">{l_item['pru']:.2f} {l_item['sym']} ➔ <b>{l_item['prix_jour']:.2f} {l_item['sym']}</b>{badge_jour_l}</td>
                    <td><b>{l_item['val_eur']:,.2f} €</b></td>
                    <td><span class="{b_pv}">{l_item['pv_eur']:+,.2f} € ({l_item['pv_pct']:+.1f}%)</span></td>
                    <td><span style="opacity:0.75;">{l_item['div_brut_l']:.1f} €</span> ➔ <b style="color:#2ecc71;">{l_item['div_net_l']:.2f} € net</b></td>
                    <td>
                        <div style="font-weight:800;">{poids:.1f}%</div>
                        <div class="score-bg"><div style="width:{min(100, poids)}%; background:#3498db; height:100%;"></div></div>
                    </td>
                </tr>
                """
        html_port += "</tbody></table>"
        afficher_html(html_port)

        col_sec, col_hist = st.columns(2)

        with col_sec:
            st.subheader("🍩 Répartition sectorielle du portefeuille")
            secteurs_tries = sorted(repartition_secteurs.items(), key=lambda x: x[1], reverse=True)
            df_camembert = pd.DataFrame([
                {
                    "Secteur": sec,
                    "Montant (€)": round(montant_s, 2),
                    "Poids (%)": round((montant_s / valeur_totale_portefeuille * 100) if valeur_totale_portefeuille > 0 else 0.0, 1),
                }
                for sec, montant_s in secteurs_tries
            ])

            spec_camembert = {
                "height": 310,
                "mark": {"type": "arc", "innerRadius": 55, "outerRadius": 125, "stroke": "#ffffff", "strokeWidth": 2},
                "encoding": {
                    "theta": {"field": "Montant (€)", "type": "quantitative", "stack": True},
                    "color": {
                        "field": "Secteur",
                        "type": "nominal",
                        "scale": {"range": ["#2ecc71", "#3498db", "#9b59b6", "#f1c40f", "#e67e22", "#e74c3c", "#1abc9c", "#34495e", "#fd79a8"]},
                        "legend": {"title": "Secteurs", "orient": "right"},
                    },
                    "tooltip": [
                        {"field": "Secteur", "type": "nominal"},
                        {"field": "Montant (€)", "type": "quantitative", "format": ",.2f"},
                        {"field": "Poids (%)", "type": "quantitative", "format": ".1f"},
                    ],
                },
                "view": {"stroke": None},
            }
            st.vega_lite_chart(df_camembert, spec_camembert, width="stretch")

            html_sec = "<div style='background:rgba(128,128,128,0.04); padding:14px; border-radius:12px; border:1px solid rgba(128,128,128,0.18);'>"
            for row_s in df_camembert.to_dict("records"):
                pct_s = row_s["Poids (%)"]
                c_sec = "#e74c3c" if pct_s > 35 else ("#f39c12" if pct_s > 25 else "#2ecc71")
                html_sec += f"""
                <div style="margin-bottom: 9px;">
                    <div style="display:flex; justify-content:space-between; font-size:0.88em; font-weight:700; margin-bottom:3px;">
                        <span>{row_s['Secteur']}</span>
                        <span>{row_s['Montant (€)']:,.0f} € ({pct_s:.1f}%)</span>
                    </div>
                    <div class="score-bg"><div style="width:{min(100, pct_s)}%; background:{c_sec}; height:100%;"></div></div>
                </div>
                """
            html_sec += "</div>"
            afficher_html(html_sec)

        with col_hist:
            st.subheader("🚀 Trajectoire & Benchmark vs ETF MSCI World (CW8)")
            col_h_rad, col_h_chk = st.columns([2.2, 1.8])
            with col_h_rad:
                choix_horizon_courbe = st.radio(
                    "Horizon boursier :",
                    ["1 Mois", "6 Mois", "1 An", "3 Ans"],
                    index=2,
                    horizontal=True,
                    label_visibility="collapsed",
                )
            with col_h_chk:
                afficher_bench_cw8 = st.checkbox("🌍 Comparer à l'ETF MSCI World (CW8)", value=True)

            map_jours = {"1 Mois": 22, "6 Mois": 126, "1 An": 252, "3 Ans": 750}
            nb_j_cible = map_jours[choix_horizon_courbe]

            longueurs_dispo = [
                len(historiques_prix[nom_a])
                for nom_a in portefeuille_utilisateur
                if nom_a not in CLES_TECHNIQUES_PF and nom_a in historiques_prix and len(historiques_prix[nom_a]) > 1
            ]
            nb_jours_reels = min(nb_j_cible, min(longueurs_dispo)) if longueurs_dispo else 30
            dates_bourse = pd.bdate_range(end=datetime.now(), periods=nb_jours_reels)
            pas_echantillon = 3 if nb_jours_reels > 300 else 1

            _, closes_cw8_brut, _, _ = recuperer_donnees("CW8.PA") if afficher_bench_cw8 else (None, None, None, None)
            serie_cw8 = closes_cw8_brut if closes_cw8_brut else []

            val_esp_fixe = float(portefeuille_utilisateur.get("Espèces", {}).get("pru", 0.0)) if isinstance(portefeuille_utilisateur.get("Espèces"), dict) else 0.0
            donnees_courbe_reelle = []
            valeurs_quotidiennes = []
            valeurs_cw8_rebased = []
            val_depart_pf = None
            cw8_depart = None

            noms_retenus_courbe = [l["nom_act"] for l in lignes_triees if not l["est_especes"]]

            for idx_j in range(0, nb_jours_reels, pas_echantillon):
                offset_fin = idx_j - nb_jours_reels
                val_jour_eur = val_esp_fixe

                for nom_a in noms_retenus_courbe:
                    d_pos = portefeuille_utilisateur.get(nom_a, {})
                    if not isinstance(d_pos, dict) or nom_a not in WATCHLIST_DEFAUT:
                        continue
                    q_a = float(d_pos.get("qte", 0.0))
                    dev_a = WATCHLIST_DEFAUT[nom_a].get("devise", "EUR")
                    fact_a = (1.0 / TAUX_USD_EUR) if dev_a == "USD" else 1.0
                    serie_c = historiques_prix.get(nom_a, [])
                    if serie_c:
                        p_hist = serie_c[offset_fin] if abs(offset_fin) <= len(serie_c) else serie_c[0]
                    else:
                        p_hist = float(prix_temps_reel.get(nom_a, d_pos.get("pru", 0.0)))
                    val_jour_eur += q_a * p_hist * fact_a

                if idx_j >= nb_jours_reels - pas_echantillon:
                    val_jour_eur = valeur_totale_portefeuille

                if val_depart_pf is None:
                    val_depart_pf = max(1.0, val_jour_eur)
                    if serie_cw8:
                        cw8_depart = serie_cw8[offset_fin] if abs(offset_fin) <= len(serie_cw8) else serie_cw8[0]

                date_iso = dates_bourse[idx_j].strftime("%Y-%m-%d")
                date_fr = dates_bourse[idx_j].strftime("%d/%m/%Y")
                ecart_pru_jour = round(val_jour_eur - cout_total_achat, 2)
                valeurs_quotidiennes.append((date_fr, round(val_jour_eur, 2)))

                donnees_courbe_reelle.append({
                    "Date": date_iso,
                    "DateFR": date_fr,
                    "Série": "Valorisation Portefeuille (€)",
                    "Montant (€)": round(val_jour_eur, 2),
                    "Écart vs PRU (€)": ecart_pru_jour,
                })
                donnees_courbe_reelle.append({
                    "Date": date_iso,
                    "DateFR": date_fr,
                    "Série": "Capital Investi / PRU (€)",
                    "Montant (€)": round(cout_total_achat, 2),
                    "Écart vs PRU (€)": ecart_pru_jour,
                })

                if afficher_bench_cw8 and serie_cw8 and cw8_depart and cw8_depart > 0:
                    p_cw8_j = serie_cw8[offset_fin] if abs(offset_fin) <= len(serie_cw8) else serie_cw8[0]
                    val_cw8_eq = val_depart_pf * (p_cw8_j / cw8_depart)
                    valeurs_cw8_rebased.append(val_cw8_eq)
                    donnees_courbe_reelle.append({
                        "Date": date_iso,
                        "DateFR": date_fr,
                        "Série": "Benchmark ETF MSCI World CW8 (€)",
                        "Montant (€)": round(val_cw8_eq, 2),
                        "Écart vs PRU (€)": round(val_cw8_eq - cout_total_achat, 2),
                    })

            df_courbe_reelle = pd.DataFrame(donnees_courbe_reelle)
            domain_series = ["Valorisation Portefeuille (€)", "Capital Investi / PRU (€)"]
            range_colors = ["#2ecc71", "#3498db"]
            range_dash = [[1, 0], [6, 4]]
            range_width = [2.8, 2.0]
            if afficher_bench_cw8 and valeurs_cw8_rebased:
                domain_series.append("Benchmark ETF MSCI World CW8 (€)")
                range_colors.append("#9b59b6")
                range_dash.append([3, 3])
                range_width.append(2.2)

            spec_courbe_bourse = {
                "height": 275,
                "layer": [
                    {
                        "mark": {"type": "line", "interpolate": "monotone"},
                        "encoding": {
                            "x": {"field": "Date", "type": "temporal", "axis": {"title": None, "format": "%b %Y", "grid": False}},
                            "y": {"field": "Montant (€)", "type": "quantitative", "scale": {"zero": False, "padding": 18}, "axis": {"title": "Valeur (€)", "format": ",.0f"}},
                            "color": {
                                "field": "Série",
                                "type": "nominal",
                                "scale": {"domain": domain_series, "range": range_colors},
                                "legend": {"orient": "top", "title": None},
                            },
                            "strokeDash": {
                                "field": "Série",
                                "type": "nominal",
                                "scale": {"domain": domain_series, "range": range_dash},
                                "legend": None,
                            },
                            "strokeWidth": {
                                "field": "Série",
                                "type": "nominal",
                                "scale": {"domain": domain_series, "range": range_width},
                                "legend": None,
                            },
                            "tooltip": [
                                {"field": "DateFR", "type": "nominal", "title": "Séance du"},
                                {"field": "Série", "type": "nominal", "title": "Courbe"},
                                {"field": "Montant (€)", "type": "quantitative", "format": ",.2f", "title": "Montant (€)"},
                                {"field": "Écart vs PRU (€)", "type": "quantitative", "format": "+,.2f", "title": "+/- Value vs PRU (€)"},
                            ],
                        },
                    },
                ],
                "view": {"stroke": None},
            }
            st.vega_lite_chart(df_courbe_reelle, spec_courbe_bourse, width="stretch")

            if valeurs_quotidiennes:
                pt_debut = valeurs_quotidiennes[0]
                pt_fin = valeurs_quotidiennes[-1]
                var_periode_eur = pt_fin[1] - pt_debut[1]
                var_periode_pct = (var_periode_eur / pt_debut[1] * 100.0) if pt_debut[1] > 0 else 0.0
                c_var_p = "#2ecc71" if var_periode_eur >= 0 else "#e74c3c"

                pic_courant = valeurs_quotidiennes[0][1]
                max_dd_pct = 0.0
                for _, v_j in valeurs_quotidiennes:
                    if v_j > pic_courant:
                        pic_courant = v_j
                    dd_j = ((v_j - pic_courant) / pic_courant * 100.0) if pic_courant > 0 else 0.0
                    if dd_j < max_dd_pct:
                        max_dd_pct = dd_j

                if valeurs_cw8_rebased and len(valeurs_cw8_rebased) >= 2:
                    perf_cw8_pct = ((valeurs_cw8_rebased[-1] - valeurs_cw8_rebased[0]) / valeurs_cw8_rebased[0] * 100.0) if valeurs_cw8_rebased[0] > 0 else 0.0
                    alpha_pct = var_periode_pct - perf_cw8_pct
                    c_alpha = "#2ecc71" if alpha_pct >= 0 else "#f39c12"
                    ligne_bench_html = (
                        f"<div style='display:flex; justify-content:space-between; padding:5px 0; border-bottom:1px solid rgba(128,128,128,0.12); font-size:0.88em;'>"
                        f"<span>🌍 <b>ETF MSCI World (CW8)</b> sur {choix_horizon_courbe}</span>"
                        f"<span style='font-weight:800; color:{c_alpha};'>CW8 : {perf_cw8_pct:+.1f}% (Alpha : {alpha_pct:+.1f}%)</span>"
                        f"</div>"
                    )
                else:
                    ligne_bench_html = ""

                html_bilan_traj = f"""
                <div style="background:rgba(128,128,128,0.04); padding:14px; border-radius:12px; border:1px solid rgba(128,128,128,0.18);">
                    <div style="font-size:0.82em; font-weight:800; text-transform:uppercase; opacity:0.75; margin-bottom:9px;">⚡ Indicateurs Quantitatifs sur {choix_horizon_courbe}</div>
                    <div style="display:flex; justify-content:space-between; padding:5px 0; border-bottom:1px solid rgba(128,128,128,0.12); font-size:0.88em;">
                        <span>📈 <b>Performance Portefeuille ({choix_horizon_courbe})</b></span>
                        <span style="color:{c_var_p}; font-weight:800;">{var_periode_eur:+,.0f} € ({var_periode_pct:+.1f}%)</span>
                    </div>
                    {ligne_bench_html}
                    <div style="display:flex; justify-content:space-between; padding:5px 0; border-bottom:1px solid rgba(128,128,128,0.12); font-size:0.88em;">
                        <span>🛡️ <b>Max Drawdown</b> (Repli max sur la période)</span>
                        <span style="color:#3498db; font-weight:800;">{max_dd_pct:.1f}%</span>
                    </div>
                    <div style="display:flex; justify-content:space-between; padding:5px 0; font-size:0.88em;">
                        <span>🎯 <b>Écart actuel vs PRU ({cout_total_achat:,.0f} €)</b></span>
                        <span style="color:{c_pv}; font-weight:800;">{plus_value_globale:+,.0f} € ({plus_value_pct:+.1f}%)</span>
                    </div>
                </div>
                """
                afficher_html(html_bilan_traj)

        # ======================================================================
        # ÉVOLUTION RÉELLE DU PORTEFEUILLE (SNAPSHOTS ENREGISTRÉS À CHAQUE SAUVEGARDE)
        # ======================================================================
        if supabase and st.session_state.get("user") is not None:
            with st.expander("📈 Évolution réelle de mon portefeuille (historique de mes sauvegardes)", expanded=True):
                if mode_gratuit:
                    afficher_verrou_saas(
                        "Évolution réelle du portefeuille (historique jour par jour)",
                        "⚡ Offre Premium (4,90 €/mois) ou 👑 Pro (8,90 €/mois)",
                        "Suivez la vraie trajectoire de votre patrimoine, versements et plus-values séparés."
                    )
                else:
                    uid_hist = str(st.session_state["user"].id)
                    cache_hist = st.session_state.get("_historique_snapshots")
                    if not isinstance(cache_hist, dict) or cache_hist.get("uid") != uid_hist:
                        try:
                            rep_hist = (
                                supabase.table("portfolio_history")
                                .select("date, capital_investi, valorisation_pea, rente_annuelle")
                                .eq("user_id", uid_hist)
                                .order("date")
                                .execute()
                            )
                            cache_hist = {"uid": uid_hist, "lignes": list(rep_hist.data or []), "erreur": False}
                        except Exception:
                            cache_hist = {"uid": uid_hist, "lignes": [], "erreur": True}
                        st.session_state["_historique_snapshots"] = cache_hist

                    points_hist = []
                    for ligne_h in cache_hist.get("lignes", []):
                        try:
                            points_hist.append({
                                "date": str(ligne_h.get("date", ""))[:10],
                                "valo": float(ligne_h.get("valorisation_pea") or 0.0),
                                "capital": float(ligne_h.get("capital_investi") or 0.0),
                                "rente": float(ligne_h.get("rente_annuelle") or 0.0),
                            })
                        except Exception:
                            continue
                    points_hist = sorted((pt for pt in points_hist if len(pt["date"]) == 10 and pt["valo"] > 0), key=lambda pt: pt["date"])

                    if cache_hist.get("erreur"):
                        st.info("L'historique n'a pas pu être lu pour le moment.")
                        if st.button("🔄 Réessayer", key="btn_relire_historique"):
                            st.session_state.pop("_historique_snapshots", None)
                            st.rerun()
                    elif len(points_hist) < 2:
                        st.info(
                            "Votre historique se construit tout seul : un point est enregistré chaque jour où vous sauvegardez "
                            "votre portefeuille. La courbe apparaîtra dès le deuxième jour enregistré."
                        )
                    else:
                        choix_periode_hist = st.radio(
                            "Période affichée :",
                            ["3 mois", "1 an", "Tout l'historique"],
                            index=2,
                            horizontal=True,
                            key="rad_periode_historique",
                        )
                        if choix_periode_hist != "Tout l'historique":
                            nb_jours_hist = 92 if choix_periode_hist == "3 mois" else 366
                            date_min_hist = (pd.Timestamp(points_hist[-1]["date"]) - pd.Timedelta(days=nb_jours_hist)).strftime("%Y-%m-%d")
                            points_periode = [pt for pt in points_hist if pt["date"] >= date_min_hist]
                            if len(points_periode) < 2:
                                points_periode = points_hist[-2:]
                        else:
                            points_periode = points_hist

                        pt_deb, pt_fin = points_periode[0], points_periode[-1]
                        delta_valo_h = pt_fin["valo"] - pt_deb["valo"]
                        delta_capital_h = pt_fin["capital"] - pt_deb["capital"]
                        gain_marche_h = delta_valo_h - delta_capital_h
                        gain_marche_pct_h = (gain_marche_h / pt_deb["valo"] * 100.0) if pt_deb["valo"] > 0 else 0.0
                        delta_rente_h = pt_fin["rente"] - pt_deb["rente"]
                        c_gain_h = "#2ecc71" if gain_marche_h >= 0 else "#e74c3c"
                        date_deb_fr = f"{pt_deb['date'][8:10]}/{pt_deb['date'][5:7]}/{pt_deb['date'][0:4]}"

                        afficher_html(f"""
                        <div class="argon-grid">
                            <div class="argon-card">
                                <div class="argon-title">💼 Valorisation enregistrée</div>
                                <div class="argon-val">{pt_fin['valo']:,.2f} €</div>
                                <div class="argon-sub">Depuis le {date_deb_fr} : <b>{delta_valo_h:+,.0f} €</b></div>
                            </div>
                            <div class="argon-card">
                                <div class="argon-title">💶 Versements sur la période</div>
                                <div class="argon-val" style="color:#3498db;">{delta_capital_h:+,.0f} €</div>
                                <div class="argon-sub">Capital investi : <b>{pt_fin['capital']:,.0f} €</b></div>
                            </div>
                            <div class="argon-card">
                                <div class="argon-title">📈 Gain dû aux marchés</div>
                                <div class="argon-val" style="color:{c_gain_h};">{gain_marche_h:+,.0f} €</div>
                                <div class="argon-sub" style="color:{c_gain_h};">Hors versements : <b>{gain_marche_pct_h:+.1f}%</b></div>
                            </div>
                            <div class="argon-card">
                                <div class="argon-title">💰 Rente annuelle</div>
                                <div class="argon-val" style="color:#2ecc71;">{pt_fin['rente']:,.0f} € / an</div>
                                <div class="argon-sub">Évolution : <b>{delta_rente_h:+,.0f} € / an</b></div>
                            </div>
                        </div>
                        """)

                        donnees_hist_graph = []
                        for pt in points_periode:
                            date_fr_h = f"{pt['date'][8:10]}/{pt['date'][5:7]}/{pt['date'][0:4]}"
                            donnees_hist_graph.append({"Date": pt["date"], "DateFR": date_fr_h, "Série": "Valorisation réelle (€)", "Montant (€)": round(pt["valo"], 2)})
                            donnees_hist_graph.append({"Date": pt["date"], "DateFR": date_fr_h, "Série": "Capital investi (€)", "Montant (€)": round(pt["capital"], 2)})
                        series_hist = ["Valorisation réelle (€)", "Capital investi (€)"]
                        st.vega_lite_chart(
                            pd.DataFrame(donnees_hist_graph),
                            {
                                "height": 300,
                                "mark": {"type": "line", "interpolate": "monotone", "point": len(points_periode) <= 40},
                                "encoding": {
                                    "x": {"field": "Date", "type": "temporal", "axis": {"title": None, "format": "%d/%m/%y", "grid": False}},
                                    "y": {"field": "Montant (€)", "type": "quantitative", "scale": {"zero": False, "padding": 18}, "axis": {"title": "Valeur (€)", "format": ",.0f"}},
                                    "color": {"field": "Série", "type": "nominal", "scale": {"domain": series_hist, "range": ["#2ecc71", "#3498db"]}, "legend": {"orient": "top", "title": None}},
                                    "strokeDash": {"field": "Série", "type": "nominal", "scale": {"domain": series_hist, "range": [[1, 0], [6, 4]]}, "legend": None},
                                    "tooltip": [
                                        {"field": "DateFR", "type": "nominal", "title": "Sauvegarde du"},
                                        {"field": "Série", "type": "nominal", "title": "Courbe"},
                                        {"field": "Montant (€)", "type": "quantitative", "format": ",.2f"},
                                    ],
                                },
                                "view": {"stroke": None},
                            },
                            width="stretch",
                        )
                        st.caption(
                            f"{len(points_hist)} jour(s) enregistré(s). Contrairement à la trajectoire simulée ci-dessus, cette courbe "
                            "reflète vos vraies valorisations, versements et ventes inclus, telles qu'enregistrées à chaque sauvegarde."
                        )

        # ======================================================================
        # PERFORMANCE RÉELLE (TRI) COMPARÉE À UN ETF MSCI WORLD AVEC LES MÊMES VERSEMENTS
        # ======================================================================
        with st.expander("🏁 Ma performance réelle comparée à un ETF MSCI World (mêmes versements, mêmes dates)", expanded=False):
            if not est_premium_ou_pro:
                afficher_verrou_saas(
                    "Performance réelle annualisée comparée à un ETF MSCI World",
                    "⚡ Offre Premium (4,90 €/mois) ou 👑 Pro (8,90 €/mois)",
                    "Votre vrai rendement annualisé, comparé à ce qu'auraient donné les mêmes sommes, aux mêmes dates, dans un ETF Monde."
                )
            else:
                pf_perf = st.session_state["portefeuille"]
                journal_perf = pf_perf.get("_journal_achats") if isinstance(pf_perf.get("_journal_achats"), list) else []
                ventes_perf = [v for v in st.session_state.get("historique_ventes", []) if isinstance(v, dict)]
                aujourd_hui_iso = datetime.now().date().isoformat()

                achats_par_action = {}
                for entree_p in journal_perf:
                    achats_par_action.setdefault(entree_p.get("action"), []).append(entree_p)

                flux_perf, lignes_perf, exclusions_perf = [], [], []
                for action_p, entrees_p in sorted(achats_par_action.items()):
                    entrees_p = sorted(entrees_p, key=lambda e: (str(e.get("date", "")), str(e.get("id", ""))))
                    info_p = WATCHLIST_DEFAUT.get(action_p, {})
                    est_usd_p = info_p.get("devise") == "USD"
                    if int((entrees_p[0].get("avant") or {}).get("qte", 0) or 0) > 0:
                        exclusions_perf.append((action_p, "détenue avant votre premier achat enregistré dans le journal"))
                        continue
                    date_debut_p = str(entrees_p[0].get("date", ""))
                    ventes_p = [v for v in ventes_perf if v.get("action") == action_p and str(v.get("date", "")) >= date_debut_p]
                    qte_attendue_p = sum(int(e.get("qte", 0)) for e in entrees_p) - sum(int(v.get("qte", 0)) for v in ventes_p)
                    position_p = pf_perf.get(action_p)
                    qte_actuelle_p = int(position_p.get("qte", 0)) if isinstance(position_p, dict) else 0
                    if qte_actuelle_p != qte_attendue_p:
                        exclusions_perf.append((action_p, "quantité modifiée en dehors du journal et des ventes"))
                        continue
                    if qte_actuelle_p > 0 and action_p not in prix_temps_reel:
                        exclusions_perf.append((action_p, "cours du jour indisponible"))
                        continue
                    historique_p = historique_long(info_p.get("symbole", "")) if info_p.get("symbole") else None
                    if historique_p is None:
                        exclusions_perf.append((action_p, "historique de cours indisponible"))
                        continue

                    mouvements_p = []
                    for e in entrees_p:
                        taux_e = float(e.get("taux_change") or TAUX_USD_EUR) if est_usd_p else 1.0
                        montant_e = float(e.get("qte", 0)) * float(e.get("prix", 0)) / taux_e + float(e.get("frais_eur", 0) or 0)
                        flux_perf.append((str(e["date"]), -montant_e, "Achat"))
                        mouvements_p.append((str(e["date"]), int(e.get("qte", 0))))
                    for v in ventes_p:
                        flux_perf.append((str(v["date"]), float(v.get("montant_eur", 0) or 0), "Vente"))
                        mouvements_p.append((str(v["date"]), -int(v.get("qte", 0))))
                    facteur_dividende_p = (0.70 / TAUX_USD_EUR) if est_usd_p else 1.0
                    for date_div, montant_div in historique_p[2]:
                        if date_debut_p < date_div <= aujourd_hui_iso:
                            qte_au_detachement = sum(q for d, q in mouvements_p if d < date_div)
                            if qte_au_detachement > 0:
                                flux_perf.append((date_div, qte_au_detachement * montant_div * facteur_dividende_p, "Dividende"))
                    facteur_valeur_p = (1.0 / TAUX_USD_EUR) if est_usd_p else 1.0
                    lignes_perf.append({
                        "action": action_p, "mouvements": mouvements_p, "historique": historique_p, "facteur": facteur_valeur_p,
                        "valeur_finale": qte_actuelle_p * float(prix_temps_reel.get(action_p, 0.0)) * facteur_valeur_p,
                    })

                historique_etf = historique_long("CW8.PA")
                if not lignes_perf:
                    st.info(
                        "Pour calculer votre performance réelle, Boursy a besoin de l'historique complet d'au moins une ligne : "
                        "tous ses achats enregistrés dans le 🧾 Journal des achats (saisie, import CSV ou import par l'IA), depuis le premier."
                    )
                elif historique_etf is None:
                    st.warning("L'historique de l'ETF MSCI World (CW8) est indisponible pour le moment. Réessayez dans quelques minutes.")
                else:
                    flux_perf.sort(key=lambda f: f[0])
                    date_premier_flux = flux_perf[0][0]
                    # L'ETF reçoit exactement les mêmes versements et retraits, aux mêmes dates (méthode PME de Long et Nickels)
                    parts_etf, flux_etf_dates = 0.0, []
                    for date_f, montant_f, _ in flux_perf:
                        cours_etf = cours_a_la_date(historique_etf, date_f) or historique_etf[1][0]
                        parts_etf -= montant_f / cours_etf
                        flux_etf_dates.append((date_f, parts_etf))
                    valeur_portefeuille_perf = sum(l["valeur_finale"] for l in lignes_perf)
                    valeur_etf_perf = parts_etf * historique_etf[1][-1]
                    tri_portefeuille = taux_rendement_interne([(d, m) for d, m, _ in flux_perf] + [(aujourd_hui_iso, valeur_portefeuille_perf)])
                    tri_etf = taux_rendement_interne([(d, m) for d, m, _ in flux_perf] + [(aujourd_hui_iso, valeur_etf_perf)])
                    total_verse = -sum(m for _, m, n in flux_perf if n == "Achat")
                    total_ventes = sum(m for _, m, n in flux_perf if n == "Vente")
                    total_dividendes = sum(m for _, m, n in flux_perf if n == "Dividende")
                    gain_portefeuille = valeur_portefeuille_perf + total_ventes + total_dividendes - total_verse
                    ecart_valeur = valeur_portefeuille_perf - valeur_etf_perf
                    duree_jours = (datetime.now().date() - datetime.fromisoformat(date_premier_flux).date()).days
                    c_tri = "#2ecc71" if (tri_portefeuille or 0) >= 0 else "#e74c3c"
                    c_ecart = "#2ecc71" if ecart_valeur >= 0 else "#f39c12"
                    texte_tri = f"{tri_portefeuille * 100:+.2f} % / an" if tri_portefeuille is not None else "Non calculable"
                    texte_tri_etf = f"{tri_etf * 100:+.2f} % / an" if tri_etf is not None else "Non calculable"
                    texte_ecart_tri = (f"{(tri_portefeuille - tri_etf) * 100:+.2f} point(s) par an"
                                       if (tri_portefeuille is not None and tri_etf is not None) else "—")
                    date_premier_fr = f"{date_premier_flux[8:10]}/{date_premier_flux[5:7]}/{date_premier_flux[0:4]}"

                    afficher_html(f"""
                    <div class="argon-grid">
                        <div class="argon-card" style="border-top: 3px solid {c_tri};">
                            <div class="argon-title">🏁 Votre rendement annualisé</div>
                            <div class="argon-val" style="color:{c_tri};">{texte_tri}</div>
                            <div class="argon-sub">Gain total : <b>{gain_portefeuille:+,.0f} €</b> depuis le {date_premier_fr}</div>
                        </div>
                        <div class="argon-card" style="border-top: 3px solid #3498db;">
                            <div class="argon-title">🌍 Mêmes versements dans le CW8</div>
                            <div class="argon-val" style="color:#3498db;">{texte_tri_etf}</div>
                            <div class="argon-sub">Valeur aujourd'hui : <b>{valeur_etf_perf:,.0f} €</b></div>
                        </div>
                        <div class="argon-card" style="border-top: 3px solid {c_ecart};">
                            <div class="argon-title">⚖️ Écart avec l'ETF</div>
                            <div class="argon-val" style="color:{c_ecart};">{ecart_valeur:+,.0f} €</div>
                            <div class="argon-sub">Soit <b>{texte_ecart_tri}</b></div>
                        </div>
                        <div class="argon-card" style="border-top: 3px solid #9b59b6;">
                            <div class="argon-title">💶 Vos flux</div>
                            <div class="argon-val" style="font-size:1.2em;">{total_verse:,.0f} € versés</div>
                            <div class="argon-sub">Ventes : <b>{total_ventes:,.0f} €</b> · Dividendes estimés : <b>{total_dividendes:,.0f} €</b></div>
                        </div>
                    </div>
                    """)
                    if duree_jours < 365:
                        st.caption("⚠️ Sur moins d'un an, le rendement annualisé est très sensible aux variations récentes : regardez surtout l'écart en euros.")

                    # Courbe mensuelle : valeur des lignes retenues, valeur de l'ETF avec les mêmes flux, argent investi net
                    points_courbe = sorted(set(
                        [d.date().isoformat() for d in pd.date_range(date_premier_flux, aujourd_hui_iso, freq="MS")]
                        + [date_premier_flux, aujourd_hui_iso]
                    ))
                    donnees_courbe_perf = []
                    for date_c in points_courbe:
                        investi_net = -sum(m for d, m, n in flux_perf if d <= date_c and n in ("Achat", "Vente"))
                        if date_c == aujourd_hui_iso:
                            valeur_pf_c = valeur_portefeuille_perf
                        else:
                            valeur_pf_c = sum(
                                sum(q for d, q in l["mouvements"] if d <= date_c) * (cours_a_la_date(l["historique"], date_c) or 0.0) * l["facteur"]
                                for l in lignes_perf
                            )
                        parts_c = next((p for d, p in reversed(flux_etf_dates) if d <= date_c), 0.0)
                        valeur_etf_c = parts_c * (cours_a_la_date(historique_etf, date_c) or 0.0)
                        date_fr_c = f"{date_c[8:10]}/{date_c[5:7]}/{date_c[0:4]}"
                        for serie_c, valeur_c in (("Vos lignes (€)", valeur_pf_c), ("Mêmes versements dans le CW8 (€)", valeur_etf_c), ("Argent investi net (€)", investi_net)):
                            donnees_courbe_perf.append({"Date": date_c, "DateFR": date_fr_c, "Série": serie_c, "Montant (€)": round(valeur_c, 2)})
                    series_perf = ["Vos lignes (€)", "Mêmes versements dans le CW8 (€)", "Argent investi net (€)"]
                    st.vega_lite_chart(
                        pd.DataFrame(donnees_courbe_perf),
                        {
                            "height": 300,
                            "mark": {"type": "line", "interpolate": "monotone"},
                            "encoding": {
                                "x": {"field": "Date", "type": "temporal", "axis": {"title": None, "format": "%m/%y", "grid": False}},
                                "y": {"field": "Montant (€)", "type": "quantitative", "scale": {"zero": False, "padding": 18}, "axis": {"title": "Valeur (€)", "format": ",.0f"}},
                                "color": {"field": "Série", "type": "nominal", "scale": {"domain": series_perf, "range": ["#2ecc71", "#3498db", "#95a5a6"]}, "legend": {"orient": "top", "title": None, "labelLimit": 320}},
                                "strokeDash": {"field": "Série", "type": "nominal", "scale": {"domain": series_perf, "range": [[1, 0], [6, 3], [2, 3]]}, "legend": None},
                                "tooltip": [
                                    {"field": "DateFR", "type": "nominal", "title": "Date"},
                                    {"field": "Série", "type": "nominal", "title": "Courbe"},
                                    {"field": "Montant (€)", "type": "quantitative", "format": ",.2f"},
                                ],
                            },
                            "view": {"stroke": None},
                        },
                        width="stretch",
                    )

                    texte_lignes = ", ".join(l["action"] for l in lignes_perf)
                    st.caption(nombres_fr(
                        f"Calcul sur {len(lignes_perf)} ligne(s) dont tout l'historique est dans le journal : {texte_lignes} "
                        f"({valeur_portefeuille_perf:,.0f} € aujourd'hui)."
                    ))
                    if exclusions_perf:
                        st.caption(
                            "Lignes non prises en compte : "
                            + " ; ".join(f"{a} ({motif})" for a, motif in exclusions_perf)
                            + ". Pour inclure une ligne détenue avant le journal, enregistrez tous ses achats depuis le premier "
                              "(par exemple en remettant sa quantité à 0, puis en important l'historique de votre courtier)."
                        )
                    st.caption(
                        "Méthode : rendement annualisé (taux de rendement interne) calculé sur vos flux réels. L'ETF Amundi MSCI World (CW8) "
                        "reçoit exactement les mêmes versements et retraits, aux mêmes dates. Dividendes estimés d'après l'historique Yahoo "
                        "(nets de 30 % pour les actions américaines), comptés à leur date de détachement ; lignes en dollars valorisées au taux "
                        "du jour. Les performances passées ne préjugent pas des performances futures."
                    )

        # ======================================================================
        # COMPTEUR OFFICIEL PLAFOND PEA (150 000 €) & RICHESSE TOTALE CRÉÉE
        # ======================================================================
        st.markdown("<div style='margin-top:18px;'></div>", unsafe_allow_html=True)
        total_pv_actees_pf = sum(float(v.get("plus_value_eur", 0.0)) for v in st.session_state.get("historique_ventes", []))
        div_encaisses_cumul = float(st.session_state.get("dividendes_encaisses_cumul", 0.0))
        # Plafond PEA : seules les plus-values actées DANS le PEA (ventes en €) réduisent les versements estimés.
        # Cette valeur est réutilisée telle quelle par la carte « Plafond Légal PEA » plus bas dans l'onglet.
        pv_actees_pea_pf = sum(
            float(v.get("plus_value_eur", 0.0))
            for v in st.session_state.get("historique_ventes", [])
            if v.get("devise", "€") != "$"
        )
        capital_autofinance = max(0.0, pv_actees_pea_pf + div_encaisses_cumul)
        cout_pru_pea_seul = sum(l["cout_eur"] for l in lignes_triees if l["devise"] == "EUR")
        versements_nets_pea = max(0.0, cout_pru_pea_seul - capital_autofinance)
        plafond_legal_pea = 150000.0
        pct_plafond_pea = min(100.0, (versements_nets_pea / plafond_legal_pea) * 100.0)
        marge_restante_pea = max(0.0, plafond_legal_pea - versements_nets_pea)

        # Richesse réellement créée : plus-values latentes + plus-values actées + dividendes DÉJÀ encaissés
        # (et non la rente annuelle prévue, qui n'a pas encore été perçue)
        richesse_totale_creee = plus_value_globale + total_pv_actees_pf + div_encaisses_cumul
        tri_global_pct = (richesse_totale_creee / cout_total_achat * 100.0) if cout_total_achat > 0 else 0.0
        c_rich = "#2ecc71" if richesse_totale_creee >= 0 else "#e74c3c"

        html_pea_tri = f"""
        <div class="argon-grid" style="margin-bottom: 18px;">
            <div class="argon-card" style="text-align:left; border-left: 4px solid #3498db;">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <span class="argon-title" style="color:#3498db; margin:0;">🏛️ Jauge Officielle Plafond PEA (150 000 €)</span>
                    <span class="b-blue">{pct_plafond_pea:.1f}% utilisé</span>
                </div>
                <div class="score-bg" style="height:10px; margin:8px 0;">
                    <div style="width:{max(2.0, pct_plafond_pea)}%; background:linear-gradient(90deg, #3498db, #2ecc71); height:100%;"></div>
                </div>
                <div style="display:flex; justify-content:space-between; font-size:0.82em; opacity:0.9;">
                    <span>Versements nets estimés : <b>{versements_nets_pea:,.0f} €</b></span>
                    <span>Marge de versement restante : <b>{marge_restante_pea:,.0f} €</b></span>
                </div>
            </div>
            <div class="argon-card" style="text-align:left; border-left: 4px solid {c_rich};">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <span class="argon-title" style="color:{c_rich}; margin:0;">🏆 Richesse Totale Créée (Latent + Acté + Dividendes encaissés)</span>
                    <span class="{'b-green' if richesse_totale_creee >= 0 else 'b-red'}">Rendement Global : {tri_global_pct:+.1f}%</span>
                </div>
                <div style="font-size:1.35em; font-weight:900; color:{c_rich}; margin:4px 0;">{richesse_totale_creee:+,.2f} €</div>
                <div style="font-size:0.80em; opacity:0.85;">
                    PV Latente : <b>{plus_value_globale:+,.0f} €</b> | PV Actées : <b>{total_pv_actees_pf:+,.0f} €</b> | Dividendes encaissés : <b style="color:#2ecc71;">+{div_encaisses_cumul:,.0f} €</b> <span style="opacity:0.75;">(rente prévue : {dividendes_nets_totaux_eur:,.0f} €/an, non comptée)</span>
                </div>
            </div>
        </div>
        """
        afficher_html(html_pea_tri)

        # ======================================================================
        # MODULE PRIME DE FIDÉLITÉ NOMINATIF ADMINISTRÉ (+10% & ACTIONS GRATUITES)
        # ======================================================================
        bonus_annuel_nom = 0.0
        texte_al = ""
        eligibles_nom_pf = [
            k for k in portefeuille_utilisateur.keys()
            if k in ("Air Liquide", "L'Oréal", "Engie", "Seb", "Crédit Agricole")
            and isinstance(portefeuille_utilisateur.get(k), dict)
            and float(portefeuille_utilisateur[k].get("qte", 0)) > 0
        ]
        if eligibles_nom_pf:
            with st.expander("🏅 Prime de Fidélité Nominatif Administré (+10% Dividende & Actions Gratuites Air Liquide)", expanded=False):
                if mode_gratuit:
                    afficher_verrou_saas(
                        "Calculateur Prime de Fidélité Nominatif Administré (+10%) & Actions Gratuites",
                        "⚡ Offre Premium (4,90 €/mois) ou 👑 Pro (8,90 €/mois)",
                        "Simulez vos primes de fidélité +10% et vos paliers d'attribution d'actions gratuites Air Liquide."
                    )
                else:
                    if "actions_nominatif" not in st.session_state:
                        st.session_state["actions_nominatif"] = eligibles_nom_pf.copy()
                    selection_nom = st.multiselect(
                        "Sélectionnez vos lignes passées au Nominatif Administré (+10% de bonus dividende après 2 années civiles) :",
                        options=eligibles_nom_pf,
                        default=[a for a in st.session_state["actions_nominatif"] if a in eligibles_nom_pf],
                        key="ms_actions_nominatif",
                    )
                    st.session_state["actions_nominatif"] = selection_nom

                    for act_n in selection_nom:
                        q_n = float(portefeuille_utilisateur[act_n].get("qte", 0))
                        div_n = float(WATCHLIST_DEFAUT.get(act_n, {}).get("div_eur", 0.0))
                        bonus_annuel_nom += q_n * div_n * 0.10

                    if "Air Liquide" in portefeuille_utilisateur and isinstance(portefeuille_utilisateur.get("Air Liquide"), dict) and float(portefeuille_utilisateur["Air Liquide"].get("qte", 0)) > 0:
                        q_al = int(portefeuille_utilisateur["Air Liquide"]["qte"])
                        act_gratuites = q_al // 10
                        manque_al = 10 - (q_al % 10) if (q_al % 10) != 0 else 0
                        cours_al = float(prix_temps_reel.get("Air Liquide", 165.0))
                        val_cadeau_al = act_gratuites * cours_al
                        texte_al = (
                            f" | 🎁 <b>Air Liquide ({q_al} titres)</b> : Droit à <b>{act_gratuites} action(s) gratuite(s)</b> (~{val_cadeau_al:,.0f} €)"
                            + (f" — <i>Plus que {manque_al} action(s) pour débloquer la suivante !</i>" if manque_al > 0 else " — <i>Palier exact de 10 atteint !</i>")
                        )

                    afficher_html(f"""
                    <div style="background:rgba(46,204,113,0.08); border:1px solid rgba(46,204,113,0.35); border-radius:10px; padding:12px 16px; font-size:0.90em;">
                        🏅 <b>Gain de Rente Nominatif (+10%) :</b> <b style="color:#2ecc71;">+{bonus_annuel_nom:.2f} € / an</b> (soit <b>+{bonus_annuel_nom*10:.0f} €</b> sur 10 ans sans apport){texte_al}
                    </div>
                    """)

        # ======================================================================
        # MINI-SIMULATEUR D'IMPACT PRU & RENFORCEMENT DCA (100% ARGON DARK/LIGHT)
        # ======================================================================
        actions_Simu_pru = [
            k for k, v in portefeuille_utilisateur.items()
            if k not in CLES_TECHNIQUES_PF and isinstance(v, dict) and float(v.get("qte", 0)) > 0
        ]
        if actions_Simu_pru:
            st.markdown("#### 🧮 Simulateur Express d'Impact PRU & DCA")
            if mode_gratuit:
                afficher_verrou_saas(
                    "Simulateur Express d'Impact PRU & Renforcement DCA",
                    "⚡ Offre Premium (4,90 €/mois) ou 👑 Pro (8,90 €/mois)",
                    "Calculez instantanément votre nouveau PRU et le gain de dividende annuel avant de passer votre ordre."
                )
            else:
                col_sim1, col_sim2 = st.columns([2, 1])
                with col_sim1:
                    act_choisie = st.selectbox(
                        "Action du portefeuille à renforcer :",
                        actions_Simu_pru,
                        key="simu_pru_action"
                    )
                with col_sim2:
                    budget_simu = st.number_input(
                        "Montant DCA à investir (€) :",
                        min_value=50.0,
                        max_value=50000.0,
                        value=float(BUDGET_MENSUEL),
                        step=50.0,
                        key="simu_pru_budget"
                    )

                pos_act = portefeuille_utilisateur.get(act_choisie, {})
                qte_act = float(pos_act.get("qte", 0.0))
                pru_act = float(pos_act.get("pru", 0.0))
                info_w = st.session_state.get("watchlist", WATCHLIST_DEFAUT).get(act_choisie, WATCHLIST_DEFAUT.get(act_choisie, {}))
                dev_sim = "$" if info_w.get("devise") == "USD" else "€"
                div_unit = float(info_w.get("div_eur", 0.0))
                cours_live = float(st.session_state.get("prix_temps_reel", {}).get(act_choisie, pru_act))

                if cours_live > 0 and qte_act > 0:
                    budget_devise = (budget_simu * TAUX_USD_EUR) if dev_sim == "$" else budget_simu
                    nb_ach = int(budget_devise // cours_live)
                    mode_1_titre = False
                    if nb_ach == 0:
                        nb_ach = 1
                        mode_1_titre = True
                    cout_ordre = nb_ach * cours_live
                    nouv_qte = qte_act + nb_ach
                    nouv_pru = ((qte_act * pru_act) + cout_ordre) / nouv_qte
                    ecart_pru = nouv_pru - pru_act
                    ecart_pru_pct = (ecart_pru / pru_act * 100) if pru_act > 0 else 0.0
                    gain_div_an = nb_ach * div_unit

                    classe_b_pru = "b-green" if ecart_pru <= 0 else "b-blue"
                    col_p = "#2ecc71" if ecart_pru <= 0 else "#3498db"
                    txt_badge = f"📉 PRU abaissé de {ecart_pru:.2f} {dev_sim} ({ecart_pru_pct:+.1f}%)" if ecart_pru <= 0 else f"📈 PRU moyenné à +{ecart_pru:.2f} {dev_sim} ({ecart_pru_pct:+.1f}%)"
                    note_1t = f"(Ajusté à 1 titre = {cout_ordre:.2f} {dev_sim})" if mode_1_titre else f"(Investi : {cout_ordre:.2f} {dev_sim})"

                    html_simu_pru = f"""
                    <div class="argon-card" style="text-align:left; margin-bottom:18px;">
                        <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px;">
                            <div>
                                <div class="argon-title">Ordre simulé au cours actuel ({cours_live:.2f} {dev_sim})</div>
                                <div style="font-size:1.08em; font-weight:900;">+{nb_ach} action(s) {act_choisie} <span style="font-size:0.84em; opacity:0.75; font-weight:600;">{note_1t}</span></div>
                            </div>
                            <div>
                                <div class="argon-title">Trajectoire du PRU</div>
                                <div style="font-size:1.08em; font-weight:900;">{pru_act:.2f} {dev_sim} ➔ <span style="color:{col_p};">{nouv_pru:.2f} {dev_sim}</span></div>
                            </div>
                            <div><span class="{classe_b_pru}">{txt_badge}</span></div>
                            <div><span class="b-green">+{gain_div_an:.2f} {dev_sim} / an de dividendes</span></div>
                        </div>
                    </div>
                    """
                    afficher_html(html_simu_pru)

        # ======================================================================
        # IMPORT MAGIQUE DU PORTEFEUILLE (EXCLUSIF OFFRE PRO 8,90 €)
        # ======================================================================
        def _analyser_ligne_import_ia(item_ext):
            """(action reconnue, quantité, PRU, statut) pour une ligne lue par Gemini."""
            if not isinstance(item_ext, dict):
                return None, 0, 0.0, "Ignorée : ligne illisible"
            nom_lu = re.sub(r"[<>]", "", str(item_ext.get("nom", ""))).strip()
            qte_lue = _nombre_lu(item_ext.get("qte"))
            pru_lu = _nombre_lu(item_ext.get("pru"))
            action_lue = _reconnaitre_action(nom_lu)
            if action_lue is None:
                return None, 0, 0.0, "Ignorée : action non reconnue (ajoutez-la d'abord à votre radar)"
            if not qte_lue or qte_lue <= 0 or pru_lu is None or pru_lu < 0:
                return action_lue, 0, 0.0, "Ignorée : quantité ou PRU illisible"
            return action_lue, int(round(qte_lue)), round(float(pru_lu), 4), "✅ À appliquer"

        def appliquer_import_ia_portefeuille():
            lignes_ext = st.session_state.get("_lignes_extraites_vision", [])
            nb_maj = 0
            for item_ext in lignes_ext:
                nom_e, qte_e, pru_e, _ = _analyser_ligne_import_ia(item_ext)
                if nom_e and qte_e > 0:
                    st.session_state["portefeuille"][nom_e] = construire_position(nom_e, qte_e, pru_e)
                    st.session_state[f"qte_{nom_e}"] = qte_e
                    st.session_state[f"pru_{nom_e}"] = pru_e
                    if nom_e not in st.session_state["watchlist"] and nom_e in WATCHLIST_DEFAUT:
                        st.session_state["watchlist"][nom_e] = WATCHLIST_DEFAUT[nom_e].copy()
                    nb_maj += 1
            st.session_state.pop("_lignes_extraites_vision", None)
            sauvegarder_dans_cloud()
            st.session_state["_notif_import_ia"] = f"✅ {nb_maj} ligne(s) importée(s) et synchronisée(s) dans votre portefeuille !"

        if st.session_state.get("_notif_import_ia"):
            st.success(st.session_state.pop("_notif_import_ia"))

        with st.expander("📸 Import Magique : mettre à jour mes positions actuelles par capture d'écran ou copier-coller (IA Gemini)", expanded=False):
            if not est_pro_max:
                afficher_verrou_saas(
                    "Import Magique IA (Lecture optique de Capture d'Écran & Copier-Coller Courtier)",
                    "👑 Offre Pro (8,90 €/mois)",
                    "Importez ou mettez à jour toutes les lignes et PRU de votre portefeuille en 1 clic grâce à Gemini Vision."
                )
            else:
                st.caption(
                    "Met à jour d'un coup vos positions actuelles (quantité et PRU tels qu'affichés par votre courtier) : "
                    "les lignes lues remplacent celles du portefeuille. Pour garder l'historique de chaque achat avec sa date, "
                    "utilisez plutôt le 🧾 Journal des achats, plus haut."
                )
                mode_imp_ia = st.radio(
                    "Méthode d'importation :",
                    ["📋 Copier-Coller le texte de mon courtier (Ultra-rapide)", "📸 Déposer une Capture d'Écran (PNG / JPG)"],
                    horizontal=True,
                    key="rad_mode_imp_ia",
                )

                cle_gem_vis = ""
                for k_s in ["GEMINI_API_KEY", "GOOGLE_API_KEY", "GEMINI_KEY"]:
                    v_s = _lire_secret(k_s)
                    if v_s:
                        cle_gem_vis = v_s
                        break

                prompt_base_json = (
                    "Extrais chaque ligne d'action détenue dans ce portefeuille boursier. "
                    "Réponds UNIQUEMENT avec un tableau JSON valide de la forme : "
                    '[{"nom": "TotalEnergies", "qte": 25, "pru": 54.20}]. '
                    "Utilise exactement les noms standards du catalogue si tu reconnais l'entreprise "
                    "(ex: TotalEnergies, Air Liquide, AXA, Rubis, LVMH, Sanofi, Engie, Vinci, BNP Paribas, "
                    "Pernod Ricard, Schneider Electric, Veolia, Alphabet - Google, Microsoft, Apple, Realty Income)."
                )

                if "Copier-Coller" in mode_imp_ia:
                    texte_courtier = st.text_area(
                        "Collez ici en vrac les lignes copiées depuis votre courtier (BoursoBank, Crédit Agricole, Fortuneo, Bourse Direct, Excel...) :",
                        placeholder="Exemple : TotalEnergies 25 titres PRU 54,20 € | Engie 40 actions à 15,10 € | Rubis 30 x 24,50 €...",
                        height=100,
                        key="txt_imp_courtier",
                    )
                    if st.button("🤖 Extraire mes positions depuis ce texte", type="primary", key="btn_ext_txt"):
                        if not cle_gem_vis:
                            st.error("⚠️ Clé `GEMINI_API_KEY` absente de vos Secrets Streamlit.")
                        elif not texte_courtier.strip():
                            st.warning("⚠️ Collez d'abord le texte de vos positions ci-dessus.")
                        else:
                            with st.spinner("🧠 Analyse de vos lignes et PRU en cours..."):
                                payload_t = json.dumps({
                                    "contents": [{"parts": [{"text": f"{prompt_base_json}\n\nTexte du portefeuille :\n{texte_courtier}"}]}]
                                }).encode("utf-8")
                                for mod_v in ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-flash-latest"]:
                                    try:
                                        url_v = f"https://generativelanguage.googleapis.com/v1beta/models/{mod_v}:generateContent?key={urllib.parse.quote(cle_gem_vis)}"
                                        req_v = urllib.request.Request(url_v, data=payload_t, headers={"Content-Type": "application/json"})
                                        with urllib.request.urlopen(req_v, timeout=25) as resp_v:
                                            res_v = json.loads(resp_v.read().decode("utf-8"))
                                            txt_v = res_v["candidates"][0]["content"]["parts"][0]["text"]
                                            deb_j, fin_j = txt_v.find("["), txt_v.rfind("]")
                                            if deb_j != -1 and fin_j != -1:
                                                st.session_state["_lignes_extraites_vision"] = json.loads(txt_v[deb_j:fin_j+1])
                                                break
                                    except Exception:
                                        continue
                else:
                    fichier_img = st.file_uploader("Choisir une capture d'écran (PNG, JPG, WEBP)", type=["png", "jpg", "jpeg", "webp"], key="up_vision_pf_v2")
                    if fichier_img is not None:
                        if st.button("🤖 Analyser ma capture d'écran avec Gemini Vision", type="primary", key="btn_ext_img"):
                            if not cle_gem_vis:
                                st.error("⚠️ Clé `GEMINI_API_KEY` absente de vos Secrets Streamlit.")
                            else:
                                import base64
                                with st.spinner("🔍 Lecture optique de vos lignes et PRU en cours..."):
                                    b64_img = base64.b64encode(fichier_img.read()).decode("utf-8")
                                    mime_t = fichier_img.type or "image/jpeg"
                                    payload_v = json.dumps({
                                        "contents": [{
                                            "parts": [
                                                {"text": prompt_base_json},
                                                {"inline_data": {"mime_type": mime_t, "data": b64_img}}
                                            ]
                                        }]
                                    }).encode("utf-8")
                                    for mod_v in ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-flash-latest"]:
                                        try:
                                            url_v = f"https://generativelanguage.googleapis.com/v1beta/models/{mod_v}:generateContent?key={urllib.parse.quote(cle_gem_vis)}"
                                            req_v = urllib.request.Request(url_v, data=payload_v, headers={"Content-Type": "application/json"})
                                            with urllib.request.urlopen(req_v, timeout=25) as resp_v:
                                                res_v = json.loads(resp_v.read().decode("utf-8"))
                                                txt_v = res_v["candidates"][0]["content"]["parts"][0]["text"]
                                                deb_j, fin_j = txt_v.find("["), txt_v.rfind("]")
                                                if deb_j != -1 and fin_j != -1:
                                                    st.session_state["_lignes_extraites_vision"] = json.loads(txt_v[deb_j:fin_j+1])
                                                    break
                                        except Exception:
                                            continue

                if st.session_state.get("_lignes_extraites_vision"):
                    lignes_ext = st.session_state["_lignes_extraites_vision"]
                    apercu_ia = []
                    for item_ext in lignes_ext:
                        action_ia, qte_ia, pru_ia, statut_ia = _analyser_ligne_import_ia(item_ext)
                        apercu_ia.append({
                            "Lu par l'IA": str(item_ext.get("nom", "")) if isinstance(item_ext, dict) else "?",
                            "Action reconnue": action_ia or "—",
                            "Quantité": qte_ia or None,
                            "PRU": pru_ia or None,
                            "Statut": statut_ia,
                        })
                    nb_applicables = sum(1 for a in apercu_ia if a["Statut"].startswith("✅"))
                    st.success(f"✅ {len(lignes_ext)} position(s) détectée(s), dont {nb_applicables} applicable(s).")
                    st.dataframe(pd.DataFrame(apercu_ia), width="stretch", hide_index=True)
                    st.button(
                        "📥 Appliquer ces positions à mon Portefeuille",
                        type="primary",
                        width="stretch",
                        on_click=appliquer_import_ia_portefeuille,
                    )


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
    pf_pack = st.session_state.get("portefeuille", {})
    wl_complet_pack = st.session_state.get("watchlist", WATCHLIST_DEFAUT)
    if mode_gratuit:
        wl_pack = {k: v for k, v in wl_complet_pack.items() if k in actions_autorisees}
    else:
        wl_pack = wl_complet_pack

    prix_tr_pack = st.session_state.get("prix_temps_reel", {})
    hist_ventes_pack = st.session_state.get("historique_ventes", [])
    liste_t1_pack = globals().get("donnees_t1", [])
    hist_prix_pack = globals().get("historiques_prix", {})
    budget_dca_pack = float(st.session_state.get("budget_dca", st.session_state.get("budget_mensuel", 450.0)))

    # --- EXTRACTEUR UNIVERSEL DE DIVIDENDES ET DE MOIS DE VERSEMENT ---
    def _extraire_infos_div_et_mois(nom_act, cours_actuel):
        inf_def = WATCHLIST_DEFAUT.get(nom_act, {})
        inf_usr = wl_complet_pack.get(nom_act, {})
        inf = {}
        if isinstance(inf_def, dict):
            inf.update(inf_def)
        if isinstance(inf_usr, dict):
            inf.update(inf_usr)

        div_val = 0.0
        for k_d in ("div_eur", "dividende", "div", "div_annuel", "dividende_eur", "coupon", "montant_div", "div_brut"):
            if inf.get(k_d) is not None:
                try:
                    v_d = float(str(inf.get(k_d)).replace("€", "").replace("$", "").replace(",", ".").strip())
                    if v_d > 0:
                        div_val = v_d
                        break
                except Exception:
                    pass

        if div_val <= 0 and cours_actuel > 0:
            for k_r in ("rendement", "rdt", "yield", "rendement_pct", "div_pct"):
                if inf.get(k_r) is not None:
                    try:
                        v_r = float(str(inf.get(k_r)).replace("%", "").replace(",", ".").strip())
                        if v_r > 0:
                            div_val = round(cours_actuel * (v_r / 100.0), 2)
                            break
                    except Exception:
                        pass

        raw_m = None
        for k_m in ("mois", "mois_div", "mois_versement", "mois_detachement", "mois_paiement", "versements", "calendrier", "dates_div"):
            if inf.get(k_m) is not None and inf.get(k_m) != [] and inf.get(k_m) != "":
                raw_m = inf.get(k_m)
                break
        if raw_m is None and isinstance(inf_def, dict):
            for k_m in ("mois", "mois_div", "mois_versement", "mois_detachement", "mois_paiement", "versements", "calendrier"):
                if inf_def.get(k_m):
                    raw_m = inf_def.get(k_m)
                    break
        if raw_m is None:
            for k_any, v_any in inf.items():
                if "mois" in str(k_any).lower() and v_any:
                    raw_m = v_any
                    break

        map_nom_m = {
            "jan": 1, "fev": 2, "fév": 2, "feb": 2, "mar": 3, "avr": 4, "apr": 4,
            "mai": 5, "may": 5, "juin": 6, "jun": 6, "juil": 7, "jul": 7,
            "aou": 8, "aoû": 8, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12, "déc": 12,
        }

        def _convertir_en_mois(item):
            res = []
            if isinstance(item, (int, float)):
                m_i = int(item)
                if 1 <= m_i <= 12:
                    res.append(m_i)
            elif isinstance(item, str):
                s_clean = item.lower().replace("/", " ").replace("-", " ").replace(";", ",").replace("|", ",")
                for morceau in s_clean.split(","):
                    morceau = morceau.strip()
                    if not morceau:
                        continue
                    if morceau.isdigit() and 1 <= int(morceau) <= 12:
                        res.append(int(morceau))
                    else:
                        for pref, num_m in map_nom_m.items():
                            if morceau.startswith(pref) or pref in morceau:
                                res.append(num_m)
                                break
            elif isinstance(item, dict):
                for k_sub in item.keys():
                    res.extend(_convertir_en_mois(k_sub))
            elif isinstance(item, (list, tuple, set)):
                for sub in item:
                    res.extend(_convertir_en_mois(sub))
            return res

        mois_extraits = sorted(list(set(_convertir_en_mois(raw_m)))) if raw_m is not None else [5]
        if not mois_extraits:
            mois_extraits = [5]

        return inf, div_val, mois_extraits

    _onglets_dispo = [v for k, v in globals().items() if k.startswith("onglet_")]
    _tab_portefeuille = (
        globals().get("onglet_portefeuille")
        or globals().get("onglet_pf")
        or (_onglets_dispo[1] if len(_onglets_dispo) >= 2 else None)
    )
    _tab_dividendes = (
        globals().get("onglet_dividendes")
        or globals().get("onglet_calendrier")
        or (_onglets_dispo[2] if len(_onglets_dispo) >= 3 else None)
    )

    # --------------------------------------------------------------------------
    # CALCULS CENTRAUX : SÉPARATION PEA (€) / CTO ($), YIELD ON COST & POIDS
    # --------------------------------------------------------------------------
    cap_inv_pea = 0.0
    val_act_pea = 0.0
    rente_pea = 0.0

    cap_inv_cto = 0.0
    val_act_cto = 0.0
    rente_cto = 0.0

    total_val_actions_pack = 0.0
    total_cout_actions_pack = 0.0
    total_rente_actions_pack = 0.0
    poids_actions_pack = {}
    lignes_yoc_details = []

    lignes_csv = ["\ufeff=== 1. MON PORTEFEUILLE ACTUEL (PEA & CTO) ==="]
    lignes_csv.append("Enveloppe;Action;Symbole;Quantite;PRU;Devise;Cours Actuel;Valorisation EUR;Plus-Value Latente EUR;Rendement Marche %;Rendement sur PRU (YoC) %;Rente Annuelle EUR")

    nb_lignes_pack_gratuit = 0
    for nom_p, pos_p in pf_pack.items():
        if (nom_p in CLES_TECHNIQUES_PF and nom_p != "Espèces") or not isinstance(pos_p, dict):
            continue
        q_p = float(pos_p.get("qte", 0.0))
        pru_p = float(pos_p.get("pru", 0.0))
        if q_p <= 0:
            continue

        # Forfait Gratuit : mêmes 2 premières lignes d'actions que le tableau de l'onglet Portefeuille
        if nom_p != "Espèces":
            if nom_p not in WATCHLIST_DEFAUT:
                continue
            if mode_gratuit and nb_lignes_pack_gratuit >= 2:
                continue
            nb_lignes_pack_gratuit += 1

        if nom_p == "Espèces":
            cap_inv_pea += pru_p
            val_act_pea += pru_p
            lignes_csv.append(f"PEA (EUR);Especes;CASH;1;{pru_p:.2f};EUR;{pru_p:.2f};{pru_p:.2f};0.00;0.00%;0.00%;0.00")
        else:
            inf_base = wl_complet_pack.get(nom_p, WATCHLIST_DEFAUT.get(nom_p, {}))
            cours_p = float(prix_tr_pack.get(nom_p, pru_p if pru_p > 0 else inf_base.get("prix_cible", 0.0)))
            inf_p, div_p, _ = _extraire_infos_div_et_mois(nom_p, cours_p)

            sym_p = inf_p.get("symbole", "")
            dev_p = inf_p.get("devise", "EUR")
            est_cto_usd = (dev_p == "USD")
            env_label = "CTO (USD)" if est_cto_usd else "PEA (EUR)"
            dev_sym_p = "$" if est_cto_usd else "€"
            fact_p = (1.0 / TAUX_USD_EUR) if est_cto_usd else 1.0

            val_eur_p = q_p * cours_p * fact_p
            cout_eur_p = q_p * pru_p * (facteur_cout_usd(pos_p) if est_cto_usd else 1.0)
            pv_lat_p = val_eur_p - cout_eur_p
            rente_eur_p = q_p * div_p * fact_p

            rdt_marche_p = (div_p / cours_p * 100.0) if cours_p > 0 else 0.0
            yoc_p = (div_p / pru_p * 100.0) if pru_p > 0 else 0.0
            payback_ans = (pru_p / div_p) if div_p > 0 else 0.0

            if est_cto_usd:
                cap_inv_cto += cout_eur_p
                val_act_cto += val_eur_p
                rente_cto += rente_eur_p
            else:
                cap_inv_pea += cout_eur_p
                val_act_pea += val_eur_p
                rente_pea += rente_eur_p

            total_val_actions_pack += val_eur_p
            total_cout_actions_pack += cout_eur_p
            total_rente_actions_pack += rente_eur_p
            poids_actions_pack[nom_p] = val_eur_p

            lignes_yoc_details.append({
                "nom": nom_p,
                "enveloppe": env_label,
                "qte": int(q_p),
                "pru": pru_p,
                "cours": cours_p,
                "dev_sym": dev_sym_p,
                "div_unitaire": div_p,
                "rdt_marche": rdt_marche_p,
                "yoc": yoc_p,
                "bonus_yoc": yoc_p - rdt_marche_p,
                "rente_eur": rente_eur_p,
                "val_eur": val_eur_p,
                "cout_eur": cout_eur_p,
                "payback": payback_ans,
            })

            lignes_csv.append(
                f"{env_label};{nom_p};{sym_p};{int(q_p)};{pru_p:.2f};{dev_p};{cours_p:.2f};{val_eur_p:.2f};{pv_lat_p:+.2f};{rdt_marche_p:.2f}%;{yoc_p:.2f}%;{rente_eur_p:.2f}"
            )

    # --------------------------------------------------------------------------
    # 1. BARRE LATÉRALE : MODE DISCRÉTION & EXPORT EXCEL / CSV ENRICHI
    # --------------------------------------------------------------------------
    st.sidebar.markdown("---")
    st.sidebar.subheader("🛡️ Outils Pro & Sécurité")

    mode_discret = st.sidebar.checkbox(
        "🕵️ Mode Discrétion (Flouter les €)",
        value=False,
        key="chk_mode_discretion_pro",
        help="Floute automatiquement vos montants en euros à l'écran (passez la souris sur une carte pour la lire).",
    )

    if mode_discret:
        st.markdown(
            """
            <style>
            .argon-val, .cal-total, .meteo-item div:nth-child(2),
            .r-table td:nth-child(4), .r-table td:nth-child(5), .r-table td:nth-child(6) {
                filter: blur(7px) !important;
                transition: filter 0.2s ease-in-out !important;
                cursor: pointer !important;
            }
            .argon-val:hover, .cal-total:hover, .meteo-item div:nth-child(2):hover,
            .r-table td:nth-child(4):hover, .r-table td:nth-child(5):hover, .r-table td:nth-child(6):hover {
                filter: none !important;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )

    lignes_csv.append("")
    lignes_csv.append("=== 2. JOURNAL DES PLUS-VALUES ACTEES (VENTES) ===")
    lignes_csv.append("Date;Action;Quantite Vendue;PRU;Prix de Vente;Devise;Cash Net Encaisse EUR;Plus ou Moins-Value Actee EUR;Performance %")

    for v_item in hist_ventes_pack:
        lignes_csv.append(
            f"{v_item.get('date','')};{v_item.get('action','')};{v_item.get('qte',0)};"
            f"{float(v_item.get('pru',0)):.2f};{float(v_item.get('prix_vente',0)):.2f};{v_item.get('devise','€')};"
            f"{float(v_item.get('montant_eur',0)):.2f};{float(v_item.get('plus_value_eur',0)):+.2f};{float(v_item.get('perf_pct',0)):+.2f}%"
        )

    contenu_csv_bytes = "\n".join(lignes_csv).encode("utf-8")
    if est_premium_ou_pro:
        st.sidebar.download_button(
            label="📥 Sauvegarde Locale (Excel / CSV)",
            data=contenu_csv_bytes,
            file_name=f"Boursy_Bilan_Complet_{datetime.now().strftime('%Y-%m-%d')}.csv",
            mime="text/csv",
            width="stretch",
        )
    else:
        st.sidebar.button("🔒 Sauvegarde CSV (Offre Premium/Pro)", disabled=True, width="stretch")

    alertes_surpond = []
    if total_val_actions_pack > 0:
        for nom_sp, val_sp in sorted(poids_actions_pack.items(), key=lambda x: x[1], reverse=True):
            pct_sp = (val_sp / total_val_actions_pack) * 100.0
            if pct_sp >= 20.0:
                alertes_surpond.append((nom_sp, pct_sp, val_sp))

    # --------------------------------------------------------------------------
    # 2. ONGLET 2 : SÉPARATION PEA/CTO, YIELD ON COST & DUEL ETF
    # --------------------------------------------------------------------------
    if _tab_portefeuille is not None and (cap_inv_pea > 0 or cap_inv_cto > 0):
        with _tab_portefeuille:
            st.markdown("---")
            st.subheader("🏛️ Architecture Patrimoniale : Séparation PEA (€) vs CTO ($), Yield on Cost & Duel ETF")

            plafond_pea_legal = 150000.0
            pv_actees_tot_pea = sum(float(v.get("plus_value_eur", 0.0)) for v in hist_ventes_pack if v.get("devise", "€") != "$")
            div_enc_pea = float(st.session_state.get("dividendes_encaisses_cumul", 0.0))
            # Même valeur que la « Jauge Officielle Plafond PEA » de l'onglet (calcul local seulement en repli)
            versements_nets_pea_unifie = float(globals().get(
                "versements_nets_pea",
                max(0.0, cap_inv_pea - max(0.0, pv_actees_tot_pea + div_enc_pea)),
            ))
            marge_pea_dispo = max(0.0, plafond_pea_legal - versements_nets_pea_unifie)
            pct_plafond_pea = min(100.0, (versements_nets_pea_unifie / plafond_pea_legal) * 100.0)
            pv_pea = val_act_pea - cap_inv_pea
            pv_cto = val_act_cto - cap_inv_cto
            c_pv_pea = "#2ecc71" if pv_pea >= 0 else "#e74c3c"
            c_pv_cto = "#2ecc71" if pv_cto >= 0 else "#e74c3c"

            yoc_global = (total_rente_actions_pack / total_cout_actions_pack * 100.0) if total_cout_actions_pack > 0 else 0.0
            rdt_marche_global = (total_rente_actions_pack / total_val_actions_pack * 100.0) if total_val_actions_pack > 0 else 0.0
            bonus_yoc_global = yoc_global - rdt_marche_global

            afficher_html(f"""
            <div class="argon-grid" style="margin-bottom: 14px;">
                <div class="argon-card" style="border-top: 3px solid #3498db;">
                    <div class="argon-title">🇫🇷 Poche PEA Éligible (Hors US)</div>
                    <div class="argon-val">{val_act_pea:,.2f} €</div>
                    <div class="argon-sub">Investi PRU : <b>{cap_inv_pea:,.0f} €</b> | PV : <span style="color:{c_pv_pea}; font-weight:700;">{pv_pea:+,.0f} €</span></div>
                </div>
                <div class="argon-card" style="border-top: 3px solid #9b59b6;">
                    <div class="argon-title">🇺🇸 Poche CTO Actions US ($)</div>
                    <div class="argon-val">{val_act_cto:,.2f} €</div>
                    <div class="argon-sub">Investi PRU : <b>{cap_inv_cto:,.0f} €</b> | PV : <span style="color:{c_pv_cto}; font-weight:700;">{pv_cto:+,.0f} €</span></div>
                </div>
                <div class="argon-card" style="border-top: 3px solid #2ecc71;">
                    <div class="argon-title">🛡️ Plafond Légal PEA (150 000 €)</div>
                    <div class="argon-val" style="color:#2ecc71;">{pct_plafond_pea:.1f}% utilisé</div>
                    <div class="argon-sub">Reste à verser sur PEA : <b>{marge_pea_dispo:,.0f} €</b></div>
                </div>
                <div class="argon-card" style="border-top: 3px solid #f39c12;">
                    <div class="argon-title">💎 Rendement sur PRU (Yield on Cost)</div>
                    <div class="argon-val" style="color:#f39c12;">{yoc_global:.2f}%</div>
                    <div class="argon-sub">Rendement marché : <b>{rdt_marche_global:.2f}%</b> ({bonus_yoc_global:+.2f}% grâce à vos PRU)</div>
                </div>
            </div>
            """)

            if alertes_surpond:
                badges_sp_html = " ".join(
                    f"<span class='b-orange' style='margin-right:6px; padding:3px 8px;'><b>{n_s}</b> : {p_s:.1f}% ({v_s:,.0f} €)</span>"
                    for n_s, p_s, v_s in alertes_surpond
                )
                afficher_html(f"""
                <div style="background:rgba(243,156,18,0.08); border-left:4px solid #f39c12; padding:10px 14px; border-radius:8px; margin-bottom:14px; font-size:0.88em;">
                    ⚖️ <b>Règle Prudentielle de Concentration (Seuil 20%) :</b> {len(alertes_surpond)} ligne(s) dépasse(nt) 20% de votre portefeuille actions :
                    <div style="margin-top:6px;">{badges_sp_html}</div>
                </div>
                """)

            with st.expander("💎 Ouvrir la Matrice du Rendement sur PRU (Yield on Cost & Années d'Amortissement)", expanded=True):
                if mode_gratuit:
                    afficher_verrou_saas(
                        "Matrice Yield on Cost & Années d'Amortissement",
                        "⚡ Offre Premium (4,90 €/mois) ou 👑 Pro (8,90 €/mois)",
                        "Visualisez votre rendement réel par rapport à votre prix d'achat initial (Yield on Cost)."
                    )
                else:
                    st.caption("Le **Yield on Cost (Rendement sur PRU)** mesure le rendement réel que vous procure chaque action par rapport au prix auquel VOUS l'avez achetée.")
                    html_yoc = "<table class='r-table'><thead><tr><th style='text-align:left;'>Action</th><th>Enveloppe</th><th>Votre PRU</th><th>Cours Actuel</th><th>Dividende / An</th><th>Rdt Marché</th><th>💎 Rdt sur PRU (YoC)</th><th>Bonus PRU</th><th>Rente Annuelle</th><th>Remboursé en</th></tr></thead><tbody>"

                    for item_y in sorted(lignes_yoc_details, key=lambda x: x["yoc"], reverse=True):
                        c_bonus = "#2ecc71" if item_y["bonus_yoc"] >= 0 else "#f39c12"
                        b_yoc = "b-green" if item_y["yoc"] >= 4.5 else ("b-blue" if item_y["yoc"] >= 2.5 else "b-orange")
                        txt_payback = f"{item_y['payback']:.1f} ans" if item_y["payback"] > 0 else "—"
                        badge_env = "<span class='b-blue'>PEA (€)</span>" if "PEA" in item_y["enveloppe"] else "<span class='b-orange'>CTO ($)</span>"

                        html_yoc += f"""
                        <tr>
                            <td class='r-name'>{item_y['nom']} <span style='font-size:0.78em; opacity:0.65;'>(x{item_y['qte']})</span></td>
                            <td>{badge_env}</td>
                            <td><b>{item_y['pru']:.2f} {item_y['dev_sym']}</b></td>
                            <td>{item_y['cours']:.2f} {item_y['dev_sym']}</td>
                            <td>{item_y['div_unitaire']:.2f} {item_y['dev_sym']}</td>
                            <td>{item_y['rdt_marche']:.2f}%</td>
                            <td><span class='{b_yoc}' style='font-weight:900;'>💎 {item_y['yoc']:.2f}%</span></td>
                            <td style='color:{c_bonus}; font-weight:800;'>{item_y['bonus_yoc']:+.2f}%</td>
                            <td style='color:#2ecc71; font-weight:800;'>{item_y['rente_eur']:,.2f} €</td>
                            <td style='font-size:0.85em; opacity:0.85;'>⏳ {txt_payback}</td>
                        </tr>
                        """
                    html_yoc += "</tbody></table>"
                    afficher_html(html_yoc)

            with st.expander("⚔️ Duel de Performance : Mon Stock-Picking (Total Return) vs ETF MSCI World (CW8) & CAC 40", expanded=True):
                if not est_pro_max:
                    afficher_verrou_saas(
                        "Duel de Performance : Stock-Picking vs ETF MSCI World (CW8) & CAC 40",
                        "👑 Offre Pro (8,90 €/mois)",
                        "Comparez votre performance globale réelle (Total Return : PV + Rente) face aux grands indices passifs."
                    )
                else:
                    st.caption(
                        "Comparaison sur la MÊME période d'1 an glissant : évolution du cours de vos lignes actuelles sur 1 an "
                        "+ leurs dividendes annuels, face aux indices sur 1 an. Le CW8 capitalise ses dividendes ; "
                        "le CAC 40 et le S&P 500 sont affichés hors dividendes."
                    )

                    # Performance 1 an des lignes ACTUELLES (mêmes quantités qu'aujourd'hui, hors espèces et hors ventes passées),
                    # calculée comme celle des indices : cours d'il y a 252 séances -> cours actuel.
                    val_actuelle_duel = 0.0
                    val_il_y_a_1an_duel = 0.0
                    rente_duel = 0.0
                    lignes_hors_duel = []
                    for l_duel in lignes_yoc_details:
                        cl_duel = hist_prix_pack.get(l_duel["nom"]) or []
                        if len(cl_duel) >= 30 and float(cl_duel[-1]) > 0:
                            idx_deb_duel = max(0, len(cl_duel) - min(252, len(cl_duel)))
                            ratio_duel = float(cl_duel[idx_deb_duel]) / float(cl_duel[-1])
                            val_actuelle_duel += l_duel["val_eur"]
                            val_il_y_a_1an_duel += l_duel["val_eur"] * ratio_duel
                            rente_duel += l_duel["rente_eur"]
                        else:
                            lignes_hors_duel.append(l_duel["nom"])

                    gain_total_return_eur = (val_actuelle_duel - val_il_y_a_1an_duel) + rente_duel
                    cap_base_total = max(1.0, val_il_y_a_1an_duel)
                    perf_user_tot_pct = (gain_total_return_eur / cap_base_total) * 100.0 if val_il_y_a_1an_duel > 0 else 0.0
                    if lignes_hors_duel:
                        st.caption("ℹ️ Lignes exclues du duel (historique de cours indisponible) : " + ", ".join(lignes_hors_duel) + ".")

                    def _perf_1an_indice(sym_idx):
                        """Performance 1 an de l'indice, ou None si son historique est indisponible (aucun chiffre inventé)."""
                        try:
                            _, cl_i, _, _ = recuperer_donnees(sym_idx)
                            if cl_i and len(cl_i) >= 30:
                                idx_deb = max(0, len(cl_i) - min(252, len(cl_i)))
                                p_deb = float(cl_i[idx_deb])
                                p_fin = float(cl_i[-1])
                                if p_deb > 0:
                                    return ((p_fin - p_deb) / p_deb) * 100.0
                        except Exception:
                            pass
                        return None

                    perf_cw8_1a = _perf_1an_indice("CW8.PA")
                    perf_cac_1a = _perf_1an_indice("^FCHI")
                    perf_sp500_1a = _perf_1an_indice("^GSPC")

                    def _txt_pct(val, nb_dec=2):
                        return f"{val:+.{nb_dec}f}%" if val is not None else "Indisponible"

                    def _txt_gain_simule(val):
                        return f"Simulé sur votre capital : <b>{cap_base_total * val / 100.0:+,.0f} €</b>" if val is not None else "Historique de l'indice indisponible"

                    alpha_vs_cw8 = (perf_user_tot_pct - perf_cw8_1a) if perf_cw8_1a is not None else None
                    alpha_vs_cac = (perf_user_tot_pct - perf_cac_1a) if perf_cac_1a is not None else None

                    c_user_duel = "#2ecc71" if perf_user_tot_pct >= 0 else "#e74c3c"
                    c_alpha_cw8 = "#95a5a6" if alpha_vs_cw8 is None else ("#2ecc71" if alpha_vs_cw8 >= 0 else "#f39c12")
                    c_alpha_cac = "#95a5a6" if alpha_vs_cac is None else ("#2ecc71" if alpha_vs_cac >= 0 else "#f39c12")
                    txt_alpha_cw8 = f"{alpha_vs_cw8:+.2f}% vs CW8" if alpha_vs_cw8 is not None else "Indisponible"
                    txt_alpha_cac = f"{alpha_vs_cac:+.2f}% vs CAC 40" if alpha_vs_cac is not None else "CAC 40 indisponible"

                    afficher_html(f"""
                    <div class="argon-grid" style="margin-top:6px;">
                        <div class="argon-card" style="border-top: 3px solid {c_user_duel};">
                            <div class="argon-title">🏆 Vos Lignes Actuelles (1 An, dividendes inclus)</div>
                            <div class="argon-val" style="color:{c_user_duel};">{perf_user_tot_pct:+.2f}%</div>
                            <div class="argon-sub">Gain 1 an (cours + rente) : <b>{gain_total_return_eur:+,.0f} €</b></div>
                        </div>
                        <div class="argon-card" style="border-top: 3px solid #3498db;">
                            <div class="argon-title">🌍 ETF MSCI World (CW8.PA - 1 An)</div>
                            <div class="argon-val" style="color:#3498db;">{_txt_pct(perf_cw8_1a)}</div>
                            <div class="argon-sub">{_txt_gain_simule(perf_cw8_1a)}</div>
                        </div>
                        <div class="argon-card" style="border-top: 3px solid #9b59b6;">
                            <div class="argon-title">🇫🇷 Indice CAC 40 (1 An, hors dividendes)</div>
                            <div class="argon-val" style="color:#9b59b6;">{_txt_pct(perf_cac_1a)}</div>
                            <div class="argon-sub">{_txt_gain_simule(perf_cac_1a)}</div>
                        </div>
                        <div class="argon-card" style="border-top: 3px solid {c_alpha_cw8};">
                            <div class="argon-title">⚡ Votre Alpha (Surperformance)</div>
                            <div class="argon-val" style="color:{c_alpha_cw8}; font-size:1.18em;">{txt_alpha_cw8}</div>
                            <div class="argon-sub">Et <b style="color:{c_alpha_cac};">{txt_alpha_cac}</b> (S&P 500 : {_txt_pct(perf_sp500_1a, 1)})</div>
                        </div>
                    </div>
                    """)

    # --------------------------------------------------------------------------
    # 3. ONGLET 3 : RADAR DES PROCHAINS DÉTACHEMENTS EN TIROIR (EXCLUSIF PRO 8,90 €)
    # --------------------------------------------------------------------------
    if _tab_dividendes is not None:
        with _tab_dividendes:
            st.markdown("---")
            with st.expander("⏳ Ouvrir le Radar des Prochains Détachements (90 jours) & Simulateur « Boost de Coupon DCA »", expanded=False):
                if not est_pro_max:
                    afficher_verrou_saas(
                        "Radar des Prochains Détachements (90J) & Simulateur Boost de Coupon DCA",
                        "👑 Offre Pro (8,90 €/mois)",
                        "Repérez les dividendes imminents à 90 jours sur vos lignes et calculez le gain immédiat de coupon si vous y allouez votre DCA."
                    )
                else:
                    st.caption("Repérez les dividendes imminents à 90 jours et calculez le gain immédiat de coupon si vous y allouez votre enveloppe DCA avant le détachement.")

                    mois_actuel_num = datetime.now().month
                    noms_mois_fr = {
                        1: "Janvier", 2: "Février", 3: "Mars", 4: "Avril",
                        5: "Mai", 6: "Juin", 7: "Juillet", 8: "Août",
                        9: "Septembre", 10: "Octobre", 11: "Novembre", 12: "Décembre",
                    }
                    fenetre_90j = [
                        mois_actuel_num,
                        (mois_actuel_num % 12) + 1,
                        ((mois_actuel_num + 1) % 12) + 1,
                        ((mois_actuel_num + 2) % 12) + 1,
                    ]
                    noms_fenetre = [noms_mois_fr[m] for m in fenetre_90j[:3]]

                    toutes_actions_div = sorted(list(set(list(WATCHLIST_DEFAUT.keys()) + list(wl_complet_pack.keys()))))
                    detachements_proches = []

                    for nom_d in toutes_actions_div:
                        if nom_d in CLES_TECHNIQUES_PF:
                            continue

                        inf_base_d = wl_complet_pack.get(nom_d, WATCHLIST_DEFAUT.get(nom_d, {}))
                        cours_def_d = float(inf_base_d.get("prix_cible", 50.0)) if isinstance(inf_base_d, dict) else 50.0
                        cours_d = float(prix_tr_pack.get(nom_d, cours_def_d))

                        inf_d, div_tot_d, mois_list_d = _extraire_infos_div_et_mois(nom_d, cours_d)
                        if div_tot_d <= 0:
                            continue

                        mois_imminents = [m for m in mois_list_d if m in fenetre_90j]
                        if mois_imminents:
                            nb_v_d = max(1, len(mois_list_d))
                            coupon_unitaire_d = div_tot_d / nb_v_d
                            dev_d = "$" if inf_d.get("devise") == "USD" else "€"
                            fact_d = (1.0 / TAUX_USD_EUR) if dev_d == "$" else 1.0
                            cours_eur_d = max(0.01, cours_d * fact_d)

                            qte_det_d = int(pf_pack.get(nom_d, {}).get("qte", 0)) if isinstance(pf_pack.get(nom_d), dict) else 0
                            coupon_deja_acquis = qte_det_d * coupon_unitaire_d * len(mois_imminents) * fact_d
                            nb_titres_dca = max(1, int(budget_dca_pack // cours_eur_d)) if budget_dca_pack >= cours_eur_d else 0
                            boost_coupon_imm = nb_titres_dca * coupon_unitaire_d * fact_d
                            boost_rente_annuelle = nb_titres_dca * div_tot_d * fact_d
                            rdt_coupon_seul = (coupon_unitaire_d / cours_d * 100.0) if cours_d > 0 else 0.0

                            dist_mois = min((m - mois_actuel_num) % 12 for m in mois_imminents)

                            detachements_proches.append({
                                "nom": nom_d,
                                "dist": dist_mois,
                                "mois_txt": ", ".join(noms_mois_fr[m] for m in sorted(mois_imminents, key=lambda x: (x - mois_actuel_num) % 12)),
                                "en_pf": qte_det_d > 0,
                                "qte_pf": qte_det_d,
                                "cours": cours_d,
                                "dev": dev_d,
                                "coupon_unit": coupon_unitaire_d,
                                "rdt_coupon": rdt_coupon_seul,
                                "acquis_eur": coupon_deja_acquis,
                                "nb_dca": nb_titres_dca,
                                "boost_imm_eur": boost_coupon_imm,
                                "boost_an_eur": boost_rente_annuelle,
                            })

                    detachements_proches.sort(key=lambda x: (not x["en_pf"], x["dist"], -x["boost_imm_eur"]))

                    if not detachements_proches:
                        st.info(f"Aucun détachement détecté sur la période {', '.join(noms_fenetre)}.")
                    else:
                        total_acquis_fenetre = sum(d["acquis_eur"] for d in detachements_proches)
                        meilleur_boost = max(detachements_proches, key=lambda x: x["boost_imm_eur"])

                        afficher_html(f"""
                        <div class="meteo-bar" style="margin-bottom: 14px;">
                            <div class="meteo-item" style="border-left-color:#2ecc71;">
                               <div>
                                    <div style="font-size:0.74em; font-weight:800; opacity:0.75;">🗓️ RADAR DE DÉTACHEMENTS (90 JOURS GLISSANTS)</div>
                                    <div style="font-size:0.98em; font-weight:900;">{' • '.join(noms_fenetre)} ({len(detachements_proches)} valeur(s) détectée(s))</div>
                                </div>
                            </div>
                            <div class="meteo-item" style="border-left-color:#3498db;">
                                <div>
                                    <div style="font-size:0.74em; font-weight:800; opacity:0.75;">💶 COUPONS DÉJÀ ACQUIS (MON PORTEFEUILLE)</div>
                                    <div style="font-size:1.02em; font-weight:900; color:#2ecc71;">+{total_acquis_fenetre:,.2f} € attendus</div>
                                </div>
                            </div>
                            <div class="meteo-item" style="border-left-color:#f39c12;">
                                <div>
                                    <div style="font-size:0.74em; font-weight:800; opacity:0.75;">🚀 MEILLEUR BOOST DCA ({budget_dca_pack:,.0f} €)</div>
                                    <div style="font-size:0.95em; font-weight:900; color:#f39c12;">{meilleur_boost['nom']} : +{meilleur_boost['boost_imm_eur']:,.2f} € dès ce détachement</div>
                                </div>
                            </div>
                        </div>
                        """)

                        html_boost = f"<table class='r-table'><thead><tr><th style='text-align:left;'>Action</th><th>Mois Détachement</th><th>Statut</th><th>Coupon Unitaire</th><th>Coupon Déjà Acquis</th><th>Renfort DCA ({budget_dca_pack:,.0f} €)</th><th>⚡ Boost Coupon Immédiat</th><th>Boost Rente / An</th></tr></thead><tbody>"
                        for d_b in detachements_proches:
                            badge_pf_b = f"<span class='b-green'>💼 {d_b['qte_pf']} titre(s)</span>" if d_b["en_pf"] else "<span class='b-blue'>🔍 Radar</span>"
                            html_boost += f"""
                            <tr>
                                <td class='r-name'>{d_b['nom']} <span style='font-size:0.78em; opacity:0.65;'>({d_b['cours']:.2f} {d_b['dev']})</span></td>
                                <td>📅 <b>{d_b['mois_txt']}</b></td>
                                <td>{badge_pf_b}</td>
                                <td><b>{d_b['coupon_unit']:.2f} {d_b['dev']}</b> <span style='font-size:0.8em; opacity:0.7;'>({d_b['rdt_coupon']:.2f}%)</span></td>
                                <td style='color:#2ecc71; font-weight:800;'>+{d_b['acquis_eur']:,.2f} €</td>
                                <td><b>+{d_b['nb_dca']} action(s)</b></td>
                                <td><span class='b-orange' style='font-weight:900;'>⚡ +{d_b['boost_imm_eur']:,.2f} €</span></td>
                                <td style='color:#3498db; font-weight:800;'>+{d_b['boost_an_eur']:,.2f} € / an</td>
                            </tr>
                            """
                        html_boost += "</tbody></table>"
                        afficher_html(html_boost)

    # --------------------------------------------------------------------------
    # 4. ONGLET 1 : BANDEAU D'OPPORTUNITÉS IMMÉDIATES & STATION GRAPHIQUE 360° (EXCLUSIF PRO 8,90 €)
    # --------------------------------------------------------------------------
    with onglet_radar:
        map_t1_sg = {d["NomBrut"]: d for d in liste_t1_pack if isinstance(d, dict) and "NomBrut" in d}
        opportunites_cibles = []

        for nom_op, inf_op in wl_pack.items():
            if nom_op in CLES_TECHNIQUES_PF or not isinstance(inf_op, dict):
                continue
            cible_op = float(inf_op.get("prix_cible", 0.0))
            dev_op = "$" if inf_op.get("devise") == "USD" else "€"
            cours_op = float(prix_tr_pack.get(nom_op, 0.0))
            sc_op = int(map_t1_sg.get(nom_op, {}).get("Score", 50))

            if cours_op > 0 and cible_op > 0:
                ecart_cible_pct = ((cours_op - cible_op) / cible_op) * 100.0
                if ecart_cible_pct <= 0:
                    opportunites_cibles.append(
                        f"<span class='cal-pill' style='border-left:3px solid #2ecc71;'>"
                        f"🎯 <b>{nom_op}</b> ({cours_op:.2f} {dev_op}) : <b style='color:#2ecc71;'>{ecart_cible_pct:+.1f}% sous cible ({cible_op:.0f} {dev_op})</b> • Score {sc_op}/100</span>"
                    )
                elif ecart_cible_pct <= 2.5:
                    opportunites_cibles.append(
                        f"<span class='cal-pill' style='border-left:3px solid #3498db;'>"
                        f"⏳ <b>{nom_op}</b> ({cours_op:.2f} {dev_op}) : <b style='color:#3498db;'>à {ecart_cible_pct:+.1f}% de la cible ({cible_op:.0f} {dev_op})</b></span>"
                    )

        html_pills_opp = (
            "".join(opportunites_cibles[:8])
            if opportunites_cibles
            else "<span style='font-size:0.85em; opacity:0.7;'>Aucune valeur sous son prix cible aujourd'hui — discipline & patience !</span>"
        )

        html_alerte_20_radar = ""
        if alertes_surpond:
            txt_sp_court = ", ".join(f"<b>{n_s} ({p_s:.0f}%)</b>" for n_s, p_s, _ in alertes_surpond[:3])
            html_alerte_20_radar = (
                f"<div style='margin-top:6px; font-size:0.82em; color:#f39c12;'>"
                f"⚖️ <b>Vigilance Concentration (>20%) :</b> {txt_sp_court} — ces lignes pèsent déjà lourd dans le portefeuille."
                f"</div>"
            )

        afficher_html(f"""
        <div class="argon-card" style="border-left: 4px solid #2ecc71; margin-top: 14px; margin-bottom: 10px; padding: 12px 16px;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
                <span style="font-size:0.82em; font-weight:800; text-transform:uppercase; color:#2ecc71;">
                    🔔 RADAR DES PRIX CIBLES (ATTEINTS & PROCHES)
                </span>
                <span class="b-green" style="font-size:0.75em;">{len(opportunites_cibles)} signal(aux) actif(s)</span>
            </div>
            <div>{html_pills_opp}</div>
            {html_alerte_20_radar}
        </div>
        """)

        with st.expander("📈 Ouvrir la Station Graphique Interactive 360° (Canal 3A, EMA 2/12, Supports & TradingView)", expanded=False):
            if not est_pro_max:
                afficher_verrou_saas(
                    "Station Graphique Interactive 360° & Terminal TradingView",
                    "👑 Offre Pro (8,90 €/mois)",
                    "Visualisez les canaux de régression 3 ans, les croisements EMA 2/12 et le terminal technique avancé."
                )
            else:
                st.caption("Sélectionnez n'importe quelle valeur de votre radar pour visualiser ses courbes EMA 2/12, son couloir de régression linéaire à 3 ans, ses supports/résistances 30J et votre PRU.")

                col_sg_filtre, col_sg_act, col_sg_hor, col_sg_mode = st.columns([1.3, 2.0, 1.3, 1.6])

                with col_sg_filtre:
                    filtre_station = st.selectbox(
                        "Filtrer la liste :",
                        ["🌐 Tout le Radar", "💼 Mon Portefeuille", "🔥 Top Scores (≥ 60)", "🎯 Prix Cibles Atteints"],
                        key="sg360_filtre_liste",
                    )

                toutes_actions_sg = sorted([k for k in wl_complet_pack.keys() if k not in CLES_TECHNIQUES_PF])
                if not toutes_actions_sg:
                    toutes_actions_sg = sorted(list(WATCHLIST_DEFAUT.keys()))

                if filtre_station == "💼 Mon Portefeuille":
                    actions_dispo_sg = [
                        k for k in toutes_actions_sg
                        if k in pf_pack and isinstance(pf_pack.get(k), dict) and float(pf_pack[k].get("qte", 0)) > 0
                    ]
                elif filtre_station == "🔥 Top Scores (≥ 60)":
                    actions_dispo_sg = [k for k in toutes_actions_sg if int(map_t1_sg.get(k, {}).get("Score", 0)) >= 60]
                elif filtre_station == "🎯 Prix Cibles Atteints":
                    actions_dispo_sg = [
                        k for k in toutes_actions_sg
                        if float(prix_tr_pack.get(k, 999999)) <= float(wl_complet_pack.get(k, {}).get("prix_cible", 0)) * 1.02
                    ]
                else:
                    actions_dispo_sg = toutes_actions_sg

                if not actions_dispo_sg:
                    actions_dispo_sg = toutes_actions_sg

                labels_actions_sg = []
                map_label_vers_nom = {}
                for nom_a_sg in actions_dispo_sg:
                    sc_sg = map_t1_sg.get(nom_a_sg, {}).get("Score", 50)
                    pr_sg = map_t1_sg.get(nom_a_sg, {}).get("Prix", "")
                    lbl_sg = f"{nom_a_sg} — {pr_sg} (Score {sc_sg}/100)" if pr_sg else f"{nom_a_sg} (Score {sc_sg}/100)"
                    labels_actions_sg.append(lbl_sg)
                    map_label_vers_nom[lbl_sg] = nom_a_sg

                with col_sg_act:
                    choix_label_sg = st.selectbox("🎯 Action à analyser :", labels_actions_sg, key="sg360_choix_action")
                    action_sg = map_label_vers_nom.get(choix_label_sg, actions_dispo_sg[0])

                with col_sg_hor:
                    horizon_sg = st.selectbox(
                        "🕒 Horizon :",
                        ["3 Mois (65 séances)", "6 Mois (130 séances)", "1 An (252 séances)", "3 Ans (Canal complet)"],
                        index=1,
                        key="sg360_choix_horizon",
                    )

                with col_sg_mode:
                    moteur_sg = st.radio(
                        "Moteur d'affichage :",
                        ["📊 Boursy Quant", "🕯️ TradingView"],
                        horizontal=True,
                        key="sg360_choix_moteur",
                    )

                info_sg = wl_complet_pack.get(action_sg, WATCHLIST_DEFAUT.get(action_sg, {}))
                sym_sg = info_sg.get("symbole", "MC.PA")
                dev_sg = "$" if info_sg.get("devise") == "USD" else "€"
                cible_sg = float(info_sg.get("prix_cible", 100.0))

                pos_pf_sg = pf_pack.get(action_sg, {})
                en_pf_sg = isinstance(pos_pf_sg, dict) and float(pos_pf_sg.get("qte", 0)) > 0
                pru_sg = float(pos_pf_sg.get("pru", 0.0)) if en_pf_sg else 0.0
                qte_sg = int(pos_pf_sg.get("qte", 0)) if en_pf_sg else 0

                _, closes_sg_full, highs_sg_full, lows_sg_full = recuperer_donnees(sym_sg)
                if not closes_sg_full or len(closes_sg_full) < 20:
                    closes_sg_full = hist_prix_pack.get(action_sg, [cible_sg] * 60)
                    highs_sg_full = [c * 1.01 for c in closes_sg_full]
                    lows_sg_full = [c * 0.99 for c in closes_sg_full]

                arr_c_full = [float(x) for x in closes_sg_full]
                n_full = len(arr_c_full)

                if n_full >= 2:
                    moy_x = (n_full - 1) / 2.0
                    moy_y = sum(arr_c_full) / n_full
                    num_reg = sum((i - moy_x) * (arr_c_full[i] - moy_y) for i in range(n_full))
                    den_reg = sum((i - moy_x) ** 2 for i in range(n_full))
                    pente_3a = (num_reg / den_reg) if den_reg > 0 else 0.0
                    intercept_3a = moy_y - pente_3a * moy_x
                    droite_reg_full = [pente_3a * i + intercept_3a for i in range(n_full)]
                    variance_3a = sum((arr_c_full[i] - droite_reg_full[i]) ** 2 for i in range(n_full)) / n_full
                    ecart_type_3a = math.sqrt(max(0.0, variance_3a))
                else:
                    droite_reg_full = list(arr_c_full)
                    ecart_type_3a = float(arr_c_full[-1] * 0.05)

                canal_haut_full = [droite_reg_full[i] + ecart_type_3a for i in range(n_full)]
                canal_bas_full = [max(0.01, droite_reg_full[i] - ecart_type_3a) for i in range(n_full)]

                s_c_full = pd.Series(arr_c_full)
                ema_rapide_full = s_c_full.ewm(span=2, adjust=False).mean().tolist()
                ema_lente_full = s_c_full.ewm(span=12, adjust=False).mean().tolist()

                fenetre_sr = min(30, n_full)
                sup_30j_sg = float(min(lows_sg_full[-fenetre_sr:])) if lows_sg_full else float(min(arr_c_full[-fenetre_sr:]))
                res_30j_sg = float(max(highs_sg_full[-fenetre_sr:])) if highs_sg_full else float(max(arr_c_full[-fenetre_sr:]))
                cours_act_sg = float(arr_c_full[-1])
                fair_val_act = float(droite_reg_full[-1])
                ecart_fv_pct = ((cours_act_sg - fair_val_act) / fair_val_act * 100.0) if fair_val_act > 0 else 0.0

                amp_sr_sg = max(0.01, res_30j_sg - sup_30j_sg)
                pos_canal_30j = max(0.0, min(100.0, ((cours_act_sg - sup_30j_sg) / amp_sr_sg) * 100.0))
                signal_ema_sg = "🟢 Haussier (EMA 2 > 12)" if ema_rapide_full[-1] >= ema_lente_full[-1] else "🔴 Baissier (EMA 2 < 12)"
                c_ema_sg = "#2ecc71" if ema_rapide_full[-1] >= ema_lente_full[-1] else "#e74c3c"
                c_fv_sg = "#2ecc71" if ecart_fv_pct <= 0 else "#f39c12"

                txt_pru_card = (
                    f"<div class='argon-val' style='color:{'#2ecc71' if cours_act_sg >= pru_sg else '#3498db'};'>{pru_sg:.2f} {dev_sg}</div>"
                    f"<div class='argon-sub'>{qte_sg} titre(s) | Écart : {((cours_act_sg - pru_sg)/pru_sg*100):+.1f}%</div>"
                    if en_pf_sg and pru_sg > 0
                    else f"<div class='argon-val' style='color:#9b59b6;'>Hors PF</div><div class='argon-sub'>Cible : <b>{cible_sg:.2f} {dev_sg}</b></div>"
                )

                html_kpi_station = f"""
                <div class="argon-grid" style="margin-top: 6px; margin-bottom: 14px;">
                    <div class="argon-card" style="border-top: 3px solid #3498db;">
                        <div class="argon-title">🏷️ Cours Live ({sym_sg})</div>
                        <div class="argon-val">{cours_act_sg:.2f} {dev_sg}</div>
                        <div class="argon-sub">Objectif Cible : <b>{cible_sg:.2f} {dev_sg}</b></div>
                    </div>
                    <div class="argon-card" style="border-top: 3px solid {c_ema_sg};">
                        <div class="argon-title">⚡ Croisement EMA 2 / 12</div>
                        <div class="argon-val" style="color:{c_ema_sg}; font-size:1.15em;">{ema_rapide_full[-1]:.2f} / {ema_lente_full[-1]:.2f}</div>
                        <div class="argon-sub"><b>{signal_ema_sg}</b></div>
                    </div>
                    <div class="argon-card" style="border-top: 3px solid #2ecc71;">
                        <div class="argon-title">🟢 Support / 🔴 Résistance 30J</div>
                        <div class="argon-val" style="font-size:1.15em;"><span style="color:#2ecc71;">{sup_30j_sg:.2f}</span> — <span style="color:#e74c3c;">{res_30j_sg:.2f} {dev_sg}</span></div>
                        <div class="argon-sub">Position dans le couloir 30J : <b>{pos_canal_30j:.0f}%</b></div>
                    </div>
                    <div class="argon-card" style="border-top: 3px solid {c_fv_sg};">
                        <div class="argon-title">📐 Canal Régression 3 Ans</div>
                        <div class="argon-val" style="color:{c_fv_sg}; font-size:1.15em;">{ecart_fv_pct:+.1f}% vs Fair Value</div>
                        <div class="argon-sub">Tunnel : <b>{canal_bas_full[-1]:.1f}</b> ➔ <b>{canal_haut_full[-1]:.1f} {dev_sg}</b></div>
                    </div>
                    <div class="argon-card" style="border-top: 3px solid #9b59b6;">
                        <div class="argon-title">💼 Votre PRU / Cible</div>
                        {txt_pru_card}
                    </div>
                </div>
                """
                afficher_html(html_kpi_station)

                if "Boursy Quant" in moteur_sg:
                    col_chk1, col_chk2, col_chk3, col_chk4, col_chk5 = st.columns(5)
                    aff_canal_3a = col_chk1.checkbox("📐 Canal 3 Ans (±1σ)", value=True, key="chk_sg360_c3a")
                    aff_ema = col_chk2.checkbox("⚡ Courbes EMA 2 & 12", value=True, key="chk_sg360_ema")
                    aff_sr30 = col_chk3.checkbox("🟢/🔴 Support & Résist. 30J", value=True, key="chk_sg360_sr")
                    aff_cible = col_chk4.checkbox("🎯 Prix Cible", value=True, key="chk_sg360_cib")
                    aff_pru = col_chk5.checkbox("💼 Mon PRU", value=en_pf_sg, disabled=not en_pf_sg, key="chk_sg360_pru")

                    map_nb_j_sg = {
                        "3 Mois (65 séances)": 65,
                        "6 Mois (130 séances)": 130,
                        "1 An (252 séances)": 252,
                        "3 Ans (Canal complet)": n_full,
                    }
                    nb_j_sg = min(n_full, map_nb_j_sg.get(horizon_sg, 130))
                    pas_sg = 2 if nb_j_sg > 350 else 1

                    dates_sg = pd.bdate_range(end=datetime.now(), periods=nb_j_sg)
                    lignes_vega_sg = []

                    for i_s in range(0, nb_j_sg, pas_sg):
                        idx_f = n_full - nb_j_sg + i_s
                        d_iso = dates_sg[i_s].strftime("%Y-%m-%d")
                        d_fr = dates_sg[i_s].strftime("%d/%m/%Y")

                        row_sg = {
                            "Date": d_iso,
                            "DateFR": d_fr,
                            "Cours": round(float(arr_c_full[idx_f]), 2),
                            "EMA_2": round(float(ema_rapide_full[idx_f]), 2),
                            "EMA_12": round(float(ema_lente_full[idx_f]), 2),
                            "FairValue_3A": round(float(droite_reg_full[idx_f]), 2),
                            "Canal_Haut": round(float(canal_haut_full[idx_f]), 2),
                            "Canal_Bas": round(float(canal_bas_full[idx_f]), 2),
                            "Support_30J": round(sup_30j_sg, 2),
                            "Resistance_30J": round(res_30j_sg, 2),
                            "Prix_Cible": round(cible_sg, 2),
                        }
                        if en_pf_sg and pru_sg > 0:
                            row_sg["Mon_PRU"] = round(pru_sg, 2)
                        lignes_vega_sg.append(row_sg)

                    df_sg = pd.DataFrame(lignes_vega_sg)
                    layers_sg = []

                    if aff_canal_3a:
                        layers_sg.append({
                            "mark": {"type": "area", "opacity": 0.13, "color": "#3498db"},
                            "encoding": {
                                "x": {"field": "Date", "type": "temporal"},
                                "y": {"field": "Canal_Bas", "type": "quantitative"},
                                "y2": {"field": "Canal_Haut"},
                            },
                        })
                        layers_sg.append({
                            "mark": {"type": "line", "strokeDash": [6, 4], "strokeWidth": 1.6, "color": "#3498db", "opacity": 0.8},
                            "encoding": {
                                "x": {"field": "Date", "type": "temporal"},
                                "y": {"field": "FairValue_3A", "type": "quantitative"},
                            },
                        })

                    if aff_sr30:
                        layers_sg.append({
                            "mark": {"type": "rule", "strokeDash": [4, 4], "strokeWidth": 1.8, "color": "#2ecc71"},
                            "encoding": {"y": {"field": "Support_30J", "type": "quantitative"}},
                        })
                        layers_sg.append({
                            "mark": {"type": "rule", "strokeDash": [4, 4], "strokeWidth": 1.8, "color": "#e74c3c"},
                            "encoding": {"y": {"field": "Resistance_30J", "type": "quantitative"}},
                        })

                    if aff_cible:
                        layers_sg.append({
                            "mark": {"type": "rule", "strokeDash": [2, 3], "strokeWidth": 1.8, "color": "#f39c12"},
                            "encoding": {"y": {"field": "Prix_Cible", "type": "quantitative"}},
                        })

                    if aff_pru and en_pf_sg and pru_sg > 0:
                        layers_sg.append({
                            "mark": {"type": "rule", "strokeWidth": 2.2, "color": "#9b59b6"},
                            "encoding": {"y": {"field": "Mon_PRU", "type": "quantitative"}},
                        })

                    if aff_ema:
                        layers_sg.append({
                            "mark": {"type": "line", "strokeWidth": 2.0, "color": "#f39c12", "opacity": 0.95},
                            "encoding": {
                                "x": {"field": "Date", "type": "temporal"},
                                "y": {"field": "EMA_2", "type": "quantitative"},
                            },
                        })
                        layers_sg.append({
                            "mark": {"type": "line", "strokeWidth": 2.2, "color": "#e67e22", "strokeDash": [3, 2], "opacity": 0.95},
                            "encoding": {
                                "x": {"field": "Date", "type": "temporal"},
                                "y": {"field": "EMA_12", "type": "quantitative"},
                            },
                        })

                    layers_sg.append({
                        "mark": {"type": "line", "strokeWidth": 2.8, "color": "#10b981"},
                        "encoding": {
                            "x": {"field": "Date", "type": "temporal", "axis": {"title": None, "format": "%b %Y", "grid": False}},
                            "y": {
                                "field": "Cours",
                                "type": "quantitative",
                                "scale": {"zero": False, "padding": 25},
                                "axis": {"title": f"Cours ({dev_sg})", "format": ",.1f"},
                            },
                            "tooltip": [
                                {"field": "DateFR", "type": "nominal", "title": "📅 Séance"},
                                {"field": "Cours", "type": "quantitative", "title": f"🏷️ Cours ({dev_sg})", "format": ",.2f"},
                                {"field": "EMA_2", "type": "quantitative", "title": "⚡ EMA Rapide (2)", "format": ",.2f"},
                                {"field": "EMA_12", "type": "quantitative", "title": "📈 EMA Lente (12)", "format": ",.2f"},
                                {"field": "FairValue_3A", "type": "quantitative", "title": "📐 Fair Value 3A", "format": ",.2f"},
                                {"field": "Support_30J", "type": "quantitative", "title": "🟢 Support 30J", "format": ",.2f"},
                                {"field": "Resistance_30J", "type": "quantitative", "title": "🔴 Résistance 30J", "format": ",.2f"},
                                {"field": "Prix_Cible", "type": "quantitative", "title": "🎯 Prix Cible", "format": ",.2f"},
                            ],
                        },
                    })

                    spec_station_vega = {
                        "height": 500,
                        "layer": layers_sg,
                        "view": {"stroke": None},
                    }
                    st.vega_lite_chart(df_sg, spec_station_vega, width="stretch")

                    afficher_html(f"""
                    <div style="display:flex; flex-wrap:wrap; gap:14px; justify-content:center; font-size:0.80em; padding:8px 12px; background:rgba(128,128,128,0.04); border-radius:8px; margin-top:-6px;">
                        <span><b style="color:#10b981;">━━</b> Cours ({cours_act_sg:.2f} {dev_sg})</span>
                        <span><b style="color:#f39c12;">━━</b> EMA Rapide 2J ({ema_rapide_full[-1]:.2f})</span>
                        <span><b style="color:#e67e22;">╍╍</b> EMA Lente 12J ({ema_lente_full[-1]:.2f})</span>
                        <span><b style="color:#3498db;">▒▒</b> Canal Régression 3A ({canal_bas_full[-1]:.1f} - {canal_haut_full[-1]:.1f})</span>
                        <span><b style="color:#2ecc71;">┈┈</b> Support 30J ({sup_30j_sg:.2f})</span>
                        <span><b style="color:#e74c3c;">┈┈</b> Résistance 30J ({res_30j_sg:.2f})</span>
                        <span><b style="color:#f39c12;">┈┈</b> Cible ({cible_sg:.2f})</span>
                        {f'<span><b style="color:#9b59b6;">━━</b> Mon PRU ({pru_sg:.2f} {dev_sg})</span>' if (en_pf_sg and pru_sg > 0) else ''}
                    </div>
                    """)

                else:
                    import streamlit.components.v1 as components

                    sym_up = sym_sg.upper().strip()
                    if sym_up.endswith(".PA") or sym_up.endswith(".AS") or sym_up.endswith(".BR") or sym_up.endswith(".LS"):
                        tv_symbol = "EURONEXT:" + sym_up.split(".")[0]
                    elif sym_up.endswith(".DE"):
                        tv_symbol = "XETR:" + sym_up.split(".")[0]
                    elif sym_up.endswith(".MI"):
                        tv_symbol = "MIL:" + sym_up.split(".")[0]
                    elif sym_up.endswith(".MC"):
                        tv_symbol = "BME:" + sym_up.split(".")[0]
                    elif sym_up.endswith(".L"):
                        tv_symbol = "LSE:" + sym_up.split(".")[0]
                    else:
                        tv_symbol = sym_up.split(".")[0]

                    tv_html = f"""
                    <div class="tradingview-widget-container" style="border-radius:12px; overflow:hidden; border:1px solid rgba(128,128,128,0.2);">
                      <div id="tv_chart_boursy" style="height:520px;"></div>
                      <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
                      <script type="text/javascript">
                      new TradingView.widget({{
                        "autosize": true,
                        "symbol": "{tv_symbol}",
                        "interval": "D",
                        "timezone": "Europe/Paris",
                        "theme": "dark",
                        "style": "1",
                        "locale": "fr",
                        "toolbar_bg": "#0f172a",
                        "enable_publishing": false,
                        "withdateranges": true,
                        "hide_side_toolbar": false,
                        "allow_symbol_change": true,
                        "studies": [
                          "Moving Average@tv-basicstudies",
                          "Moving Average@tv-basicstudies",
                          "RSI@tv-basicstudies",
                          "MACD@tv-basicstudies"
                        ],
                        "container_id": "tv_chart_boursy"
                      }});
                      </script>
                    </div>
                    """
                    components.html(tv_html, height=535)
                    st.caption(nombres_fr(f"💡 Terminal TradingView synchronisé sur **{tv_symbol}** avec indicateurs pré-chargés. Repères Boursy : Support 30J = **{sup_30j_sg:.2f} {dev_sg}** | Résistance 30J = **{res_30j_sg:.2f} {dev_sg}** | Cible = **{cible_sg:.2f} {dev_sg}**."))
except Exception as e_pack:
    st.warning(f"Initialisation du Super-Pack Pro V2 ({e_pack})")


# ==============================================================================
# PIED DE PAGE : MENTIONS LÉGALES, CGV, DROIT DE RÉTRACTATION & CONFORMITÉ AMF (NON-CIF) — textes dans pages_legales.py
# ==============================================================================
# Identité de l'éditeur (obligatoire, loi LCEN) : à renseigner dans les secrets Streamlit
afficher_pages_legales(_lire_secret("EDITEUR_NOM"), _lire_secret("EDITEUR_SIRET"), _lire_secret("EDITEUR_ADRESSE"), CONTACT_EMAIL)
