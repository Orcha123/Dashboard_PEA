import urllib.request
import urllib.error
import urllib.parse
import io
import json
import math
import re
import smtplib
import time
from concurrent.futures import ThreadPoolExecutor
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import pandas as pd
import streamlit as st
from supabase import create_client

# ==============================================================================
# CONFIGURATION DE LA PAGE & DESIGN ARGON UI
# ==============================================================================
st.set_page_config(
    page_title="Boursy - Suite Boursière PEA, US & Dividendes",
    page_icon="📈",
    layout="wide",
)

CLES_TECHNIQUES_PF = ("Espèces", "_historique_ventes", "_quota_ia", "_niveau_abo", "_div_encaisses_cumul", "_stripe_customer_id", "_alertes_auto", "_alertes_envoyees", "_journal_achats")


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
    - Sinon, repli sur l'adresse e-mail du compte connecté.
    """
    if user is None:
        return False
    id_admin = _lire_secret("ADMIN_USER_ID")
    if id_admin:
        return str(getattr(user, "id", "")) == id_admin
    if not ADMIN_EMAIL:
        return False
    return str(getattr(user, "email", "") or "").lower() == ADMIN_EMAIL.lower()
_MOTIF_NOMBRE_FR = re.compile(r"(?<![\w.,/])(?<!IA )(?<!Boursy )(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d+)(?!\w|[.,/]\d)")


def nombres_fr(texte):
    """
    Met les nombres d'un texte au format français : 11,709.45 -> 11 709,45 (espace insécable et virgule décimale).
    Seul le texte affiché est touché : les balises HTML, leurs attributs et les blocs <style>/<script> restent intacts.
    """
    if not isinstance(texte, str) or not texte:
        return texte
    morceaux = re.split(r"(<[^>]+>)", texte)
    hors_texte = False
    for i_m, morceau in enumerate(morceaux):
        if morceau.startswith("<"):
            debut_balise = morceau[1:8].lower()
            if debut_balise.startswith(("style", "script")):
                hors_texte = True
            elif debut_balise.startswith(("/style", "/script")):
                hors_texte = False
        elif not hors_texte:
            morceaux[i_m] = _MOTIF_NOMBRE_FR.sub(lambda m: m.group(1).replace(",", "\u00a0").replace(".", ","), morceau)
    return "".join(morceaux)


def markdown_fr(texte, **options):
    """st.markdown avec les nombres au format français."""
    st.markdown(nombres_fr(texte), **options)


def afficher_html(html_brut):
    """Supprime les indentations pour empêcher Streamlit d'afficher le HTML en bloc de code."""
    html_propre = "\n".join(ligne.strip() for ligne in html_brut.splitlines() if ligne.strip())
    # Chaque tableau est placé dans un cadre défilant : lisible sur mobile sans élargir toute la page
    html_propre = re.sub(r"<table\s+class=(['\"])r-table\1", r'<div class="r-wrap"><table class="r-table"', html_propre)
    html_propre = html_propre.replace("</table>", "</table></div>")
    st.markdown(nombres_fr(html_propre), unsafe_allow_html=True)

STYLE_ARGON = """
<style>
[data-testid="stToolbarActions"], .stAppDeployButton { display: none !important; }
.argon-grid { display: flex; gap: 15px; margin: 10px 0 22px 0; flex-wrap: wrap; font-family: 'Segoe UI', Roboto, Helvetica, sans-serif; }
.argon-card { flex: 1; min-width: 200px; background: linear-gradient(145deg, rgba(128,128,128,0.06) 0%, rgba(128,128,128,0.02) 100%); border: 1px solid rgba(128,128,128,0.22); border-radius: 14px; padding: 16px 18px; box-shadow: 0 4px 15px rgba(0,0,0,0.04); text-align: center; }
.argon-title { font-size: 0.76em; text-transform: uppercase; letter-spacing: 0.8px; opacity: 0.75; margin-bottom: 6px; font-weight: 800; }
.argon-val { font-size: 1.55em; font-weight: 900; margin-bottom: 5px; }
.argon-sub { font-size: 0.83em; font-weight: 600; opacity: 0.88; }
.meteo-bar { display: flex; gap: 12px; margin-bottom: 18px; flex-wrap: wrap; font-family: 'Segoe UI', sans-serif; }
.meteo-item { flex: 1; min-width: 180px; background: rgba(128,128,128,0.04); border-left: 4px solid #3498db; border-radius: 8px; padding: 10px 14px; display: flex; justify-content: space-between; align-items: center; border-top: 1px solid rgba(128,128,128,0.12); border-right: 1px solid rgba(128,128,128,0.12); border-bottom: 1px solid rgba(128,128,128,0.12); }
.r-table { width: 100%; border-collapse: collapse; font-family: 'Segoe UI', sans-serif; margin-bottom: 22px; font-size: 0.92em; }
.r-table th { border-bottom: 2px solid rgba(128,128,128,0.3); padding: 12px 8px; text-align: center; font-weight: 800; text-transform: uppercase; font-size: 0.79em; letter-spacing: 0.5px; background-color: rgba(128,128,128,0.06); }
.r-table td { border-bottom: 1px solid rgba(128,128,128,0.14); padding: 11px 8px; text-align: center; vertical-align: middle; }
.r-name { font-weight: 800; font-size: 1.01em; text-align: left !important; }
.b-green { background: rgba(46,204,113,0.18); color: #2ecc71; padding: 4px 9px; border-radius: 6px; font-weight: 700; display: inline-block; font-size: 0.88em; }
.b-blue { background: rgba(52,152,219,0.18); color: #3498db; padding: 4px 9px; border-radius: 6px; font-weight: 700; display: inline-block; font-size: 0.88em; }
.b-yellow { background: rgba(241,196,15,0.18); color: #f39c12; padding: 4px 9px; border-radius: 6px; font-weight: 700; display: inline-block; font-size: 0.88em; }
.b-orange { background: rgba(230,126,34,0.18); color: #e67e22; padding: 4px 9px; border-radius: 6px; font-weight: 700; display: inline-block; font-size: 0.88em; }
.b-red { background: rgba(231,76,60,0.18); color: #e74c3c; padding: 4px 9px; border-radius: 6px; font-weight: 700; display: inline-block; font-size: 0.88em; }
.b-purple { background: rgba(155,89,182,0.18); color: #9b59b6; padding: 4px 9px; border-radius: 6px; font-weight: 700; display: inline-block; font-size: 0.88em; }
.b-neutral { background: rgba(128,128,128,0.15); opacity: 0.9; padding: 4px 9px; border-radius: 6px; font-weight: 700; display: inline-block; font-size: 0.88em; }
.score-bg { width: 100%; background: rgba(128,128,128,0.2); height: 8px; border-radius: 4px; overflow: hidden; margin-top: 5px; }
.cal-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 14px; margin: 15px 0 25px 0; font-family: 'Segoe UI', sans-serif; }
.cal-card { background: rgba(128,128,128,0.04); border: 1px solid rgba(128,128,128,0.2); border-radius: 12px; padding: 14px; display: flex; flex-direction: column; justify-content: space-between; min-height: 125px; }
.cal-card-active { background: linear-gradient(145deg, rgba(46,204,113,0.10) 0%, rgba(52,152,219,0.05) 100%); border: 1px solid rgba(46,204,113,0.38); border-radius: 12px; padding: 14px; display: flex; flex-direction: column; justify-content: space-between; min-height: 125px; }
.cal-month { font-size: 0.92em; font-weight: 800; text-transform: uppercase; letter-spacing: 0.6px; opacity: 0.85; border-bottom: 1px solid rgba(128,128,128,0.15); padding-bottom: 6px; margin-bottom: 8px; display: flex; justify-content: space-between; align-items: center; }
.cal-total { font-size: 1.25em; font-weight: 900; color: #2ecc71; }
.cal-pill { display: inline-block; background: rgba(128,128,128,0.13); border-radius: 5px; padding: 3px 7px; font-size: 0.80em; font-weight: 600; margin: 2px 3px 2px 0; }
.ia-box { background: linear-gradient(145deg, rgba(155,89,182,0.08) 0%, rgba(52,152,219,0.06) 100%); border: 1px solid rgba(155,89,182,0.32); border-radius: 14px; padding: 20px 24px; margin-top: 15px; font-family: 'Segoe UI', sans-serif; }
.ia-flash { background: linear-gradient(135deg, rgba(46,204,113,0.10) 0%, rgba(52,152,219,0.10) 100%); border-left: 4px solid #2ecc71; border-radius: 10px; padding: 14px 18px; margin: 6px 0 20px 0; font-family: 'Segoe UI', sans-serif; font-size: 0.95em; line-height: 1.5; border-top: 1px solid rgba(128,128,128,0.15); border-right: 1px solid rgba(128,128,128,0.15); border-bottom: 1px solid rgba(128,128,128,0.15); }
.goal-box { background: linear-gradient(145deg, rgba(46,204,113,0.07) 0%, rgba(52,152,219,0.07) 100%); border: 1px solid rgba(46,204,113,0.32); border-radius: 14px; padding: 18px 22px; margin: 8px 0 24px 0; font-family: 'Segoe UI', sans-serif; }
.goal-bar-bg { width: 100%; background: rgba(128,128,128,0.22); height: 16px; border-radius: 10px; overflow: hidden; margin: 10px 0 14px 0; box-shadow: inset 0 1px 3px rgba(0,0,0,0.2); }
.goal-steps { display: flex; gap: 10px; flex-wrap: wrap; justify-content: space-between; margin-top: 8px; }
.goal-step { flex: 1; min-width: 120px; border-radius: 9px; padding: 8px 10px; text-align: center; font-size: 0.84em; font-weight: 700; border: 1px solid rgba(128,128,128,0.2); background: rgba(128,128,128,0.04); }

/* ===== HABILLAGE BOURSY 3.0 : fond, en-tête, cartes, tableaux défilants, onglets, mobile ===== */
:root { --bz-vert: #10b981; --bz-bleu: #3b82f6; --bz-carte: rgba(148,163,184,0.07); --bz-bord: rgba(148,163,184,0.20); --bz-police: Inter, "Segoe UI", system-ui, -apple-system, Roboto, "Helvetica Neue", Arial, sans-serif; }
.stApp { background-image: radial-gradient(1100px 520px at 8% -8%, rgba(16,185,129,0.11), transparent 60%), radial-gradient(900px 480px at 100% 0%, rgba(59,130,246,0.10), transparent 55%); background-attachment: fixed; }
[data-testid="stMainBlockContainer"], .block-container { padding-top: 4.2rem; max-width: 1500px; }
[data-testid="stSidebar"] { border-right: 1px solid var(--bz-bord); }
.argon-grid, .meteo-bar, .r-table, .cal-grid, .ia-box, .ia-flash, .goal-box { font-family: var(--bz-police); }
.argon-val, .cal-total, .r-table td, .meteo-item { font-variant-numeric: tabular-nums; }

.bz-hero { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; padding: 18px 22px; margin: 0 0 16px 0; border-radius: 18px; border: 1px solid var(--bz-bord); background: linear-gradient(120deg, rgba(16,185,129,0.16) 0%, rgba(59,130,246,0.12) 55%, rgba(148,163,184,0.04) 100%); font-family: var(--bz-police); }
.bz-logo { width: 52px; height: 52px; border-radius: 14px; display: flex; align-items: center; justify-content: center; background: linear-gradient(135deg, #10b981 0%, #3b82f6 100%); box-shadow: 0 8px 22px rgba(16,185,129,0.30); flex: 0 0 auto; }
.bz-nom { font-size: 1.75em; font-weight: 900; letter-spacing: -0.03em; line-height: 1.1; }
.bz-slogan { font-size: 0.92em; opacity: 0.78; font-weight: 600; margin-top: 3px; }
.bz-hero-droite { margin-left: auto; display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
.bz-puce { display: inline-flex; align-items: center; gap: 7px; padding: 6px 12px; border-radius: 999px; font-size: 0.80em; font-weight: 700; border: 1px solid var(--bz-bord); background: rgba(148,163,184,0.08); white-space: nowrap; }
.bz-point { width: 8px; height: 8px; border-radius: 50%; background: var(--bz-vert); box-shadow: 0 0 0 4px rgba(16,185,129,0.18); }

.argon-card { border-radius: 16px; border-color: var(--bz-bord); background: linear-gradient(160deg, rgba(148,163,184,0.10) 0%, rgba(148,163,184,0.03) 100%); box-shadow: 0 6px 20px rgba(0,0,0,0.10); transition: transform 0.15s ease, box-shadow 0.15s ease, border-color 0.15s ease; }
.argon-card:hover { transform: translateY(-2px); box-shadow: 0 12px 28px rgba(0,0,0,0.18); border-color: rgba(16,185,129,0.45); }
.argon-val { letter-spacing: -0.02em; }
.meteo-item { border-radius: 12px; background: var(--bz-carte); }
.cal-card, .cal-card-active { border-radius: 14px; }

.r-wrap { overflow-x: auto; border: 1px solid var(--bz-bord); border-radius: 14px; margin-bottom: 22px; background: rgba(148,163,184,0.04); -webkit-overflow-scrolling: touch; }
.r-wrap .r-table { margin-bottom: 0; }
.r-table th { white-space: nowrap; }
.r-table tbody tr { transition: background 0.12s ease; }
.r-table tbody tr:hover { background: rgba(148,163,184,0.09); }
.r-table tbody tr:last-child td { border-bottom: none; }

[data-testid="stTabs"] [role="tablist"] { gap: 8px; flex-wrap: wrap; row-gap: 8px; }
[data-testid="stTabs"] [role="tab"] { border-radius: 999px; padding: 7px 15px; height: auto; border: 1px solid var(--bz-bord); background: var(--bz-carte); transition: background 0.12s ease, border-color 0.12s ease; }
[data-testid="stTabs"] [role="tab"]:hover { border-color: rgba(16,185,129,0.50); }
[data-testid="stTabs"] [role="tab"][aria-selected="true"] { background: rgba(16,185,129,0.16); border-color: rgba(16,185,129,0.60); }
[data-testid="stTabs"] [data-baseweb="tab-highlight"], [data-testid="stTabs"] [data-baseweb="tab-border"], [data-testid="stTabs"] .react-aria-SelectionIndicator, [data-testid="stTabs"] [role="tablist"]::after { display: none !important; }
[data-testid="stTabs"] [role="tablist"] { margin-bottom: 14px; }
.bz-5 .argon-card { min-width: 165px; }

[data-testid="stExpander"] details { border-radius: 14px; border-color: var(--bz-bord); background: rgba(148,163,184,0.04); }
.stButton > button, .stDownloadButton > button, .stLinkButton > a, .stFormSubmitButton > button { border-radius: 10px; font-weight: 600; }

@media (max-width: 760px) {
    [data-testid="stMainBlockContainer"], .block-container { padding-left: 0.9rem; padding-right: 0.9rem; padding-top: 3.8rem; }
    .bz-hero { padding: 14px 16px; }
    .bz-nom { font-size: 1.4em; }
    .bz-hero-droite { margin-left: 0; }
    .argon-grid { gap: 10px; }
    .argon-card { min-width: 44%; padding: 13px 12px; }
    .argon-val { font-size: 1.22em; }
    .meteo-item { min-width: 44%; }
    .r-wrap .r-table { min-width: 680px; font-size: 0.86em; }
    .cal-grid { grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); }
}
</style>
"""
afficher_html(STYLE_ARGON)

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

def _stripe_get(chemin, cle_stripe):
    """Appel GET authentifié à l'API Stripe (lève une exception en cas d'erreur HTTP ou réseau)."""
    req = urllib.request.Request(
        f"https://api.stripe.com/v1/{chemin}",
        headers={"Authorization": f"Bearer {cle_stripe}"},
    )
    with urllib.request.urlopen(req, timeout=8) as resp:
        return json.loads(resp.read().decode("utf-8"))


def creer_session_portail_stripe(id_client):
    """
    Ouvre une session du portail client Stripe pour ce client et renvoie son adresse (valable quelques minutes).
    Contrairement au lien de connexion du portail, aucun e-mail n'est nécessaire : l'abonné arrive directement
    sur sa page de gestion (résiliation, factures, moyen de paiement). None si impossible.
    """
    cle_stripe = _lire_secret("STRIPE_SECRET_KEY")
    if not cle_stripe or not (isinstance(id_client, str) and id_client.startswith("cus_")):
        return None
    champs = {"customer": id_client}
    adresse_retour = _lire_secret("APP_URL")
    if not adresse_retour:
        try:
            adresse_retour = str(st.context.url or "").split("?")[0]
        except Exception:
            adresse_retour = ""
    if adresse_retour.startswith("http"):
        champs["return_url"] = adresse_retour
    req = urllib.request.Request(
        "https://api.stripe.com/v1/billing_portal/sessions",
        data=urllib.parse.urlencode(champs).encode("utf-8"),
        headers={"Authorization": f"Bearer {cle_stripe}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            return json.loads(resp.read().decode("utf-8")).get("url")
    except Exception:
        return None


def _ids_prix_stripe(nom_secret):
    """Identifiants de prix Stripe (price_...) déclarés dans un secret, séparés par des virgules."""
    return {p.strip() for p in _lire_secret(nom_secret).split(",") if p.strip()}


def _palier_depuis_abonnement_stripe(sub):
    """
    Déduit le palier ('premium' ou 'pro') d'un abonnement Stripe.
    - Fiable : par identifiant de prix, via les secrets STRIPE_PRICE_PREMIUM et STRIPE_PRICE_PRO.
    - Repli (si ces secrets sont absents) : par montant RAMENÉ AU MOIS (un abonnement annuel est divisé par 12),
      <= 6,00 EUR/mois = Premium, au-delà = Pro. Un montant inconnu ou nul donne Premium (jamais Pro par défaut).
    """
    prix_premium = _ids_prix_stripe("STRIPE_PRICE_PREMIUM")
    prix_pro = _ids_prix_stripe("STRIPE_PRICE_PRO")
    palier = None
    for ligne in ((sub.get("items") or {}).get("data") or []):
        prix = ligne.get("price") or {}
        id_prix = str(prix.get("id") or "")
        if id_prix and id_prix in prix_pro:
            palier_ligne = "pro"
        elif id_prix and id_prix in prix_premium:
            palier_ligne = "premium"
        else:
            try:
                montant_cts = float(prix.get("unit_amount") or prix.get("unit_amount_decimal") or 0)
            except Exception:
                montant_cts = 0.0
            recurrence = prix.get("recurring") or {}
            try:
                nb_periodes = max(1, int(recurrence.get("interval_count") or 1))
            except Exception:
                nb_periodes = 1
            mois_par_periode = {"day": 1.0 / 30.0, "week": 12.0 / 52.0, "month": 1.0, "year": 12.0}.get(
                str(recurrence.get("interval") or "month"), 1.0
            )
            montant_mensuel_cts = montant_cts / (mois_par_periode * nb_periodes)
            palier_ligne = "pro" if montant_mensuel_cts > 600 else "premium"
        if palier_ligne == "pro":
            return "pro"
        palier = palier_ligne
    return palier or "premium"


def _fin_programmee_abonnement_stripe(sub):
    """Date (JJ/MM/AAAA) de fin d'accès si une résiliation est programmée, sinon None."""
    if not (sub.get("cancel_at_period_end") or sub.get("cancel_at")):
        return None
    ts_fin = sub.get("cancel_at") or sub.get("current_period_end")
    if not ts_fin:
        # Versions récentes de l'API Stripe : la fin de période est portée par les lignes de l'abonnement
        lignes = (sub.get("items") or {}).get("data") or []
        if lignes:
            ts_fin = lignes[0].get("current_period_end")
    try:
        return datetime.fromtimestamp(int(ts_fin)).strftime("%d/%m/%Y") if ts_fin else None
    except Exception:
        return None


def _etat_abonnements_client_stripe(id_client, cle_stripe):
    """(palier, date_fin_programmée) du meilleur abonnement actif d'un client Stripe ; (None, None) si aucun."""
    try:
        data_sub = _stripe_get(
            f"subscriptions?customer={urllib.parse.quote(str(id_client))}&status=all&limit=10", cle_stripe
        )
    except urllib.error.HTTPError as err_http:
        if err_http.code in (400, 404):  # client Stripe supprimé ou inconnu : aucun abonnement
            return None, None
        raise
    palier, date_fin = None, None
    for sub in data_sub.get("data", []):
        if sub.get("status") not in ("active", "trialing"):
            continue
        if palier != "pro":
            palier = _palier_depuis_abonnement_stripe(sub)
            date_fin = _fin_programmee_abonnement_stripe(sub)
    return palier, date_fin


def _clients_stripe_par_reference(user_id, cle_stripe):
    """
    Clients Stripe ayant finalisé un paiement lancé depuis CE compte Boursy.
    Les liens de paiement transportent client_reference_id = UUID du compte : l'abonné est donc retrouvé
    même s'il a payé avec une autre adresse e-mail que celle de son compte.
    """
    try:
        try:
            data_cs = _stripe_get("checkout/sessions?limit=100&status=complete", cle_stripe)
        except urllib.error.HTTPError:
            data_cs = _stripe_get("checkout/sessions?limit=100", cle_stripe)
    except Exception:
        return []
    trouves = []
    for cs in data_cs.get("data", []):
        if cs.get("status") == "complete" and str(cs.get("client_reference_id") or "") == str(user_id):
            id_c = cs.get("customer")
            if isinstance(id_c, dict):
                id_c = id_c.get("id")
            if id_c and id_c not in trouves:
                trouves.append(id_c)
    return trouves


def verifier_abonnement_stripe(email_client, user_id=None, id_client_memorise=None):
    """
    Vérifie en direct sur Stripe l'état de l'abonnement du client. Retourne :
    - {"niveau": "premium" | "pro" | "gratuit", "fin": date de fin programmée ou None, "client_id": "cus_..." ou None} ;
    - None si la clé Stripe n'est pas configurée ou en cas d'erreur réseau (rien n'est alors conclu).

    Le client Stripe est recherché dans cet ordre :
    1. identifiant client mémorisé dans la table protégée « abonnements » ;
    2. adresse e-mail du compte ;
    3. paiements portant le client_reference_id du compte (paiement fait avec une autre adresse).
    """
    cle_stripe = _lire_secret("STRIPE_SECRET_KEY")
    if not email_client or not cle_stripe:
        return None
    uid = str(user_id) if user_id else ""
    try:
        ids_clients = []

        # 1. Identifiant mémorisé dans la table protégée (jamais dans le portefeuille, que l'utilisateur peut modifier)
        if isinstance(id_client_memorise, str) and id_client_memorise.startswith("cus_"):
            ids_clients.append(id_client_memorise)

        # 2. Recherche par adresse e-mail
        data_cust = _stripe_get(f"customers?email={urllib.parse.quote(email_client.strip())}&limit=5", cle_stripe)
        for client in data_cust.get("data", []):
            id_c = client.get("id")
            if id_c and id_c not in ids_clients:
                ids_clients.append(id_c)

        meilleur_palier, date_fin_programmee, id_retenu = None, None, None

        def _evaluer(id_c):
            nonlocal meilleur_palier, date_fin_programmee, id_retenu
            palier_c, fin_c = _etat_abonnements_client_stripe(id_c, cle_stripe)
            if palier_c and meilleur_palier != "pro":
                meilleur_palier, date_fin_programmee, id_retenu = palier_c, fin_c, id_c

        for id_c in ids_clients:
            _evaluer(id_c)

        # 3. Aucun abonnement trouvé : recherche par référence de compte
        if meilleur_palier is None and uid:
            for id_c in _clients_stripe_par_reference(uid, cle_stripe):
                if id_c not in ids_clients:
                    ids_clients.append(id_c)
                    _evaluer(id_c)

        if meilleur_palier in ("premium", "pro"):
            return {"niveau": meilleur_palier, "fin": date_fin_programmee, "client_id": id_retenu}
        return {"niveau": "gratuit", "fin": None, "client_id": None}
    except Exception:
        return None


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
    client = st.session_state.get("_supabase_client")
    if client is None or user is None:
        return None
    try:
        rep_abo = client.table("abonnements").select("niveau, stripe_customer_id, fin_programmee").eq("user_id", str(user.id)).execute()
        return dict(rep_abo.data[0]) if rep_abo.data else {}
    except Exception:
        return None


def enregistrer_abonnement_protege(user_id, niveau, client_id, fin):
    """Écrit le niveau vérifié sur Stripe dans la table abonnements. Retourne False si la clé de service manque."""
    client_serveur = init_supabase_serveur()
    if client_serveur is None:
        return False
    try:
        client_serveur.table("abonnements").upsert({
            "user_id": str(user_id),
            "niveau": niveau,
            "stripe_customer_id": client_id,
            "fin_programmee": fin,
            "verifie_le": datetime.now().astimezone().isoformat(),
        }).execute()
        return True
    except Exception:
        return False


def supprimer_compte_utilisateur(user):
    """
    Efface définitivement un compte : snapshots, données de portefeuille, abonnement, puis le compte de connexion.
    Nécessite la clé de service. Retourne (succès, message d'erreur éventuel).
    """
    client_serveur = init_supabase_serveur()
    if client_serveur is None or user is None:
        return False, "La suppression automatique n'est pas disponible pour le moment. Écrivez-nous à l'adresse de contact des mentions légales."
    uid = str(user.id)
    try:
        for table_a_vider in ("portfolio_history", "user_data", "abonnements"):
            client_serveur.table(table_a_vider).delete().eq("user_id", uid).execute()
        client_serveur.auth.admin.delete_user(uid)
        return True, ""
    except Exception as erreur_suppr:
        return False, f"La suppression n'a pas pu aboutir ({erreur_suppr}). Réessayez ou écrivez-nous à l'adresse de contact des mentions légales."


def etablir_niveau_abonnement(user, verifier_stripe=True):
    """
    Fixe le niveau d'abonnement de la session à partir de sources fiables uniquement :
    compte administrateur, puis Stripe (si configuré et joignable), sinon la table protégée « abonnements ».
    Retourne le niveau retenu ("gratuit", "premium" ou "pro").
    """
    if user is None:
        return "gratuit"
    st.session_state["_stripe_sync_session_ok"] = True
    if est_compte_admin(user):
        st.session_state.update(est_abonne_pro=True, niveau_abonnement="pro", abo_fin_periode=None)
        return "pro"

    ligne = lire_abonnement_protege(user) or {}
    niveau = ligne.get("niveau") if ligne.get("niveau") in ("gratuit", "premium", "pro") else "gratuit"
    fin = ligne.get("fin_programmee")
    st.session_state["_stripe_client_id"] = ligne.get("stripe_customer_id")

    if verifier_stripe:
        verdict = verifier_abonnement_stripe(str(user.email or "").lower(), user.id, ligne.get("stripe_customer_id"))
        if verdict is not None:
            client_id = verdict["client_id"] or ligne.get("stripe_customer_id")
            if (verdict["niveau"], verdict["fin"], client_id) != (niveau, fin, ligne.get("stripe_customer_id")):
                enregistrer_abonnement_protege(user.id, verdict["niveau"], client_id, verdict["fin"])
            niveau, fin = verdict["niveau"], verdict["fin"]
            st.session_state["_stripe_client_id"] = client_id

    st.session_state.update(est_abonne_pro=(niveau != "gratuit"), niveau_abonnement=niveau, abo_fin_periode=fin)
    return niveau
def envoyer_email_alerte(destinataire, liste_alertes):
    smtp_user = _lire_secret("SMTP_EMAIL")
    smtp_pass = _lire_secret("SMTP_PASSWORD")
    if not smtp_user or not smtp_pass:
        return False, "Pour activer l'envoi d'emails, ajoutez `SMTP_EMAIL` et `SMTP_PASSWORD` dans vos Secrets Streamlit."

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"🔔 Boursy — {len(liste_alertes)} Alerte(s) Prix Cible & Signaux"
        msg["From"] = smtp_user
        msg["To"] = destinataire

        lignes_html = "".join(
            f"<li style='margin-bottom:8px;'><b>{a['Actif']}</b> : Cours <b>{a['Prix']}</b> (Cible : {a['Cible']}) — Score : <b>{a['Score']}/100</b> ({a['Motif']})</li>"
            for a in liste_alertes
        )
        corps_html = f"""
        <html><body style="font-family: Arial, sans-serif; color: #2c3e50;">
            <h2>📈 Rapport d'Alertes Boursy ({datetime.now().strftime('%d/%m/%Y')})</h2>
            <p>Votre radar a relevé les signaux suivants (information statistique, pas un conseil en investissement) :</p>
            <ul>{lignes_html}</ul>
            <p><a href="https://boursy.streamlit.app" style="background:#2ecc71; color:white; padding:10px 16px; text-decoration:none; border-radius:6px; font-weight:bold;">Ouvrir mon Dashboard Boursy</a></p>
        </body></html>
        """
        msg.attach(MIMEText(corps_html, "html", "utf-8"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=10) as server:
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, destinataire, msg.as_string())
        return True, f"✅ Email d'alerte envoyé avec succès à {destinataire} !"
    except Exception as e:
        return False, f"Erreur SMTP : {e}"

# ==============================================================================
# TAUX DE CHANGE & MÉTÉO DES MARCHÉS (CAC 40, S&P 500, VIX)
# ==============================================================================
HEADERS_YAHOO_PRO = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
}

# ------------------------------------------------------------------------------
# FRAÎCHEUR DES COURS : toutes les 5 minutes en séance, toutes les heures marchés fermés
# ------------------------------------------------------------------------------
RAFRAICHISSEMENT_SEANCE_SECONDES = 300


def heure_paris():
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Europe/Paris"))
    except Exception:
        return datetime.now()


def marches_ouverts():
    """Vrai du lundi au vendredi entre l'ouverture de Paris (9h00) et la clôture de New York (22h05), heure de Paris."""
    maintenant = heure_paris()
    minutes = maintenant.hour * 60 + maintenant.minute
    return maintenant.weekday() < 5 and 9 * 60 <= minutes < 22 * 60 + 5


def creneau_cours():
    """
    Étiquette du créneau de cours en vigueur. Les lectures Yahoo sont mises en cache PAR créneau :
    un nouveau créneau toutes les 5 minutes en séance (cours rafraîchis), toutes les heures sinon.
    """
    instant = int(time.time())
    if marches_ouverts():
        return f"S{instant // RAFRAICHISSEMENT_SEANCE_SECONDES}"
    return f"F{instant // 3600}"


@st.cache_data(ttl=7200, max_entries=64)
def heure_maj_cours(creneau):
    """Heure (Paris) à laquelle les cours du créneau ont été lus pour la première fois."""
    return heure_paris().strftime("%H:%M")


@st.cache_data(ttl=1800, max_entries=32)
def _taux_change_yahoo(creneau):
    """Taux EUR/USD lu sur Yahoo. Lève une erreur en cas d'échec : un échec n'est ainsi jamais mis en cache."""
    for srv in ("query1", "query2"):
        try:
            url = f"https://{srv}.finance.yahoo.com/v8/finance/chart/EURUSD=X?range=1d&interval=1d"
            req = urllib.request.Request(url, headers=HEADERS_YAHOO_PRO)
            with urllib.request.urlopen(req, timeout=5) as response:
                data = json.loads(response.read().decode("utf-8"))
                taux = float(data["chart"]["result"][0]["meta"]["regularMarketPrice"])
                if taux > 0:
                    return taux
        except Exception:
            continue
    raise RuntimeError("Taux EUR/USD indisponible")


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
    for srv in ("query1", "query2"):
        try:
            url = f"https://{srv}.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbole)}?range=5d&interval=1d"
            req = urllib.request.Request(url, headers=HEADERS_YAHOO_PRO)
            with urllib.request.urlopen(req, timeout=5) as response:
                data = json.loads(response.read().decode("utf-8"))
                res = data["chart"]["result"][0]
                prix = float(res["meta"]["regularMarketPrice"])
                closes = [float(c) for c in res["indicators"]["quote"][0]["close"] if c is not None]
                veille = closes[-2] if len(closes) >= 2 else float(res["meta"].get("chartPreviousClose", prix))
                var_pct = ((prix - veille) / veille * 100.0) if veille > 0 else 0.0
                return prix, var_pct
        except Exception:
            continue
    raise RuntimeError(f"Indice indisponible : {symbole}")

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
            if pf_a_sauver.get("_alertes_auto"):
                try:
                    res_al = supabase.table("user_data").select("portefeuille").eq("user_id", user_id_str).execute()
                    pf_al = (res_al.data[0].get("portefeuille") or {}) if res_al.data else {}
                    if isinstance(pf_al, dict) and isinstance(pf_al.get("_alertes_envoyees"), list):
                        pf_a_sauver["_alertes_envoyees"] = pf_al["_alertes_envoyees"]
                        st.session_state["portefeuille"]["_alertes_envoyees"] = pf_al["_alertes_envoyees"]
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
ENRICHISSEMENT_CATALOGUE = {
    # Actions Françaises (CAC 40 & SBF 120 - PEA)
    "Air Liquide": ("AI.PA", "EUR", "Chimie/Industrie", 165.0, 3.20, 0.55, "+8.5%", ["Mai"]),
    "Airbus": ("AIR.PA", "EUR", "Aéronautique/Défense", 145.0, 2.00, 0.35, "+6.5%", ["Avr"]),
    "Alstom": ("ALO.PA", "EUR", "Ferroviaire", 18.0, 0.25, 0.30, "+2.0%", ["Juil"]),
    "Alten": ("ATE.PA", "EUR", "Ingénierie/Tech", 95.0, 1.50, 0.25, "+8.0%", ["Juin"]),
    "Amundi": ("AMUN.PA", "EUR", "Finance/Gestion", 62.0, 4.10, 0.70, "+5.5%", ["Mai"]),
    "Arkema": ("AKE.PA", "EUR", "Chimie", 82.0, 3.50, 0.45, "+6.5%", ["Mai"]),
    "AXA": ("CS.PA", "EUR", "Assurance", 35.0, 1.98, 0.55, "+9.2%", ["Mai"]),
    "Bic": ("BB.PA", "EUR", "Consommation", 58.0, 2.85, 0.50, "+5.0%", ["Mai"]),
    "BioMérieux": ("BIM.PA", "EUR", "Santé/Diagnostic", 98.0, 0.85, 0.28, "+6.0%", ["Mai"]),
    "BNP Paribas": ("BNP.PA", "EUR", "Banque", 65.0, 4.60, 0.50, "+7.0%", ["Mai"]),
    "Bolloré": ("BOL.PA", "EUR", "Holding/Logistique", 5.6, 0.07, 0.25, "+3.0%", ["Juin"]),
    "Bouygues": ("EN.PA", "EUR", "BTP/Télécoms", 32.0, 1.90, 0.65, "+3.5%", ["Mai"]),
    "Bureau Veritas": ("BVI.PA", "EUR", "Certification", 27.0, 0.83, 0.55, "+6.0%", ["Mai"]),
    "Capgemini": ("CAP.PA", "EUR", "Services IT", 165.0, 3.40, 0.35, "+10.0%", ["Mai"]),
    "Carrefour": ("CA.PA", "EUR", "Distribution", 14.0, 0.87, 0.52, "+8.0%", ["Juin"]),
    "Coface": ("COFA.PA", "EUR", "Assurance Crédit", 13.5, 1.30, 0.80, "+7.5%", ["Mai"]),
    "Covivio": ("COV.PA", "EUR", "Immobilier", 48.0, 3.30, 0.78, "+2.0%", ["Mai"]),
    "Crédit Agricole": ("ACA.PA", "EUR", "Banque", 14.0, 1.05, 0.55, "+6.5%", ["Mai"]),
    "Danone": ("BN.PA", "EUR", "Agroalimentaire", 60.0, 2.10, 0.60, "+3.5%", ["Mai"]),
    "Dassault Aviation": ("AM.PA", "EUR", "Aéronautique/Défense", 195.0, 3.37, 0.32, "+9.0%", ["Mai"]),
    "Dassault Systèmes": ("DSY.PA", "EUR", "Logiciels/Tech", 33.0, 0.23, 0.22, "+7.0%", ["Mai"]),
    "Edenred": ("EDEN.PA", "EUR", "Paiements/Services", 34.0, 1.10, 0.48, "+9.5%", ["Mai"]),
    "Eiffage": ("FGR.PA", "EUR", "BTP/Concessions", 88.0, 4.10, 0.42, "+8.5%", ["Mai"]),
    "Elis": ("ELIS.PA", "EUR", "Services Industriels", 20.0, 0.43, 0.30, "+6.0%", ["Mai"]),
    "Engie": ("ENGI.PA", "EUR", "Énergie/Utilities", 16.0, 1.43, 0.65, "+5.0%", ["Mai"]),
    "EssilorLuxottica": ("EL.PA", "EUR", "Santé/Optique", 205.0, 3.95, 0.55, "+7.5%", ["Mai"]),
    "Eurazeo": ("RF.PA", "EUR", "Private Equity", 72.0, 2.42, 0.45, "+8.0%", ["Mai"]),
    "Euronext": ("ENX.PA", "EUR", "Bourse/Finance", 92.0, 2.48, 0.50, "+6.5%", ["Mai"]),
    "FDJ - Française des Jeux": ("FDJ.PA", "EUR", "Loisirs/Loterie", 34.0, 1.78, 0.75, "+7.0%", ["Mai"]),
    "GTT - Gaztransport": ("GTT.PA", "EUR", "Ingénierie/GNL", 125.0, 7.30, 0.80, "+11.0%", ["Juin", "Déc"]),
    "Gecina": ("GFC.PA", "EUR", "Immobilier", 92.0, 5.30, 0.75, "+2.0%", ["Mar", "Juil"]),
    "Getlink": ("GET.PA", "EUR", "Infrastructures", 15.5, 0.55, 0.55, "+6.0%", ["Juin"]),
    "Hermès": ("RMS.PA", "EUR", "Luxe", 2050.0, 15.00, 0.35, "+14.0%", ["Fév", "Mai"]),
    "Ipsen": ("IPN.PA", "EUR", "Santé/Pharma", 108.0, 1.20, 0.25, "+4.0%", ["Mai"]),
    "Icade": ("ICAD.PA", "EUR", "Immobilier", 24.0, 4.30, 0.82, "+1.5%", ["Mar", "Juil"]),
    "Interparfums": ("ITP.PA", "EUR", "Cosmétiques/Luxe", 42.0, 1.15, 0.55, "+10.0%", ["Mai"]),
    "Kering": ("KER.PA", "EUR", "Luxe", 230.0, 6.00, 0.58, "+3.0%", ["Jan", "Mai"]),
    "Klépierre": ("LI.PA", "EUR", "Immobilier Commercial", 26.0, 1.80, 0.72, "+4.5%", ["Mar", "Juil"]),
    "L'Oréal": ("OR.PA", "EUR", "Cosmétiques", 360.0, 6.60, 0.52, "+8.5%", ["Avr"]),
    "Legrand": ("LR.PA", "EUR", "Équipement Élec.", 95.0, 2.09, 0.48, "+7.5%", ["Mai"]),
    "LVMH": ("MC.PA", "EUR", "Luxe", 620.0, 13.00, 0.45, "+12.0%", ["Avr", "Déc"]),
    "M6 - Métropole TV": ("MMT.PA", "EUR", "Médias", 12.0, 1.25, 0.68, "+4.0%", ["Mai"]),
    "Michelin": ("ML.PA", "EUR", "Automobile/Pneus", 32.0, 1.35, 0.48, "+6.5%", ["Mai"]),
    "Nexans": ("NEX.PA", "EUR", "Câbles/Énergie", 105.0, 2.30, 0.35, "+10.0%", ["Mai"]),
    "Orange": ("ORA.PA", "EUR", "Télécoms", 10.5, 0.72, 0.68, "+2.0%", ["Juin", "Déc"]),
    "Pernod Ricard": ("RI.PA", "EUR", "Spiritueux", 70.0, 4.70, 0.55, "+6.0%", ["Juil", "Nov"]),
    "Publicis": ("PUB.PA", "EUR", "Communication", 92.0, 3.40, 0.48, "+8.5%", ["Juil"]),
    "Rémy Cointreau": ("RCO.PA", "EUR", "Spiritueux", 62.0, 2.00, 0.52, "+4.0%", ["Oct"]),
    "Renault": ("RNO.PA", "EUR", "Automobile", 42.0, 1.85, 0.30, "+8.0%", ["Mai"]),
    "Rexel": ("RXL.PA", "EUR", "Distribution Élec.", 24.0, 1.20, 0.45, "+7.0%", ["Mai"]),
    "Rubis": ("RUI.PA", "EUR", "Énergie/Stockage", 25.0, 1.98, 0.62, "+3.5%", ["Juin"]),
    "Safran": ("SAF.PA", "EUR", "Aéronautique/Défense", 195.0, 2.20, 0.38, "+9.5%", ["Mai"]),
    "Saint-Gobain": ("SGO.PA", "EUR", "Matériaux", 78.0, 2.10, 0.38, "+7.5%", ["Juin"]),
    "Sanofi": ("SAN.PA", "EUR", "Santé", 90.0, 3.76, 0.58, "+4.8%", ["Mai"]),
    "Schneider Electric": ("SU.PA", "EUR", "Industrie/Tech", 210.0, 3.50, 0.48, "+8.8%", ["Mai"]),
    "Scor": ("SCR.PA", "EUR", "Réassurance", 20.0, 1.80, 0.55, "+4.0%", ["Mai"]),
    "Seb": ("SK.PA", "EUR", "Électroménager", 92.0, 2.62, 0.42, "+5.5%", ["Mai"]),
    "Société Générale": ("GLE.PA", "EUR", "Banque", 25.0, 0.90, 0.40, "+3.0%", ["Mai"]),
    "Sodexo": ("SW.PA", "EUR", "Restauration/Services", 75.0, 3.10, 0.50, "+6.0%", ["Déc"]),
    "Sopra Steria": ("SOP.PA", "EUR", "Services IT", 175.0, 4.65, 0.38, "+9.0%", ["Mai"]),
    "Spie": ("SPIE.PA", "EUR", "Services Énergie", 34.0, 0.83, 0.42, "+7.5%", ["Mai", "Sep"]),
    "Stellantis": ("STLAP.PA", "EUR", "Automobile", 13.0, 1.55, 0.35, "+6.0%", ["Mai"]),
    "STMicroelectronics": ("STMPA.PA", "EUR", "Semi-conducteurs", 26.0, 0.36, 0.18, "+5.0%", ["Mar", "Juin", "Sep", "Déc"]),
    "Téléperformance": ("TEP.PA", "EUR", "Relation Client", 88.0, 3.85, 0.45, "+7.0%", ["Mai"]),
    "TF1": ("TFI.PA", "EUR", "Médias", 8.0, 0.55, 0.62, "+5.0%", ["Avr"]),
    "Thales": ("HO.PA", "EUR", "Défense/Aérospatial", 148.0, 3.40, 0.40, "+8.5%", ["Mai", "Déc"]),
    "TotalEnergies": ("TTE.PA", "EUR", "Énergie", 58.0, 3.22, 0.42, "+6.1%", ["Jan", "Avr", "Juil", "Oct"]),
    "Trigano": ("TRI.PA", "EUR", "Loisirs/Camping-cars", 118.0, 3.50, 0.25, "+9.0%", ["Mai", "Déc"]),
    "Vallourec": ("VK.PA", "EUR", "Énergie/Tubes", 15.0, 1.50, 0.45, "+5.0%", ["Mai"]),
    "Veolia": ("VIE.PA", "EUR", "Environnement", 28.0, 1.25, 0.65, "+6.5%", ["Mai"]),
    "Verallia": ("VRLA.PA", "EUR", "Emballage Verre", 27.0, 2.15, 0.50, "+8.0%", ["Mai"]),
    "Vicat": ("VCT.PA", "EUR", "Matériaux/Ciment", 35.0, 2.00, 0.42, "+4.5%", ["Mai"]),
    "Vinci": ("DG.PA", "EUR", "Concessions/BTP", 105.0, 4.50, 0.52, "+7.5%", ["Avr", "Nov"]),
    "Vivendi": ("VIV.PA", "EUR", "Médias/Divertissement", 9.5, 0.25, 0.45, "+3.0%", ["Avr"]),
    "Wendel": ("MF.PA", "EUR", "Holding/Investissement", 88.0, 4.00, 0.45, "+6.5%", ["Mai"]),

    # Grandes Actions Européennes éligibles PEA
    "Allianz (Allemagne)": ("ALV.DE", "EUR", "Assurance EUR", 265.0, 13.80, 0.60, "+8.0%", ["Mai"]),
    "ASML Holding (Pays-Bas)": ("ASML.AS", "EUR", "Semi-conducteurs EUR", 680.0, 6.10, 0.32, "+14.0%", ["Fév", "Mai", "Août", "Nov"]),
    "BMW (Allemagne)": ("BMW.DE", "EUR", "Automobile EUR", 78.0, 6.00, 0.38, "+5.0%", ["Mai"]),
    "Deutsche Telekom (All.)": ("DTE.DE", "EUR", "Télécoms EUR", 25.0, 0.77, 0.48, "+6.0%", ["Avr"]),
    "Enel (Italie)": ("ENEL.MI", "EUR", "Énergie EUR", 6.8, 0.43, 0.65, "+5.5%", ["Jan", "Juil"]),
    "Ferrari (Italie)": ("RACE.MI", "EUR", "Luxe/Auto EUR", 385.0, 2.44, 0.30, "+12.0%", ["Mai"]),
    "Iberdrola (Espagne)": ("IBE.MC", "EUR", "Énergie Verte EUR", 12.5, 0.55, 0.65, "+6.5%", ["Jan", "Juil"]),
    "Inditex - Zara (Espagne)": ("ITX.MC", "EUR", "Mode/Retail EUR", 46.0, 1.54, 0.60, "+9.0%", ["Mai", "Nov"]),
    "ING Groep (Pays-Bas)": ("INGA.AS", "EUR", "Banque EUR", 15.0, 1.10, 0.50, "+7.0%", ["Mai", "Août"]),
    "Intesa Sanpaolo (Italie)": ("ISP.MI", "EUR", "Banque EUR", 3.6, 0.30, 0.70, "+8.0%", ["Mai", "Nov"]),
    "Mercedes-Benz (Allemagne)": ("MBG.DE", "EUR", "Automobile EUR", 58.0, 5.30, 0.42, "+6.0%", ["Mai"]),
    "SAP (Allemagne)": ("SAP.DE", "EUR", "Logiciels/Cloud EUR", 190.0, 2.20, 0.40, "+7.5%", ["Mai"]),
    "Shell (Pays-Bas)": ("SHELL.AS", "EUR", "Énergie EUR", 31.0, 1.28, 0.38, "+5.0%", ["Mar", "Juin", "Sep", "Déc"]),
    "Siemens (Allemagne)": ("SIE.DE", "EUR", "Industrie/Tech EUR", 170.0, 4.70, 0.48, "+6.5%", ["Fév"]),
    "Unilever (Pays-Bas)": ("UNA.AS", "EUR", "Consommation EUR", 52.0, 1.73, 0.62, "+3.5%", ["Mar", "Juin", "Sep", "Déc"]),

    # ETFs éligibles PEA (Capitalisants / Distribuants)
    "ETF Amundi MSCI World PEA (CW8)": ("CW8.PA", "EUR", "ETF Monde PEA", 510.0, 0.0, 0.0, "+9.5%", ["Mai"]),
    "ETF BNP S&P 500 PEA (ESE)": ("ESE.PA", "EUR", "ETF USA PEA", 25.0, 0.0, 0.0, "+10.5%", ["Mai"]),
    "ETF Amundi Nasdaq-100 PEA (PUST)": ("PUST.PA", "EUR", "ETF Tech US PEA", 72.0, 0.0, 0.0, "+12.0%", ["Mai"]),
    "ETF Amundi Euro Stoxx 50 PEA": ("MSE.PA", "EUR", "ETF Europe PEA", 48.0, 1.45, 0.40, "+6.5%", ["Juil", "Déc"]),

    # Actions Américaines (CTO en USD - Dividend Aristocrats & Tech)
    "AbbVie": ("ABBV", "USD", "Santé US", 175.0, 6.20, 0.58, "+7.5%", ["Fév", "Mai", "Août", "Nov"]),
    "Alphabet - Google": ("GOOGL", "USD", "Tech US", 170.0, 0.80, 0.12, "+10.0%", ["Mar", "Juin", "Sep", "Déc"]),
    "Amazon": ("AMZN", "USD", "Tech/E-Commerce US", 185.0, 0.0, 0.0, "+12.0%", ["Mai"]),
    "Apple": ("AAPL", "USD", "Tech US", 200.0, 1.00, 0.16, "+5.5%", ["Fév", "Mai", "Août", "Nov"]),
    "Broadcom": ("AVGO", "USD", "Semi-conducteurs US", 160.0, 2.12, 0.42, "+14.0%", ["Mar", "Juin", "Sep", "Déc"]),
    "Caterpillar": ("CAT", "USD", "Industrie US", 330.0, 5.64, 0.28, "+8.0%", ["Fév", "Mai", "Août", "Nov"]),
    "Chevron": ("CVX", "USD", "Énergie US", 148.0, 6.52, 0.55, "+6.0%", ["Mar", "Juin", "Sep", "Déc"]),
    "Coca-Cola": ("KO", "USD", "Consommation US", 62.0, 1.94, 0.70, "+4.5%", ["Avr", "Juil", "Oct", "Déc"]),
    "Costco": ("COST", "USD", "Distribution US", 820.0, 4.64, 0.28, "+11.0%", ["Fév", "Mai", "Août", "Nov"]),
    "Eli Lilly": ("LLY", "USD", "Santé/Pharma US", 800.0, 5.20, 0.35, "+15.0%", ["Mar", "Juin", "Sep", "Déc"]),
    "ExxonMobil": ("XOM", "USD", "Énergie US", 112.0, 3.80, 0.44, "+4.5%", ["Mar", "Juin", "Sep", "Déc"]),
    "Home Depot": ("HD", "USD", "Distribution US", 365.0, 9.00, 0.58, "+8.5%", ["Mar", "Juin", "Sep", "Déc"]),
    "Johnson & Johnson": ("JNJ", "USD", "Santé US", 155.0, 4.96, 0.52, "+5.5%", ["Mar", "Juin", "Sep", "Déc"]),
    "JPMorgan Chase": ("JPM", "USD", "Banque US", 205.0, 5.00, 0.28, "+7.0%", ["Jan", "Avr", "Juil", "Oct"]),
    "Main Street Capital (Mensuel)": ("MAIN", "USD", "Finance/BDC US", 48.0, 3.00, 0.72, "+4.5%", ["Jan", "Fév", "Mar", "Avr", "Mai", "Juin", "Juil", "Août", "Sep", "Oct", "Nov", "Déc"]),
    "Mastercard": ("MA", "USD", "Paiements US", 460.0, 2.64, 0.20, "+13.0%", ["Fév", "Mai", "Août", "Nov"]),
    "McDonald's": ("MCD", "USD", "Restauration US", 275.0, 7.08, 0.58, "+7.5%", ["Mar", "Juin", "Sep", "Déc"]),
    "Merck & Co": ("MRK", "USD", "Santé/Pharma US", 112.0, 3.08, 0.48, "+6.5%", ["Jan", "Avr", "Juil", "Oct"]),
    "Meta Platforms": ("META", "USD", "Tech US", 520.0, 2.00, 0.12, "+10.0%", ["Mar", "Juin", "Sep", "Déc"]),
    "Microsoft": ("MSFT", "USD", "Tech US", 400.0, 3.32, 0.25, "+10.2%", ["Mar", "Juin", "Sep", "Déc"]),
    "NVIDIA": ("NVDA", "USD", "IA & Semi-conducteurs US", 120.0, 0.04, 0.02, "+15.0%", ["Mar", "Juin", "Sep", "Déc"]),
    "PepsiCo": ("PEP", "USD", "Consommation US", 168.0, 5.42, 0.66, "+7.0%", ["Jan", "Mar", "Juin", "Sep"]),
    "Pfizer": ("PFE", "USD", "Santé/Pharma US", 28.0, 1.68, 0.68, "+3.0%", ["Mar", "Juin", "Sep", "Déc"]),
    "Procter & Gamble": ("PG", "USD", "Consommation US", 162.0, 4.03, 0.62, "+6.0%", ["Fév", "Mai", "Août", "Nov"]),
    "Realty Income": ("O", "USD", "Immobilier US (REIT)", 55.0, 3.16, 0.74, "+3.8%", ["Jan", "Fév", "Mar", "Avr", "Mai", "Juin", "Juil", "Août", "Sep", "Oct", "Nov", "Déc"]),
    "Texas Instruments": ("TXN", "USD", "Semi-conducteurs US", 185.0, 5.44, 0.65, "+7.5%", ["Fév", "Mai", "Août", "Nov"]),
    "UnitedHealth": ("UNH", "USD", "Santé/Assurance US", 520.0, 8.40, 0.32, "+12.0%", ["Mar", "Juin", "Sep", "Déc"]),
    "Verizon": ("VZ", "USD", "Télécoms US", 40.0, 2.71, 0.60, "+2.0%", ["Fév", "Mai", "Août", "Nov"]),
    "Visa": ("V", "USD", "Paiements US", 275.0, 2.36, 0.22, "+14.0%", ["Mar", "Juin", "Sep", "Déc"]),
    "Walmart": ("WMT", "USD", "Distribution US", 72.0, 0.83, 0.35, "+4.0%", ["Jan", "Avr", "Mai", "Sep"]),
}

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

WATCHLIST_DEFAUT.update(st.session_state["watchlist"])

def recuperer_donnees(symbole):
    """Cours + historique 3 ans. Un échec Yahoo renvoie (None, None, None, None) sans être mis en cache."""
    try:
        return _recuperer_donnees_yahoo(symbole, creneau_cours())
    except Exception:
        return None, None, None, None


@st.cache_data(ttl=3600, max_entries=1500)
def _recuperer_donnees_yahoo(symbole, creneau):
    sym_enc = urllib.parse.quote(str(symbole).strip())
    for srv in ("query1", "query2"):
        url = f"https://{srv}.finance.yahoo.com/v8/finance/chart/{sym_enc}?range=3y&interval=1d"
        req = urllib.request.Request(url, headers=HEADERS_YAHOO_PRO)
        try:
            with urllib.request.urlopen(req, timeout=6) as response:
                data = json.loads(response.read().decode("utf-8"))
                result = data["chart"]["result"][0]
                quote = result.get("indicators", {}).get("quote", [{}])[0]
                # Les 3 séries restent alignées séance par séance : une séance sans clôture est écartée des trois,
                # et un plus haut / plus bas manquant est remplacé par la clôture du jour.
                bruts_c = quote.get("close") or []
                bruts_h = quote.get("high") or []
                bruts_b = quote.get("low") or []
                closes, hauts, bas = [], [], []
                for i_s, c_s in enumerate(bruts_c):
                    if c_s is None:
                        continue
                    h_s = bruts_h[i_s] if i_s < len(bruts_h) and bruts_h[i_s] is not None else c_s
                    b_s = bruts_b[i_s] if i_s < len(bruts_b) and bruts_b[i_s] is not None else c_s
                    closes.append(float(c_s))
                    hauts.append(float(h_s))
                    bas.append(float(b_s))
                prix_actuel = float(result.get("meta", {}).get("regularMarketPrice") or (closes[-1] if closes else 0.0))
                if prix_actuel > 0 and closes:
                    return prix_actuel, closes, hauts, bas
        except Exception:
            continue
    raise RuntimeError(f"Cours indisponible pour {symbole}")

@st.cache_data(ttl=1800)
def inspecter_dividende_yahoo_live(symbole):
    """Extrait automatiquement le cours, la devise, le dividende annuel et les mois de versement depuis Yahoo."""
    sym_enc = urllib.parse.quote(str(symbole).strip())
    map_num_vers_nom = {
        1: "Jan", 2: "Fév", 3: "Mar", 4: "Avr", 5: "Mai", 6: "Juin",
        7: "Juil", 8: "Août", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Déc",
    }
    for srv in ("query1", "query2"):
        url_c = f"https://{srv}.finance.yahoo.com/v8/finance/chart/{sym_enc}?interval=1d&range=1y&events=div"
        req_c = urllib.request.Request(url_c, headers=HEADERS_YAHOO_PRO)
        try:
            with urllib.request.urlopen(req_c, timeout=6) as rep:
                data_c = json.loads(rep.read().decode("utf-8"))
                res0 = data_c["chart"]["result"][0]
                meta = res0.get("meta", {})
                closes = [float(x) for x in res0.get("indicators", {}).get("quote", [{}])[0].get("close", []) if x is not None]
                cours_live = float(meta.get("regularMarketPrice") or (closes[-1] if closes else 50.0))
                # Devise RÉELLE de cotation (EUR, USD, mais aussi GBP, CHF, DKK...) : l'appelant refuse celles non gérées
                devise = str(meta.get("currency") or "EUR").upper()

                divs_dict = res0.get("events", {}).get("dividends", {})
                div_annuel = 0.0
                mois_nums = set()
                if isinstance(divs_dict, dict) and divs_dict:
                    seuil_ts = datetime.now().timestamp() - (375 * 86400)
                    for _, d_obj in divs_dict.items():
                        ts_d = float(d_obj.get("date", 0))
                        mt_d = float(d_obj.get("amount", 0.0))
                        if ts_d >= seuil_ts and mt_d > 0:
                            div_annuel += mt_d
                            mois_nums.add(datetime.fromtimestamp(ts_d).month)

                mois_noms = [map_num_vers_nom[m] for m in sorted(list(mois_nums))] if mois_nums else (["Mar", "Juin", "Sep", "Déc"] if devise == "USD" else ["Mai"])
                return round(cours_live, 2), devise, round(div_annuel, 2), mois_noms
        except Exception:
            continue
    return None, "EUR", 0.0, ["Mai"]

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

    q_enc = urllib.parse.quote(q_clean)
    for host_y in ("query2.finance.yahoo.com", "query1.finance.yahoo.com"):
        url = f"https://{host_y}/v1/finance/search?q={q_enc}&quotesCount=10&newsCount=0"
        req = urllib.request.Request(url, headers=HEADERS_YAHOO_PRO)
        try:
            with urllib.request.urlopen(req, timeout=6) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                for item in data.get("quotes", []):
                    q_type = item.get("quoteType", "")
                    sym = str(item.get("symbol", "")).strip().upper()
                    if q_type in ("EQUITY", "ETF") and sym and sym not in symboles_vus:
                        nom_long = item.get("shortname") or item.get("longname") or sym
                        bourse = item.get("exchDisp") or item.get("exchange") or ""
                        secteur_y = item.get("sectorDisp") or item.get("industryDisp") or ("ETF" if q_type == "ETF" else "Action Internationale")
                        est_eur = any(sym.endswith(suf) for suf in (".PA", ".AS", ".DE", ".MI", ".MC", ".BR", ".HE", ".LS", ".VI"))
                        dev_y = "EUR" if est_eur else "USD"
                        # Suffixe de place inconnu (.L, .SW, .CO...) : la devise réelle est vérifiée sur Yahoo à la sélection
                        dev_lbl = dev_y if (est_eur or "." not in sym) else "devise à vérifier"
                        resultats.append({
                            "label": f"{nom_long} ({sym} — {bourse} | {dev_lbl})",
                            "nom": nom_long,
                            "symbole": sym,
                            "devise": dev_y,
                            "secteur": secteur_y,
                        })
                        symboles_vus.add(sym)
            if resultats:
                break
        except Exception:
            continue

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
def calculer_rsi(clotures, periode=14):
    if len(clotures) < periode + 1:
        return 50.0
    variations = [clotures[i] - clotures[i - 1] for i in range(1, len(clotures))]
    gains = [v if v > 0 else 0 for v in variations[-periode:]]
    pertes = [-v if v < 0 else 0 for v in variations[-periode:]]
    moy_gain = sum(gains) / periode
    moy_perte = sum(pertes) / periode
    if moy_perte == 0:
        return 100.0
    rs = moy_gain / moy_perte
    return 100.0 - (100.0 / (1.0 + rs))

def calculer_stochastique(clotures, hauts, bas, periode=14):
    if len(clotures) < periode or len(hauts) < periode or len(bas) < periode:
        return 50.0
    plus_bas = min(bas[-periode:])
    plus_haut = max(hauts[-periode:])
    if plus_haut == plus_bas:
        return 50.0
    k = ((clotures[-1] - plus_bas) / (plus_haut - plus_bas)) * 100.0
    return max(0.0, min(100.0, k))

def calculer_atr_pct(clotures, hauts, bas, periode=14):
    n = min(len(clotures), len(hauts), len(bas))
    if n < periode + 1 or clotures[-1] <= 0:
        return 1.5
    trs = []
    for i in range(n - periode, n):
        tr = max(
            hauts[i] - bas[i],
            abs(hauts[i] - clotures[i - 1]),
            abs(bas[i] - clotures[i - 1])
        )
        trs.append(tr)
    atr = sum(trs) / len(trs)
    return (atr / clotures[-1]) * 100.0

def calculer_bollinger(clotures, periode=20):
    if len(clotures) < periode:
        return clotures[-1] * 0.95, clotures[-1] * 1.05
    fenetre = clotures[-periode:]
    moyenne = sum(fenetre) / periode
    variance = sum((x - moyenne) ** 2 for x in fenetre) / periode
    ecart_type = math.sqrt(variance)
    return moyenne - (2 * ecart_type), moyenne + (2 * ecart_type)

def calculer_macd(clotures):
    if len(clotures) < 35:
        return 0.0, 0.0
    k12, k26, k9 = 2 / 13, 2 / 27, 2 / 10
    e12, e26 = sum(clotures[:12]) / 12, sum(clotures[:26]) / 26
    macds = []
    for i, prix in enumerate(clotures):
        if i >= 12:
            e12 = (prix * k12) + (e12 * (1 - k12))
        if i >= 26:
            e26 = (prix * k26) + (e26 * (1 - k26))
            macds.append(e12 - e26)
    if len(macds) < 9:
        return macds[-1], 0.0
    sig = sum(macds[:9]) / 9
    for m in macds[9:]:
        sig = (m * k9) + (sig * (1 - k9))
    return macds[-1], sig

def calculer_ema_serie(clotures, periode):
    if not clotures:
        return []
    k = 2 / (periode + 1)
    emas = []
    if len(clotures) >= periode:
        sma = sum(clotures[:periode]) / periode
        ema = sma
        for i, prix in enumerate(clotures):
            if i < periode - 1:
                emas.append(None)
            elif i == periode - 1:
                emas.append(sma)
            else:
                ema = (prix * k) + (ema * (1 - k))
                emas.append(ema)
    else:
        ema = clotures[0]
        for prix in clotures:
            ema = (prix * k) + (ema * (1 - k))
            emas.append(ema)
    return emas

def analyser_signal_ema_2_12(clotures):
    if len(clotures) < 15:
        return "⚪ Neutre", 0
    ema2_serie = calculer_ema_serie(clotures, 2)
    ema12_serie = calculer_ema_serie(clotures, 12)
    valides = [(e2, e12) for e2, e12 in zip(ema2_serie, ema12_serie) if e2 is not None and e12 is not None]
    if len(valides) < 2:
        return "⚪ Neutre", 0
    veille_e2, veille_e12 = valides[-2]
    jour_e2, jour_e12 = valides[-1]
    ecart_pct = ((jour_e2 - jour_e12) / jour_e12 * 100) if jour_e12 > 0 else 0.0

    if veille_e2 <= veille_e12 and jour_e2 > jour_e12:
        return "🟢 Croisement haussier", 15
    elif jour_e2 > jour_e12 and ecart_pct >= 0.20:
        return "🟢 Tendance haussière", 12
    elif veille_e2 >= veille_e12 and jour_e2 < jour_e12:
        return "🔴 Croisement baissier", -10
    else:
        return "⚪ Neutre", 5

def calculer_regression_lineaire(clotures):
    n = len(clotures)
    if n < 2:
        return clotures[-1], 0.0, [], 0.0
    x = list(range(n))
    moy_x, moy_y = sum(x) / n, sum(clotures) / n
    numerateur = sum((x[i] - moy_x) * (clotures[i] - moy_y) for i in range(n))
    denominateur = sum((x[i] - moy_x) ** 2 for i in range(n))
    pente = numerateur / denominateur if denominateur != 0 else 0
    ordonnee = moy_y - (pente * moy_x)
    droite_regression = [(pente * i) + ordonnee for i in range(n)]
    residus = [clotures[i] - droite_regression[i] for i in range(n)]
    std_res = math.sqrt(sum(r ** 2 for r in residus) / n)
    val_reg = max(0.01, float(droite_regression[-1]))
    ecart_pct = ((clotures[-1] - val_reg) / val_reg) * 100.0
    return val_reg, ecart_pct, droite_regression, std_res


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
    for srv in ("query1", "query2"):
        try:
            url = f"https://{srv}.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbole)}?range=3mo&interval=1d"
            req = urllib.request.Request(url, headers=HEADERS_YAHOO_PRO)
            with urllib.request.urlopen(req, timeout=5) as response:
                data = json.loads(response.read().decode("utf-8"))
                closes = [float(c) for c in data["chart"]["result"][0]["indicators"]["quote"][0]["close"] if c is not None]
            if len(closes) < 15:
                return "⚪ Neutre", "#95a5a6"

            def calc_ema(vals, periode):
                k = 2.0 / (periode + 1.0)
                ema = [vals[0]]
                for p in vals[1:]:
                    ema.append(p * k + ema[-1] * (1.0 - k))
                return ema

            ema2 = calc_ema(closes, 2)
            ema12 = calc_ema(closes, 12)

            if ema2[-2] <= ema12[-2] and ema2[-1] > ema12[-1]:
                return "🚀 Croisement haussier", "#2ecc71"
            elif ema2[-1] > ema12[-1] and closes[-1] >= ema2[-1]:
                return "🟢 Tendance haussière", "#2ecc71"
            elif ema2[-1] > ema12[-1]:
                return "🟡 Neutre (Pause)", "#f39c12"
            else:
                return "🔴 Tendance baissière", "#e74c3c"
        except Exception:
            continue
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

    score = 0
    payout_r = float(info.get("payout_ratio", 0.60))
    if payout_r <= 0.55:
        score += 18
    elif payout_r <= 0.72:
        score += 13
    else:
        score += 6

    if rendement_actuel >= 0.05:
        score += 15
    elif rendement_actuel >= 0.03:
        score += 11
    else:
        score += 6

    if prix_cible > 0 and prix_actuel <= prix_cible:
        score += 15
    elif prix_cible > 0 and prix_actuel <= prix_cible * 1.05:
        score += 8

    if ecart_reg_pct <= -10:
        score += 15
    elif ecart_reg_pct < 0:
        score += 10
    elif ecart_reg_pct <= 5:
        score += 4

    score += pts_ema

    if rsi <= 32 or stoch_k <= 20:
        score += 14
    elif rsi <= 46 or stoch_k <= 35:
        score += 9
    elif rsi >= 72 and stoch_k >= 80:
        score -= 10

    if prix_actuel <= borne_inf * 1.02:
        score += 6
    if macd_val > macd_sig:
        score += 7
    else:
        score -= 2

    score = int(min(100, max(0, score)))
    est_surevalue = (prix_cible > 0 and prix_actuel >= prix_cible * 1.22 and (rsi >= 70 or prix_actuel >= borne_sup))

    if est_surevalue:
        decision = "🟠 ZONE HAUTE"
    elif score >= 65 and "🔴" not in statut_ema_2_12:
        decision = "🟢 SIGNAL FORT"
    elif score >= 45 and "🔴" not in statut_ema_2_12:
        decision = "🔵 SIGNAL FAVORABLE"
    else:
        decision = "⚪ SIGNAL NEUTRE"

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
candidats_dca_top2 = candidats_tries[:2]
budget_courant = BUDGET_MENSUEL
achats_simules = {item["nom"]: 0 for item in candidats_tries}

continuer = True
while continuer:
    continuer = False
    for item in candidats_dca_top2:
        if budget_courant >= item["prix_eur"] and item["prix_eur"] > 0:
            achats_simules[item["nom"]] += 1
            budget_courant -= item["prix_eur"]
            continuer = True

montant_investi_dca = BUDGET_MENSUEL - budget_courant
montant_tot_div_dca = sum(achats_simules[item["nom"]] * item["div_eur"] for item in candidats_dca_top2)

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
# ONGLET 1 : RADAR ALGORITHMIQUE, ALLOCATION DCA (MAX 2 LIGNES) & ALERTES EMAIL
# ------------------------------------------------------------------------------
with onglet_radar:
    if mode_gratuit:
        st.warning("🌱 **Forfait Gratuit (0 €)** : 2 valeurs affichées. Passez à **Premium (4,90 €/mois)** ou **Pro (8,90 €/mois)** dans le menu de gauche pour débloquer l'ensemble du catalogue PEA & US !")

    nb_opportunites = sum(1 for d in donnees_t1 if "SIGNAL FORT" in d["Décision"] or "SIGNAL FAVORABLE" in d["Décision"])
    meilleure_opp = candidats_tries[0]["nom"] if candidats_tries else "Aucune"

    html_radar_kpi = f"""
    <div class="argon-grid">
        <div class="argon-card">
            <div class="argon-title">🎯 Signaux Favorables</div>
            <div class="argon-val" style="color: #2ecc71;">{nb_opportunites} / {len(actions_autorisees)}</div>
            <div class="argon-sub">Top Signal : <b>{meilleure_opp}</b></div>
        </div>
        <div class="argon-card">
            <div class="argon-title">💰 Enveloppe DCA Mensuelle</div>
            <div class="argon-val">{BUDGET_MENSUEL:.0f} €</div>
            <div class="argon-sub">Investi simulé : <b>{montant_investi_dca:.2f} €</b> (Reste {budget_courant:.2f} €)</div>
        </div>
        <div class="argon-card">
            <div class="argon-title">🌱 Gain de Rente DCA</div>
            <div class="argon-val" style="color: #3498db;">+{montant_tot_div_dca:.2f} € / an</div>
            <div class="argon-sub">Concentré sur 1 à 2 lignes max</div>
        </div>
        <div class="argon-card">
            <div class="argon-title">🔔 Alertes Prix Cible / Achat</div>
            <div class="argon-val" style="color: #f39c12;">{len(alertes_detectees)} active(s)</div>
            <div class="argon-sub">Valeurs sous cible ou en signal fort</div>
        </div>
    </div>
    """
    afficher_html(html_radar_kpi)

    col_dca_exp, col_al_exp = st.columns(2)

    with col_dca_exp:
        with st.expander(f"🛒 Simulation de Répartition DCA ({BUDGET_MENSUEL:.0f} € — 2 lignes max)", expanded=True):
            st.caption("Simulation mathématique : répartition de votre enveloppe sur les 2 scores les plus élevés du radar. Ce n'est pas une recommandation d'achat.")
            achats_retenus = [item for item in candidats_dca_top2 if achats_simules.get(item["nom"], 0) > 0]
            if not achats_retenus:
                st.info("Aucune action ne remplit actuellement les critères d'achat DCA.")
            else:
                html_dca = "<table class='r-table'><thead><tr><th style='text-align:left;'>Valeur (score le plus élevé)</th><th>Score</th><th>Qté</th><th>Coût (€)</th><th>+Div/an</th></tr></thead><tbody>"
                for item in achats_retenus:
                    q_sim = achats_simules[item["nom"]]
                    cout_tot = q_sim * item["prix_eur"]
                    div_gagne = q_sim * item["div_eur"]
                    html_dca += f"<tr><td class='r-name'><b>{item['nom']}</b></td><td><span class='b-green'>{item['score']} / 100</span></td><td><b>{q_sim}</b></td><td>{cout_tot:.1f} €</td><td style='color:#2ecc71; font-weight:700;'>+{div_gagne:.2f} €</td></tr>"
                html_dca += "</tbody></table>"
                afficher_html(html_dca)

    with col_al_exp:
        with st.expander(f"🔔 Centre d'Alertes & Notification Email ({len(alertes_detectees)} signal/signaux)", expanded=True):
            if not est_pro_max:
                afficher_verrou_saas(
                    "Alertes Prix Cibles & Notifications Email",
                    "👑 Offre Pro (8,90 €/mois)",
                    "Recevez directement par email vos alertes dès qu'une action passe sous votre prix cible ou déclenche un signal technique fort."
                )
            elif not alertes_detectees:
                st.info("Aucune valeur n'est actuellement sous son prix cible ou en signal technique fort.")
            else:
                for al in alertes_detectees[:4]:
                    markdown_fr(f"• **{al['Actif']}** à **{al['Prix']}** (Cible : `{al['Cible']}`) — **{al['Motif']}**")
                email_dest = str(st.session_state["user"].email) if st.session_state.get("user") else ADMIN_EMAIL
                if st.button(f"📧 M'envoyer ce rapport d'alertes par email ({email_dest})", width="stretch"):
                    ok_mail, msg_mail = envoyer_email_alerte(email_dest, alertes_detectees)
                    if ok_mail:
                        st.success(msg_mail)
                    else:
                        st.info(msg_mail)

            # --- ALERTES AUTOMATIQUES : envoi chaque soir de bourse par la tâche planifiée (alertes_quotidiennes.py) ---
            if est_pro_max and st.session_state.get("user") is not None and isinstance(st.session_state.get("portefeuille"), dict):
                alertes_auto_actuel = bool(st.session_state["portefeuille"].get("_alertes_auto", False))
                alertes_auto_voulu = st.toggle(
                    "📬 Recevoir automatiquement un e-mail dès qu'une valeur de mon radar passe sous son prix cible",
                    value=alertes_auto_actuel,
                    help="Vérification chaque soir de bourse, même sans ouvrir Boursy. Un seul e-mail par valeur, "
                         "renvoyé au plus une fois par semaine tant qu'elle reste sous son prix cible.",
                )
                if alertes_auto_voulu != alertes_auto_actuel:
                    st.session_state["portefeuille"]["_alertes_auto"] = bool(alertes_auto_voulu)
                    sauvegarder_dans_cloud()

    # --- TITRE DU TABLEAU 1 PLEINE LARGEUR (GAUCHE) + BOUTON ACTUALISER (DROITE) ---
    col_titre_t1, col_btn_t1 = st.columns([4, 1])
    with col_titre_t1:
        st.markdown(
            "<h3 style='margin: 12px 0 6px 0; padding: 0;'>📊 Tableau 1 : Timing, Momentum & Score Algorithmique (EUR & US)</h3>",
            unsafe_allow_html=True
        )
    with col_btn_t1:
        st.markdown("<div style='margin-top: 8px;'></div>", unsafe_allow_html=True)
        if st.button("🔄 Actualiser les cours", width="stretch", key="btn_actu_radar_t1"):
            st.cache_data.clear()
            if "prix_temps_reel" in st.session_state:
                st.session_state["prix_temps_reel"] = {}
            st.rerun()

    html_t1 = """
    <table class="r-table">
    <thead>
        <tr>
            <th style="text-align: left;">Actif (Devise)</th>
            <th>Cours (Origine / €)</th>
            <th>Prix Cible</th>
            <th>Écart Cible</th>
            <th>RSI (14J)</th>
            <th>Stoch. %K</th>
            <th>MACD</th>
            <th>Signal EMA 2/12</th>
            <th style="width: 145px;">Score / 100</th>
            <th>Décision Algo</th>
        </tr>
    </thead>
    <tbody>
    """
    for d in sorted(donnees_t1, key=lambda x: x["Score"], reverse=True):
        ecart_str = str(d["Écart Cible (%)"])
        badge_ecart = f"<span class='b-green'>{ecart_str}</span>" if "🟢" in ecart_str else (f"<span class='b-yellow'>{ecart_str}</span>" if "🟡" in ecart_str else f"<span class='b-neutral'>{ecart_str}</span>")

        sc = d["Score"]
        c_bar = "#2ecc71" if sc >= 65 else ("#3498db" if sc >= 45 else "#e74c3c")

        dec = d["Décision"]
        dec_html = f"<span class='b-green'>{dec}</span>" if "SIGNAL FORT" in dec else (f"<span class='b-blue'>{dec}</span>" if "SIGNAL FAVORABLE" in dec else (f"<span class='b-red'>{dec}</span>" if "ZONE HAUTE" in dec else f"<span class='b-neutral'>{dec}</span>"))

        rsi_v = d["RSI"]
        rsi_badge = f"<span class='b-green'>{rsi_v}</span>" if rsi_v <= 35 else (f"<span class='b-red'>{rsi_v}</span>" if rsi_v >= 70 else f"<b>{rsi_v}</b>")

        stoch_v = int(d["Stoch"])
        stoch_badge = f"<span class='b-green'>{stoch_v}%</span>" if stoch_v <= 20 else (f"<span class='b-red'>{stoch_v}%</span>" if stoch_v >= 80 else f"{stoch_v}%")

        html_t1 += f"""
        <tr>
            <td class="r-name">{d['Actif']}</td>
            <td style="white-space:nowrap;"><b>{d['Prix']}</b>{f' <span style="opacity:0.7; font-size:0.86em;">({d["PrixEUR"]})</span>' if '$' in d['Prix'] else ''}</td>
            <td style="opacity: 0.85;">{d['Prix Cible']}</td>
            <td>{badge_ecart}</td>
            <td>{rsi_badge}</td>
            <td>{stoch_badge}</td>
            <td>{d['MACD']}</td>
            <td><span class='b-neutral'>{d['EMA 2/12']}</span></td>
            <td>
                <div style="font-weight: 800; font-size: 0.9em;">{sc} / 100</div>
                <div class="score-bg"><div style="width: {min(100, sc)}%; background: {c_bar}; height: 100%;"></div></div>
            </td>
            <td>{dec_html}</td>
        </tr>
        """
    html_t1 += "</tbody></table>"
    afficher_html(html_t1)

    tab_val, tab_tech, tab_div = st.tabs([
        "📐 Tableau 2 : Analyse Value & Canal 3 Ans",
        "🎯 Tableau 3 : Indicateurs Techniques Avancés (Bollinger, Stoch, ATR)",
        "🛡️ Tableau 4 : Sûreté & Croissance des Dividendes",
    ])

    with tab_val:
        if mode_gratuit:
            afficher_verrou_saas(
                "Tableau 2 : Analyse Value & Canal de Régression Linéaire sur 3 Ans",
                "⚡ Offre Premium (4,90 €/mois) ou 👑 Pro (8,90 €/mois)",
                "Repérez instantanément les actions historiquement décotées par rapport à leur tendance centrale à 3 ans."
            )
        else:
            st.caption("📉 **Classement Value automatique :** Trié de la **plus forte décote** (en haut) jusqu'aux valeurs **les plus chères** (en bas).")
            donnees_t2_triees = sorted(donnees_t2, key=lambda x: (x["OrdreStatut"], x["EcartNum"]))
            html_t2 = "<table class='r-table'><thead><tr><th style='width:65px;'>Rang</th><th style='text-align: left;'>Actif</th><th>Cours Actuel</th><th>Tendance Linéaire 3A</th><th>Écart à la Tendance</th><th>Diagnostic Value</th></tr></thead><tbody>"
            for rang_idx, d in enumerate(donnees_t2_triees, start=1):
                st_val = d["Statut Value"]
                b_val = "b-green" if "DÉCOTE" in st_val else ("b-yellow" if "SOUS-ÉVALUÉE" in st_val else "b-neutral")
                c_ecart = "#2ecc71" if d["EcartNum"] <= -10 else ("#f39c12" if d["EcartNum"] < 0 else "#e74c3c")
                badge_rang = f"<span class='b-green'>#{rang_idx}</span>" if d["OrdreStatut"] == 0 else (f"<span class='b-yellow'>#{rang_idx}</span>" if d["OrdreStatut"] == 1 else f"<span class='b-neutral'>#{rang_idx}</span>")
                html_t2 += f"<tr><td>{badge_rang}</td><td class='r-name'>{d['Actif']}</td><td><b>{d['Prix']}</b></td><td>{d['Tendance 3A']}</td><td style='color:{c_ecart}; font-weight:800;'>{d['Écart %']}</td><td><span class='{b_val}'>{st_val}</span></td></tr>"
            html_t2 += "</tbody></table>"
            afficher_html(html_t2)

            if droites_regression_dict:
                st.markdown("#### 📈 Visualisation du Canal de Régression Linéaire sur 3 Ans")
                noms_tries_value = [d["NomBrut"] for d in donnees_t2_triees if d["NomBrut"] in droites_regression_dict]
                act_choisie_graph = st.selectbox("Choisir une action à inspecter graphiquement (classées par décote) :", noms_tries_value)
                closes_g, reg_g, std_g, sym_g = droites_regression_dict[act_choisie_graph]
                df_graph = pd.DataFrame({
                    "Cours Clôture": closes_g,
                    "Tendance Centrale 3A": reg_g,
                    "Borne Haute (+2σ)": [r + 2 * std_g for r in reg_g],
                    "Borne Basse d'Achat (-2σ)": [r - 2 * std_g for r in reg_g],
                })
                st.line_chart(df_graph)

    with tab_tech:
        if mode_gratuit:
            afficher_verrou_saas(
                "Tableau 3 : Indicateurs Techniques Avancés (Supports 30J, Bollinger, Stochastique & ATR)",
                "⚡ Offre Premium (4,90 €/mois) ou 👑 Pro (8,90 €/mois)",
                "Obtenez le Score de Timing court terme et un niveau de prix technique de référence pour chaque action."
            )
        else:
            html_guide_tech = """
            <div class="argon-grid" style="margin-bottom: 14px;">
                <div class="argon-card" style="text-align:left; padding:12px 15px;">
                    <div class="argon-title" style="color:#2ecc71;">📏 1. Canal 30 Jours (Support / Résistance)</div>
                    <div style="font-size:0.82em; opacity:0.9; line-height:1.45;">Le <b>Support</b> est le plancher où les acheteurs défendent le titre. Plus la jauge est proche de <b>0% (Bas)</b>, meilleur est le point d'entrée.</div>
                </div>
                <div class="argon-card" style="text-align:left; padding:12px 15px;">
                    <div class="argon-title" style="color:#3498db;">🌊 2. Bandes de Bollinger (20 Jours)</div>
                    <div style="font-size:0.82em; opacity:0.9; line-height:1.45;">Contiennent 95% des variations normales. Un cours sur le <b>Bas de Bollinger</b> indique un titre statistiquement bradé à court terme.</div>
                </div>
                <div class="argon-card" style="text-align:left; padding:12px 15px;">
                    <div class="argon-title" style="color:#f39c12;">⚡ 3. Oscillateur Stochastique (14J)</div>
                    <div style="font-size:0.82em; opacity:0.9; line-height:1.45;">Mesure la vitesse d'essoufflement. <b>&lt; 20% (Survente)</b> = zone de survente. <b>&gt; 80% (Surachat)</b> = risque de repli.</div>
                </div>
                <div class="argon-card" style="text-align:left; padding:12px 15px;">
                    <div class="argon-title" style="color:#9b59b6;">🎯 4. ATR & Niveau Technique de Référence</div>
                    <div style="font-size:0.82em; opacity:0.9; line-height:1.45;">L'<b>ATR</b> mesure l'amplitude moyenne d'une journée. Il sert à estimer un <b>niveau de prix technique de référence</b>, proche des supports récents.</div>
                </div>
            </div>
            """
            afficher_html(html_guide_tech)
            st.caption("🎯 **Classement par Opportunité de Timing :** Trié de la **meilleure fenêtre d'entrée court terme (#1 en haut)** jusqu'aux valeurs **en surchauffe (en bas)**.")

            donnees_t4_enrichies = []
            for d in donnees_t4:
                try:
                    parts_prix = d["Prix"].split()
                    prix_f = float(parts_prix[0])
                    sym_dev = parts_prix[1] if len(parts_prix) > 1 else "€"
                    sup_f = float(d["Support 30J"].split()[0])
                    res_f = float(d["Résistance 30J"].split()[0])
                except Exception:
                    prix_f, sym_dev, sup_f, res_f = 50.0, "€", 45.0, 55.0

                try:
                    bloc_b = d["Bollinger (20J)"].split("]")[0].replace("[", "")
                    b_inf_s, b_sup_s = bloc_b.split(" - ")
                    borne_inf_f, borne_sup_f = float(b_inf_s), float(b_sup_s)
                except Exception:
                    borne_inf_f, borne_sup_f = sup_f, res_f

                try:
                    stoch_f = float(d["Stochastique"].split("%")[0])
                except Exception:
                    stoch_f = 50.0

                try:
                    atr_f = float(d["Volatilité ATR"].split("%")[0])
                except Exception:
                    atr_f = 1.5

                amp_30j = max(0.01, res_f - sup_f)
                pos_canal_pct = max(0.0, min(100.0, ((prix_f - sup_f) / amp_30j) * 100.0))

                amp_boll = max(0.01, borne_sup_f - borne_inf_f)
                pos_boll_pct = max(0.0, min(100.0, ((prix_f - borne_inf_f) / amp_boll) * 100.0))

                rebond_res_pct = ((res_f - prix_f) / prix_f * 100.0) if prix_f > 0 else 0.0

                score_timing = int(round(100.0 - (0.40 * pos_canal_pct + 0.35 * stoch_f + 0.25 * pos_boll_pct)))
                score_timing = max(5, min(98, score_timing))

                plancher_tech = max(sup_f, min(prix_f, (sup_f + borne_inf_f) / 2.0))

                if pos_boll_pct <= 22:
                    diag_boll = f"<span class='b-green'>🟢 Bas de canal ({borne_inf_f:.1f} {sym_dev})</span><br><span style='font-size:0.78em; opacity:0.8;'>Prix comprimé (Rebond probable)</span>"
                elif pos_boll_pct >= 82:
                    diag_boll = f"<span class='b-red'>🔴 Haut de canal ({borne_sup_f:.1f} {sym_dev})</span><br><span style='font-size:0.78em; opacity:0.8;'>Extension haute (Prudence)</span>"
                else:
                    diag_boll = f"<span class='b-neutral'>⚪ Zone neutre [{borne_inf_f:.1f} - {borne_sup_f:.1f}]</span><br><span style='font-size:0.78em; opacity:0.8;'>Position : {pos_boll_pct:.0f}% de l'élastique</span>"

                if stoch_f <= 20:
                    diag_stoch = f"<span class='b-green'>🟢 {stoch_f:.0f}% (Survente)</span><br><span style='font-size:0.78em; opacity:0.8;'>Zone de survente</span>"
                elif stoch_f <= 38:
                    diag_stoch = f"<span class='b-blue'>🔵 {stoch_f:.0f}% (Zone basse)</span><br><span style='font-size:0.78em; opacity:0.8;'>Point d'entrée favorable</span>"
                elif stoch_f >= 80:
                    diag_stoch = f"<span class='b-red'>🔴 {stoch_f:.0f}% (Surachat)</span><br><span style='font-size:0.78em; opacity:0.8;'>Surchauffe court terme</span>"
                else:
                    diag_stoch = f"<span class='b-neutral'>⚪ {stoch_f:.0f}% (Neutre)</span><br><span style='font-size:0.78em; opacity:0.8;'>Tendance en cours</span>"

                if atr_f < 1.3:
                    profil_atr = "🛡️ Calme"
                elif atr_f <= 2.2:
                    profil_atr = "⚖️ Modérée"
                else:
                    profil_atr = "⚡ Nerveuse"

                if score_timing >= 68:
                    ordre_statut = 0
                    action_tech = f"<span class='b-green'>🟢 TIMING TECHNIQUE FAVORABLE</span><br><span style='font-size:0.80em;'>Cours actuel proche des supports (<b>{prix_f:.2f} {sym_dev}</b>)</span>"
                elif score_timing >= 50:
                    ordre_statut = 1
                    action_tech = f"<span class='b-blue'>🔵 TIMING CORRECT</span><br><span style='font-size:0.80em;'>Niveau technique de référence : <b>{plancher_tech:.2f} {sym_dev}</b></span>"
                elif score_timing >= 33:
                    ordre_statut = 2
                    action_tech = f"<span class='b-yellow'>🟡 TIMING NEUTRE</span><br><span style='font-size:0.80em;'>Niveau technique de référence : <b>{plancher_tech:.2f} {sym_dev}</b></span>"
                else:
                    ordre_statut = 3
                    cible_repli = (sup_f + res_f) / 2.0
                    action_tech = f"<span class='b-red'>🟠 ZONE HAUTE DU CANAL</span><br><span style='font-size:0.80em;'>Milieu du canal 30J : <b>{cible_repli:.2f} {sym_dev}</b></span>"

                donnees_t4_enrichies.append({
                    "Actif": d["Actif"],
                    "Prix": d["Prix"],
                    "Support": d["Support 30J"],
                    "Resistance": d["Résistance 30J"],
                    "PosCanal": pos_canal_pct,
                    "RebondPct": rebond_res_pct,
                    "DiagBoll": diag_boll,
                    "DiagStoch": diag_stoch,
                    "ATR": f"{atr_f:.2f}% / j ({profil_atr})",
                    "ScoreTiming": score_timing,
                    "OrdreStatut": ordre_statut,
                    "ActionTech": action_tech,
                })

            donnees_t4_enrichies.sort(key=lambda x: (x["OrdreStatut"], -x["ScoreTiming"]))

            html_t4 = """
            <table class='r-table'>
            <thead>
                <tr>
                    <th style='width:55px;'>Rang</th>
                    <th style='text-align: left;'>Actif</th>
                    <th style='width:230px;'>Position dans le Canal 30J<br><span style='font-size:0.82em; opacity:0.75;'>(Support ➔ Cours ➔ Résistance)</span></th>
                    <th>Marge avant Résistance</th>
                    <th>Diagnostic Bollinger (20J)</th>
                    <th>Momentum Stochastique</th>
                    <th>Volatilité (ATR)</th>
                    <th style='width:125px;'>Score Timing</th>
                    <th>Lecture Technique & Niveau de Référence</th>
                </tr>
            </thead>
            <tbody>
            """
            for idx_r, item_t in enumerate(donnees_t4_enrichies, start=1):
                pos_c = item_t["PosCanal"]
                c_jauge_c = "#2ecc71" if pos_c <= 35 else ("#3498db" if pos_c <= 65 else "#e74c3c")
                sc_t = item_t["ScoreTiming"]
                c_sc_t = "#2ecc71" if sc_t >= 68 else ("#3498db" if sc_t >= 50 else ("#f39c12" if sc_t >= 33 else "#e74c3c"))
                b_rang = "b-green" if item_t["OrdreStatut"] == 0 else ("b-blue" if item_t["OrdreStatut"] == 1 else ("b-yellow" if item_t["OrdreStatut"] == 2 else "b-neutral"))

                html_t4 += f"""
                <tr>
                    <td><span class='{b_rang}'>#{idx_r}</span></td>
                    <td class='r-name'>{item_t['Actif']}<br><span style='font-size:0.84em; opacity:0.8;'>Cours : <b>{item_t['Prix']}</b></span></td>
                    <td>
                        <div style='display:flex; justify-content:space-between; font-size:0.78em; font-weight:700;'>
                            <span style='color:#2ecc71;'>Sup: {item_t['Support']}</span>
                            <span>{pos_c:.0f}%</span>
                            <span style='color:#e74c3c;'>Rés: {item_t['Resistance']}</span>
                        </div>
                        <div class='score-bg'><div style='width:{max(4, min(100, pos_c))}%; background:{c_jauge_c}; height:100%;'></div></div>
                    </td>
                    <td style='color:#2ecc71; font-weight:800;'>+{item_t['RebondPct']:.1f}%<br><span style='font-size:0.76em; opacity:0.75; font-weight:600;'>potentiel 30J</span></td>
                    <td>{item_t['DiagBoll']}</td>
                    <td>{item_t['DiagStoch']}</td>
                    <td><span class='b-purple'>{item_t['ATR']}</span></td>
                    <td>
                        <div style='font-weight:800; font-size:0.9em;'>{sc_t} / 100</div>
                        <div class='score-bg'><div style='width:{sc_t}%; background:{c_sc_t}; height:100%;'></div></div>
                    </td>
                    <td>{item_t['ActionTech']}</td>
                </tr>
                """
            html_t4 += "</tbody></table>"
            afficher_html(html_t4)

    with tab_div:
        if mode_gratuit:
            afficher_verrou_saas(
                "Tableau 4 : Sûreté des Dividendes, Payout Ratio & Détecteur de Yield Trap",
                "⚡ Offre Premium (4,90 €/mois) ou 👑 Pro (8,90 €/mois)",
                "Vérifiez la solidité du Payout Ratio, la croissance sur 5 ans et les pièges à rendement sur l'ensemble du catalogue."
            )
        else:
            html_guide_div = """
            <div class="argon-grid" style="margin-bottom: 14px;">
                <div class="argon-card" style="text-align:left; padding:12px 15px;">
                    <div class="argon-title" style="color:#2ecc71;">💰 1. Rendement & Gain pour 1 000 €</div>
                    <div style="font-size:0.82em; opacity:0.9; line-height:1.45;">Indique le revenu annuel généré immédiatement pour <b>1 000 € investis</b>. Un rendement entre <b>3,5% et 7%</b> offre le meilleur équilibre en PEA.</div>
                </div>
                <div class="argon-card" style="text-align:left; padding:12px 15px;">
                    <div class="argon-title" style="color:#3498db;">🛡️ 2. Payout Ratio (Marge de Sécurité)</div>
                    <div style="font-size:0.82em; opacity:0.9; line-height:1.45;">Part des bénéfices versée en dividende. <b>&le; 55%</b> = Ultra sûr (l'entreprise garde du cash pour investir). <b>&gt; 75%</b> = Dividende sous tension.</div>
                </div>
                <div class="argon-card" style="text-align:left; padding:12px 15px;">
                    <div class="argon-title" style="color:#f39c12;">🚀 3. Croissance 5A & Effet YoC</div>
                    <div style="font-size:0.82em; opacity:0.9; line-height:1.45;">Mesure la hausse annuelle du coupon. Le <b>YoC 5 Ans</b> projette votre futur rendement annuel sur votre prix d'achat d'aujourd'hui.</div>
                </div>
                <div class="argon-card" style="text-align:left; padding:12px 15px;">
                    <div class="argon-title" style="color:#9b59b6;">🏆 4. Score Rente (/100) & Profil</div>
                    <div style="font-size:0.82em; opacity:0.9; line-height:1.45;">Combine <b>Sûreté du Payout (40%)</b>, <b>Rendement (35%)</b> et <b>Croissance (25%)</b> pour distinguer les Pépites Royales des Vaches à lait.</div>
                </div>
            </div>
            """
            afficher_html(html_guide_div)
            st.caption("🏆 **Classement par Qualité de Rente :** Trié de la **meilleure combinaison Rendement + Sûreté + Croissance (#1 en haut)** jusqu'aux valeurs secondaires.")

            donnees_t3_enrichies = []
            for d in donnees_t3:
                nom_pur = d["Actif"].rsplit(" (", 1)[0]
                info_w = WATCHLIST.get(nom_pur, WATCHLIST_DEFAUT.get(nom_pur, {}))
                mois_v = info_w.get("mois_div", ["Mai"])
                if len(mois_v) == 12:
                    freq_str = "📅 Mensuel (12x/an)"
                elif len(mois_v) == 4:
                    freq_str = f"📅 Trimestriel ({', '.join(mois_v)})"
                elif len(mois_v) > 1:
                    freq_str = f"📅 {len(mois_v)}x/an ({', '.join(mois_v)})"
                else:
                    freq_str = f"📅 Annuel ({mois_v[0] if mois_v else 'Mai'})"

                try:
                    rend_pct = float(str(d["Rendement"]).replace("%", "").strip())
                except Exception:
                    rend_pct = 3.0

                try:
                    payout_pct = float(str(d["Payout"]).replace("%", "").strip())
                except Exception:
                    payout_pct = 55.0

                try:
                    croiss_clean = str(d["Croissance 5a"]).replace("+", "").replace("%", "").replace("/an", "").strip()
                    croiss_pct = float(croiss_clean)
                except Exception:
                    croiss_pct = 5.0

                rente_1000 = rend_pct * 10.0
                taux_c_borne = max(0.0, min(20.0, croiss_pct))
                yoc_5a = rend_pct * ((1.0 + taux_c_borne / 100.0) ** 5)

                if payout_pct <= 50:
                    pts_payout = 40.0
                elif payout_pct <= 60:
                    pts_payout = 35.0
                elif payout_pct <= 72:
                    pts_payout = 27.0
                elif payout_pct <= 85:
                    pts_payout = 18.0
                else:
                    pts_payout = 8.0

                pts_rend = min(35.0, max(5.0, rend_pct * 5.2))
                pts_croiss = min(25.0, max(3.0, taux_c_borne * 2.5))
                score_rente = int(round(min(99.0, max(15.0, pts_payout + pts_rend + pts_croiss))))

                if payout_pct <= 55:
                    c_pay = "#2ecc71"
                    diag_payout = f"<span style='color:#2ecc71; font-weight:800;'>🛡️ Ultra Sûr ({payout_pct:.0f}%)</span><br><span style='font-size:0.76em; opacity:0.8;'>{100 - payout_pct:.0f}% des profits réinvestis</span>"
                elif payout_pct <= 72:
                    c_pay = "#3498db"
                    diag_payout = f"<span style='color:#3498db; font-weight:800;'>✅ Solide ({payout_pct:.0f}%)</span><br><span style='font-size:0.76em; opacity:0.8;'>Distribution bien couverte</span>"
                else:
                    c_pay = "#f39c12" if payout_pct <= 85 else "#e74c3c"
                    diag_payout = f"<span style='color:{c_pay}; font-weight:800;'>🟡 Élevé ({payout_pct:.0f}%)</span><br><span style='font-size:0.76em; opacity:0.8;'>Marge de manœuvre réduite</span>"

                if croiss_pct >= 8.0:
                    diag_croiss = f"<span class='b-green'>🚀 +{croiss_pct:.1f}% / an</span><br><span style='font-size:0.76em; opacity:0.8;'>Accélérateur fort</span>"
                elif croiss_pct >= 4.5:
                    diag_croiss = f"<span class='b-blue'>📈 +{croiss_pct:.1f}% / an</span><br><span style='font-size:0.76em; opacity:0.8;'>Hausse régulière &gt; inflation</span>"
                else:
                    diag_croiss = f"<span class='b-neutral'>🐢 +{croiss_pct:.1f}% / an</span><br><span style='font-size:0.76em; opacity:0.8;'>Croissance modérée</span>"

                if score_rente >= 76 and payout_pct <= 65:
                    ordre_div = 0
                    decision_div = "<span class='b-green'>👑 PROFIL COMPLET</span><br><span style='font-size:0.80em;'>Rendement, sûreté et croissance réunis</span>"
                elif rend_pct >= 5.0 and payout_pct <= 75:
                    ordre_div = 1
                    decision_div = "<span class='b-blue'>💵 RENDEMENT ÉLEVÉ</span><br><span style='font-size:0.80em;'>Payout maîtrisé</span>"
                elif croiss_pct >= 7.5 and payout_pct <= 60:
                    ordre_div = 2
                    decision_div = "<span class='b-purple'>🚀 CROISSANCE DU DIVIDENDE</span><br><span style='font-size:0.80em;'>Hausse rapide du coupon sur 5 ans</span>"
                else:
                    ordre_div = 3
                    decision_div = "<span class='b-yellow'>⚖️ PROFIL MODÉRÉ</span><br><span style='font-size:0.80em;'>Critères partiellement réunis</span>"

                donnees_t3_enrichies.append({
                    "Actif": d["Actif"],
                    "FreqStr": freq_str,
                    "DivAct": d["Div/Act"],
                    "RendPct": rend_pct,
                    "Rente1000": rente_1000,
                    "YoC5A": yoc_5a,
                    "PayoutPct": payout_pct,
                    "CouleurPay": c_pay,
                    "DiagPayout": diag_payout,
                    "DiagCroiss": diag_croiss,
                    "ScoreRente": score_rente,
                    "OrdreDiv": ordre_div,
                    "DecisionDiv": decision_div,
                })

            donnees_t3_enrichies.sort(key=lambda x: (x["OrdreDiv"], -x["ScoreRente"]))

            html_t3 = """
            <table class='r-table'>
            <thead>
                <tr>
                    <th style='width:55px;'>Rang</th>
                    <th style='text-align: left;'>Actif & Calendrier</th>
                    <th>Dividende / Action<br><span style='font-size:0.82em; opacity:0.75;'>(& Gain pour 1 000 €)</span></th>
                    <th>Rendement Actuel<br><span style='font-size:0.82em; opacity:0.75;'>(➔ Projeté à 5 Ans)</span></th>
                    <th style='width:210px;'>Jauge Payout Ratio<br><span style='font-size:0.82em; opacity:0.75;'>(Part des bénéfices versée)</span></th>
                    <th>Dynamique 5 Ans</th>
                    <th style='width:125px;'>Score Rente</th>
                    <th>Profil de Rente</th>
                </tr>
            </thead>
            <tbody>
            """
            for idx_d, item_d in enumerate(donnees_t3_enrichies, start=1):
                sc_r = item_d["ScoreRente"]
                c_sc_r = "#2ecc71" if sc_r >= 75 else ("#3498db" if sc_r >= 60 else "#f39c12")
                b_rang_d = "b-green" if item_d["OrdreDiv"] == 0 else ("b-blue" if item_d["OrdreDiv"] == 1 else ("b-purple" if item_d["OrdreDiv"] == 2 else "b-neutral"))
                pay_w = max(5.0, min(100.0, item_d["PayoutPct"]))

                html_t3 += f"""
                <tr>
                    <td><span class='{b_rang_d}'>#{idx_d}</span></td>
                    <td class='r-name'>{item_d['Actif']}<br><span style='font-size:0.78em; opacity:0.75; font-weight:600;'>{item_d['FreqStr']}</span></td>
                    <td><b>{item_d['DivAct']}</b><br><span style='font-size:0.80em; color:#2ecc71; font-weight:700;'>+{item_d['Rente1000']:.1f} €/an pour 1 000 €</span></td>
                    <td>
                        <span style='color:#2ecc71; font-weight:900; font-size:1.05em;'>{item_d['RendPct']:.2f}%</span><br>
                        <span style='font-size:0.78em; opacity:0.85;'>➔ YoC 5A : <b>{item_d['YoC5A']:.2f}%</b></span>
                    </td>
                    <td>
                        {item_d['DiagPayout']}
                        <div class='score-bg'><div style='width:{pay_w}%; background:{item_d['CouleurPay']}; height:100%;'></div></div>
                    </td>
                    <td>{item_d['DiagCroiss']}</td>
                    <td>
                        <div style='font-weight:800; font-size:0.9em;'>{sc_r} / 100</div>
                        <div class='score-bg'><div style='width:{sc_r}%; background:{c_sc_r}; height:100%;'></div></div>
                    </td>
                    <td>{item_d['DecisionDiv']}</td>
                </tr>
                """
            html_t3 += "</tbody></table>"
            afficher_html(html_t3)

            # --- DÉTECTEUR DE YIELD TRAP (PIÈGES À RENDEMENT) & BONUS NOMINATIF +10% ---
            valeurs_nominatif_eligibles = {"Air Liquide", "L'Oréal", "Engie", "Seb", "Crédit Agricole"}
            alertes_yield_trap = []
            pistes_nominatif = []
            map_t2_trap = {d["Actif"]: d for d in donnees_t2}

            for item_d in donnees_t3_enrichies:
                nom_pur_d = item_d["Actif"].rsplit(" (", 1)[0]
                ecart_3a_d = float(map_t2_trap.get(item_d["Actif"], {}).get("EcartNum", 0.0))
                rend_d = item_d["RendPct"]
                pay_d = item_d["PayoutPct"]

                if rend_d >= 7.8 and (pay_d >= 75.0 or ecart_3a_d <= -12.0):
                    motif_trap = f"Rendement élevé ({rend_d:.2f}%) avec Payout tendu ({pay_d:.0f}%)" if pay_d >= 75.0 else f"Rendement facial ({rend_d:.2f}%) gonflé par une chute du cours ({ecart_3a_d:+.1f}% vs 3A)"
                    alertes_yield_trap.append(f"<li><b>{item_d['Actif']}</b> : {motif_trap} — <i>Vérifiez le cash-flow avant d'acheter.</i></li>")

                if nom_pur_d in valeurs_nominatif_eligibles:
                    rend_boost = rend_d * 1.10
                    pistes_nominatif.append(
                        f"<span class='cal-pill' style='border:1px solid rgba(46,204,113,0.4);'>"
                        f"🏅 <b>{nom_pur_d}</b> : {rend_d:.2f}% ➔ <b style='color:#2ecc71;'>{rend_boost:.2f}%</b> au Nominatif (+10%)"
                        f"</span>"
                    )

            html_trap = (
                "<ul style='margin:6px 0 0 18px; padding:0; font-size:0.84em; line-height:1.5;'>" + "".join(alertes_yield_trap) + "</ul>"
                if alertes_yield_trap
                else "<div style='font-size:0.84em; color:#2ecc71; font-weight:700; margin-top:4px;'>✅ Aucun piège à rendement (Yield Trap) détecté dans votre sélection actuelle.</div>"
            )
            html_nom_pills = "".join(pistes_nominatif) if pistes_nominatif else "<span style='font-size:0.84em; opacity:0.7;'>Aucune valeur éligible au bonus +10% dans le radar.</span>"

            html_radar_pro = f"""
            <div class="argon-grid" style="margin-top: 10px;">
                <div class="argon-card" style="text-align:left; border-left: 4px solid {'#e74c3c' if alertes_yield_trap else '#2ecc71'};">
                    <div class="argon-title" style="color:{'#e74c3c' if alertes_yield_trap else '#2ecc71'};">🚨 Détecteur Algorithmique de "Yield Trap" (Piège à Rendement)</div>
                    {html_trap}
                </div>
                <div class="argon-card" style="text-align:left; border-left: 4px solid #f39c12;">
                    <div class="argon-title" style="color:#f39c12;">🏅 Valeurs du Radar Éligibles à la Prime de Fidélité (+10% Dividende au Nominatif Administré)</div>
                    <div style="margin-top:6px;">{html_nom_pills}</div>
                </div>
            </div>
            """
            afficher_html(html_radar_pro)
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
        for cle_t in ("_historique_ventes", "_quota_ia", "_niveau_abo", "_div_encaisses_cumul", "_stripe_customer_id", "_alertes_auto", "_alertes_envoyees", "_journal_achats"):
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
        sauvegarder_dans_cloud()
        st.session_state["_notif_journal"] = ("ok", f"✅ Achat enregistré : +{qte} {nom_action}. Nouvelle ligne : {position['qte']} titre(s), PRU {position['pru']:.2f}.")

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

    def _importer_achats(lignes_a_importer):
        for ligne in sorted(lignes_a_importer, key=lambda l: l["date"]):
            appliquer_achat(ligne["action"], ligne["date"], ligne["qte"], ligne["prix"], ligne["frais"], ligne["taux"], source="import")
        sauvegarder_dans_cloud()
        # Nouveau champ de dépôt (clé différente) : le fichier importé disparaît de l'écran
        st.session_state["_compteur_import_achats"] = int(st.session_state.get("_compteur_import_achats", 0)) + 1
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
                "Indiquez quelle colonne contient quoi : seuls les achats d'actions reconnues sont importés."
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
                        signatures_existantes = {
                            f"{e.get('date')}|{e.get('action')}|{int(e.get('qte', 0))}|{float(e.get('prix', 0)):.4f}" for e in journal_achats
                        }
                        lignes_valides, apercu_import = [], []
                        for _, rangee in tableau_csv.iterrows():
                            libelle = str(rangee.get(col_valeur, "") or "")
                            date_lue = pd.to_datetime(rangee.get(col_date), dayfirst=True, errors="coerce")
                            qte_lue = _nombre_lu(rangee.get(col_qte))
                            prix_lu = _nombre_lu(rangee.get(col_prix))
                            frais_lus = _nombre_lu(rangee.get(col_frais)) if col_frais != "(aucune)" else 0.0
                            sens_lu = _normaliser(rangee.get(col_sens, "")) if col_sens != "(aucune)" else ""
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
                                    "prix": float(prix_lu), "frais": abs(float(frais_lus or 0.0)), "taux": float(taux_import),
                                }
                                signature = f"{ligne['date']}|{ligne['action']}|{ligne['qte']}|{ligne['prix']:.4f}"
                                if ligne["qte"] <= 0:
                                    statut = "Ignorée : quantité nulle"
                                elif signature in signatures_existantes:
                                    statut = "Ignorée : déjà dans le journal"
                                else:
                                    signatures_existantes.add(signature)
                                    lignes_valides.append(ligne)
                                    statut = "✅ À importer"
                            apercu_import.append({
                                "Date": date_lue.strftime("%d/%m/%Y") if not pd.isna(date_lue) else "?",
                                "Valeur (fichier)": libelle,
                                "Action reconnue": action_lue or "—",
                                "Quantité": qte_lue,
                                "Prix": prix_lu,
                                "Statut": statut,
                            })
                        st.dataframe(pd.DataFrame(apercu_import), width="stretch", hide_index=True)
                        if lignes_valides:
                            st.button(f"📥 Importer {len(lignes_valides)} achat(s)", type="primary", width="stretch",
                                      on_click=_importer_achats, args=(lignes_valides,), key="btn_importer_achats")
                        else:
                            st.warning("Aucun achat importable dans ce fichier.")

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
        def appliquer_import_ia_portefeuille():
            lignes_ext = st.session_state.get("_lignes_extraites_vision", [])
            nb_maj = 0
            for item_ext in lignes_ext:
                if not isinstance(item_ext, dict):
                    continue
                nom_e = re.sub(r"[<>]", "", str(item_ext.get("nom", ""))).strip()
                qte_e = int(float(item_ext.get("qte", 0)))
                pru_e = round(float(item_ext.get("pru", 0.0)), 2)
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

        with st.expander("📸 Import Magique : Mettre à jour mon portefeuille par Capture d'Écran ou Copier-Coller (IA Gemini)", expanded=False):
            if not est_pro_max:
                afficher_verrou_saas(
                    "Import Magique IA (Lecture optique de Capture d'Écran & Copier-Coller Courtier)",
                    "👑 Offre Pro (8,90 €/mois)",
                    "Importez ou mettez à jour toutes les lignes et PRU de votre portefeuille en 1 clic grâce à Gemini Vision."
                )
            else:
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
                    st.success(f"✅ {len(lignes_ext)} position(s) détectée(s) !")
                    st.dataframe(pd.DataFrame(lignes_ext), width="stretch")
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
    st.subheader("📅 Calendrier Annuel des Dividendes & Simulateur Effet Boule de Neige")

    if not actions_actives_pf:
        st.warning("Ajoutez des actions dans votre portefeuille pour générer votre calendrier de revenus passifs.")
    else:
        # --- TABLEAU DES PROCHAINS DÉTACHEMENTS (90J - EXCLUSIF PRO 8,90 €) ---
        @st.cache_data(ttl=3600)
        def recuperer_prochain_detachement_90j(symbole):
            for srv in ("query1", "query2"):
                try:
                    url = f"https://{srv}.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbole)}?range=2y&interval=1d&events=div"
                    req = urllib.request.Request(url, headers=HEADERS_YAHOO_PRO)
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        data = json.loads(resp.read().decode("utf-8"))
                    divs = data["chart"]["result"][0].get("events", {}).get("dividends", {})
                    if not divs:
                        return None, None, None

                    ajd = datetime.now().date()
                    prochaines_dates = []
                    for ts_key, d_info in divs.items():
                        dt_hist = datetime.fromtimestamp(int(d_info.get("date", ts_key))).date()
                        montant_u = float(d_info.get("amount", 0.0))
                        for annee_cible in [ajd.year, ajd.year + 1]:
                            try:
                                dt_proj = dt_hist.replace(year=annee_cible)
                            except ValueError:
                                dt_proj = dt_hist.replace(year=annee_cible, day=28)
                            ecart_jours = (dt_proj - ajd).days
                            if 0 <= ecart_jours <= 90:
                                prochaines_dates.append((ecart_jours, dt_proj, montant_u))

                    if not prochaines_dates:
                        return None, None, None
                    prochaines_dates.sort(key=lambda x: x[0])
                    return prochaines_dates[0]
                except Exception:
                    continue
            return None, None, None

        if est_pro_max:
            lignes_detachement_90j = []
            source_actions = st.session_state.get("watchlist", WATCHLIST_DEFAUT)
            for nom_d, pos_d in portefeuille_utilisateur.items():
                if nom_d in CLES_TECHNIQUES_PF or not isinstance(pos_d, dict) or float(pos_d.get("qte", 0)) <= 0:
                    continue
                info_d = source_actions.get(nom_d, WATCHLIST_DEFAUT.get(nom_d, {}))
                sym_d = info_d.get("symbole", "")
                if not sym_d:
                    continue
                nb_j, date_ex, mt_unit = recuperer_prochain_detachement_90j(sym_d)
                if date_ex is not None:
                    qte_d = float(pos_d.get("qte", 0))
                    dev_d = "$" if info_d.get("devise") == "USD" else "€"
                    lignes_detachement_90j.append({
                        "jours": nb_j,
                        "Action": nom_d,
                        "Date Ex-Dividende": date_ex.strftime("%d/%m/%Y"),
                        "Échéance": f"J-{nb_j}" if nb_j > 0 else "⚡ Aujourd'hui",
                        "Coupon unitaire": f"{mt_unit:.2f} {dev_d}",
                        "Total estimé": f"{mt_unit * qte_d:.2f} {dev_d}"
                    })

            if lignes_detachement_90j:
                lignes_detachement_90j.sort(key=lambda x: x["jours"])
                html_90j = """
                <div style="margin-bottom: 8px; display:flex; justify-content:space-between; align-items:center;">
                    <span style="font-size:0.85em; font-weight:800; text-transform:uppercase; color:#3498db;">📌 Prochains Détachements de Dividendes (Horizon 90 Jours)</span>
                    <span class="b-blue">{nb} détachement(s) détecté(s)</span>
                </div>
                <table class="r-table">
                <thead>
                    <tr>
                        <th style="text-align:left;">Action</th>
                        <th>Date Ex-Dividende Estimée</th>
                        <th>Échéance</th>
                        <th>Coupon Unitaire</th>
                        <th>Montant Estimé</th>
                    </tr>
                </thead>
                <tbody>
                """.format(nb=len(lignes_detachement_90j))

                for item_d in lignes_detachement_90j:
                    j_rest = item_d.get("jours", 90)
                    b_ech = "b-red" if j_rest <= 15 else ("b-blue" if j_rest <= 45 else "b-neutral")
                    html_90j += f"""
                    <tr>
                        <td class="r-name">🏢 {item_d['Action']}</td>
                        <td><b>📅 {item_d['Date Ex-Dividende']}</b></td>
                        <td><span class="{b_ech}">⏳ {item_d['Échéance']}</span></td>
                        <td>{item_d['Coupon unitaire']} / action</td>
                        <td><span class="b-green">+{item_d['Total estimé']}</span></td>
                    </tr>
                    """
                html_90j += "</tbody></table>"
                afficher_html(html_90j)

        # --- GUICHET D'ENCAISSEMENT DES DIVIDENDES VERS LA POCHE ESPÈCES (PREMIUM & PRO) ---
        def encaisser_dividende_vers_especes():
            act_enc = st.session_state.get("sel_act_enc_div")
            mt_enc = float(st.session_state.get("input_mt_enc_div", 0.0))
            if act_enc and mt_enc > 0:
                esp_actuel = float(st.session_state.get("pru_Espèces", st.session_state["portefeuille"].get("Espèces", {}).get("pru", 0.0))) if isinstance(st.session_state["portefeuille"].get("Espèces"), dict) else float(st.session_state.get("pru_Espèces", 0.0))
                nouveau_esp = round(esp_actuel + mt_enc, 2)
                st.session_state["pru_Espèces"] = nouveau_esp
                st.session_state["qte_Espèces"] = 1
                st.session_state["portefeuille"]["Espèces"] = {"qte": 1, "pru": nouveau_esp}
                st.session_state["dividendes_encaisses_cumul"] = round(float(st.session_state.get("dividendes_encaisses_cumul", 0.0)) + mt_enc, 2)
                sauvegarder_dans_cloud()
                st.session_state["_notif_div_encaisse"] = f"✅ +{mt_enc:,.2f} € de dividendes ({act_enc}) crédités dans votre poche Espèces (Nouveau solde Espèces : {nouveau_esp:,.2f} €) !"

        if st.session_state.get("_notif_div_encaisse"):
            st.success(nombres_fr(st.session_state.pop("_notif_div_encaisse")))

        actions_div_pf = [
            k for k, v in portefeuille_utilisateur.items()
            if k not in CLES_TECHNIQUES_PF and isinstance(v, dict) and float(v.get("qte", 0)) > 0
        ]
        if actions_div_pf:
            with st.expander("📥 Guichet d'Encaissement en 1 Clic : Créditer un dividende détaché dans ma poche Espèces", expanded=False):
                if mode_gratuit:
                    afficher_verrou_saas(
                        "Guichet d'Encaissement Automatique des Dividendes vers la Poche Espèces",
                        "⚡ Offre Premium (4,90 €/mois) ou 👑 Pro (8,90 €/mois)",
                        "Créditez vos coupons détachés directement dans vos liquidités PEA/CTO en 1 clic."
                    )
                else:
                    col_ed1, col_ed2, col_ed3 = st.columns([2, 1.5, 1.5])
                    with col_ed1:
                        act_choisie_div = st.selectbox("Action ayant versé son dividende :", actions_div_pf, key="sel_act_enc_div")
                    info_ed = WATCHLIST_DEFAUT.get(act_choisie_div, {})
                    qte_ed = float(portefeuille_utilisateur.get(act_choisie_div, {}).get("qte", 0))
                    fact_ed = (1.0 / TAUX_USD_EUR) if info_ed.get("devise") == "USD" else 1.0
                    nb_vers_ed = max(1, len(info_ed.get("mois_div", ["Mai"])))
                    bonus_nom_ed = 1.10 if act_choisie_div in st.session_state.get("actions_nominatif", []) else 1.0
                    montant_coupon_defaut = round((qte_ed * float(info_ed.get("div_eur", 0.0)) * fact_ed * bonus_nom_ed) / nb_vers_ed, 2)

                    with col_ed2:
                        st.number_input("Montant net reçu (€) :", min_value=0.01, value=max(0.01, montant_coupon_defaut), step=1.0, key="input_mt_enc_div")
                    with col_ed3:
                        st.markdown("<div style='margin-top:28px;'></div>", unsafe_allow_html=True)
                        st.button(
                            "💶 Créditer mes Espèces",
                            type="primary",
                            width="stretch",
                            on_click=encaisser_dividende_vers_especes,
                        )

        mois_ordre = ["Jan", "Fév", "Mar", "Avr", "Mai", "Juin", "Juil", "Août", "Sep", "Oct", "Nov", "Déc"]
        noms_mois_complets = {
            "Jan": "Janvier", "Fév": "Février", "Mar": "Mars", "Avr": "Avril",
            "Mai": "Mai", "Juin": "Juin", "Juil": "Juillet", "Août": "Août",
            "Sep": "Septembre", "Oct": "Octobre", "Nov": "Novembre", "Déc": "Décembre"
        }
        revenus_par_mois = {m: 0.0 for m in mois_ordre}
        details_par_mois = {m: [] for m in mois_ordre}
        total_annuel_div = 0.0

        noms_retenus_div = [l["nom_act"] for l in lignes_triees if not l["est_especes"]]
        for nom_act in noms_retenus_div:
            data_pos = portefeuille_utilisateur.get(nom_act, {})
            if not isinstance(data_pos, dict) or nom_act not in WATCHLIST_DEFAUT:
                continue
            qte = float(data_pos.get("qte", 0.0))
            if qte <= 0:
                continue
            info_act = WATCHLIST_DEFAUT[nom_act]
            devise = info_act.get("devise", "EUR")
            facteur = (1.0 / TAUX_USD_EUR) if devise == "USD" else 1.0
            div_annuel_eur = qte * float(info_act.get("div_eur", 0.0)) * facteur
            total_annuel_div += div_annuel_eur

            mois_versement = info_act.get("mois_div", ["Mai"])
            if mois_versement:
                montant_par_versement = div_annuel_eur / len(mois_versement)
                for m in mois_versement:
                    if m in revenus_par_mois:
                        revenus_par_mois[m] += montant_par_versement
                        details_par_mois[m].append((nom_act, montant_par_versement))

        rente_mensuelle_moy = total_annuel_div / 12.0
        meilleur_mois = max(revenus_par_mois.items(), key=lambda x: x[1]) if total_annuel_div > 0 else ("Mai", 0.0)
        nb_mois_actifs = sum(1 for v in revenus_par_mois.values() if v > 0)

        html_div_kpi = f"""
        <div class="argon-grid">
            <div class="argon-card">
                <div class="argon-title">💵 Rente Annuelle Globale</div>
                <div class="argon-val" style="color:#2ecc71;">{total_annuel_div:,.2f} € / an</div>
                <div class="argon-sub">Dividendes convertis en Euros (€)</div>
            </div>
            <div class="argon-card">
                <div class="argon-title">🗓️ Revenu Mensuel Moyen</div>
                <div class="argon-val" style="color:#3498db;">{rente_mensuelle_moy:,.2f} € / mois</div>
                <div class="argon-sub">{nb_mois_actifs} / 12 mois avec versement</div>
            </div>
            <div class="argon-card">
                <div class="argon-title">🏆 Mois Record</div>
                <div class="argon-val">{noms_mois_complets[meilleur_mois[0]]} ({meilleur_mois[1]:.1f} €)</div>
                <div class="argon-sub">Pic de détachement annuel</div>
            </div>
            <div class="argon-card">
                <div class="argon-title">🔄 Force de Frappe DCA + Div.</div>
                <div class="argon-val">+{total_annuel_div + (BUDGET_MENSUEL*12):,.0f} € / an</div>
                <div class="argon-sub">Capacité d'investissement annuelle</div>
            </div>
        </div>
        """
        afficher_html(html_div_kpi)

        paliers_rente = [
            (50.0, "🥉 Palier 1 : 50 € / mois"),
            (100.0, "🥈 Palier 2 : 100 € / mois"),
            (250.0, "🥇 Palier 3 : 250 € / mois"),
            (500.0, "💎 Palier 4 : 500 € / mois"),
            (1000.0, "👑 Palier 5 : 1 000 € / mois"),
        ]
        prochain_palier_val = 1000.0
        prochain_palier_nom = "👑 Palier 5 : 1 000 € / mois"
        for val_p, nom_p in paliers_rente:
            if rente_mensuelle_moy < val_p:
                prochain_palier_val = val_p
                prochain_palier_nom = nom_p
                break

        pct_jauge = min(100.0, max(2.0, (rente_mensuelle_moy / prochain_palier_val) * 100.0)) if prochain_palier_val > 0 else 100.0
        manque_mensuel = max(0.0, prochain_palier_val - rente_mensuelle_moy)
        manque_annuel = manque_mensuel * 12.0
        rendement_moy_pf = (total_annuel_div / valeur_totale_portefeuille) if valeur_totale_portefeuille > 0 and total_annuel_div > 0 else 0.052
        rendement_moy_pf = max(0.035, min(0.10, rendement_moy_pf))
        capital_requis_palier = manque_annuel / rendement_moy_pf
        epargne_mensuelle_totale = max(50.0, BUDGET_MENSUEL + rente_mensuelle_moy)
        mois_estimes_palier = max(1, int(math.ceil(capital_requis_palier / epargne_mensuelle_totale))) if manque_mensuel > 0 else 0

        steps_html = ""
        for val_p, nom_p in paliers_rente:
            if rente_mensuelle_moy >= val_p:
                steps_html += f"<div class='goal-step' style='border-color:#2ecc71; background:rgba(46,204,113,0.16); color:#2ecc71;'>✅ {nom_p}<br><span style='font-size:0.8em;'>Validé !</span></div>"
            elif val_p == prochain_palier_val:
                steps_html += f"<div class='goal-step' style='border-color:#3498db; background:rgba(52,152,219,0.18); color:#3498db;'>🎯 {nom_p}<br><span style='font-size:0.8em;'>En cours ({pct_jauge:.1f}%)</span></div>"
            else:
                steps_html += f"<div class='goal-step' style='opacity:0.65;'>🔒 {nom_p}<br><span style='font-size:0.8em;'>À débloquer</span></div>"

        html_jauge_rente = f"""
        <div class="goal-box">
            <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px;">
                <div>
                    <div style="font-size:0.80em; font-weight:800; text-transform:uppercase; letter-spacing:0.7px; color:#2ecc71;">🎯 Jauge d'Objectif de Rente Mensuelle</div>
                    <div style="font-size:1.22em; font-weight:900; margin-top:2px;">Cap actuel : {prochain_palier_nom} — <span style="color:#2ecc71;">{rente_mensuelle_moy:.2f} €</span> / {prochain_palier_val:.0f} € par mois</div>
                </div>
                <div style="text-align:right;">
                    <span class="b-green" style="font-size:0.95em;">Progression : {pct_jauge:.1f}%</span>
                </div>
            </div>
            <div class="goal-bar-bg">
                <div style="width:{pct_jauge:.1f}%; height:100%; background:linear-gradient(90deg, #2ecc71 0%, #3498db 100%); border-radius:10px;"></div>
            </div>
            <div style="display:flex; justify-content:space-between; font-size:0.88em; margin-bottom:12px; flex-wrap:wrap; gap:8px;">
                <span>💡 Il vous manque <b>+{manque_mensuel:.2f} € / mois</b> (soit <b>+{manque_annuel:.0f} € / an</b> de dividendes) pour valider ce palier.</span>
                <span>⏱️ <b>Estimation au rythme DCA actuel ({BUDGET_MENSUEL:.0f} €/mois) :</b> atteint dans env. <b>{mois_estimes_palier} mois</b> (~{capital_requis_palier:,.0f} € à investir).</span>
            </div>
            <div class="goal-steps">{steps_html}</div>
        </div>
        """
        afficher_html(html_jauge_rente)

        st.markdown("#### 🗓️ Calendrier Mois par Mois des Dividendes Versés sur l'Année")
        html_grille_12mois = "<div class='cal-grid'>"
        for idx_m, m_code in enumerate(mois_ordre, start=1):
            montant_m = revenus_par_mois[m_code]
            liste_ent = details_par_mois[m_code]
            classe_carte = "cal-card-active" if montant_m > 0 else "cal-card"
            couleur_montant = "#2ecc71" if montant_m > 0 else "rgba(128,128,128,0.5)"

            if liste_ent:
                pills_html = "".join(f"<span class='cal-pill'><b>{nom_e}</b> : {val_e:.1f} €</span>" for nom_e, val_e in liste_ent)
            else:
                pills_html = "<span style='font-size:0.82em; opacity:0.45; font-style:italic;'>Aucun détachement prévu</span>"

            html_grille_12mois += f"""
            <div class="{classe_carte}">
                <div>
                    <div class="cal-month">
                        <span>{idx_m:02d}. {noms_mois_complets[m_code]}</span>
                        <span style="font-size:0.85em;">{'💰' if montant_m > 0 else '⚪'}</span>
                    </div>
                    <div style="margin-bottom:10px;">{pills_html}</div>
                </div>
                <div style="text-align:right; border-top:1px dashed rgba(128,128,128,0.2); padding-top:6px;">
                    <span style="font-size:0.78em; opacity:0.75; margin-right:6px;">Total :</span>
                    <span class="cal-total" style="color:{couleur_montant};">{montant_m:,.2f} €</span>
                </div>
            </div>
            """
        html_grille_12mois += "</div>"
        afficher_html(html_grille_12mois)

        st.markdown("#### 📊 Diagramme en Bâtons des Dividendes par Mois (€)")
        df_bar_div = pd.DataFrame([
            {"Ordre": i, "Mois": noms_mois_complets[m], "Dividendes (€)": round(revenus_par_mois[m], 2)}
            for i, m in enumerate(mois_ordre)
        ])
        spec_bar_div = {
            "height": 300,
            "mark": {"type": "bar", "cornerRadiusTopLeft": 6, "cornerRadiusTopRight": 6, "color": "#2ecc71"},
            "encoding": {
                "x": {"field": "Mois", "type": "nominal", "sort": list(noms_mois_complets.values()), "axis": {"labelAngle": 0, "title": "Mois de l'année"}},
                "y": {"field": "Dividendes (€)", "type": "quantitative", "axis": {"title": "Montant versé (€)"}},
                "tooltip": [
                    {"field": "Mois", "type": "nominal"},
                    {"field": "Dividendes (€)", "type": "quantitative", "format": ",.2f"},
                ],
            },
        }
        st.vega_lite_chart(df_bar_div, spec_bar_div, width="stretch")

        st.markdown("---")
        st.markdown("#### ❄️ Simulateur Interactif d'Effet Boule de Neige (DCA + Dividendes Réinvestis)")

        rendement_actuel_pf = (total_annuel_div / valeur_totale_portefeuille * 100.0) if valeur_totale_portefeuille > 0 else 4.8
        rendement_defaut_slider = float(max(1.5, min(10.0, round(rendement_actuel_pf, 1))))

        col_sl1, col_sl2, col_sl3, col_sl4 = st.columns(4)
        with col_sl1:
            horizon_annees = st.slider("⏳ Horizon (Années)", min_value=5, max_value=30, value=15, step=1)
        with col_sl2:
            dca_simule = st.slider("💶 Apport DCA Mensuel (€)", min_value=0, max_value=10000, value=int(min(10000, max(0, BUDGET_MENSUEL))), step=50)
        with col_sl3:
            rendement_simule_pct = st.slider("🌱 Rendement Dividende (%)", min_value=1.0, max_value=12.0, value=rendement_defaut_slider, step=0.2)
        with col_sl4:
            croissance_annuelle_pct = st.slider("📈 Croissance Annuelle Cours/Div (%)", min_value=0.0, max_value=10.0, value=3.0, step=0.5)

        cap_courant = valeur_totale_portefeuille
        cap_investi_cumule = cout_total_achat if cout_total_achat > 0 else valeur_totale_portefeuille
        lignes_proj = []
        donnees_graph_boule = []

        for annee in range(1, horizon_annees + 1):
            apport_annuel = float(dca_simule * 12)
            cap_investi_cumule += apport_annuel
            plus_value_croissance = cap_courant * (croissance_annuelle_pct / 100.0)
            div_annee = (cap_courant + apport_annuel / 2.0) * (rendement_simule_pct / 100.0)
            cap_courant = cap_courant + apport_annuel + plus_value_croissance + div_annee
            rente_mensuelle_an = div_annee / 12.0

            annee_cal = datetime.now().year + annee
            donnees_graph_boule.append({
                "Année": f"{annee_cal}",
                "Capital Total Boule de Neige (€)": round(cap_courant, 0),
                "Total Apports Personnels (€)": round(cap_investi_cumule, 0),
                "Rente Annuelle (€/an)": round(div_annee, 0),
            })
            lignes_proj.append({
                "Horizon": f"Année +{annee} ({annee_cal})",
                "Apports Cumulés": f"{cap_investi_cumule:,.0f} €",
                "Capital Projeté": f"{cap_courant:,.0f} €",
                "Gains & Dividendes Réinvestis": f"+{cap_courant - cap_investi_cumule:,.0f} €",
                "Rente Annuelle": f"{div_annee:,.0f} € / an",
                "Rente Mensuelle": f"{rente_mensuelle_an:,.1f} € / mois",
            })

        dernier_pt = donnees_graph_boule[-1]
        gain_pur_interets = dernier_pt["Capital Total Boule de Neige (€)"] - dernier_pt["Total Apports Personnels (€)"]

        html_kpi_snow = f"""
        <div class="argon-grid">
            <div class="argon-card">
                <div class="argon-title">🏔️ Capital Final à {horizon_annees} Ans</div>
                <div class="argon-val" style="color:#2ecc71;">{dernier_pt['Capital Total Boule de Neige (€)']:,.0f} €</div>
                <div class="argon-sub">Dont Apports : <b>{dernier_pt['Total Apports Personnels (€)']:,.0f} €</b></div>
            </div>
            <div class="argon-card">
                <div class="argon-title">✨ Intérêts Composés Gagnés</div>
                <div class="argon-val" style="color:#9b59b6;">+{gain_pur_interets:,.0f} €</div>
                <div class="argon-sub">Dividendes réinvestis + Croissance</div>
            </div>
            <div class="argon-card">
                <div class="argon-title">💵 Future Rente Annuelle</div>
                <div class="argon-val" style="color:#3498db;">{dernier_pt['Rente Annuelle (€/an)']:,.0f} € / an</div>
                <div class="argon-sub">En {dernier_pt['Année']}</div>
            </div>
            <div class="argon-card">
                <div class="argon-title">🏖️ Future Rente Mensuelle</div>
                <div class="argon-val" style="color:#f39c12;">{dernier_pt['Rente Annuelle (€/an)']/12.0:,.0f} € / mois</div>
                <div class="argon-sub">Revenu passif mensuel estimé</div>
            </div>
        </div>
        """
        afficher_html(html_kpi_snow)

        col_g_snow1, col_g_snow2 = st.columns(2)
        df_snow_chart = pd.DataFrame(donnees_graph_boule).set_index("Année")
        with col_g_snow1:
            st.markdown("**📈 Courbe d'Accélération : Capital Total vs Apports Personnels (€)**")
            st.area_chart(df_snow_chart[["Capital Total Boule de Neige (€)", "Total Apports Personnels (€)"]], height=300)
        with col_g_snow2:
            st.markdown("**💵 Progression de votre Rente Annuelle de Dividendes (€/an)**")
            st.bar_chart(df_snow_chart[["Rente Annuelle (€/an)"]], height=300)

        with st.expander(f"📋 Voir le tableau détaillé année par année sur {horizon_annees} ans", expanded=True):
            html_proj = "<table class='r-table'><thead><tr><th style='text-align:left;'>Horizon</th><th>Apports Cumulés</th><th>Capital Projeté (€)</th><th>Intérêts Composés</th><th>Rente Annuelle</th><th>Rente Mensuelle</th></tr></thead><tbody>"
            for lp in lignes_proj:
                html_proj += f"<tr><td class='r-name'>{lp['Horizon']}</td><td>{lp['Apports Cumulés']}</td><td><b>{lp['Capital Projeté']}</b></td><td style='color:#9b59b6; font-weight:700;'>{lp['Gains & Dividendes Réinvestis']}</td><td style='color:#2ecc71; font-weight:800;'>{lp['Rente Annuelle']}</td><td><span class='b-blue'>{lp['Rente Mensuelle']}</span></td></tr>"
            html_proj += "</tbody></table>"
            afficher_html(html_proj)
# ------------------------------------------------------------------------------
# ONGLET 4 : COACH & AUDIT IA 2.0 (AVEC PHRASE FLASH + AUTO-DISCOVERY GEMINI)
# ------------------------------------------------------------------------------
with onglet_ia:
    st.subheader("🤖 Coach & Audit IA 2.0 (Diagnostic Instantané & Intelligence Gemini)")

    quota_utilise = int(st.session_state.get("quota_ia_utilise", 0))
    quota_restant = max(0, quota_ia_max - quota_utilise)

    nb_lignes_actions = sum(
        1 for k, v in portefeuille_utilisateur.items()
        if k not in CLES_TECHNIQUES_PF and isinstance(v, dict) and float(v.get("qte", 0)) > 0 and k in WATCHLIST_DEFAUT
    )
    poids_max_ligne = 0.0
    nom_max_ligne = "Aucune"
    if valeur_totale_portefeuille > 0 and lignes_triees:
        for l_it in lignes_triees:
            if not l_it["est_especes"]:
                p_it = (l_it["val_eur"] / valeur_totale_portefeuille) * 100.0
                if p_it > poids_max_ligne:
                    poids_max_ligne = p_it
                    nom_max_ligne = l_it["nom_act"]

    note_sante_pf = min(100, max(20, int(40 + min(30, nb_lignes_actions * 5) + (20 if poids_max_ligne <= 30 else 5) + (10 if len(repartition_secteurs) >= 3 else 0))))
    taux_couverture_dca = (dividendes_bruts_totaux_eur / (BUDGET_MENSUEL * 12) * 100.0) if BUDGET_MENSUEL > 0 else 0.0

    html_ia_header = f"""
    <div class="argon-grid">
        <div class="argon-card">
            <div class="argon-title">🩺 Score de Santé Portefeuille</div>
            <div class="argon-val" style="color:#2ecc71;">{note_sante_pf} / 100</div>
            <div class="argon-sub">{nb_lignes_actions} ligne(s) | {len(repartition_secteurs)} secteur(s)</div>
        </div>
        <div class="argon-card">
            <div class="argon-title">⚖️ Ligne Principale (Concentration)</div>
            <div class="argon-val" style="color:{'#2ecc71' if poids_max_ligne <= 30 else '#f39c12'};">{poids_max_ligne:.1f}%</div>
            <div class="argon-sub">Plus forte position : <b>{nom_max_ligne}</b></div>
        </div>
        <div class="argon-card">
            <div class="argon-title">🔄 Autonomie Financière DCA</div>
            <div class="argon-val" style="color:#3498db;">{taux_couverture_dca:.1f}%</div>
            <div class="argon-sub">Part du DCA annuel financée par vos dividendes</div>
        </div>
        <div class="argon-card">
            <div class="argon-title">⚡ Crédits d'Audit IA du Jour</div>
            <div class="argon-val" style="color:#9b59b6;">{quota_restant} / {quota_ia_max}</div>
            <div class="argon-sub">Forfait actif : <b>{niveau_acces.upper()}</b> | VIX : {vix_val:.1f}</div>
        </div>
    </div>
    """
    afficher_html(html_ia_header)

    top_opps_noms = [f"<b>{c['nom']}</b> ({c['score']}/100)" for c in candidats_dca_top2]
    texte_opps_moment = " et ".join(top_opps_noms) if top_opps_noms else "aucune valeur en signal fort actuellement"
    etat_conc_court = "bien équilibré" if poids_max_ligne <= 30 else f"concentré sur <b>{nom_max_ligne}</b> ({poids_max_ligne:.1f}%)"

    # --- SYNTHÈSE DES PLUS-VALUES ACTÉES POUR LE COACH IA ---
    hist_ventes_ia = st.session_state.get("historique_ventes", []) if est_pro_max else []
    total_pv_actee_ia = sum(float(v.get("plus_value_eur", 0.0)) for v in hist_ventes_ia)
    total_vol_vendu_ia = sum(float(v.get("montant_eur", 0.0)) for v in hist_ventes_ia)
    total_cout_vendu_ia = total_vol_vendu_ia - total_pv_actee_ia
    perf_extraction_ia = (total_pv_actee_ia / total_cout_vendu_ia * 100.0) if total_cout_vendu_ia > 0 else 0.0
    nb_ventes_gagnantes_ia = sum(1 for v in hist_ventes_ia if float(v.get("plus_value_eur", 0.0)) >= 0)
    texte_bilan_ventes_flash = (
        f" Vos arbitrages ont permis d'acter <b>{total_pv_actee_ia:+,.2f} €</b> de plus-values réelles "
        f"(performance d'extraction de <b>{perf_extraction_ia:+.2f}%</b> sur {len(hist_ventes_ia)} vente(s))."
        if hist_ventes_ia else ""
    )

    html_phrase_flash = f"""
    <div class="ia-flash">
        💡 <b>Synthèse Flash du Coach :</b> Votre portefeuille actif de <b>{valeur_totale_portefeuille:,.0f} €</b> ({plus_value_pct:+.1f}% latent) est {etat_conc_court} et génère <b>{dividendes_nets_totaux_eur:,.0f} € net/an</b> ({dividendes_nets_totaux_eur/12.0:.1f} €/mois).{texte_bilan_ventes_flash} Les signaux techniques les plus forts du moment concernent {texte_opps_moment}.
    </div>
    """
    afficher_html(html_phrase_flash)

    # ==========================================================================
    # SYNTHÈSE CROISÉE 360° DES OPPORTUNITÉS DU MOMENT (RADAR + TECH + DIV + PF)
    # ==========================================================================
    map_t2_ia = {d["Actif"]: d for d in donnees_t2}
    map_t3_ia = {d["Actif"]: d for d in donnees_t3}
    map_t4_ia = {d["Actif"]: d for d in donnees_t4}

    synthese_opportunites = []
    for d1 in donnees_t1:
        clef_actif = d1["Actif"]
        nom_b = d1["NomBrut"]
        d2 = map_t2_ia.get(clef_actif, {})
        d3 = map_t3_ia.get(clef_actif, {})
        d4 = map_t4_ia.get(clef_actif, {})

        info_w = WATCHLIST_DEFAUT.get(nom_b, {})
        devise_a = info_w.get("devise", "EUR")
        sym_d = "$" if devise_a == "USD" else "€"
        facteur_d = (1.0 / TAUX_USD_EUR) if devise_a == "USD" else 1.0

        try:
            prix_f = float(str(d1["Prix"]).split()[0])
        except Exception:
            prix_f = float(prix_temps_reel.get(nom_b, 50.0))

        try:
            sup_f = float(str(d4.get("Support 30J", f"{prix_f*0.95}")).split()[0])
            res_f = float(str(d4.get("Résistance 30J", f"{prix_f*1.05}")).split()[0])
        except Exception:
            sup_f, res_f = prix_f * 0.95, prix_f * 1.05

        amp_30 = max(0.01, res_f - sup_f)
        pos_canal_30 = max(0.0, min(100.0, ((prix_f - sup_f) / amp_30) * 100.0))
        stoch_f = float(d1.get("Stoch", 50.0))
        score_timing_ct = int(round(100.0 - (0.55 * pos_canal_30 + 0.45 * stoch_f)))
        score_timing_ct = max(10, min(98, score_timing_ct))

        ecart_3a = float(d2.get("EcartNum", 0.0))
        try:
            rend_f = float(str(d3.get("Rendement", "3.0%")).replace("%", "").strip())
        except Exception:
            rend_f = 3.0
        try:
            payout_f = float(str(d3.get("Payout", "55%")).replace("%", "").strip())
        except Exception:
            payout_f = 55.0

        pos_pf = portefeuille_utilisateur.get(nom_b)
        bonus_pf = 0
        est_sous_pru = False
        if pos_pf and isinstance(pos_pf, dict) and float(pos_pf.get("qte", 0)) > 0:
            q_pf = int(pos_pf["qte"])
            pru_pf = float(pos_pf["pru"])
            val_l_eur = q_pf * prix_f * facteur_d
            poids_pf = (val_l_eur / valeur_totale_portefeuille * 100.0) if valeur_totale_portefeuille > 0 else 0.0
            ecart_pru_pct = ((prix_f - pru_pf) / pru_pf * 100.0) if pru_pf > 0 else 0.0

            if prix_f < pru_pf and poids_pf < 25.0:
                est_sous_pru = True
                bonus_pf = 8
                badge_pf = f"<span class='b-green'>📉 Sous votre PRU ({pru_pf:.2f} {sym_d} | {ecart_pru_pct:+.1f}%)</span>"
                conseil_pf = f"Cours sous votre PRU (poids actuel : {poids_pf:.1f}%)"
            elif poids_pf >= 28.0:
                bonus_pf = -12
                badge_pf = f"<span class='b-yellow'>⚖️ Ligne forte ({poids_pf:.1f}% du PF)</span>"
                conseil_pf = f"PRU : {pru_pf:.2f} {sym_d} — ligne déjà importante dans le portefeuille"
            else:
                bonus_pf = 4
                badge_pf = f"<span class='b-blue'>💼 En portefeuille ({q_pf} act. | {poids_pf:.1f}%)</span>"
                conseil_pf = f"PRU : {pru_pf:.2f} {sym_d} ({ecart_pru_pct:+.1f}%)"
        else:
            bonus_pf = 6
            badge_pf = "<span class='b-purple'>✨ Absente du portefeuille</span>"
            conseil_pf = "Valeur absente du portefeuille"

        pts_radar = float(d1["Score"]) * 0.40
        pts_timing = float(score_timing_ct) * 0.25
        pts_value = (20.0 if ecart_3a <= -10 else (15.0 if ecart_3a < 0 else (8.0 if ecart_3a <= 5 else 2.0)))
        pts_div = min(15.0, (rend_f * 1.8) + (5.0 if payout_f <= 65 else 1.5))
        score_conv = int(round(min(99.0, max(12.0, pts_radar + pts_timing + pts_value + pts_div + bonus_pf))))

        ordre_limite_ideal = max(sup_f, min(prix_f, sup_f + 0.25 * amp_30))

        synthese_opportunites.append({
            "Nom": nom_b,
            "Actif": clef_actif,
            "Prix": d1["Prix"],
            "Cible": d1["Prix Cible"],
            "EcartCible": d1["Écart Cible (%)"],
            "ScoreRadar": d1["Score"],
            "ScoreTiming": score_timing_ct,
            "ScoreConv": score_conv,
            "RSI": d1["RSI"],
            "Stoch": int(stoch_f),
            "Ecart3A": d2.get("Écart %", "0.0%"),
            "Ecart3ANum": ecart_3a,
            "StatutValue": d2.get("Statut Value", "Neutre"),
            "Rendement": d3.get("Rendement", "N/A"),
            "RendNum": rend_f,
            "Payout": d3.get("Payout", "N/A"),
            "PayoutNum": payout_f,
            "Support": d4.get("Support 30J", "N/A"),
            "OrdreLimite": f"{ordre_limite_ideal:.2f} {sym_d}",
            "BadgePF": badge_pf,
            "ConseilPF": conseil_pf,
            "EstSousPRU": est_sous_pru,
            "EnPortefeuille": bool(pos_pf and isinstance(pos_pf, dict) and float(pos_pf.get("qte", 0)) > 0),
        })

    synthese_opportunites.sort(key=lambda x: x["ScoreConv"], reverse=True)

    st.markdown("#### 🎯 Radar de Convergence 360° : les Signaux les Plus Convergents")
    st.caption("Croisement automatique en temps réel entre vos **4 Tableaux Techniques/Fondamentaux** et **les lignes de votre Portefeuille**.")

    if synthese_opportunites:
        top_podium = synthese_opportunites[:3]
        medailles = ["🥇 CONVERGENCE #1", "🥈 CONVERGENCE #2", "🥉 CONVERGENCE #3"]
        couleurs_bord = ["#2ecc71", "#3498db", "#9b59b6"]

        html_podium = "<div class='argon-grid'>"
        for idx_p, opp in enumerate(top_podium):
            c_b = couleurs_bord[idx_p]
            b_val_c = "b-green" if opp["Ecart3ANum"] < 0 else "b-neutral"
            b_tim_c = "b-green" if opp["ScoreTiming"] >= 65 else ("b-blue" if opp["ScoreTiming"] >= 48 else "b-yellow")

            nom_o = opp["Nom"]
            pos_p = portefeuille_utilisateur.get(nom_o)
            conseil_pru_dynamique = opp["ConseilPF"]

            if pos_p and isinstance(pos_p, dict) and float(pos_p.get("qte", 0)) > 0:
                q_actuelle = float(pos_p["qte"])
                pru_actuel = float(pos_p["pru"])
                try:
                    prix_act_f = float(str(opp["Prix"]).split()[0])
                except Exception:
                    prix_act_f = pru_actuel

                nouveau_pru_simule = ((q_actuelle * pru_actuel) + (1 * prix_act_f)) / (q_actuelle + 1)
                sym_dev_p = "$" if "$" in opp["Prix"] else "€"

                if prix_act_f < pru_actuel:
                    conseil_pru_dynamique = f"Simulation : 1 titre de plus ferait passer votre PRU de <b>{pru_actuel:.2f} ➔ {nouveau_pru_simule:.2f} {sym_dev_p}</b>"
                else:
                    conseil_pru_dynamique = f"Cours au-dessus de votre PRU ({pru_actuel:.2f} {sym_dev_p})"

            html_podium += f"""
            <div class="argon-card" style="text-align:left; border-top: 4px solid {c_b}; min-width: 260px;">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
                    <span style="font-size:0.75em; font-weight:900; color:{c_b}; letter-spacing:0.6px;">{medailles[idx_p]}</span>
                    <span class="b-green" style="font-size:0.82em;">Convergence : {opp['ScoreConv']}/100</span>
                </div>
                <div style="font-size:1.22em; font-weight:900; margin-bottom:4px;">{opp['Actif']} — <span style="color:{c_b};">{opp['Prix']}</span></div>
                <div style="font-size:0.80em; opacity:0.85; margin-bottom:10px;">🎯 Objectif Cible : <b>{opp['Cible']}</b> ({opp['EcartCible']})</div>
                <div style="display:flex; flex-wrap:wrap; gap:5px; margin-bottom:10px;">
                    <span class="b-blue" style="font-size:0.76em;">📊 Radar : {opp['ScoreRadar']}/100 (RSI {opp['RSI']})</span>
                    <span class="{b_val_c}" style="font-size:0.76em;">📐 Canal 3A : {opp['Ecart3A']}</span>
                    <span class="{b_tim_c}" style="font-size:0.76em;">⚡ Timing 30J : {opp['ScoreTiming']}/100</span>
                    <span class="b-green" style="font-size:0.76em;">💰 Div : {opp['Rendement']} (Payout {opp['Payout']})</span>
                </div>
                <div style="background:rgba(128,128,128,0.06); border-radius:8px; padding:8px 10px; font-size:0.82em; line-height:1.45;">
                    <div style="margin-bottom:4px;">{opp['BadgePF']}</div>
                    <div>💡 {conseil_pru_dynamique}</div>
                    <div style="margin-top:4px; color:#2ecc71; font-weight:700;">📏 Niveau technique de référence : {opp['OrdreLimite']} (Support : {opp['Support']})</div>
                </div>
            </div>
            """
        html_podium += "</div>"
        afficher_html(html_podium)

        opp_moyennage = next((x for x in synthese_opportunites if x["EstSousPRU"]), None)
        opp_value_timing = sorted(synthese_opportunites, key=lambda x: (x["Ecart3ANum"] - x["ScoreTiming"] * 0.3))[0]
        opp_rendement = sorted([x for x in synthese_opportunites if x["PayoutNum"] <= 75], key=lambda x: x["RendNum"], reverse=True)
        opp_rend_top = opp_rendement[0] if opp_rendement else synthese_opportunites[0]
        opp_decouverte = next((x for x in synthese_opportunites if not x["EnPortefeuille"]), synthese_opportunites[0])

        txt_moy = f"<b>{opp_moyennage['Nom']}</b> (Cours {opp_moyennage['Prix']} sous votre PRU)" if opp_moyennage else "Toutes vos lignes sont au-dessus de leur PRU 🎉"

        html_boussole = f"""
        <div class="meteo-bar" style="margin-top: -6px; margin-bottom: 18px;">
            <div class="meteo-item" style="border-left-color:#2ecc71;">
                <div><div style="font-size:0.72em; font-weight:800; opacity:0.75;">📉 COURS SOUS VOTRE PRU</div><div style="font-size:0.90em; margin-top:2px;">{txt_moy}</div></div>
            </div>
            <div class="meteo-item" style="border-left-color:#3498db;">
                <div><div style="font-size:0.72em; font-weight:800; opacity:0.75;">📐 TOP DÉCOTE + TIMING</div><div style="font-size:0.90em; margin-top:2px;"><b>{opp_value_timing['Nom']}</b> (3A : {opp_value_timing['Ecart3A']} | Timing {opp_value_timing['ScoreTiming']}/100)</div></div>
            </div>
            <div class="meteo-item" style="border-left-color:#f39c12;">
                <div><div style="font-size:0.72em; font-weight:800; opacity:0.75;">👑 RENDEMENT LE PLUS ÉLEVÉ (PAYOUT ≤ 75 %)</div><div style="font-size:0.90em; margin-top:2px;"><b>{opp_rend_top['Nom']}</b> ({opp_rend_top['Rendement']} | Payout {opp_rend_top['Payout']})</div></div>
            </div>
            <div class="meteo-item" style="border-left-color:#9b59b6;">
                <div><div style="font-size:0.72em; font-weight:800; opacity:0.75;">🌱 MEILLEURE CONVERGENCE HORS PORTEFEUILLE</div><div style="font-size:0.90em; margin-top:2px;"><b>{opp_decouverte['Nom']}</b> (Convergence {opp_decouverte['ScoreConv']}/100)</div></div>
            </div>
        </div>
        """
        afficher_html(html_boussole)

        with st.expander("📊 Voir la Matrice Complète de Convergence 360° (Toutes vos actions classées)", expanded=False):
            if mode_gratuit:
                afficher_verrou_saas(
                    "Matrice Complète de Convergence 360° (Ensemble du Catalogue)",
                    "⚡ Offre Premium (4,90 €/mois) ou 👑 Pro (8,90 €/mois)",
                    "Débloquez le classement croisé intégral sur toutes vos actions PEA et US."
                )
            else:
                html_mat = """
                <table class='r-table'>
                <thead>
                    <tr>
                        <th>Rang</th>
                        <th style='text-align:left;'>Actif</th>
                        <th>Score Convergence</th>
                        <th>Radar (/100)</th>
                        <th>Canal 3 Ans</th>
                        <th>Timing 30J</th>
                        <th>Dividende (Payout)</th>
                        <th>Statut Portefeuille</th>
                        <th>Niveau Technique</th>
                    </tr>
                </thead>
                <tbody>
                """
                for idx_m, om in enumerate(synthese_opportunites, start=1):
                    c_conv = "#2ecc71" if om["ScoreConv"] >= 70 else ("#3498db" if om["ScoreConv"] >= 55 else "#f39c12")
                    html_mat += f"""
                    <tr>
                        <td><b>#{idx_m}</b></td>
                        <td class='r-name'>{om['Actif']}<br><span style='font-size:0.80em; opacity:0.75;'>Cours : {om['Prix']}</span></td>
                        <td>
                            <div style='font-weight:900; color:{c_conv};'>{om['ScoreConv']} / 100</div>
                            <div class='score-bg'><div style='width:{om['ScoreConv']}%; background:{c_conv}; height:100%;'></div></div>
                        </td>
                        <td><b>{om['ScoreRadar']}</b> (RSI {om['RSI']})</td>
                        <td>{om['Ecart3A']}</td>
                        <td>{om['ScoreTiming']}/100 (Stoch {om['Stoch']}%)</td>
                        <td><b style='color:#2ecc71;'>{om['Rendement']}</b> ({om['Payout']})</td>
                        <td>{om['BadgePF']}</td>
                        <td><span class='b-green'>{om['OrdreLimite']}</span></td>
                    </tr>
                    """
                html_mat += "</tbody></table>"
                afficher_html(html_mat)

    @st.cache_data(ttl=3600)
    def lister_modeles_gemini_actifs(cle_api):
        modeles = []
        try:
            url_list = f"https://generativelanguage.googleapis.com/v1beta/models?key={urllib.parse.quote(cle_api)}"
            req_list = urllib.request.Request(url_list, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req_list, timeout=8) as resp_l:
                data_l = json.loads(resp_l.read().decode("utf-8"))
                for m_info in data_l.get("models", []):
                    methodes = m_info.get("supportedGenerationMethods", [])
                    nom_m = m_info.get("name", "").replace("models/", "")
                    if "generateContent" in methodes and "gemini" in nom_m:
                        modeles.append(nom_m)
        except Exception:
            pass
        return modeles

    def generer_audit_expert_hybride(question_utilisateur, code_audit=""):
        if question_utilisateur:
            for s_a, a_a in [
                ("opportunite", "opportunité"), ("strategie", "stratégie"),
                ("securite", "sécurité"), ("equilibre", "équilibre"),
                ("repartition", "répartition"), ("sante", "santé"),
                ("impot", "impôt"), ("fiscalite", "fiscalité"),
            ]:
                # Mots entiers uniquement : « puissante » ou « croissante » ne doivent pas devenir « puissanté »
                question_utilisateur = re.sub(rf"\b{s_a}(s?)\b", rf"{a_a}\1", question_utilisateur)
                question_utilisateur = re.sub(rf"\b{s_a.capitalize()}(s?)\b", rf"{a_a.capitalize()}\1", question_utilisateur)

        plus_value_glob = valeur_totale_portefeuille - cout_total_achat
        pv_pct_glob = (plus_value_glob / cout_total_achat * 100) if cout_total_achat > 0 else 0.0
        rente_mens_nette = dividendes_nets_totaux_eur / 12.0

        top_3_lignes = [
            f"**{l['nom_act']}** ({l['val_eur']:,.0f} €, soit {(l['val_eur']/valeur_totale_portefeuille*100 if valeur_totale_portefeuille>0 else 0):.1f}% du portefeuille, PV : `{l['pv_eur']:+,.0f} €`)"
            for l in lignes_triees if not l["est_especes"]
        ][:3]
        top_3_radar = [
            f"**{d['Actif']}** (Score `{d['Score']}/100` — {d['Décision']}, Cours : {d['Prix']}, Cible : {d['Prix Cible']}, RSI : {d['RSI']})"
            for d in sorted(donnees_t1, key=lambda x: x["Score"], reverse=True)[:3]
        ]

        if hist_ventes_ia:
            lignes_v_recap = "\n".join(
                f"* **{v['date']} — {v['action']}** (x{v['qte']}) : Vendu à **{v['prix_vente']:.2f} {v['devise']}** vs PRU **{v['pru']:.2f} {v['devise']}** ➔ Plus/Moins-Value actée : **`{v['plus_value_eur']:+,.2f} € ({v['perf_pct']:+.2f}%)`**"
                for v in hist_ventes_ia[:10]
            )
            bloc_recap_pv_md = f"""#### 💰 Bilan de vos Arbitrages & Plus/Moins-Values Actées (Réalisées)
- **Total Plus/Moins-Values Nettes Actées :** **`{total_pv_actee_ia:+,.2f} €`** extraits sur **{len(hist_ventes_ia)} arbitrage(s)**.
- **Performance d'Extraction Réelle :** **`{perf_extraction_ia:+.2f}%`** (calculée sur **{total_cout_vendu_ia:,.2f} €** de capital initial vendu, pour **{total_vol_vendu_ia:,.2f} €** encaissés net).
- **Taux de Réussite (Win Rate) :** **{nb_ventes_gagnantes_ia} vente(s) gagnante(s) sur {len(hist_ventes_ia)}** ({(nb_ventes_gagnantes_ia/len(hist_ventes_ia)*100):.0f}% de réussite).
- **Dernières opérations actées :**
{lignes_v_recap}"""
        else:
            bloc_recap_pv_md = """#### 💰 Bilan de vos Arbitrages & Plus/Moins-Values Actées (Réalisées)
- *Aucune vente actée active (ou module Arbitrages réservé à l'offre Pro 8,90 €/mois).*"""

        if code_audit == "AUDIT_1":
            return f"""### 🔍 Audit Complet 360°, Plus-Values Actées & Optimisation Fiscale

#### 1. Bilan Patrimonial & Performance Globale
- **Valorisation Active :** Votre portefeuille s'élève à **{valeur_totale_portefeuille:,.2f} €** pour un capital investi de **{cout_total_achat:,.2f} €**, soit une performance latente de **{plus_value_glob:+,.2f} € ({pv_pct_glob:+.2f}%)**.
- **Score de Santé Global :** **{note_sante_pf}/100** avec **{nb_lignes_actions} ligne(s) active(s)** répartie(s) sur **{len(repartition_secteurs)} secteur(s)**.
- **Vos Piliers Principaux :** {', '.join(top_3_lignes) if top_3_lignes else 'Aucune ligne enregistrée'}.

{bloc_recap_pv_md}

#### 3. Analyse de Concentration & PRU
- **Concentration Maximale :** Votre première ligne (**{nom_max_ligne}**) pèse **{poids_max_ligne:.1f}%** de votre patrimoine. {'✅ Excellente maîtrise du risque (< 30%).' if poids_max_ligne <= 30 else '⚠️ Attention : cette ligne dépasse le seuil prudentiel de 30%. Une répartition plus homogène réduirait la dépendance à cette seule ligne.'}

#### 4. Bilan Fiscal PEA (EUR) vs CTO (USD)
- **Exposition Devises :** **{exposition_eur:,.0f} € en zone Euro (PEA)** contre **{exposition_usd:,.0f} € en Dollars US (CTO)**.
- **Efficience Fiscale des Dividendes :** Vos actions produisent **{dividendes_bruts_totaux_eur:,.2f} € brut/an**, soit **{dividendes_nets_totaux_eur:,.2f} € net/an ({rente_mens_nette:.2f} € net/mois)**.

*⚖️ Rappel : Analyse statistique et pédagogique générée par le moteur Boursy 2.0 (Non-CIF).*"""

        elif code_audit == "AUDIT_2":
            achats_txt = "\n".join(
                f"* **{item['nom']} ({item['devise']})** : Simulation : **{achats_simules[item['nom']]} action(s)** à `{item['prix_eur']:.2f} €` (Score : **{item['score']}/100**, Gain de rente : **+{achats_simules[item['nom']]*item['div_eur']:.2f} €/an**)"
                for item in candidats_dca_top2 if achats_simules.get(item["nom"], 0) > 0
            )
            if not achats_txt:
                achats_txt = "* Aucune valeur ne valide simultanément un score ≥ 45/100 et un signal EMA haussier/neutre aujourd'hui."
            return f"""### 🛒 Simulation de Répartition DCA du Mois ({BUDGET_MENSUEL:.0f} €) selon le VIX & le RSI

#### 1. Lecture de la Météo des Marchés
- **Indice de nervosité VIX :** **{vix_val:.1f}** ({etat_vix}) | **CAC 40 :** {cac_str} | **S&P 500 :** {sp_str}.
- **Contexte de marché :** {'Le VIX est élevé : la nervosité domine le marché, et ces phases s’accompagnent souvent de cours plus bas sur de nombreuses valeurs.' if vix_val >= 22 else 'Le marché est calme à normal : la simulation retient les valeurs au score le plus élevé, en tenant compte du RSI (14J) et de l’écart au prix cible.'}

#### 2. Top 3 des Signaux Techniques du Jour
{chr(10).join('* ' + s for s in top_3_radar)}

#### 3. Répartition Condensée de votre Enveloppe de {BUDGET_MENSUEL:.0f} € (Max 2 lignes)
{achats_txt}
- **Total investi ce mois-ci :** **{montant_investi_dca:.2f} €** (Liquidités restantes : **{budget_courant:.2f} €**)
- **Nouveaux dividendes annuels acquis :** **+{montant_tot_div_dca:.2f} € / an**.

*⚖️ Rappel : Analyse statistique et pédagogique générée par le moteur Boursy 2.0 (Non-CIF).*"""

        elif code_audit == "AUDIT_3":
            return f"""### 🌍 Arbitrage Stratégique : PEA (EUR) vs Actions US ($)

#### 1. Analyse du Taux de Change EUR/USD
- **Parité actuelle :** **1 € = {TAUX_USD_EUR:.4f} $** (soit **1 $ = {1/TAUX_USD_EUR:.4f} €**).
- **Impact Devises :** {'L’euro est au-dessus de 1,08 $ : les actifs cotés en dollars coûtent moins cher en euros qu’avec un euro plus faible.' if TAUX_USD_EUR >= 1.08 else 'Le dollar est fort face à l’euro : les actifs cotés en dollars coûtent plus cher en euros.'}

#### 2. Complémentarité Rendement Européen (PEA) vs Croissance US (CTO)
- **Poche Socle PEA (TotalEnergies, Air Liquide, AXA, Rubis, Vinci...) :** Idéale pour maximiser le **flux de dividendes immédiat (4 % à 8 %)** sans frottement fiscal lors du réinvestissement.
- **Poche Accélérateur US (Microsoft, Apple, Realty Income, Coca-Cola...) :** Apporte une **croissance séculaire** et des versements trimestriels ou mensuels qui lissent votre calendrier de rente.

*⚖️ Rappel : Analyse statistique et pédagogique générée par le moteur Boursy 2.0 (Non-CIF).*"""

        elif code_audit == "AUDIT_4":
            choc_20 = valeur_totale_portefeuille * 0.80
            return f"""### 🛡️ Stress-Test, Gestion des Risques & Diversification

#### 1. Simulation de Krach Boursier (-20 % sur les marchés)
- **Valorisation après choc de -20 % :** Votre portefeuille passerait temporairement de **{valeur_totale_portefeuille:,.0f} €** à **{choc_20:,.0f} €** (soit un repli latent de `-{valeur_totale_portefeuille * 0.20:,.0f} €`).
- **Résilience de votre Rente Passive :** Même en cas de baisse de 20 % des cours boursiers, **votre rente de dividendes ({dividendes_bruts_totaux_eur:,.2f} €/an) dépend du nombre d'actions détenues** et non des fluctuations quotidiennes du marché !

#### 2. Diagnostic de Concentration Sectorielle
- **Ligne numéro 1 :** **{nom_max_ligne}** représente **{poids_max_ligne:.1f}%** du portefeuille sur **{len(repartition_secteurs)} secteur(s)**.

*⚖️ Rappel : Analyse statistique et pédagogique générée par le moteur Boursy 2.0 (Non-CIF).*"""

        elif code_audit == "AUDIT_5":
            manque_100 = max(0.0, (100.0 * 12) - dividendes_nets_totaux_eur)
            cap_requis_100 = manque_100 / 0.055
            return f"""### 💵 Optimisation de la Rente & Accélération Boule de Neige

#### 1. Trajectoire Actuelle de vos Revenus Passifs
- **Rente Annuelle Actuelle :** **{dividendes_bruts_totaux_eur:,.2f} € brut / an** (**{dividendes_nets_totaux_eur:,.2f} € net / an**).
- **Revenu Mensuel Lissé :** **{rente_mens_nette:,.2f} € net / mois** (couvrant déjà **{taux_couverture_dca:.1f}%** de votre effort d'épargne DCA annuel).

#### 2. Feuille de Route vers le Palier des 100 € / mois (1 200 € / an)
- **Écart restant à combler :** Il vous manque **{manque_100:,.2f} € de dividendes annuels** pour franchir le cap symbolique des **100 € / mois** (soit environ **{cap_requis_100:,.0f} €** à investir à 5,5 % de rendement).

*⚖️ Rappel : Analyse statistique et pédagogique générée par le moteur Boursy 2.0 (Non-CIF).*"""

        elif code_audit == "AUDIT_6":
            perf_globale_cumulee = plus_value_glob + total_pv_actee_ia
            return f"""### 💰 Audit Complet de vos Arbitrages & Plus/Moins-Values Actées

{bloc_recap_pv_md}

#### 📊 Comparaison Performance Latente vs Performance Actée
- **Plus/Moins-Value Latente (Portefeuille actif) :** **`{plus_value_glob:+,.2f} € ({pv_pct_glob:+.2f}%)`**
- **Plus/Moins-Value Réalisée (Extraite par vos ventes) :** **`{total_pv_actee_ia:+,.2f} € ({perf_extraction_ia:+.2f}%)`**
- **Création de Valeur Totale Cumulée (Latent + Acté) :** **`{perf_globale_cumulee:+,.2f} €`**

#### 🎯 Point Fiscal sur vos Arbitrages
- **Enveloppe PEA :** Les plus-values actées au sein du PEA ne subissent **aucune imposition immédiate** tant que le cash reste dans l'enveloppe, le produit de cession (`{total_vol_vendu_ia:,.2f} €`) reste donc disponible dans l'enveloppe.

*⚖️ Rappel : Analyse statistique et pédagogique générée par le moteur Boursy 2.0 (Non-CIF).*"""

        q_low = question_utilisateur.strip().lower()
        if any(m in q_low for m in ["vente", "vendu", "actée", "actee", "arbitrage", "plus-value", "moins-value", "réalisé"]):
            return f"""### 🧠 Réponse de votre Coach IA 2.0 — Bilan des Plus/Moins-Values Actées

**Votre question :** *« {question_utilisateur} »*

{bloc_recap_pv_md}

*⚖️ Rappel : Analyse statistique et pédagogique générée par le moteur Boursy 2.0 (Non-CIF).*"""

        focus_actions = []
        for d in donnees_t1:
            nom_b = d["NomBrut"]
            if nom_b.lower() in q_low:
                info_w = WATCHLIST_DEFAUT.get(nom_b, {})
                pos_pf = portefeuille_utilisateur.get(nom_b)
                txt_pf = f"Détenue en portefeuille (**{pos_pf['qte']} actions** avec un PRU de **{pos_pf['pru']}**)" if (pos_pf and isinstance(pos_pf, dict)) else "Non détenue actuellement en portefeuille"
                focus_actions.append(
                    f"* **{d['Actif']}** : Cours actuel **{d['Prix']}** | Prix Cible : **{d['Prix Cible']}** ({d['Écart Cible (%)']}) | "
                    f"RSI : **{d['RSI']}** | Stochastique : **{d['Stoch']}%** | Signal EMA 2/12 : **{d['EMA 2/12']}** | "
                    f"Rendement : **{(info_w.get('div_eur',0)/ max(0.01, prix_temps_reel.get(nom_b, 1))*100):.2f}%** | "
                    f"Score Algo : **{d['Score']}/100 ({d['Décision']})** — *{txt_pf}*."
                )

        if focus_actions:
            bloc_focus = "\n".join(focus_actions)
            return f"""### 🧠 Réponse Personnalisée de votre Coach IA 2.0

**Votre question :** *« {question_utilisateur} »*

#### 1. Analyse Technique & Fondamentale sur mesure
{bloc_focus}

#### 2. Stratégie adaptée à votre Portefeuille ({valeur_totale_portefeuille:,.0f} €)
- **Repères :** le Radar compare le cours actuel à votre **Prix Cible** et à votre **PRU** ; un **Score ≥ 55/100** signifie qu'une majorité d'indicateurs sont favorables.

*⚖️ Rappel : Analyse statistique et pédagogique générée par le moteur Boursy 2.0 (Non-CIF).*"""

        else:
            return f"""### 🧠 Synthèse Globale de votre Coach IA 2.0

**Votre question :** *« {question_utilisateur} »*

- **Portefeuille Actif :** **{valeur_totale_portefeuille:,.2f} €** (Plus-value latente : **{plus_value_glob:+,.2f} € / {pv_pct_glob:+.2f}%**).
- **Rente Annuelle :** **{dividendes_nets_totaux_eur:,.2f} € net/an** ({rente_mens_nette:.2f} € net/mois).

{bloc_recap_pv_md}

*⚖️ Rappel : Analyse statistique et pédagogique générée par le moteur Boursy 2.0 (Non-CIF).*"""

    def appeler_gemini_coach(question_utilisateur, code_audit=""):
        # Protection anti-abus API : si le visiteur n'est pas connecté à un compte, utilise le moteur local gratuit
        if st.session_state.get("user") is None:
            return generer_audit_expert_hybride(question_utilisateur, code_audit)

        cle_gemini = ""
        for nom_secret in ["GEMINI_API_KEY", "GOOGLE_API_KEY", "GEMINI_KEY"]:
            val_s = _lire_secret(nom_secret)
            if val_s:
                cle_gemini = val_s
                break
        if not cle_gemini:
            return generer_audit_expert_hybride(question_utilisateur, code_audit)

        resume_pf = []
        for l_it in lignes_triees:
            if l_it["est_especes"]:
                resume_pf.append(f"- Espèces : {l_it['val_eur']:.2f} €")
            else:
                p_l = (l_it["val_eur"] / valeur_totale_portefeuille * 100) if valeur_totale_portefeuille > 0 else 0
                resume_pf.append(
                    f"- {l_it['nom_act']} ({l_it['env_label']}) : Qté={l_it['qte']}, PRU={l_it['pru']} {l_it['sym']}, "
                    f"Cours={l_it['prix_jour']:.2f} {l_it['sym']}, Val={l_it['val_eur']:.1f} € (Poids {p_l:.1f}%), "
                    f"PV={l_it['pv_eur']:+.1f} € ({l_it['pv_pct']:+.1f}%), Div Net={l_it['div_net_l']:.2f} €/an"
                )

        resume_radar = [
            f"- {d['Actif']} : Prix={d['Prix']}, Cible={d['Prix Cible']}, RSI={d['RSI']}, Stoch={d['Stoch']}%, EMA={d['EMA 2/12']}, Score={d['Score']}/100 ({d['Décision']})"
            for d in donnees_t1[:15]
        ]

        plus_value_glob = valeur_totale_portefeuille - cout_total_achat
        resume_ventes_ia = [
            f"- {v['date']} ({v['mois_annee']}) : Vente de {v['qte']} {v['action']} à {v['prix_vente']} {v['devise']} "
            f"(PRU {v['pru']} {v['devise']}) -> Plus/Moins-value actée : {v['plus_value_eur']:+.2f} € ({v['perf_pct']:+.2f}%)"
            for v in hist_ventes_ia[:15]
        ]
        bloc_ventes_prompt = (
            f"Total Plus/Moins-Values Actées : {total_pv_actee_ia:+.2f} € (Performance d'extraction réelle : {perf_extraction_ia:+.2f}% sur {len(hist_ventes_ia)} vente(s), {nb_ventes_gagnantes_ia} gagnante(s), Cash total encaissé : {total_vol_vendu_ia:.2f} €).\n"
            + "\n".join(resume_ventes_ia)
            if hist_ventes_ia else "Aucune vente actée enregistrée pour le moment."
        )

        prompt_complet = f"""Tu es Boursy Coach IA 2.0, un expert patrimonial et boursier de haut niveau spécialisé dans les stratégies PEA, CTO US et dividendes croissants en DCA.
Voici les données exactes en temps réel du portefeuille de l'utilisateur :
- Météo des marchés : CAC 40 = {cac_str}, S&P 500 = {sp_str}, VIX = {vix_val:.1f} ({etat_vix})
- Taux de change EUR/USD : 1 € = {TAUX_USD_EUR:.4f} $
- Valorisation totale active : {valeur_totale_portefeuille:.2f} € (Capital investi : {cout_total_achat:.2f} €, Plus-value latente : {plus_value_glob:+.2f} €)
- Rente annuelle : {dividendes_bruts_totaux_eur:.2f} € brut / {dividendes_nets_totaux_eur:.2f} € net par an (soit {dividendes_nets_totaux_eur/12:.2f} € net/mois)
- Enveloppe DCA mensuelle : {BUDGET_MENSUEL:.0f} € / mois (condensée sur 1 à 2 lignes max)
- Bilan des Plus-Values ou Moins-Values Actées (Réalisées) & Arbitrages :
{bloc_ventes_prompt}
- Détail des lignes du portefeuille (triées par poids décroissant) :
{chr(10).join(resume_pf) if resume_pf else 'Portefeuille vide'}
- Signaux techniques et fondamentaux du Radar Boursy aujourd'hui :
{chr(10).join(resume_radar)}

Mission demandée par l'utilisateur : {question_utilisateur}

Réponds en français avec une structure claire (titres, puces, chiffres précis tirés de son portefeuille, un récapitulatif dédié aux performances de ses plus-values ou moins-values actées, ses points forts, points de vigilance et pistes de réflexion). Ne formule jamais de recommandation personnalisée d'achat ou de vente : pas de « achetez » ni « vendez », pas de quantités ni de prix d'ordre à passer. Décris ce que montrent les indicateurs et laisse la décision à l'utilisateur. Rappelle discrètement en fin de message qu'il s'agit d'un audit pédagogique et statistique (non-CIF).
"""
        modeles_candidats = lister_modeles_gemini_actifs(cle_gemini)
        priorite_modeles = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-flash-latest", "gemini-2.5-pro"]
        modeles_propres = [
            m for m in modeles_candidats
            if not any(ex in m for ex in ["tts", "audio", "image", "vision", "embedding", "bis", "exp"])
        ]
        modeles_ordonnes = []
        # Les modèles "prioritaires" ne sont tentés que s'ils existent encore chez Google (évite des appels voués à l'échec)
        priorites_valides = [m for m in priorite_modeles if (not modeles_candidats or m in modeles_candidats)]
        for m_prio in priorites_valides + modeles_propres + modeles_candidats:
            if m_prio not in modeles_ordonnes:
                modeles_ordonnes.append(m_prio)

        for mod in modeles_ordonnes[:8]:
            try:
                url_api = f"https://generativelanguage.googleapis.com/v1beta/models/{mod}:generateContent?key={urllib.parse.quote(cle_gemini)}"
                payload_ia = json.dumps({"contents": [{"parts": [{"text": prompt_complet}]}]}).encode("utf-8")
                req_ia = urllib.request.Request(
                    url_api,
                    data=payload_ia,
                    headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
                )
                with urllib.request.urlopen(req_ia, timeout=25) as resp_ia:
                    res_json = json.loads(resp_ia.read().decode("utf-8"))
                    texte_rep = res_json["candidates"][0]["content"]["parts"][0]["text"]
                    if texte_rep:
                        return texte_rep
            except Exception:
                continue

        return generer_audit_expert_hybride(question_utilisateur, code_audit)

    st.markdown("#### 🚀 Choisissez un Audit Prédéfini en 1 Clic (ou posez votre question ci-dessous)")
    col_ia1, col_ia2, col_ia3 = st.columns(3)
    prompt_choisi = None
    code_audit_choisi = ""
    titre_audit = ""

    if col_ia1.button("🔍 1. Audit Complet 360° & Fiscalité", width="stretch"):
        titre_audit = "Audit Complet 360° & Fiscalité"
        code_audit_choisi = "AUDIT_1"
        prompt_choisi = "Réalise un audit 360° complet de mon portefeuille : équilibre sectoriel, récapitulatif de mes plus-values ou moins-values actées, analyse de mes PRU par rapport aux cours actuels, et optimisation fiscale de ma rente."
    if col_ia2.button("🛒 2. Simulation DCA du Mois (VIX & RSI)", width="stretch"):
        titre_audit = "Simulation DCA du Mois"
        code_audit_choisi = "AUDIT_2"
        prompt_choisi = f"Compte tenu du VIX actuel ({vix_val:.1f}) et des indicateurs techniques du radar (RSI, Stochastique, EMA 2/12, écart au prix cible), que montrent les indicateurs pour les valeurs de mon radar, et comment se répartirait mathématiquement une enveloppe de {BUDGET_MENSUEL:.0f} € selon le score de l'algorithme ?"
    if col_ia3.button("🌍 3. Arbitrage PEA (EUR) vs Actions US ($)", width="stretch"):
        titre_audit = "Arbitrage PEA (EUR) vs Actions US ($)"
        code_audit_choisi = "AUDIT_3"
        prompt_choisi = "Analyse la pertinence d'arbitrer ou de renforcer mes valeurs européennes de rendement en PEA face aux géants américains en CTO compte tenu de la parité EUR/USD actuelle et de mes lignes."

    col_ia4, col_ia5, col_ia6 = st.columns(3)
    if col_ia4.button("🛡️ 4. Stress-Test, Risques & Diversification", width="stretch"):
        titre_audit = "Stress-Test, Risques & Diversification"
        code_audit_choisi = "AUDIT_4"
        prompt_choisi = "Analyse les risques de concentration de mon portefeuille (poids de mes plus grosses lignes et secteurs dominants), fais un stress-test en cas de baisse de marché de 20% et montre quels secteurs sont peu ou pas représentés."
    if col_ia5.button("💵 5. Optimisation de la Rente & Boule de Neige", width="stretch"):
        titre_audit = "Optimisation de la Rente & Calendrier"
        code_audit_choisi = "AUDIT_5"
        prompt_choisi = "Analyse la régularité de mes dividendes sur les 12 mois de l'année, identifie les mois creux à renforcer et décris les leviers qui accéléreraient mon effet boule de neige vers 100 €/mois puis 500 €/mois de rente."
    if col_ia6.button("💰 6. Bilan de mes Plus/Moins-Values Actées (Pro)", width="stretch"):
        if not est_pro_max:
            st.warning("🔒 L'audit des Arbitrages & Plus-Values Actées est réservé à l'offre **Pro (8,90 €/mois)**.")
        else:
            titre_audit = "Bilan de mes Arbitrages & Plus-Values Actées"
            code_audit_choisi = "AUDIT_6"
            prompt_choisi = "Fais-moi un récapitulatif complet et détaillé des performances de mes plus-values ou moins-values actées (réalisées), analyse mon taux de réussite (win rate), ma performance d'extraction réelle et le montant de cash disponible après ces ventes."

    st.markdown("---")
    col_q_input, col_q_btn, col_q_clear = st.columns([4, 1.3, 0.8])
    with col_q_input:
        question_libre = st.text_input(
            "💬 Posez une question personnalisée à votre Coach IA 2.0 :",
            placeholder="Ex: Analyse mon PRU sur Rubis et mes opportunités DCA du mois...",
            label_visibility="collapsed",
        )
    with col_q_btn:
        if st.button("✨ Lancer l'Analyse IA", type="primary", width="stretch"):
            if question_libre.strip():
                titre_audit = f"Question libre : {question_libre.strip()}"
                code_audit_choisi = "LIBRE"
                prompt_choisi = question_libre.strip()
    with col_q_clear:
        if st.button("🗑️ Effacer", width="stretch"):
            st.session_state["reponse_ia_coach"] = ""
            st.session_state["historique_chat_ia"] = []
            st.rerun()

    if prompt_choisi:
        if quota_restant <= 0:
            st.error("🔒 Vous avez atteint votre quota journalier d'analyses IA. Passez au forfait supérieur dans le menu de gauche (3 audits/jour en Premium 4,90 € ou 15 audits/jour en Pro 8,90 €) !")
        else:
            with st.spinner("🧠 Le Coach IA 2.0 analyse votre portefeuille et les indicateurs techniques en direct..."):
                reponse_texte = appeler_gemini_coach(prompt_choisi, code_audit_choisi)
                st.session_state["quota_ia_utilise"] = quota_utilise + 1
                sauvegarder_dans_cloud()
                st.session_state["reponse_ia_coach"] = reponse_texte
                st.session_state["historique_chat_ia"].insert(0, {
                    "heure": datetime.now().strftime("%H:%M"),
                    "titre": titre_audit,
                    "reponse": reponse_texte,
                })
                st.rerun()

    if st.session_state.get("reponse_ia_coach"):
        afficher_html("<div class='ia-box'><b>📋 Dernier Rapport d'Audit de votre Coach IA 2.0 :</b></div>")
        markdown_fr(st.session_state["reponse_ia_coach"])

    if len(st.session_state.get("historique_chat_ia", [])) > 1:
        with st.expander(f"🕒 Consulter l'historique de vos {len(st.session_state['historique_chat_ia'])} analyses IA de la session", expanded=False):
            for idx_h, item_h in enumerate(st.session_state["historique_chat_ia"]):
                st.markdown(f"#### {idx_h + 1}. {item_h['titre']} *(à {item_h['heure']})*")
                markdown_fr(item_h["reponse"])
                st.markdown("---")


# ------------------------------------------------------------------------------
# ONGLET 5 : ARBITRAGES, VENTES & CALENDRIER 12 MOIS ARGON DES PLUS-VALUES ACTÉES (EXCLUSIF PRO 8,90 €)
# ------------------------------------------------------------------------------
with onglet_ventes:
    st.subheader("💰 Journal des Arbitrages & Calendrier 12 Mois des Plus-Values Actées")

    if not est_pro_max:
        afficher_verrou_saas(
            "Journal des Arbitrages, Crédit Espèces Auto & Calendrier 12 Mois des Plus-Values Actées",
            "👑 Offre Pro (8,90 €/mois)",
            "Ce module exclusif Pro déduit automatiquement vos actions vendues du portefeuille, crédite votre poche Espèces en 1 clic et calcule votre calendrier mensuel Argon de plus-values réalisées ainsi que votre Win Rate."
        )
        afficher_html("""
        <div class="argon-grid" style="opacity:0.45; pointer-events:none; filter:blur(2px);">
            <div class="argon-card" style="border-top: 3px solid #2ecc71;">
                <div class="argon-title">💰 Total Plus/Moins-Values Actées</div>
                <div class="argon-val" style="color:#2ecc71;">+1 420,00 €</div>
                <div class="argon-sub">Aperçu réservé aux membres Pro</div>
            </div>
            <div class="argon-card" style="border-top: 3px solid #3498db;">
                <div class="argon-title">📈 Performance d'Extraction Réelle</div>
                <div class="argon-val" style="color:#2ecc71;">+18,40%</div>
                <div class="argon-sub">Calcul automatique sur PRU</div>
            </div>
            <div class="argon-card" style="border-top: 3px solid #2ecc71;">
                <div class="argon-title">🎯 Taux de Réussite (Win Rate)</div>
                <div class="argon-val" style="color:#3498db;">88%</div>
                <div class="argon-sub">Suivi des arbitrages gagnants</div>
            </div>
            <div class="argon-card" style="border-top: 3px solid #9b59b6;">
                <div class="argon-title">💵 Cash Total Extrait (Cessions)</div>
                <div class="argon-val" style="color:#9b59b6;">9 140,00 €</div>
                <div class="argon-sub">Crédit Espèces automatique</div>
            </div>
        </div>
        """)
    else:
        st.caption("Enregistrez vos cessions : vos actions sont immédiatement déduites du portefeuille, le cash net rejoint vos Espèces (si coché) et vos plus/moins-values s'additionnent mois par mois dans le calendrier Argon.")

        # --- RECHARGEMENT AUTOMATIQUE DES VENTES DEPUIS SUPABASE À LA CONNEXION ---
        if supabase and st.session_state.get("user"):
            uid_connecte = str(st.session_state["user"].id)
            # Une seule tentative par compte et par session (avant : une requête Supabase à CHAQUE rafraîchissement
            # tant que l'historique des ventes était vide)
            if (
                not st.session_state.get("historique_ventes")
                and not st.session_state.get("_ventes_videes_volontairement", False)
                and st.session_state.get("_ventes_rechargees_pour") != uid_connecte
            ):
                st.session_state["_ventes_rechargees_pour"] = uid_connecte
                try:
                    rep_v = supabase.table("user_data").select("portefeuille").eq("user_id", uid_connecte).execute()
                    if rep_v.data and len(rep_v.data) > 0:
                        pf_cloud = rep_v.data[0].get("portefeuille") or {}
                        if isinstance(pf_cloud, dict) and isinstance(pf_cloud.get("_historique_ventes"), list):
                            st.session_state["historique_ventes"] = list(pf_cloud["_historique_ventes"])
                except Exception:
                    pass

        def executer_vente_portefeuille(act_v, qte_det_v, pru_v, dev_sym_v):
            qte_vendue = int(st.session_state.get(f"input_qte_v_{act_v}", 1))
            prix_vente = float(st.session_state.get(f"input_prix_v_{act_v}", pru_v))
            frais_v = float(st.session_state.get(f"input_frais_v_{act_v}", 0.0))
            date_v = st.session_state.get(f"input_date_v_{act_v}", datetime.now().date())
            crediter_esp = bool(st.session_state.get(f"input_cred_esp_{act_v}", True))

            facteur_v = (1.0 / TAUX_USD_EUR) if dev_sym_v == "$" else 1.0
            montant_brut_eur = qte_vendue * prix_vente * facteur_v
            montant_net_eur = round(montant_brut_eur - frais_v, 2)
            # Coût d'achat au taux €/$ du jour de l'achat (s'il est renseigné) : la plus-value actée inclut l'effet de change
            pos_avant_vente = st.session_state["portefeuille"].get(act_v)
            facteur_cout_v = facteur_cout_usd(pos_avant_vente) if dev_sym_v == "$" else 1.0
            taux_achat_v = pos_avant_vente.get("taux_achat") if isinstance(pos_avant_vente, dict) else None
            cout_init_eur = round(qte_vendue * pru_v * facteur_cout_v, 2)
            pv_eur = round(montant_net_eur - cout_init_eur, 2)
            perf_pct = round((pv_eur / cout_init_eur * 100.0) if cout_init_eur > 0 else 0.0, 2)

            nouvelle_vente = {
                "id": datetime.now().strftime("%Y%m%d%H%M%S"),
                "date": date_v.strftime("%Y-%m-%d"),
                "annee": date_v.strftime("%Y"),
                "mois_num": int(date_v.strftime("%m")),
                "mois_annee": date_v.strftime("%Y-%m"),
                "action": act_v,
                "qte": qte_vendue,
                "pru": float(pru_v),
                "prix_vente": float(prix_vente),
                "frais_eur": float(frais_v),
                "devise": dev_sym_v,
                "montant_eur": montant_net_eur,
                "cout_initial_eur": cout_init_eur,
                "plus_value_eur": pv_eur,
                "perf_pct": perf_pct,
                "credite_especes": crediter_esp,
            }
            if taux_achat_v:
                nouvelle_vente["taux_achat"] = taux_achat_v
            if "historique_ventes" not in st.session_state or not isinstance(st.session_state["historique_ventes"], list):
                st.session_state["historique_ventes"] = []
            st.session_state["historique_ventes"].insert(0, nouvelle_vente)
            st.session_state["portefeuille"]["_historique_ventes"] = st.session_state["historique_ventes"]
            st.session_state["_ventes_videes_volontairement"] = False

 
           # 1. Déduction immédiate des actions dans l'Onglet 2
            nouvelle_qte = max(0, int(qte_det_v) - qte_vendue)
            st.session_state[f"qte_{act_v}"] = nouvelle_qte
            if nouvelle_qte <= 0:
                st.session_state["portefeuille"].pop(act_v, None)
            else:
                if act_v in st.session_state["portefeuille"] and isinstance(st.session_state["portefeuille"][act_v], dict):
                    st.session_state["portefeuille"][act_v]["qte"] = nouvelle_qte
                else:
                    st.session_state["portefeuille"][act_v] = construire_position(act_v, nouvelle_qte, float(pru_v))

            # 2. Crédit automatique de la poche Espèces
            if crediter_esp:
                esp_dict = st.session_state["portefeuille"].get("Espèces", {})
                esp_actuel = float(st.session_state.get("pru_Espèces", esp_dict.get("pru", 0.0) if isinstance(esp_dict, dict) else 0.0))
                nouveau_esp = round(max(0.0, esp_actuel + montant_net_eur), 2)
                st.session_state["pru_Espèces"] = nouveau_esp
                st.session_state["qte_Espèces"] = 1 if nouveau_esp > 0 else 0
                if nouveau_esp > 0:
                    st.session_state["portefeuille"]["Espèces"] = {"qte": 1, "pru": nouveau_esp}

            sauvegarder_dans_cloud()
            st.session_state["_derniere_notif_vente"] = (
                f"✅ Vente actée : -{qte_vendue} {act_v} (Reste : {nouvelle_qte}) | "
                f"Plus/Moins-Value actée : {pv_eur:+,.2f} € ({perf_pct:+.2f}%)"
                + (f" | +{montant_net_eur:,.2f} € crédités dans vos Espèces !" if crediter_esp else "")
            )

        def annuler_vente_portefeuille(idx_v):
            hist = st.session_state.get("historique_ventes", [])
            if 0 <= idx_v < len(hist):
                v_suppr = hist.pop(idx_v)
                st.session_state["portefeuille"]["_historique_ventes"] = hist
                if len(hist) == 0:
                    st.session_state["_ventes_videes_volontairement"] = True

                act_s = v_suppr.get("action", "")
                qte_s = int(v_suppr.get("qte", 0))
                pru_s = float(v_suppr.get("pru", 0.0))
                mt_s = float(v_suppr.get("montant_eur", 0.0))
                avait_credite_esp = bool(v_suppr.get("credite_especes", False))

                if act_s and qte_s > 0:
                    pos_s = st.session_state["portefeuille"].get(act_s, {})
                    qte_actuelle = int(st.session_state.get(f"qte_{act_s}", pos_s.get("qte", 0) if isinstance(pos_s, dict) else 0))
                    qte_restauree = qte_actuelle + qte_s
                    pru_rest = float(st.session_state.get(f"pru_{act_s}", pru_s))
                    st.session_state[f"qte_{act_s}"] = qte_restauree
                    st.session_state[f"pru_{act_s}"] = pru_rest
                    pos_restauree = construire_position(act_s, qte_restauree, pru_rest)
                    if v_suppr.get("taux_achat") and "taux_achat" not in pos_restauree:
                        # La ligne avait été entièrement vendue : on lui rend le taux €/$ d'achat mémorisé avec la vente
                        pos_restauree["taux_achat"] = v_suppr["taux_achat"]
                        try:
                            st.session_state[f"txa_{act_s}"] = min(5.0, max(0.0, float(v_suppr["taux_achat"])))
                        except Exception:
                            pass
                    st.session_state["portefeuille"][act_s] = pos_restauree

                if avait_credite_esp and mt_s > 0:
                    esp_d = st.session_state["portefeuille"].get("Espèces", {})
                    esp_act = float(st.session_state.get("pru_Espèces", esp_d.get("pru", 0.0) if isinstance(esp_d, dict) else 0.0))
                    nouv_esp = round(max(0.0, esp_act - mt_s), 2)
                    st.session_state["pru_Espèces"] = nouv_esp
                    if nouv_esp > 0:
                        st.session_state["portefeuille"]["Espèces"] = {"qte": 1, "pru": nouv_esp}
                    else:
                        st.session_state["portefeuille"].pop("Espèces", None)
                        st.session_state["qte_Espèces"] = 0

                sauvegarder_dans_cloud()
                st.session_state["_derniere_notif_vente"] = f"🔄 Arbitrage annulé : +{qte_s} action(s) {act_s} restaurée(s) en portefeuille."

        if st.session_state.get("_derniere_notif_vente"):
            st.success(nombres_fr(st.session_state.pop("_derniere_notif_vente")))

        # --- BANDEAU DE CONTRÔLE EN DIRECT (ACTIONS vs ESPÈCES vs TOTAL) ---
        esp_dispo_actuel = float(portefeuille_utilisateur.get("Espèces", {}).get("pru", 0.0)) if isinstance(portefeuille_utilisateur.get("Espèces"), dict) else 0.0
        val_actions_seules = max(0.0, valeur_totale_portefeuille - esp_dispo_actuel)

        html_bar_synchro = f"""
        <div class="meteo-bar" style="margin-bottom: 16px;">
            <div class="meteo-item" style="border-left-color:#3498db;">
                <div>
                    <div style="font-size:0.74em; font-weight:800; opacity:0.75;">📈 VALORISATION ACTIONS SEULES</div>
                    <div style="font-size:1.05em; font-weight:900;">{val_actions_seules:,.2f} €</div>
                </div>
            </div>
            <div class="meteo-item" style="border-left-color:#2ecc71;">
                <div>
                    <div style="font-size:0.74em; font-weight:800; opacity:0.75;">💶 POCHE ESPÈCES DISPONIBLE</div>
                    <div style="font-size:1.05em; font-weight:900; color:#2ecc71;">{esp_dispo_actuel:,.2f} €</div>
                </div>
            </div>
            <div class="meteo-item" style="border-left-color:#9b59b6;">
                <div>
                    <div style="font-size:0.74em; font-weight:800; opacity:0.75;">💼 PATRIMOINE TOTAL (ACTIONS + ESPÈCES)</div>
                    <div style="font-size:1.05em; font-weight:900;">{valeur_totale_portefeuille:,.2f} € <span style="font-size:0.82em; opacity:0.8;">(PV Latente : {plus_value_globale:+,.2f} €)</span></div>
                </div>
            </div>
        </div>
        """
        afficher_html(html_bar_synchro)

        # --- GUICHET D'ENREGISTREMENT D'UNE VENTE ---
        actions_vendables = [
            k for k, v in portefeuille_utilisateur.items()
            if k not in CLES_TECHNIQUES_PF and isinstance(v, dict) and float(v.get("qte", 0)) > 0
        ]

        with st.expander("➕ Enregistrer une nouvelle vente d'action (Déduction Actions & Crédit Espèces automatiques)", expanded=not bool(st.session_state.get("historique_ventes"))):
            if not actions_vendables:
                st.info("Vous ne possédez actuellement aucune action en portefeuille à vendre. Renseignez d'abord vos lignes dans l'onglet 2.")
            else:
                action_vendue = st.selectbox("1️⃣ Choisissez l'action vendue :", actions_vendables, key="sel_action_vente")

                pos_actuelle_v = portefeuille_utilisateur.get(action_vendue, {})
                qte_detenue = int(pos_actuelle_v.get("qte", 1))
                pru_actuel = float(pos_actuelle_v.get("pru", 0.0))
                info_w_v = WATCHLIST_DEFAUT.get(action_vendue, {})
                dev_v = "$" if info_w_v.get("devise") == "USD" else "€"
                cours_actuel_v = float(st.session_state.get("prix_temps_reel", {}).get(action_vendue, pru_actuel))

                markdown_fr(
                    f"<div style='background:rgba(52,152,219,0.08); border-left:4px solid #3498db; padding:8px 12px; border-radius:6px; margin-bottom:12px; font-size:0.9em;'>"
                    f"📌 En portefeuille : <b>{qte_detenue} action(s) {action_vendue}</b> | Votre PRU : <b>{pru_actuel:.2f} {dev_v}</b> | Cours actuel : <b>{cours_actuel_v:.2f} {dev_v}</b>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

                col_v1, col_v2, col_v3, col_v4 = st.columns(4)
                with col_v1:
                    qte_a_vendre = st.number_input("Quantité vendue :", min_value=1, max_value=qte_detenue, value=min(1, qte_detenue), step=1, key=f"input_qte_v_{action_vendue}")
                with col_v2:
                    prix_vente_saisi = st.number_input(f"Prix de vente unitaire ({dev_v}) :", min_value=0.01, value=float(round(cours_actuel_v, 2)), step=0.5, key=f"input_prix_v_{action_vendue}")
                with col_v3:
                    frais_vente_eur = st.number_input("Frais de courtage (€) :", min_value=0.0, value=0.0, step=0.5, key=f"input_frais_v_{action_vendue}")
                with col_v4:
                    date_vente = st.date_input("Date de la vente :", value=datetime.now(), key=f"input_date_v_{action_vendue}")

                crediter_especes_chk = st.checkbox(
                    "💶 Créditer automatiquement le montant net encaissé dans ma poche Espèces (Liquidités)",
                    value=True,
                    key=f"input_cred_esp_{action_vendue}",
                )

                facteur_apercu = (1.0 / TAUX_USD_EUR) if dev_v == "$" else 1.0
                net_apercu_eur = round((qte_a_vendre * prix_vente_saisi * facteur_apercu) - frais_vente_eur, 2)
                facteur_cout_apercu = facteur_cout_usd(pos_actuelle_v) if dev_v == "$" else 1.0
                cout_apercu_eur = round(qte_a_vendre * pru_actuel * facteur_cout_apercu, 2)
                pv_apercu_eur = round(net_apercu_eur - cout_apercu_eur, 2)
                perf_apercu_pct = (pv_apercu_eur / cout_apercu_eur * 100.0) if cout_apercu_eur > 0 else 0.0
                c_apercu = "#2ecc71" if pv_apercu_eur >= 0 else "#e74c3c"

                markdown_fr(
                    f"<div style='background:rgba(128,128,128,0.05); border:1px dashed {c_apercu}; padding:10px 14px; border-radius:8px; margin:8px 0 12px 0; font-size:0.88em;'>"
                    f"🔎 <b>Aperçu de l'opération :</b> Reste après vente : <b>{qte_detenue - qte_a_vendre} titre(s) {action_vendue}</b> | "
                    f"Cash net encaissé : <b>+{net_apercu_eur:,.2f} €</b> | "
                    f"Plus/Moins-Value actée : <span style='color:{c_apercu}; font-weight:800;'>{pv_apercu_eur:+,.2f} € ({perf_apercu_pct:+.2f}%)</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

                st.button(
                    "🚀 Valider la vente & Ajouter au Calendrier des Plus-Values",
                    type="primary",
                    width="stretch",
                    on_click=executer_vente_portefeuille,
                    args=(action_vendue, qte_detenue, pru_actuel, dev_v),
                )

        historique_v = st.session_state.get("historique_ventes", [])

        if not historique_v:
            st.info("💡 Aucune vente enregistrée pour le moment. Dès que vous validerez une vente ci-dessus, votre calendrier 12 mois Argon s'affichera automatiquement.")
        else:
            total_pv_actee = sum(float(v.get("plus_value_eur", 0.0)) for v in historique_v)
            total_montant_vendu = sum(float(v.get("montant_eur", 0.0)) for v in historique_v)
            total_cout_initial = sum(float(v.get("cout_initial_eur", float(v.get("montant_eur", 0.0)) - float(v.get("plus_value_eur", 0.0)))) for v in historique_v)
            perf_globale_actee_pct = (total_pv_actee / total_cout_initial * 100.0) if total_cout_initial > 0 else 0.0

            nb_gagnantes = sum(1 for v in historique_v if float(v.get("plus_value_eur", 0.0)) >= 0)
            nb_perdantes = len(historique_v) - nb_gagnantes
            win_rate = (nb_gagnantes / len(historique_v) * 100.0) if historique_v else 0.0
            c_pv_act = "#2ecc71" if total_pv_actee >= 0 else "#e74c3c"

            # --- 4 CARTES KPI ARGON ---
            html_kpi_ventes = f"""
            <div class="argon-grid">
                <div class="argon-card" style="border-top: 3px solid {c_pv_act};">
                    <div class="argon-title">💰 Total Plus/Moins-Values Actées</div>
                    <div class="argon-val" style="color:{c_pv_act};">{total_pv_actee:+,.2f} €</div>
                    <div class="argon-sub">Solde net réalisé sur {len(historique_v)} opération(s)</div>
                </div>
                <div class="argon-card" style="border-top: 3px solid #3498db;">
                    <div class="argon-title">📈 Performance d'Extraction Réelle</div>
                    <div class="argon-val" style="color:{c_pv_act};">{perf_globale_actee_pct:+.2f}%</div>
                    <div class="argon-sub">Sur {total_cout_initial:,.0f} € de capital initial cédé</div>
                </div>
                <div class="argon-card" style="border-top: 3px solid #2ecc71;">
                    <div class="argon-title">🎯 Taux de Réussite (Win Rate)</div>
                    <div class="argon-val" style="color:#3498db;">{win_rate:.0f}%</div>
                    <div class="argon-sub"><span style="color:#2ecc71; font-weight:700;">{nb_gagnantes} gagnante(s)</span> / <span style="color:#e74c3c; font-weight:700;">{nb_perdantes} perdante(s)</span></div>
                </div>
                <div class="argon-card" style="border-top: 3px solid #9b59b6;">
                    <div class="argon-title">💵 Cash Total Extrait (Cessions)</div>
                    <div class="argon-val" style="color:#9b59b6;">{total_montant_vendu:,.2f} €</div>
                    <div class="argon-sub">Poche Espèces actuelle : <b>{esp_dispo_actuel:,.2f} €</b></div>
                </div>
            </div>
            """
            afficher_html(html_kpi_ventes)

            # ======================================================================
            # CALENDRIER 12 MOIS ARGON DES PLUS & MOINS-VALUES ACTÉES
            # ======================================================================
            annees_dispo = sorted(list({str(v.get("date", str(datetime.now().year)))[:4] for v in historique_v}), reverse=True)
            if not annees_dispo:
                annees_dispo = [str(datetime.now().year)]
            options_filtre_annee = annees_dispo + (["Toutes les années (Cumul)"] if len(annees_dispo) > 1 else [])

            col_an_t, col_an_sel = st.columns([2.8, 1.2])
            with col_an_t:
                st.markdown("#### 🗓️ Calendrier Mensuel des Plus & Moins-Values Actées (Style Argon)")
                st.caption("Somme automatique mois par mois de toutes vos plus-values et moins-values réalisées selon la date de vente.")
            with col_an_sel:
                annee_choisie_v = st.selectbox("Période affichée :", options_filtre_annee, key="sel_annee_cal_ventes")

            mois_noms_12 = [
                (1, "Janvier"), (2, "Février"), (3, "Mars"), (4, "Avril"),
                (5, "Mai"), (6, "Juin"), (7, "Juillet"), (8, "Août"),
                (9, "Septembre"), (10, "Octobre"), (11, "Novembre"), (12, "Décembre"),
            ]
            pv_par_mois_12 = {m_idx: 0.0 for m_idx, _ in mois_noms_12}
            cout_par_mois_12 = {m_idx: 0.0 for m_idx, _ in mois_noms_12}
            encaisse_par_mois_12 = {m_idx: 0.0 for m_idx, _ in mois_noms_12}
            pills_par_mois_12 = {m_idx: [] for m_idx, _ in mois_noms_12}

            for v in historique_v:
                date_s = str(v.get("date", ""))
                if annee_choisie_v == "Toutes les années (Cumul)" or date_s.startswith(str(annee_choisie_v)):
                    try:
                        m_num = int(date_s.split("-")[1])
                    except Exception:
                        m_num = int(v.get("mois_num", 1))
                    pv_v = float(v.get("plus_value_eur", 0.0))
                    mt_v = float(v.get("montant_eur", 0.0))
                    cout_v = float(v.get("cout_initial_eur", mt_v - pv_v))
                    pv_par_mois_12[m_num] += pv_v
                    cout_par_mois_12[m_num] += cout_v
                    encaisse_par_mois_12[m_num] += mt_v
                    pills_par_mois_12[m_num].append((v["action"], v["qte"], pv_v, date_s[8:10] + "/" + date_s[5:7]))

            max_abs_mois = max([abs(val) for val in pv_par_mois_12.values()] + [1.0])
            total_periode_sel = sum(pv_par_mois_12.values())
            nb_mois_verts = sum(1 for m_i in pv_par_mois_12 if pills_par_mois_12[m_i] and pv_par_mois_12[m_i] >= 0)
            nb_mois_rouges = sum(1 for m_i in pv_par_mois_12 if pills_par_mois_12[m_i] and pv_par_mois_12[m_i] < 0)
            meilleur_mois_idx = max(pv_par_mois_12, key=lambda k: pv_par_mois_12[k]) if any(pills_par_mois_12.values()) else None
            txt_meilleur_mois = f"{dict(mois_noms_12)[meilleur_mois_idx]} ({pv_par_mois_12[meilleur_mois_idx]:+,.2f} €)" if (meilleur_mois_idx and pv_par_mois_12[meilleur_mois_idx] != 0) else "N/A"
            c_tot_per = "#2ecc71" if total_periode_sel >= 0 else "#e74c3c"

            html_resume_cal = f"""
            <div class="meteo-bar" style="margin-bottom: 14px;">
                <div class="meteo-item" style="border-left-color:{c_tot_per};">
                    <div>
                        <div style="font-size:0.72em; font-weight:800; opacity:0.75;">📊 BILAN NET ({annee_choisie_v})</div>
                        <div style="font-size:0.98em; font-weight:900; color:{c_tot_per};">{total_periode_sel:+,.2f} € actés</div>
                    </div>
                </div>
                <div class="meteo-item" style="border-left-color:#2ecc71;">
                    <div>
                        <div style="font-size:0.72em; font-weight:800; opacity:0.75;">🟢 MOIS GAGNANTS VS 🔴 PERDANTS</div>
                        <div style="font-size:0.95em; font-weight:800;"><span style="color:#2ecc71;">{nb_mois_verts} mois vert(s)</span> / <span style="color:#e74c3c;">{nb_mois_rouges} mois rouge(s)</span></div>
                    </div>
                </div>
                <div class="meteo-item" style="border-left-color:#f39c12;">
                    <div>
                        <div style="font-size:0.72em; font-weight:800; opacity:0.75;">🏆 MEILLEUR MOIS D'EXTRACTION</div>
                        <div style="font-size:0.95em; font-weight:800;">{txt_meilleur_mois}</div>
                    </div>
                </div>
            </div>
            """
            afficher_html(html_resume_cal)

            libelle_an_court = "" if annee_choisie_v == "Toutes les années (Cumul)" else str(annee_choisie_v)
            html_cal_ventes = "<div class='cal-grid'>"
            for m_idx, m_label in mois_noms_12:
                tot_m = pv_par_mois_12[m_idx]
                cout_m = cout_par_mois_12[m_idx]
                enc_m = encaisse_par_mois_12[m_idx]
                perf_m = (tot_m / cout_m * 100.0) if cout_m > 0 else 0.0
                liste_p = pills_par_mois_12[m_idx]
                pct_barre = min(100.0, max(6.0, (abs(tot_m) / max_abs_mois) * 100.0)) if liste_p else 0.0

                if liste_p:
                    classe_c = "cal-card-active"
                    c_tot = "#2ecc71" if tot_m >= 0 else "#e74c3c"
                    bord_top = f"border-top: 3px solid {c_tot};"
                    badge_m = f"<span class='{'b-green' if tot_m >= 0 else 'b-red'}' style='font-size:0.72em; padding:2px 7px;'>{perf_m:+.1f}%</span>"
                    pills_str = "".join(
                        f"<span class='cal-pill' style='border-left: 3px solid {'#2ecc71' if pv_p >= 0 else '#e74c3c'};'>"
                        f"<b>{act_p}</b> (x{q_p}) : <span style='color:{'#2ecc71' if pv_p >= 0 else '#e74c3c'}; font-weight:800;'>{pv_p:+,.1f} €</span>"
                        f"</span>"
                        for act_p, q_p, pv_p, _ in liste_p
                    )
                    barre_html = f"<div class='score-bg' style='height:5px; margin:6px 0 4px 0;'><div style='width:{pct_barre:.0f}%; background:{c_tot}; height:100%;'></div></div>"
                    sous_info_m = f"<div style='font-size:0.72em; opacity:0.7; display:flex; justify-content:space-between;'><span>{len(liste_p)} vente(s)</span><span>Cash : {enc_m:,.0f} €</span></div>"
                else:
                    classe_c = "cal-card"
                    c_tot = "rgba(128,128,128,0.45)"
                    bord_top = ""
                    badge_m = "<span style='font-size:0.75em; opacity:0.4;'>⚪</span>"
                    pills_str = "<span style='font-size:0.80em; opacity:0.42; font-style:italic;'>Aucune vente ce mois</span>"
                    barre_html = ""
                    sous_info_m = ""

                html_cal_ventes += f"""
                <div class="{classe_c}" style="{bord_top}">
                    <div>
                        <div class="cal-month">
                            <span>{m_idx:02d}. {m_label} {libelle_an_court}</span>
                            {badge_m}
                        </div>
                        <div style="margin-bottom:8px;">{pills_str}</div>
                    </div>
                    <div>
                        {sous_info_m}
                        {barre_html}
                        <div style="text-align:right; border-top:1px dashed rgba(128,128,128,0.2); padding-top:6px; margin-top:4px;">
                            <span style="font-size:0.75em; opacity:0.75; margin-right:4px;">Net mois :</span>
                            <span class="cal-total" style="color:{c_tot};">{tot_m:+,.2f} €</span>
                        </div>
                    </div>
                </div>
                """
            html_cal_ventes += "</div>"
            afficher_html(html_cal_ventes)

            # --- TABLEAU RÉCAPITULATIF MOIS PAR MOIS ---
            st.markdown("#### 📊 Tableau Récapitulatif d'Extraction de Performance Mois par Mois")
            agregation_mois = {}
            for v in historique_v:
                m_key = v.get("mois_annee", str(v.get("date", ""))[:7])
                if m_key not in agregation_mois:
                    agregation_mois[m_key] = {"nb_ventes": 0, "montant_total": 0.0, "cout_total": 0.0, "pv_totale": 0.0}
                pv_val = float(v.get("plus_value_eur", 0.0))
                mt_val = float(v.get("montant_eur", 0.0))
                ct_val = float(v.get("cout_initial_eur", mt_val - pv_val))
                agregation_mois[m_key]["nb_ventes"] += 1
                agregation_mois[m_key]["montant_total"] += mt_val
                agregation_mois[m_key]["cout_total"] += ct_val
                agregation_mois[m_key]["pv_totale"] += pv_val

            html_t_mois = "<table class='r-table'><thead><tr><th style='text-align:left;'>Mois (Année-Mois)</th><th>Opérations</th><th>Capital Initial Vendu (€)</th><th>Cash Net Encaissé (€)</th><th>Plus/Moins-Value Actée (€)</th><th>Performance Extraite (%)</th></tr></thead><tbody>"
            for m_k in sorted(agregation_mois.keys(), reverse=True):
                d_m = agregation_mois[m_k]
                p_m_pct = (d_m["pv_totale"] / d_m["cout_total"] * 100.0) if d_m["cout_total"] > 0 else 0.0
                b_m = "b-green" if d_m["pv_totale"] >= 0 else "b-red"
                c_m_col = "#2ecc71" if d_m["pv_totale"] >= 0 else "#e74c3c"

                html_t_mois += f"""
                <tr>
                    <td class='r-name'>📅 {m_k}</td>
                    <td><b>{d_m['nb_ventes']}</b> vente(s)</td>
                    <td>{d_m['cout_total']:,.2f} €</td>
                    <td><b>{d_m['montant_total']:,.2f} €</b></td>
                    <td><span class='{b_m}'>{d_m['pv_totale']:+,.2f} €</span></td>
                    <td style='color:{c_m_col}; font-weight:800;'>{p_m_pct:+.2f}%</td>
                </tr>
                """
            html_t_mois += "</tbody></table>"
            afficher_html(html_t_mois)

            with st.expander("📋 Historique détaillé de chaque vente & Annulation (Restauration)", expanded=False):
                for idx_h, item_h in enumerate(historique_v):
                    col_h1, col_h2, col_h3 = st.columns([3, 2, 1])
                    with col_h1:
                        badge_esp = "💶 Crédité en Espèces" if item_h.get("credite_especes") else "📤 Hors Espèces"
                        markdown_fr(f"**{item_h['action']}** — **{item_h['qte']} action(s)** vendue(s) à **{item_h['prix_vente']:.2f} {item_h['devise']}** *(PRU : {item_h['pru']:.2f} {item_h['devise']})*")
                        st.caption(nombres_fr(f"Date : {item_h['date']} | Encaissé net : {item_h['montant_eur']:,.2f} € ({badge_esp})"))
                    with col_h2:
                        col_pv_s = "#2ecc71" if item_h["plus_value_eur"] >= 0 else "#e74c3c"
                        markdown_fr(f"Plus/Moins-Value : <span style='color:{col_pv_s}; font-weight:800;'>{item_h['plus_value_eur']:+,.2f} € ({item_h['perf_pct']:+.2f}%)</span>", unsafe_allow_html=True)
                    with col_h3:
                        st.button(
                            "🗑️ Annuler",
                            key=f"suppr_vente_{item_h['id']}_{idx_h}",
                            on_click=annuler_vente_portefeuille,
                            args=(idx_h,),
                            width="stretch",
                        )
                    st.markdown("---")
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
# FOOTER, MENTIONS LÉGALES, CGV, DROIT DE RÉTRACTATION & CONFORMITÉ AMF (NON-CIF)
# ==============================================================================
NOM_APP_LEGAL = "Boursy"  # Changez ici en "Nano" dès que votre nom final est choisi
# Identité de l'éditeur (obligatoire, loi LCEN) : à renseigner dans les secrets Streamlit
NOM_EDITEUR = _lire_secret("EDITEUR_NOM") or "Éditeur à renseigner (secret EDITEUR_NOM)"
NUMERO_SIRET = _lire_secret("EDITEUR_SIRET") or "en cours d'immatriculation"
ADRESSE_EDITEUR = _lire_secret("EDITEUR_ADRESSE") or "adresse à renseigner (secret EDITEUR_ADRESSE)"
CONTACT_AFFICHE = CONTACT_EMAIL or "adresse de contact à renseigner (secret CONTACT_EMAIL)"

st.markdown("---")
with st.expander(f"⚖️ Mentions Légales, CGV, Droit de Rétractation & Avertissement AMF ({NOM_APP_LEGAL} SaaS)", expanded=False):
    tab_leg_amf, tab_leg_cgv, tab_leg_retract, tab_leg_rgpd, tab_leg_confid = st.tabs([
        "🛡️ 1. Avertissement AMF (Non-CIF)",
        "💳 2. CGV & Abonnements (4,90 € / 8,90 €)",
        "⏳ 3. Droit de Rétractation (L221-28)",
        "🏛️ 4. Mentions Légales",
        "🔒 5. Politique de Confidentialité",
    ])

    with tab_leg_amf:
        afficher_html(f"""
        <div style="font-size:0.86em; line-height:1.6; opacity:0.92;">
            <b>1. Absence de Conseil en Investissement Financier (Statut Non-CIF)</b><br>
            La plateforme <b>{NOM_APP_LEGAL}</b> est un outil logiciel d'analyse statistique, quantitative et de suivi patrimonial à vocation strictement <b>pédagogique et informative</b>. L'éditeur n'agit en aucun cas en qualité de Conseiller en Investissements Financiers (CIF) au sens des articles L.541-1 et suivants du Code monétaire et financier, ni en tant que prestataire de services d'investissement (PSI) agréé par l'Autorité des Marchés Financiers (AMF).<br><br>
            <b>2. Nature des indicateurs algorithmiques et de l'Intelligence Artificielle</b><br>
            Les scores (/100), signaux techniques (RSI, Stochastique, Bandes de Bollinger, MACD, croisements EMA 2/12, ATR, canaux de régression linéaire à 3 ans), simulations d'allocation DCA et synthèses générées par le module <b>Coach IA (Google Gemini)</b> constituent des traitements mathématiques automatisés. Ils ne sauraient être interprétés comme une recommandation personnalisée d'achat, de vente ou de conservation d'instruments financiers.<br><br>
            <b>3. Responsabilité de l'utilisateur et exactitude des flux de marché</b><br>
            Les cotations, historiques de cours, taux de change (EUR/USD) et calendriers de dividendes proviennent de flux tiers publics (notamment Yahoo Finance) fournis « en l'état », pouvant comporter des délais ou des imprécisions. L'investissement en bourse (PEA / CTO) comporte un <b>risque de perte en capital</b>. L'utilisateur demeure seul maître et responsable de ses décisions d'investissement auprès de son établissement bancaire ou courtier. Les performances passées ne préjugent pas des performances futures.
        </div>
        """)

    with tab_leg_cgv:
        afficher_html(f"""
        <div style="font-size:0.86em; line-height:1.6; opacity:0.92;">
            <b>Article 1 — Objet et Architecture des Offres</b><br>
            Les présentes Conditions Générales de Vente (CGV) régissent la souscription aux services numériques de la plateforme <b>{NOM_APP_LEGAL}</b>, déclinés en trois formules :<br>
            • <b>🌱 Forfait Gratuit (0,00 € / mois) :</b> Accès découverte limité à 2 valeurs dans le radar/portefeuille et 1 crédit d'audit IA par jour.<br>
            • <b>⚡ Forfait Premium (4,90 € TTC / mois) :</b> Accès au catalogue complet (+100 valeurs PEA/US & recherche Yahoo Live), Tableaux 1 à 4 débloqués, gestion de portefeuille illimitée, export CSV, simulateur PRU, guichet d'encaissement espèces et 3 crédits d'audit IA par jour.<br>
            • <b>👑 Forfait Pro Max (8,90 € TTC / mois) :</b> Accès intégral incluant les fonctionnalités Premium ainsi que le Journal des Arbitrages & Calendrier 12 mois des Plus-Values Actées, la Station Graphique Interactive 360° (Quant & TradingView), l'Import Magique IA par capture d'écran, le Duel de performance vs ETF, le Radar de détachements à 90 jours, les alertes par email et 15 crédits d'audit IA par jour.<br><br>
            <b>Article 2 — Paiement Sécurisé et Facturation</b><br>
            Les règlements sont opérés par carte bancaire via notre prestataire certifié PCI-DSS <b>Stripe</b>. Aucune coordonnée bancaire n'est stockée sur les serveurs de {NOM_APP_LEGAL}. Le prix est exigible comptant à la souscription, puis renouvelé par tacite reconduction mensuelle à la date anniversaire.<br><br>
            <b>Article 3 — Absence d'Engagement et Résiliation en 1 Clic</b><br>
            Les abonnements <b>Premium</b> et <b>Pro Max</b> sont <b>sans aucun engagement de durée</b>. L'abonné peut résilier ou modifier sa formule à tout moment en un clic depuis le menu latéral gauche via le bouton <b>« ⚙️ Gérer mon abonnement / Factures »</b> (Portail Client officiel Stripe). Toute résiliation prend effet à l'issue de la période mensuelle en cours : l'utilisateur conserve l'intégralité de ses accès payants jusqu'au dernier jour de la période facturée, puis son compte repasse automatiquement en Forfait Gratuit sans perte de ses données enregistrées.
        </div>
        """)

    with tab_leg_retract:
        afficher_html(f"""
        <div style="font-size:0.86em; line-height:1.6; opacity:0.92;">
            <b>Renoncement exprès au droit de rétractation (Article L221-28 13° du Code de la consommation)</b><br>
            Conformément aux dispositions de l'article L221-28 13° du Code de la consommation français, le droit de rétractation de quatorze (14) jours ne peut être exercé pour les contrats de fourniture d'un contenu numérique non fourni sur un support matériel dont l'exécution a commencé après accord préalable exprès du consommateur et renoncement exprès à son droit de rétractation.<br><br>
            En validant son paiement sur l'interface Stripe et en accédant instantanément aux fonctionnalités débloquées des offres <b>Premium (4,90 €/mois)</b> ou <b>Pro Max (8,90 €/mois)</b>, le Client :
            <ul style="margin:6px 0 8px 18px;">
                <li>Demande expressément l'activation immédiate de son abonnement numérique avant l'expiration du délai légal de rétractation ;</li>
                <li>Reconnaît qu'il renonce expressément à son droit de rétractation pour la période mensuelle entamée.</li>
            </ul>
            En conséquence, aucun remboursement prorata temporis ne sera effectué pour le mois en cours en cas d'annulation, l'accès aux outils Pro/Premium demeurant pleinement actif jusqu'à l'échéance mensuelle.
        </div>
        """)

    with tab_leg_rgpd:
        afficher_html(f"""
        <div style="font-size:0.86em; line-height:1.6; opacity:0.92;">
            <b>1. Éditeur et Hébergement (Loi LCEN)</b><br>
            • <b>Éditeur du service :</b> {NOM_EDITEUR} — SIRET : {NUMERO_SIRET} — {ADRESSE_EDITEUR}<br>
            • <b>Contact & Support Client :</b> <a href="mailto:{CONTACT_AFFICHE}">{CONTACT_AFFICHE}</a><br>
            • <b>Hébergement de l'application :</b> Streamlit Cloud / Snowflake Inc. (San Mateo, Californie, USA)<br>
            • <b>Hébergement de la base de données chiffrée :</b> Supabase Inc. (Infrastructure Cloud sécurisée avec protocole Row Level Security)<br><br>
            <b>2. Données personnelles</b><br>
            Le traitement de vos données personnelles est décrit dans l'onglet <b>🔒 5. Politique de Confidentialité</b>.
        </div>
        """)

    with tab_leg_confid:
        afficher_html(f"""
        <div style="font-size:0.86em; line-height:1.6; opacity:0.92;">
            <b>1. Responsable du traitement</b><br>
            {NOM_EDITEUR} — {ADRESSE_EDITEUR} — contact : <a href="mailto:{CONTACT_AFFICHE}">{CONTACT_AFFICHE}</a>.<br><br>
            <b>2. Données collectées</b><br>
            • Votre adresse e-mail et votre mot de passe (conservé sous forme chiffrée par Supabase, jamais lisible par l'éditeur).<br>
            • Les données que vous saisissez : actions suivies, quantités, prix de revient, prix cibles, budget, ventes, dividendes encaissés, préférences d'alertes.<br>
            • Votre niveau d'abonnement et votre identifiant client Stripe. Vos coordonnées bancaires sont traitées par Stripe uniquement et ne nous sont jamais transmises.<br>
            • Les questions posées au coach IA, transmises avec un résumé de votre portefeuille au moment de l'analyse.<br>
            • Des données techniques de connexion (adresse IP, navigateur), traitées par nos hébergeurs pour faire fonctionner le service.<br><br>
            <b>3. Finalités et base légale</b><br>
            Ces données servent uniquement à fournir le service que vous avez demandé (suivi de portefeuille, alertes, analyses, gestion de l'abonnement) : la base légale est l'exécution du contrat. Elles ne sont ni vendues, ni louées, ni utilisées à des fins publicitaires.<br><br>
            <b>4. Durée de conservation</b><br>
            Tant que votre compte existe. À sa suppression, vos données de portefeuille, votre historique et votre compte sont effacés immédiatement. Les justificatifs de paiement sont conservés par Stripe et par l'éditeur pendant la durée exigée par les obligations comptables.<br><br>
            <b>5. Destinataires (sous-traitants)</b><br>
            • <b>Supabase</b> : comptes utilisateurs et base de données.<br>
            • <b>Streamlit Cloud (Snowflake Inc., États-Unis)</b> : hébergement de l'application.<br>
            • <b>Stripe</b> : paiement et gestion des abonnements.<br>
            • <b>Google</b> : API Gemini (analyses du coach IA, à votre demande) et Gmail (envoi des e-mails).<br>
            • <b>GitHub (Microsoft)</b> : exécution de la tâche quotidienne d'envoi des alertes.<br>
            Les cours de bourse sont obtenus auprès de Yahoo Finance : seuls les symboles des actions lui sont transmis, jamais vos données personnelles.<br><br>
            <b>6. Transferts hors de l'Union européenne</b><br>
            Certains de ces prestataires sont situés aux États-Unis. Ces transferts s'appuient sur les garanties prévues par le RGPD (décision d'adéquation du Data Privacy Framework ou clauses contractuelles types de la Commission européenne, selon le prestataire).<br><br>
            <b>7. Vos droits</b><br>
            Vous disposez d'un droit d'accès, de rectification, d'effacement, de limitation, d'opposition et de portabilité. Vous pouvez :<br>
            • exporter vos données avec le bouton <b>📥 Export CSV</b> ;<br>
            • supprimer vous-même votre compte et toutes vos données dans <b>⚙️ Mon compte</b> (menu de gauche, une fois connecté) ;<br>
            • pour toute autre demande, écrire à <a href="mailto:{CONTACT_AFFICHE}">{CONTACT_AFFICHE}</a>.<br>
            Si vous estimez que vos droits ne sont pas respectés, vous pouvez adresser une réclamation à la <b>CNIL</b> (www.cnil.fr).<br><br>
            <b>8. Cookies</b><br>
            Boursy n'utilise aucun cookie publicitaire ni de mesure d'audience. Seuls les cookies techniques nécessaires au fonctionnement de l'application et de la connexion sont utilisés.
        </div>
        """)

afficher_html(
    f"<div style='text-align: center; font-size: 0.80em; opacity: 0.72; padding: 6px 0 14px 0;'>"
    f"⚖️ <b>{NOM_APP_LEGAL} SaaS</b> — Suite Boursière PEA, US & Dividendes | "
    f"Outil d'analyse statistique et pédagogique (Non-CIF) • Paiements sécurisés par Stripe • Contact : {CONTACT_AFFICHE}"
    f"</div>"
)
