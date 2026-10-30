import urllib.request
import urllib.parse
import json
import math
import smtplib
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

ADMIN_EMAIL = "orcha12345@gmail.com"

def afficher_html(html_brut):
    """Supprime les indentations pour empêcher Streamlit d'afficher le HTML en bloc de code."""
    html_propre = "\n".join(ligne.strip() for ligne in html_brut.splitlines() if ligne.strip())
    st.markdown(html_propre, unsafe_allow_html=True)

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
</style>
"""
afficher_html(STYLE_ARGON)

# ==============================================================================
# CONNEXION SUPABASE, STRIPE & EMAILS D'ALERTE
# ==============================================================================
@st.cache_resource
def init_supabase():
    try:
        url = str(st.secrets["SUPABASE_URL"]).strip().rstrip("/")
        key = str(st.secrets["SUPABASE_KEY"]).strip()
        return create_client(url, key)
    except Exception:
        return None

supabase = init_supabase()

def verifier_abonnement_stripe(email_client):
    if not email_client or not hasattr(st, "secrets"):
        return False
    cle_stripe = str(st.secrets.get("STRIPE_SECRET_KEY", "")).strip().strip('"').strip("'")
    if not cle_stripe:
        return False
    try:
        url_cust = f"https://api.stripe.com/v1/customers?email={urllib.parse.quote(email_client.strip())}&limit=5"
        req_cust = urllib.request.Request(url_cust, headers={"Authorization": f"Bearer {cle_stripe}"})
        with urllib.request.urlopen(req_cust, timeout=8) as resp:
            data_cust = json.loads(resp.read().decode("utf-8"))
        for client in data_cust.get("data", []):
            cid = client.get("id")
            url_sub = f"https://api.stripe.com/v1/subscriptions?customer={cid}&status=all&limit=5"
            req_sub = urllib.request.Request(url_sub, headers={"Authorization": f"Bearer {cle_stripe}"})
            with urllib.request.urlopen(req_sub, timeout=8) as resp_s:
                data_sub = json.loads(resp_s.read().decode("utf-8"))
                for sub in data_sub.get("data", []):
                    if sub.get("status") in ("active", "trialing"):
                        return True
        return False
    except Exception:
        return False

def envoyer_email_alerte(destinataire, liste_alertes):
    if not hasattr(st, "secrets"):
        return False, "Secrets Streamlit non disponibles."
    smtp_user = str(st.secrets.get("SMTP_EMAIL", "")).strip()
    smtp_pass = str(st.secrets.get("SMTP_PASSWORD", "")).strip()
    if not smtp_user or not smtp_pass:
        return False, "Pour activer l'envoi d'emails, ajoutez `SMTP_EMAIL` et `SMTP_PASSWORD` dans vos Secrets Streamlit."

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"🔔 Boursy — {len(liste_alertes)} Alerte(s) d'Achat & Prix Cible détectée(s)"
        msg["From"] = smtp_user
        msg["To"] = destinataire

        lignes_html = "".join(
            f"<li style='margin-bottom:8px;'><b>{a['Actif']}</b> : Cours <b>{a['Prix']}</b> (Cible : {a['Cible']}) — Score : <b>{a['Score']}/100</b> ({a['Motif']})</li>"
            for a in liste_alertes
        )
        corps_html = f"""
        <html><body style="font-family: Arial, sans-serif; color: #2c3e50;">
            <h2>📈 Rapport d'Alertes Boursy ({datetime.now().strftime('%d/%m/%Y')})</h2>
            <p>Votre radar algorithmique a détecté les opportunités suivantes :</p>
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
@st.cache_data(ttl=1800)
def recuperer_taux_change():
    try:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/EURUSD=X?range=1d&interval=1d"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())
            taux = float(data["chart"]["result"][0]["meta"]["regularMarketPrice"])
            return taux if taux > 0 else 1.08
    except Exception:
        return 1.08

@st.cache_data(ttl=1800)
def recuperer_indice_meteo(symbole):
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbole)}?range=5d&interval=1d"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())
            res = data["chart"]["result"][0]
            prix = float(res["meta"]["regularMarketPrice"])
            closes = [float(c) for c in res["indicators"]["quote"][0]["close"] if c is not None]
            veille = closes[-2] if len(closes) >= 2 else float(res["meta"].get("chartPreviousClose", prix))
            var_pct = ((prix - veille) / veille * 100.0) if veille > 0 else 0.0
            return prix, var_pct
    except Exception:
        return None, 0.0

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
if "budget_dca" not in st.session_state:
    st.session_state["budget_dca"] = 450.0
if "est_abonne_pro" not in st.session_state:
    st.session_state["est_abonne_pro"] = False
if "reponse_ia_coach" not in st.session_state:
    st.session_state["reponse_ia_coach"] = ""
if "historique_chat_ia" not in st.session_state:
    st.session_state["historique_chat_ia"] = []

date_jour_str = datetime.now().strftime("%Y-%m-%d")
if st.session_state.get("quota_ia_date") != date_jour_str:
    st.session_state["quota_ia_date"] = date_jour_str
    st.session_state["quota_ia_utilise"] = 0

def synchroniser_widgets_portefeuille(portefeuille_cloud, watchlist_courante):
    toutes_les_actions = set(list(watchlist_courante.keys()) + list(PORTEFEUILLE_DEFAUT.keys()))
    for nom_act in toutes_les_actions:
        if nom_act in portefeuille_cloud and isinstance(portefeuille_cloud[nom_act], dict):
            st.session_state[f"qte_{nom_act}"] = int(portefeuille_cloud[nom_act].get("qte", 0))
            st.session_state[f"pru_{nom_act}"] = float(portefeuille_cloud[nom_act].get("pru", 0.0))
        else:
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
    if supabase and st.session_state["user"]:
        try:
            user_id_str = str(st.session_state["user"].id)
            email_str = str(st.session_state["user"].email)
            watchlist_actuelle = st.session_state.get("watchlist", WATCHLIST_DEFAUT)

            est_pro_val = True if email_str.lower() == ADMIN_EMAIL.lower() else bool(st.session_state.get("est_abonne_pro", False))
            st.session_state["est_abonne_pro"] = est_pro_val

            payload = {
                "user_id": user_id_str,
                "email": email_str,
                "budget_dca": float(st.session_state["budget_dca"]),
                "watchlist": dict(watchlist_actuelle),
                "portefeuille": dict(st.session_state["portefeuille"]),
                "est_abonne_pro": est_pro_val,
                "updated_at": datetime.utcnow().isoformat()
            }
            supabase.table("user_data").upsert(payload).execute()

            dict_prix = st.session_state.get("prix_temps_reel", {})
            taux_usd_eur = st.session_state.get("taux_change", 1.08)
            if dict_prix:
                pf_actuel = st.session_state["portefeuille"]
                val_totale = 0.0
                cap_investi = 0.0
                rente_tot = 0.0

                for nom, data in pf_actuel.items():
                    if nom == "Espèces":
                        val_esp = float(data.get("pru", 0.0))
                        val_totale += val_esp
                        cap_investi += val_esp
                    elif nom in watchlist_actuelle:
                        q = float(data.get("qte", 0.0))
                        pru = float(data.get("pru", 0.0))
                        cours = float(dict_prix.get(nom, watchlist_actuelle[nom].get("prix_cible", 50.0)))
                        devise = watchlist_actuelle[nom].get("devise", "EUR")
                        facteur = (1.0 / taux_usd_eur) if devise == "USD" else 1.0

                        val_totale += q * cours * facteur
                        cap_investi += q * pru * facteur
                        rente_tot += q * float(watchlist_actuelle[nom].get("div_eur", 0.0)) * facteur

                date_du_jour = datetime.now().strftime("%Y-%m-%d")
                snapshot_payload = {
                    "user_id": user_id_str,
                    "date": date_du_jour,
                    "capital_investi": round(cap_investi, 2),
                    "valorisation_pea": round(val_totale, 2),
                    "rente_annuelle": round(rente_tot, 2)
                }
                supabase.table("portfolio_history").delete().eq("user_id", user_id_str).eq("date", date_du_jour).execute()
                supabase.table("portfolio_history").insert(snapshot_payload).execute()

            st.sidebar.success("✅ Sauvegardé & Snapshot du jour mis à jour !")
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

if supabase is None:
    st.sidebar.warning("⚠️ Base de données non connectée. Mode local actif.")
else:
    if st.session_state["user"] is None:
        choix_auth = st.sidebar.radio("Navigation compte :", ["Se connecter", "Créer un compte", "Mot de passe oublié"])
        email_input = st.sidebar.text_input("Adresse Email").strip()

        if choix_auth == "Se connecter":
            password_input = st.sidebar.text_input("Mot de passe", type="password")
            if st.sidebar.button("🔓 Connexion", type="primary", use_container_width=True):
                try:
                    res = supabase.auth.sign_in_with_password({"email": email_input, "password": password_input})
                    st.session_state["user"] = res.user
                    email_connecte = str(res.user.email).lower()

                    data = supabase.table("user_data").select("*").eq("user_id", res.user.id).execute()
                    if data.data:
                        profil = data.data[0]
                        wl_cloud = profil.get("watchlist")
                        st.session_state["watchlist"] = wl_cloud if wl_cloud is not None else WATCHLIST_DEFAUT.copy()
                        pf_raw = profil.get("portefeuille")
                        portefeuille_cloud = pf_raw if pf_raw is not None else PORTEFEUILLE_DEFAUT.copy()
                        st.session_state["portefeuille"] = portefeuille_cloud
                        st.session_state["budget_dca"] = float(profil.get("budget_dca") or 450.0)

                        est_pro_bdd = bool(profil.get("est_abonne_pro", False))
                        if email_connecte == ADMIN_EMAIL.lower():
                            est_pro_bdd = True
                        elif not est_pro_bdd and verifier_abonnement_stripe(email_connecte):
                            est_pro_bdd = True
                            supabase.table("user_data").update({"est_abonne_pro": True}).eq("user_id", str(res.user.id)).execute()

                        st.session_state["est_abonne_pro"] = est_pro_bdd
                        synchroniser_widgets_portefeuille(portefeuille_cloud, st.session_state["watchlist"])
                    else:
                        st.session_state["est_abonne_pro"] = (email_connecte == ADMIN_EMAIL.lower())
                        sauvegarder_dans_cloud()
                    st.rerun()
                except Exception:
                    st.sidebar.error("Identifiants incorrects ou compte inexistant.")

        elif choix_auth == "Créer un compte":
            password_input = st.sidebar.text_input("Choisir un mot de passe (6 car. min.)", type="password")
            if st.sidebar.button("✨ S'inscrire gratuitement", type="primary", use_container_width=True):
                try:
                    res = supabase.auth.sign_up({"email": email_input, "password": password_input})
                    if res.user:
                        st.session_state["user"] = res.user
                        st.session_state["watchlist"] = WATCHLIST_DEFAUT.copy()
                        st.session_state["portefeuille"] = PORTEFEUILLE_DEFAUT.copy()
                        st.session_state["est_abonne_pro"] = (str(res.user.email).lower() == ADMIN_EMAIL.lower())
                        sauvegarder_dans_cloud()
                        st.sidebar.success("Compte créé avec succès !")
                        st.rerun()
                except Exception as e:
                    st.sidebar.error(f"Erreur d'inscription : {e}")

        else:
            st.sidebar.caption("Recevez un lien sécurisé de réinitialisation par email :")
            if st.sidebar.button("📧 Envoyer le lien", use_container_width=True):
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
        est_admin_connecte = (email_courant.lower() == ADMIN_EMAIL.lower())
        if est_admin_connecte:
            st.session_state["est_abonne_pro"] = True

        if st.query_params.get("paiement") == "succes" and not st.session_state.get("est_abonne_pro", False):
            if verifier_abonnement_stripe(email_courant):
                st.session_state["est_abonne_pro"] = True
                supabase.table("user_data").update({"est_abonne_pro": True}).eq("user_id", str(st.session_state["user"].id)).execute()
                st.balloons()
                st.sidebar.success("🎉 Paiement validé ! Abonnement Boursy Pro actif.")

        st.sidebar.success(f"Connecté : **{email_courant}**")

        if st.sidebar.button("🔄 Charger mes données", type="primary", use_container_width=True):
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
                    st.session_state["est_abonne_pro"] = True if est_admin_connecte else bool(profil.get("est_abonne_pro", False))
                    synchroniser_widgets_portefeuille(portefeuille_cloud, st.session_state["watchlist"])
                    st.sidebar.success("✅ Données synchronisées !")
                    st.rerun()
            except Exception as e:
                st.sidebar.error(f"Erreur : {e}")

        col_btn1, col_btn2 = st.sidebar.columns(2)
        if col_btn1.button("💾 Sauver", use_container_width=True):
            if sauvegarder_dans_cloud():
                st.toast("✅ Profil & Snapshot sauvegardés dans le Cloud !")
        if col_btn2.button("🚪 Sortir", use_container_width=True):
            supabase.auth.sign_out()
            st.session_state["user"] = None
            st.session_state["est_abonne_pro"] = False
            st.rerun()

WATCHLIST = st.session_state["watchlist"]
TAUX_USD_EUR = recuperer_taux_change()
st.session_state["taux_change"] = TAUX_USD_EUR

if st.sidebar.button("🔄 Actualiser les cours Bourse", use_container_width=True):
    st.cache_data.clear()
    st.toast("⚡ Cours boursiers, indices et taux EUR/USD actualisés !")
    st.rerun()

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

mode_ajout = st.sidebar.radio("Mode d'ajout :", ["Catalogue (PEA & US)", "Ticker Yahoo libre"], horizontal=True)

if mode_ajout == "Catalogue (PEA & US)":
    choix_menu_yf = st.sidebar.selectbox("Sélectionner une valeur :", ["-- Choisir une action --"] + sorted(CATALOGUE_ACTIONS.keys()))
    if choix_menu_yf != "-- Choisir une action --":
        symbole_sel, devise_sel, secteur_def = CATALOGUE_ACTIONS[choix_menu_yf]
        nom_propre = choix_menu_yf.split(" (")[0]
        with st.sidebar.form("form_catalogue_yf"):
            st.markdown(f"**{nom_propre}** (`{symbole_sel}`) — **{devise_sel}**")
            nouveau_secteur = st.text_input("Secteur", value=secteur_def)
            nouveau_cible = st.number_input(f"Prix cible ({devise_sel})", min_value=0.0, value=float(WATCHLIST.get(nom_propre, {}).get("prix_cible", 100.0)), step=1.0)
            nouveau_div = st.number_input(f"Dividende annuel ({devise_sel})", min_value=0.0, value=float(WATCHLIST.get(nom_propre, {}).get("div_eur", 2.5)), step=0.1)
            nouveau_payout = st.number_input("Payout Ratio (ex: 0.50)", min_value=0.0, max_value=2.0, value=float(WATCHLIST.get(nom_propre, {}).get("payout_ratio", 0.50)), step=0.05)
            nouveau_croiss = st.text_input("Croissance Div. 5A", value=WATCHLIST.get(nom_propre, {}).get("croissance_5a", "+6.0%"))
            liste_mois_possibles = ["Jan", "Fév", "Mar", "Avr", "Mai", "Juin", "Juil", "Août", "Sep", "Oct", "Nov", "Déc"]
            def_mois = ["Mar", "Juin", "Sep", "Déc"] if devise_sel == "USD" else ["Mai"]
            nouveau_mois = st.multiselect("Mois de versement :", liste_mois_possibles, default=WATCHLIST.get(nom_propre, {}).get("mois_div", def_mois))

            if st.form_submit_button("➕ Ajouter / Mettre à jour"):
                st.session_state["watchlist"][nom_propre] = {
                    "symbole": symbole_sel,
                    "prix_cible": nouveau_cible,
                    "secteur": nouveau_secteur,
                    "div_eur": nouveau_div,
                    "payout_ratio": nouveau_payout,
                    "croissance_5a": nouveau_croiss,
                    "mois_div": nouveau_mois,
                    "devise": devise_sel,
                }
                sauvegarder_dans_cloud()
                st.rerun()
else:
    with st.sidebar.form("form_ticker_libre"):
        nom_libre = st.text_input("Nom de l'entreprise (ex: Netflix)").strip()
        sym_libre = st.text_input("Ticker Yahoo (ex: NFLX ou ASML.AS)").strip().upper()
        dev_libre = st.selectbox("Devise de cotation :", ["EUR", "USD"])
        sec_libre = st.text_input("Secteur", value="Technologie")
        cible_libre = st.number_input(f"Prix cible ({dev_libre})", min_value=0.0, value=100.0, step=1.0)
        div_libre = st.number_input(f"Dividende annuel ({dev_libre})", min_value=0.0, value=1.5, step=0.1)
        payout_libre = st.number_input("Payout Ratio (ex: 0.45)", min_value=0.0, max_value=2.0, value=0.45, step=0.05)
        liste_mois_possibles = ["Jan", "Fév", "Mar", "Avr", "Mai", "Juin", "Juil", "Août", "Sep", "Oct", "Nov", "Déc"]
        mois_libre = st.multiselect("Mois de versement :", liste_mois_possibles, default=["Mai"])

        if st.form_submit_button("➕ Ajouter ce Ticker"):
            if nom_libre and sym_libre:
                st.session_state["watchlist"][nom_libre] = {
                    "symbole": sym_libre,
                    "prix_cible": cible_libre,
                    "secteur": sec_libre,
                    "div_eur": div_libre,
                    "payout_ratio": payout_libre,
                    "croissance_5a": "+5.0%",
                    "mois_div": mois_libre,
                    "devise": dev_libre,
                }
                sauvegarder_dans_cloud()
                st.rerun()

with st.sidebar.expander("🗑️ Supprimer une action du radar"):
    if WATCHLIST:
        action_a_suppr = st.selectbox("Choisir l'action à retirer :", list(WATCHLIST.keys()))
        if st.button("Supprimer définitivement"):
            if action_a_suppr in st.session_state["watchlist"]:
                del st.session_state["watchlist"][action_a_suppr]
            if action_a_suppr in st.session_state["portefeuille"]:
                del st.session_state["portefeuille"][action_a_suppr]
            st.session_state[f"qte_{action_a_suppr}"] = 0
            sauvegarder_dans_cloud()
            st.rerun()

# --- GESTION SAAS & CONSOLE ADMIN ---
st.sidebar.markdown("---")
st.sidebar.header("💎 Offre Boursy & Accès")

est_admin = (
    st.session_state.get("user") is not None
    and str(st.session_state["user"].email).lower() == ADMIN_EMAIL.lower()
)

simuler_visiteur_gratuit = False
if est_admin:
    with st.sidebar.expander("👑 Console Administrateur SaaS", expanded=False):
        simuler_visiteur_gratuit = st.checkbox("Simuler la vue Visiteur Gratuit (Freemium)", value=False)
        if supabase:
            try:
                res_users = supabase.table("user_data").select("user_id, email, est_abonne_pro").execute()
                liste_u = res_users.data if res_users.data else []
                nb_pro = sum(1 for u in liste_u if u.get("est_abonne_pro"))
                st.caption(f"👥 **{len(liste_u)} inscrit(s)** | 💎 **{nb_pro} Abonné(s) Pro**")
            except Exception:
                pass

if est_admin and not simuler_visiteur_gratuit:
    mode_gratuit = False
elif simuler_visiteur_gratuit:
    mode_gratuit = True
else:
    mode_gratuit = not bool(st.session_state.get("est_abonne_pro", False))

quota_ia_max = 2 if mode_gratuit else 15

if mode_gratuit:
    actions_autorisees = list(WATCHLIST.keys())[:2]
    st.sidebar.info("🔒 **Offre Découverte (Freemium)** : 2 valeurs débloquées & 2 audits IA/jour.")
    lien_stripe_base = str(st.secrets.get("STRIPE_CHECKOUT_URL", "")).strip() if hasattr(st, "secrets") else ""
    if lien_stripe_base:
        if st.session_state.get("user") is not None:
            email_client_url = urllib.parse.quote(str(st.session_state["user"].email))
            sep = "&" if "?" in lien_stripe_base else "?"
            lien_stripe_final = f"{lien_stripe_base}{sep}prefilled_email={email_client_url}"
        else:
            lien_stripe_final = lien_stripe_base
        st.sidebar.link_button("💎 S'abonner à Boursy Pro (Stripe)", lien_stripe_final, type="primary", use_container_width=True)
else:
    actions_autorisees = list(WATCHLIST.keys())
    st.sidebar.success(f"💎 **Abonné Boursy Pro actif** : {len(WATCHLIST)} valeurs débloquées & 15 audits IA/jour.")

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
        return "🟢 Achat (Croisement)", 15
    elif jour_e2 > jour_e12 and ecart_pct >= 0.20:
        return "🟢 Achat (Haussier)", 12
    elif veille_e2 >= veille_e12 and jour_e2 < jour_e12:
        return "🔴 Vente (Croisement)", -10
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

@st.cache_data(ttl=3600)
def recuperer_donnees(symbole):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbole}?range=3y&interval=1d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=6) as response:
            data = json.loads(response.read().decode())
            result = data["chart"]["result"][0]
            prix_actuel = float(result["meta"]["regularMarketPrice"])
            quote = result["indicators"]["quote"][0]
            closes = [float(p) for p in quote.get("close", []) if p is not None]
            hauts = [float(h) for h in quote.get("high", []) if h is not None]
            bas = [float(l) for l in quote.get("low", []) if l is not None]
            return prix_actuel, closes, hauts, bas
    except Exception:
        return None, None, None, None

# ==============================================================================
# EN-TÊTE PRINCIPAL, MÉTÉO DES MARCHÉS & BANNIÈRE D'ACCUEIL
# ==============================================================================
st.title("📈 Boursy - Suite Boursière PEA, US & Dividendes")

cac_pts, cac_var = recuperer_indice_meteo("^FCHI")
sp_pts, sp_var = recuperer_indice_meteo("^GSPC")
vix_pts, vix_var = recuperer_indice_meteo("^VIX")

cac_str = f"{cac_pts:,.0f} pts ({cac_var:+.2f}%)" if cac_pts else "En attente"
sp_str = f"{sp_pts:,.0f} pts ({sp_var:+.2f}%)" if sp_pts else "En attente"
vix_val = vix_pts if vix_pts else 18.0
etat_vix = "🟢 Marché Calme" if vix_val < 16 else ("🔥 Peur / Opportunités DCA" if vix_val >= 24 else "🟡 Volatilité Normale")
c_cac = "#2ecc71" if cac_var >= 0 else "#e74c3c"
c_sp = "#2ecc71" if sp_var >= 0 else "#e74c3c"
c_vix = "#2ecc71" if vix_val < 16 else ("#e74c3c" if vix_val >= 24 else "#f39c12")

html_meteo = f"""
<div class="meteo-bar">
    <div class="meteo-item" style="border-left-color: {c_cac};">
        <div><div style="font-size:0.75em; font-weight:800; opacity:0.7;">🇫🇷 CAC 40 (PARIS)</div><div style="font-weight:900; font-size:1.05em;">{cac_str}</div></div>
        <span style="color:{c_cac}; font-weight:800;">{'▲' if cac_var >= 0 else '▼'}</span>
    </div>
    <div class="meteo-item" style="border-left-color: {c_sp};">
        <div><div style="font-size:0.75em; font-weight:800; opacity:0.7;">🇺🇸 S&P 500 (NEW YORK)</div><div style="font-weight:900; font-size:1.05em;">{sp_str}</div></div>
        <span style="color:{c_sp}; font-weight:800;">{'▲' if sp_var >= 0 else '▼'}</span>
    </div>
    <div class="meteo-item" style="border-left-color: {c_vix};">
        <div><div style="font-size:0.75em; font-weight:800; opacity:0.7;">🌡️ INDICE VIX (NERVOSITÉ)</div><div style="font-weight:900; font-size:1.05em;">{vix_val:.1f} — {etat_vix}</div></div>
    </div>
    <div class="meteo-item" style="border-left-color: #9b59b6;">
        <div><div style="font-size:0.75em; font-weight:800; opacity:0.7;">💱 PARITÉ EUR / USD</div><div style="font-weight:900; font-size:1.05em;">1 € = {TAUX_USD_EUR:.4f} $</div></div>
    </div>
</div>
"""
afficher_html(html_meteo)

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
# TRAITEMENT DU MOTEUR BOURSIER SUR LA WATCHLIST
# ==============================================================================
resultats_analysed = []
donnees_t1, donnees_t2, donnees_t3, donnees_t4 = [], [], [], []
alertes_detectees = []
historiques_prix = {}
droites_regression_dict = {}
prix_temps_reel = {}

for nom, info in list(st.session_state["watchlist"].items()):
    prix_actuel, closes, hauts, bas = recuperer_donnees(info["symbole"])
    if prix_actuel is None or not closes:
        continue

    prix_temps_reel[nom] = prix_actuel
    historiques_prix[nom] = closes
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
        decision = "⚠️ ALLÈGEMENT"
    elif score >= 65 and "🔴" not in statut_ema_2_12:
        decision = "🔥 ACHAT FORT"
    elif score >= 45 and "🔴" not in statut_ema_2_12:
        decision = "✅ ACCUMULATION"
    else:
        decision = "⏸️ CONSERVATION"

    if (prix_cible > 0 and prix_actuel <= prix_cible) or "ACHAT FORT" in decision:
        motif_al = "Sous le Prix Cible 🎯" if (prix_cible > 0 and prix_actuel <= prix_cible) else "Signal Technique Achat Fort 🔥"
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
onglet_radar, onglet_portefeuille, onglet_dividendes, onglet_ia = st.tabs([
    "🔍 1. Radar, DCA & Alertes",
    "💼 2. Portefeuille & Trajectoire Boursière",
    "📅 3. Calendrier 12 Mois & Boule de Neige",
    "🤖 4. Coach & Audit IA 2.0 (Gemini)",
])

# ------------------------------------------------------------------------------
# ONGLET 1 : RADAR ALGORITHMIQUE, ALLOCATION DCA (MAX 2 LIGNES) & ALERTES EMAIL
# ------------------------------------------------------------------------------
with onglet_radar:
    if mode_gratuit:
        st.warning("🔒 **Aperçu Découverte (Freemium)** : 2 valeurs affichées. Passez à Boursy Pro dans la barre latérale pour débloquer l'ensemble du catalogue PEA & US !")

    nb_opportunites = sum(1 for d in donnees_t1 if "ACHAT" in d["Décision"] or "ACCUMULATION" in d["Décision"])
    meilleure_opp = candidats_tries[0]["nom"] if candidats_tries else "Aucune"

    html_radar_kpi = f"""
    <div class="argon-grid">
        <div class="argon-card">
            <div class="argon-title">🎯 Opportunités Actives</div>
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
            <div class="argon-sub">Valeurs sous cible ou Achat Fort</div>
        </div>
    </div>
    """
    afficher_html(html_radar_kpi)

    col_dca_exp, col_al_exp = st.columns(2)

    with col_dca_exp:
        with st.expander(f"🛒 Plan d'Achat DCA Condensé ({BUDGET_MENSUEL:.0f} € — Max 2 lignes)", expanded=True):
            achats_retenus = [item for item in candidats_dca_top2 if achats_simules.get(item["nom"], 0) > 0]
            if not achats_retenus:
                st.info("Aucune action ne remplit actuellement les critères d'achat DCA.")
            else:
                html_dca = "<table class='r-table'><thead><tr><th style='text-align:left;'>Action Prioritaire</th><th>Score</th><th>Qté</th><th>Coût (€)</th><th>+Div/an</th></tr></thead><tbody>"
                for item in achats_retenus:
                    q_sim = achats_simules[item["nom"]]
                    cout_tot = q_sim * item["prix_eur"]
                    div_gagne = q_sim * item["div_eur"]
                    html_dca += f"<tr><td class='r-name'><b>{item['nom']}</b></td><td><span class='b-green'>{item['score']} / 100</span></td><td><b>{q_sim}</b></td><td>{cout_tot:.1f} €</td><td style='color:#2ecc71; font-weight:700;'>+{div_gagne:.2f} €</td></tr>"
                html_dca += "</tbody></table>"
                afficher_html(html_dca)

    with col_al_exp:
        with st.expander(f"🔔 Centre d'Alertes & Notification Email ({len(alertes_detectees)} signal/signaux)", expanded=True):
            if not alertes_detectees:
                st.info("Aucune valeur n'est actuellement sous son prix cible ou en signal d'Achat Fort.")
            else:
                for al in alertes_detectees[:4]:
                    st.markdown(f"• **{al['Actif']}** à **{al['Prix']}** (Cible : `{al['Cible']}`) — **{al['Motif']}**")
                email_dest = str(st.session_state["user"].email) if st.session_state.get("user") else ADMIN_EMAIL
                if st.button(f"📧 M'envoyer ce rapport d'alertes par email ({email_dest})", use_container_width=True):
                    ok_mail, msg_mail = envoyer_email_alerte(email_dest, alertes_detectees)
                    if ok_mail:
                        st.success(msg_mail)
                    else:
                        st.info(msg_mail)

    st.subheader("📊 Tableau 1 : Timing, Momentum & Score Algorithmique (EUR & US)")
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
        dec_html = f"<span class='b-green'>{dec}</span>" if "ACHAT FORT" in dec else (f"<span class='b-blue'>{dec}</span>" if "ACCUMULATION" in dec else (f"<span class='b-red'>{dec}</span>" if "ALLÈGEMENT" in dec else f"<span class='b-neutral'>{dec}</span>"))

        rsi_v = d["RSI"]
        rsi_badge = f"<span class='b-green'>{rsi_v}</span>" if rsi_v <= 35 else (f"<span class='b-red'>{rsi_v}</span>" if rsi_v >= 70 else f"<b>{rsi_v}</b>")

        stoch_v = int(d["Stoch"])
        stoch_badge = f"<span class='b-green'>{stoch_v}%</span>" if stoch_v <= 20 else (f"<span class='b-red'>{stoch_v}%</span>" if stoch_v >= 80 else f"{stoch_v}%")

        html_t1 += f"""
        <tr>
            <td class="r-name">{d['Actif']}</td>
            <td><b>{d['Prix']}</b> <span style="opacity:0.7; font-size:0.86em;">({d['PrixEUR']})</span></td>
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
        html_t4 = "<table class='r-table'><thead><tr><th style='text-align: left;'>Actif</th><th>Support 30J</th><th>Cours Actuel</th><th>Résistance 30J</th><th>Bandes de Bollinger (20J)</th><th>Oscillateur Stochastique</th><th>Volatilité ATR (14J)</th></tr></thead><tbody>"
        for d in donnees_t4:
            html_t4 += f"<tr><td class='r-name'>{d['Actif']}</td><td style='color: #2ecc71; font-weight:700;'>{d['Support 30J']}</td><td><b>{d['Prix']}</b></td><td style='color: #e74c3c; font-weight:700;'>{d['Résistance 30J']}</td><td>{d['Bollinger (20J)']}</td><td><span class='b-neutral'>{d['Stochastique']}</span></td><td><span class='b-purple'>{d['Volatilité ATR']}</span></td></tr>"
        html_t4 += "</tbody></table>"
        afficher_html(html_t4)

    with tab_div:
        html_t3 = "<table class='r-table'><thead><tr><th style='text-align: left;'>Actif</th><th>Dividende / Action (Origine & €)</th><th>Rendement Brut</th><th>Payout Ratio</th><th>Croissance 5A</th><th>Indice de Sûreté</th></tr></thead><tbody>"
        for d in donnees_t3:
            html_t3 += f"<tr><td class='r-name'>{d['Actif']}</td><td><b>{d['Div/Act']}</b></td><td style='color: #2ecc71; font-weight:800;'>{d['Rendement']}</td><td>{d['Payout']}</td><td><b>{d['Croissance 5a']}</b></td><td><span class='b-green'>{d['Sûreté']}</span></td></tr>"
        html_t3 += "</tbody></table>"
        afficher_html(html_t3)


# ------------------------------------------------------------------------------
# ONGLET 2 : PORTEFEUILLE, RÉPARTITION SECTORIELLE & TRAJECTOIRE BOURSIÈRE
# ------------------------------------------------------------------------------
with onglet_portefeuille:
    st.subheader("💼 Gestionnaire de Portefeuille Multidevises & Fiscalité")

    with st.expander("✏️ Saisir ou modifier mes actions détenues (Quantité & PRU)", expanded=False):
        st.markdown("#### 💶 Poche Liquidités (Espèces disponibles)")
        pru_esp_defaut = st.session_state["portefeuille"].get("Espèces", {}).get("pru", 0.0)
        montant_especes = st.number_input("Montant Espèces (€)", min_value=0.0, value=float(st.session_state.get("pru_Espèces", pru_esp_defaut)), step=50.0, key="pru_Espèces")

        nouveau_portefeuille_temp = {}
        if montant_especes > 0:
            nouveau_portefeuille_temp["Espèces"] = {"qte": 1, "pru": montant_especes}
            st.session_state["qte_Espèces"] = 1

        st.markdown("---")
        st.markdown("#### 📈 Mes Positions Actions (Saisissez le PRU dans la devise de l'action : € ou $)")
        cols_saisie = st.columns(3)

        for idx, (nom_act, info_act) in enumerate(WATCHLIST_DEFAUT.items()):
            col_active = cols_saisie[idx % 3]
            devise_a = info_act.get("devise", "EUR")
            with col_active:
                st.markdown(f"**{nom_act}** *({devise_a})*")
                qte_defaut = st.session_state["portefeuille"].get(nom_act, {}).get("qte", 0)
                pru_defaut = st.session_state["portefeuille"].get(nom_act, {}).get("pru", float(info_act["prix_cible"]))

                qte_saisie = st.number_input(f"Quantité ({nom_act})", min_value=0, value=int(st.session_state.get(f"qte_{nom_act}", qte_defaut)), key=f"qte_{nom_act}")
                pru_saisi = st.number_input(f"PRU Unitaire ({devise_a})", min_value=0.0, value=float(st.session_state.get(f"pru_{nom_act}", pru_defaut)), step=0.5, key=f"pru_{nom_act}")

                if qte_saisie > 0:
                    nouveau_portefeuille_temp[nom_act] = {"qte": qte_saisie, "pru": pru_saisi}
                st.markdown("---")

        st.session_state["portefeuille"] = nouveau_portefeuille_temp
        if st.button("💾 Enregistrer mon portefeuille & créer un Snapshot Cloud", type="primary", use_container_width=True):
            sauvegarder_dans_cloud()

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

    if not portefeuille_utilisateur:
        st.warning("Votre portefeuille est vide. Ouvrez le volet ci-dessus pour renseigner vos lignes.")
    else:
        mode_fiscal_pea = st.radio(
            "⚖️ Mode de calcul fiscal des dividendes :",
            [
                "Réinvestissement en PEA (0% d'impôt sur les actions EUR en PEA, -30% Flat Tax/Retenue US sur CTO USD)",
                "Retrait en poche : PEA > 5 ans (-17.2% PS sur EUR) & CTO (-30% Flat Tax sur USD)",
            ],
            horizontal=True,
        )
        taux_net_eur = 1.0 if "Réinvestissement" in mode_fiscal_pea else (1.0 - 0.172)
        taux_net_usd = 0.70

        lignes_detaillees = []

        for nom_act, data_pos in portefeuille_utilisateur.items():
            if nom_act == "Espèces":
                val_especes = float(data_pos["pru"])
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

            qte = float(data_pos["qte"])
            pru = float(data_pos["pru"])
            info_act = WATCHLIST_DEFAUT[nom_act]
            devise = info_act.get("devise", "EUR")
            sym = "$" if devise == "USD" else "€"
            env_label = "CTO US" if devise == "USD" else "PEA"
            facteur = (1.0 / TAUX_USD_EUR) if devise == "USD" else 1.0
            prix_jour = float(prix_temps_reel.get(nom_act, info_act["prix_cible"]))

            val_ligne_eur = qte * prix_jour * facteur
            cout_ligne_eur = qte * pru * facteur
            pv_eur = val_ligne_eur - cout_ligne_eur
            pv_pct = (pv_eur / cout_ligne_eur * 100) if cout_ligne_eur > 0 else 0.0
            div_brut_eur = qte * float(info_act["div_eur"]) * facteur
            div_net_eur = div_brut_eur * (taux_net_usd if devise == "USD" else taux_net_eur)

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
            })

        lignes_triees = sorted(lignes_detaillees, key=lambda x: x["val_eur"], reverse=True)

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

        html_kpi_port = f"""
        <div class="argon-grid">
            <div class="argon-card">
                <div class="argon-title">💼 Valorisation Totale (€)</div>
                <div class="argon-val">{valeur_totale_portefeuille:,.2f} €</div>
                <div class="argon-sub">Capital investi : <b>{cout_total_achat:,.2f} €</b></div>
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
            df_export = pd.DataFrame(lignes_export_csv)
            csv_bytes = df_export.to_csv(index=False, sep=";").encode("utf-8-sig")
            st.download_button(
                label="📥 Exporter Bilan CSV (Excel)",
                data=csv_bytes,
                file_name=f"Boursy_Portefeuille_{datetime.now().strftime('%Y-%m-%d')}.csv",
                mime="text/csv",
                use_container_width=True,
            )

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
                html_port += f"""
                <tr>
                    <td class="r-name">{l_item['nom_act']} <span class="b-neutral" style="font-size:0.75em;">{l_item['env_label']}</span></td>
                    <td><b>{l_item['qte']}</b></td>
                    <td>{l_item['pru']:.2f} {l_item['sym']} ➔ <b>{l_item['prix_jour']:.2f} {l_item['sym']}</b></td>
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
            st.vega_lite_chart(df_camembert, spec_camembert, use_container_width=True)

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
            st.subheader("🚀 Trajectoire Boursière au Fil du Temps")
            choix_horizon_courbe = st.radio(
                "Horizon boursier :",
                ["1 Mois", "6 Mois", "1 An", "3 Ans"],
                index=2,
                horizontal=True,
                label_visibility="collapsed",
            )
            map_jours = {"1 Mois": 22, "6 Mois": 126, "1 An": 252, "3 Ans": 750}
            nb_j_cible = map_jours[choix_horizon_courbe]

            longueurs_dispo = [
                len(historiques_prix[nom_a])
                for nom_a in portefeuille_utilisateur
                if nom_a != "Espèces" and nom_a in historiques_prix and len(historiques_prix[nom_a]) > 1
            ]
            nb_jours_reels = min(nb_j_cible, min(longueurs_dispo)) if longueurs_dispo else 30
            dates_bourse = pd.bdate_range(end=datetime.now(), periods=nb_jours_reels)
            pas_echantillon = 3 if nb_jours_reels > 300 else 1

            val_esp_fixe = float(portefeuille_utilisateur.get("Espèces", {}).get("pru", 0.0)) if "Espèces" in portefeuille_utilisateur else 0.0
            donnees_courbe_reelle = []
            valeurs_quotidiennes = []

            for idx_j in range(0, nb_jours_reels, pas_echantillon):
                offset_fin = idx_j - nb_jours_reels
                val_jour_eur = val_esp_fixe

                for nom_a, d_pos in portefeuille_utilisateur.items():
                    if nom_a == "Espèces" or nom_a not in WATCHLIST_DEFAUT:
                        continue
                    q_a = float(d_pos["qte"])
                    dev_a = WATCHLIST_DEFAUT[nom_a].get("devise", "EUR")
                    fact_a = (1.0 / TAUX_USD_EUR) if dev_a == "USD" else 1.0
                    serie_c = historiques_prix.get(nom_a, [])
                    if serie_c:
                        p_hist = serie_c[offset_fin] if abs(offset_fin) <= len(serie_c) else serie_c[0]
                    else:
                        p_hist = float(prix_temps_reel.get(nom_a, WATCHLIST_DEFAUT[nom_a]["prix_cible"]))
                    val_jour_eur += q_a * p_hist * fact_a

                if idx_j >= nb_jours_reels - pas_echantillon:
                    val_jour_eur = valeur_totale_portefeuille

                date_iso = dates_bourse[idx_j].strftime("%Y-%m-%d")
                date_fr = dates_bourse[idx_j].strftime("%d/%m/%Y")
                ecart_pru_jour = round(val_jour_eur - cout_total_achat, 2)
                valeurs_quotidiennes.append((date_fr, round(val_jour_eur, 2)))

                donnees_courbe_reelle.append({
                    "Date": date_iso,
                    "DateFR": date_fr,
                    "Série": "Valorisation Boursière (€)",
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

            df_courbe_reelle = pd.DataFrame(donnees_courbe_reelle)

            spec_courbe_bourse = {
                "height": 275,
                "layer": [
                    {
                        "mark": {"type": "area", "opacity": 0.18, "interpolate": "monotone"},
                        "encoding": {
                            "x": {"field": "Date", "type": "temporal", "axis": {"title": None, "format": "%b %Y", "grid": False}},
                            "y": {"field": "Montant (€)", "type": "quantitative", "scale": {"zero": False, "padding": 18}, "axis": {"title": "Valeur (€)", "format": ",.0f"}},
                            "color": {
                                "field": "Série",
                                "type": "nominal",
                                "scale": {"domain": ["Valorisation Boursière (€)", "Capital Investi / PRU (€)"], "range": ["#2ecc71", "#3498db"]},
                                "legend": {"orient": "top", "title": None},
                            },
                        },
                    },
                    {
                        "mark": {"type": "line", "interpolate": "monotone"},
                        "encoding": {
                            "x": {"field": "Date", "type": "temporal"},
                            "y": {"field": "Montant (€)", "type": "quantitative", "scale": {"zero": False, "padding": 18}},
                            "color": {
                                "field": "Série",
                                "type": "nominal",
                                "scale": {"domain": ["Valorisation Boursière (€)", "Capital Investi / PRU (€)"], "range": ["#2ecc71", "#3498db"]},
                            },
                            "strokeDash": {
                                "field": "Série",
                                "type": "nominal",
                                "scale": {"domain": ["Valorisation Boursière (€)", "Capital Investi / PRU (€)"], "range": [[1, 0], [6, 4]]},
                                "legend": None,
                            },
                            "strokeWidth": {
                                "field": "Série",
                                "type": "nominal",
                                "scale": {"domain": ["Valorisation Boursière (€)", "Capital Investi / PRU (€)"], "range": [2.8, 2.0]},
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
            st.vega_lite_chart(df_courbe_reelle, spec_courbe_bourse, use_container_width=True)

            if valeurs_quotidiennes:
                pt_debut = valeurs_quotidiennes[0]
                pt_fin = valeurs_quotidiennes[-1]
                pt_haut = max(valeurs_quotidiennes, key=lambda x: x[1])
                pt_bas = min(valeurs_quotidiennes, key=lambda x: x[1])
                var_periode_eur = pt_fin[1] - pt_debut[1]
                var_periode_pct = (var_periode_eur / pt_debut[1] * 100.0) if pt_debut[1] > 0 else 0.0
                c_var_p = "#2ecc71" if var_periode_eur >= 0 else "#e74c3c"

                html_bilan_traj = f"""
                <div style="background:rgba(128,128,128,0.04); padding:14px; border-radius:12px; border:1px solid rgba(128,128,128,0.18);">
                    <div style="font-size:0.82em; font-weight:800; text-transform:uppercase; opacity:0.75; margin-bottom:9px;">⚡ Dynamique Boursière sur {choix_horizon_courbe}</div>
                    <div style="display:flex; justify-content:space-between; padding:5px 0; border-bottom:1px solid rgba(128,128,128,0.12); font-size:0.88em;">
                        <span>📈 <b>Variation sur {choix_horizon_courbe}</b></span>
                        <span style="color:{c_var_p}; font-weight:800;">{var_periode_eur:+,.0f} € ({var_periode_pct:+.1f}%)</span>
                    </div>
                    <div style="display:flex; justify-content:space-between; padding:5px 0; border-bottom:1px solid rgba(128,128,128,0.12); font-size:0.88em;">
                        <span>🏔️ <b>Pic le plus haut</b> ({pt_haut[0]})</span>
                        <span style="color:#2ecc71; font-weight:800;">{pt_haut[1]:,.0f} €</span>
                    </div>
                    <div style="display:flex; justify-content:space-between; padding:5px 0; border-bottom:1px solid rgba(128,128,128,0.12); font-size:0.88em;">
                        <span>🛡️ <b>Point le plus bas</b> ({pt_bas[0]})</span>
                        <span style="color:#3498db; font-weight:800;">{pt_bas[1]:,.0f} €</span>
                    </div>
                    <div style="display:flex; justify-content:space-between; padding:5px 0; font-size:0.88em;">
                        <span>🎯 <b>Écart actuel vs PRU ({cout_total_achat:,.0f} €)</b></span>
                        <span style="color:{c_pv}; font-weight:800;">{plus_value_globale:+,.0f} € ({plus_value_pct:+.1f}%)</span>
                    </div>
                </div>
                """
                afficher_html(html_bilan_traj)


# ------------------------------------------------------------------------------
# ONGLET 3 : JAUGE D'OBJECTIF DE RENTE, CALENDRIER 12 MOIS & BOULE DE NEIGE
# ------------------------------------------------------------------------------
with onglet_dividendes:
    st.subheader("📅 Calendrier Annuel des Dividendes & Simulateur Effet Boule de Neige")

    if not portefeuille_utilisateur:
        st.warning("Ajoutez des actions dans votre portefeuille pour générer votre calendrier de revenus passifs.")
    else:
        mois_ordre = ["Jan", "Fév", "Mar", "Avr", "Mai", "Juin", "Juil", "Août", "Sep", "Oct", "Nov", "Déc"]
        noms_mois_complets = {
            "Jan": "Janvier", "Fév": "Février", "Mar": "Mars", "Avr": "Avril",
            "Mai": "Mai", "Juin": "Juin", "Juil": "Juillet", "Août": "Août",
            "Sep": "Septembre", "Oct": "Octobre", "Nov": "Novembre", "Déc": "Décembre"
        }
        revenus_par_mois = {m: 0.0 for m in mois_ordre}
        details_par_mois = {m: [] for m in mois_ordre}
        total_annuel_div = 0.0

        for nom_act, data_pos in portefeuille_utilisateur.items():
            if nom_act == "Espèces" or nom_act not in WATCHLIST_DEFAUT:
                continue
            qte = float(data_pos["qte"])
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
        st.vega_lite_chart(df_bar_div, spec_bar_div, use_container_width=True)

        st.markdown("---")
        st.markdown("#### ❄️ Simulateur Interactif d'Effet Boule de Neige (DCA + Dividendes Réinvestis)")

        rendement_actuel_pf = (total_annuel_div / valeur_totale_portefeuille * 100.0) if valeur_totale_portefeuille > 0 else 4.8
        rendement_defaut_slider = float(max(1.5, min(10.0, round(rendement_actuel_pf, 1))))

        col_sl1, col_sl2, col_sl3, col_sl4 = st.columns(4)
        with col_sl1:
            horizon_annees = st.slider("⏳ Horizon (Années)", min_value=5, max_value=30, value=15, step=1)
        with col_sl2:
            dca_simule = st.slider("💶 Apport DCA Mensuel (€)", min_value=0, max_value=3000, value=int(BUDGET_MENSUEL), step=50)
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

    quota_utilise = st.session_state.get("quota_ia_utilise", 0)
    quota_restant = max(0, quota_ia_max - quota_utilise)

    nb_lignes_actions = sum(1 for k in portefeuille_utilisateur if k != "Espèces" and k in WATCHLIST_DEFAUT)
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
            <div class="argon-sub">Météo VIX ({vix_val:.1f}) & EUR/USD ({TAUX_USD_EUR:.3f}) actifs</div>
        </div>
    </div>
    """
    afficher_html(html_ia_header)

    top_opps_noms = [f"<b>{c['nom']}</b> ({c['score']}/100)" for c in candidats_dca_top2]
    texte_opps_moment = " et ".join(top_opps_noms) if top_opps_noms else "aucune valeur en signal fort actuellement"
    etat_conc_court = "bien équilibré" if poids_max_ligne <= 30 else f"concentré sur <b>{nom_max_ligne}</b> ({poids_max_ligne:.1f}%)"

    html_phrase_flash = f"""
    <div class="ia-flash">
        💡 <b>Synthèse Flash du Coach :</b> Votre portefeuille de <b>{valeur_totale_portefeuille:,.0f} €</b> ({plus_value_pct:+.1f}%) est {etat_conc_court} et génère <b>{dividendes_nets_totaux_eur:,.0f} € net/an</b> ({dividendes_nets_totaux_eur/12.0:.1f} €/mois), tandis que les meilleures opportunités DCA du moment sont {texte_opps_moment}.
    </div>
    """
    afficher_html(html_phrase_flash)

    def generer_audit_expert_hybride(question_utilisateur, code_audit=""):
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

        if code_audit == "AUDIT_1":
            return f"""### 🔍 Audit Complet 360° & Optimisation Fiscale

#### 1. Bilan Patrimonial & Performance Globale
* **Valorisation Totale :** Votre portefeuille s'élève à **{valeur_totale_portefeuille:,.2f} €** pour un capital investi de **{cout_total_achat:,.2f} €**, soit une performance latente de **{plus_value_glob:+,.2f} € ({pv_pct_glob:+.2f}%)**.
* **Score de Santé Global :** **{note_sante_pf}/100** avec **{nb_lignes_actions} ligne(s) active(s)** répartie(s) sur **{len(repartition_secteurs)} secteur(s)**.
* **Vos Piliers Principaux (par poids décroissant) :** {', '.join(top_3_lignes) if top_3_lignes else 'Aucune ligne enregistrée'}.

#### 2. Analyse de Concentration & PRU
* **Concentration Maximale :** Votre première ligne (**{nom_max_ligne}**) pèse **{poids_max_ligne:.1f}%** de votre patrimoine. {'✅ Excellente maîtrise du risque (< 30%).' if poids_max_ligne <= 30 else '⚠️ Attention : cette ligne dépasse le seuil prudentiel de 30%. Privilégiez le renforcement de vos lignes secondaires lors de vos prochains DCA.'}
* **Qualité des Points d'Entrée (PRU) :** Les lignes affichant une moins-value latente mais un **Payout Ratio sain (< 65%)** constituent vos meilleures opportunités de moyennage à la baisse pour booster votre rendement sur coût d'achat (*Yield on Cost*).

#### 3. Bilan Fiscal PEA (EUR) vs CTO (USD)
* **Exposition Devises :** **{exposition_eur:,.0f} € en zone Euro (PEA)** contre **{exposition_usd:,.0f} € en Dollars US (CTO)**.
* **Efficience Fiscale des Dividendes :** Vos actions produisent **{dividendes_bruts_totaux_eur:,.2f} € brut/an**, soit **{dividendes_nets_totaux_eur:,.2f} € net/an ({rente_mens_nette:.2f} € net/mois)**. En logeant vos valeurs européennes de rendement sur PEA, vous économisez **100 % d'impôt** tant que les dividendes sont réinvestis dans l'enveloppe.

*⚖️ Rappel : Analyse statistique et pédagogique générée par le moteur Boursy 2.0 (Non-CIF).*"""

        elif code_audit == "AUDIT_2":
            achats_txt = "\n".join(
                f"* **{item['nom']} ({item['devise']})** : Acheter **{achats_simules[item['nom']]} action(s)** à `{item['prix_eur']:.2f} €` (Score : **{item['score']}/100**, Gain de rente : **+{achats_simules[item['nom']]*item['div_eur']:.2f} €/an**)"
                for item in candidats_dca_top2 if achats_simules.get(item["nom"], 0) > 0
            )
            if not achats_txt:
                achats_txt = "* Aucune valeur ne valide simultanément un score ≥ 45/100 et un signal EMA haussier/neutre aujourd'hui."
            return f"""### 🛒 Plan d'Action DCA du Mois ({BUDGET_MENSUEL:.0f} €) selon le VIX & le RSI

#### 1. Lecture de la Météo des Marchés
* **Indice de nervosité VIX :** **{vix_val:.1f}** ({etat_vix}) | **CAC 40 :** {cac_str} | **S&P 500 :** {sp_str}.
* **Stratégie de Timing :** {'Avec un VIX élevé, la peur domine le marché : c est le moment idéal pour déployer 100 % de votre enveloppe DCA sur les valeurs décotées.' if vix_val >= 22 else 'Dans ce marché calme à normal, concentrez strictement vos achats sur les 1 ou 2 meilleures valeurs dont le RSI (14J) est inférieur à 45 ou sous votre Prix Cible.'}

#### 2. Top 3 des Signaux Techniques du Jour
* {chr(10).join('* ' + s for s in top_3_radar)}

#### 3. Répartition Condensée de votre Enveloppe de {BUDGET_MENSUEL:.0f} € (Max 2 lignes)
{achats_txt}
* **Total investi ce mois-ci :** **{montant_investi_dca:.2f} €** (Liquidités restantes pour le mois suivant : **{budget_courant:.2f} €**)
* **Nouveaux dividendes annuels acquis :** **+{montant_tot_div_dca:.2f} € / an**.

*⚖️ Rappel : Analyse statistique et pédagogique générée par le moteur Boursy 2.0 (Non-CIF).*"""

        elif code_audit == "AUDIT_3":
            return f"""### 🌍 Arbitrage Stratégique : PEA (EUR) vs Actions US ($)

#### 1. Analyse du Taux de Change EUR/USD
* **Parité actuelle :** **1 € = {TAUX_USD_EUR:.4f} $** (soit **1 $ = {1/TAUX_USD_EUR:.4f} €**).
* **Impact Devises :** {'L Euro est actuellement solide face au Dollar (> 1.08 $), ce qui offre un point d entrée avantageux pour convertir des Euros vers des actifs américains en CTO.' if TAUX_USD_EUR >= 1.08 else 'Le Dollar est actuellement fort face à l Euro : privilégiez en priorité le renforcement de vos pépites européennes en PEA pour éviter d acheter du Dollar au plus haut.'}

#### 2. Complémentarité Rendement Européen (PEA) vs Croissance US (CTO)
* **Poche Socle PEA (TotalEnergies, Air Liquide, AXA, Rubis, Vinci...) :** Idéale pour maximiser le **flux de dividendes immédiat (4 % à 8 %)** sans frottement fiscal lors du réinvestissement.
* **Poche Accélérateur US (Microsoft, Apple, Realty Income, Coca-Cola...) :** Apporte une **croissance séculaire à 2 chiffres** et des versements trimestriels ou mensuels qui lissent votre calendrier de rente.
* **Recommandation d'équilibre :** Visez une répartition cible de **75 % à 85 % sur votre PEA** (jusqu'au plafond de 150 000 € de versements) et **15 % à 25 % sur les géants US** lors des replis de leur RSI sous 40.

*⚖️ Rappel : Analyse statistique et pédagogique générée par le moteur Boursy 2.0 (Non-CIF).*"""

        elif code_audit == "AUDIT_4":
            choc_20 = valeur_totale_portefeuille * 0.80
            return f"""### 🛡️ Stress-Test, Gestion des Risques & Diversification

#### 1. Simulation de Krach Boursier (-20 % sur les marchés)
* **Valorisation après choc de -20 % :** Votre portefeuille passerait temporairement de **{valeur_totale_portefeuille:,.0f} €** à **{choc_20:,.0f} €** (soit un repli latent de `-{valeur_totale_portefeuille * 0.20:,.0f} €`).
* **Résilience de votre Rente Passive :** Même en cas de baisse de 20 % des cours boursiers, **votre rente de dividendes ({dividendes_bruts_totaux_eur:,.2f} €/an) dépend du nombre d'actions détenues** et non des fluctuations quotidiennes du marché ! Mieux encore : votre DCA mensuel de **{BUDGET_MENSUEL:.0f} €** achètera **25 % d'actions en plus** pendant la baisse.

#### 2. Diagnostic de Concentration Sectorielle
* **Ligne numéro 1 :** **{nom_max_ligne}** représente **{poids_max_ligne:.1f}%** du portefeuille.
* **Nombre de secteurs couverts :** **{len(repartition_secteurs)} secteur(s)**.
* **Pistes de sécurisation :** Assurez-vous qu'aucun secteur cyclique (Banque, Énergie, Luxe) ne dépasse **35 %** du total. Renforcez les secteurs défensifs (**Santé via Sanofi / J&J**, **Gaz industriels via Air Liquide**, **Consommation de base**) pour amortir la volatilité (ATR).

*⚖️ Rappel : Analyse statistique et pédagogique générée par le moteur Boursy 2.0 (Non-CIF).*"""

        elif code_audit == "AUDIT_5":
            manque_100 = max(0.0, (100.0 * 12) - dividendes_nets_totaux_eur)
            cap_requis_100 = manque_100 / 0.055
            return f"""### 💵 Optimisation de la Rente & Accélération Boule de Neige

#### 1. Trajectoire Actuelle de vos Revenus Passifs
* **Rente Annuelle Actuelle :** **{dividendes_bruts_totaux_eur:,.2f} € brut / an** (**{dividendes_nets_totaux_eur:,.2f} € net / an**).
* **Revenu Mensuel Lissé :** **{rente_mens_nette:,.2f} € net / mois** (couvrant déjà **{taux_couverture_dca:.1f}%** de votre effort d'épargne DCA annuel).

#### 2. Feuille de Route vers le Palier des 100 € / mois (1 200 € / an)
* **Écart restant à combler :** Il vous manque **{manque_100:,.2f} € de dividendes annuels** pour franchir le cap symbolique des **100 € / mois**.
* **Capital additionnel nécessaire (à 5,5 % de rendement moyen) :** Environ **{cap_requis_100:,.0f} €**, soit environ **{max(1, int(cap_requis_100 / max(1, BUDGET_MENSUEL + rente_mens_nette)))} mois** avec votre DCA de **{BUDGET_MENSUEL:.0f} €/mois** et le réinvestissement intégral de vos dividendes.

#### 3. Comment lisser vos 12 mois de versements
* **Action concrète :** En Europe, beaucoup de sociétés paient en **Mai/Juin**. Pour encaisser des dividendes chaque mois de l'année, appuyez-vous sur **TotalEnergies** (Jan/Avr/Juil/Oct), **Pernod Ricard / Vinci** (Avr/Juil/Nov), ou des valeurs trimestrielles/mensuelles comme **Realty Income** et **Microsoft**.

*⚖️ Rappel : Analyse statistique et pédagogique générée par le moteur Boursy 2.0 (Non-CIF).*"""

        else:
            q_low = question_utilisateur.lower()
            focus_actions = []
            for d in donnees_t1:
                nom_b = d["NomBrut"]
                if nom_b.lower() in q_low:
                    info_w = WATCHLIST_DEFAUT.get(nom_b, {})
                    pos_pf = portefeuille_utilisateur.get(nom_b)
                    txt_pf = f"Détenue en portefeuille (**{pos_pf['qte']} actions** avec un PRU de **{pos_pf['pru']}**)" if pos_pf else "Non détenue actuellement en portefeuille"
                    focus_actions.append(
                        f"* **{d['Actif']}** : Cours actuel **{d['Prix']}** | Prix Cible : **{d['Prix Cible']}** ({d['Écart Cible (%)']}) | "
                        f"RSI : **{d['RSI']}** | Stochastique : **{d['Stoch']}%** | Signal EMA 2/12 : **{d['EMA 2/12']}** | "
                        f"Rendement : **{(info_w.get('div_eur',0)/ max(0.01, prix_temps_reel.get(nom_b, 1))*100):.2f}%** | "
                        f"Score Algo : **{d['Score']}/100 ({d['Décision']})** — *{txt_pf}*."
                    )

            bloc_focus = "\n".join(focus_actions) if focus_actions else "* Voici les 3 meilleures opportunités détectées sur votre radar aujourd'hui :\n  * " + "\n  * ".join(top_3_radar)

            return f"""### 🧠 Réponse Personnalisée de votre Coach IA 2.0

**Votre question :** *« {question_utilisateur} »*

#### 1. Analyse Technique & Fondamentale en Direct
{bloc_focus}

#### 2. Recommandation Stratégique par rapport à votre Portefeuille ({valeur_totale_portefeuille:,.0f} €)
* **Discipline de Prix Cible & PRU :** Tant que le cours d'une action est **inférieur à votre Prix Cible** (ou inférieur à votre PRU actuel) avec un **RSI < 45** et un **Score ≥ 50/100**, le renforcement progressif via votre enveloppe DCA de **{BUDGET_MENSUEL:.0f} €/mois** est optimal.
* **Gestion du Timing :** Si le titre affiche un RSI supérieur à 65 ou dépasse nettement son objectif de cours, patientez sur un repli vers le **Support 30J** ou la **Borne Basse de Bollinger** avant d'exécuter votre ordre.

*⚖️ Rappel : Analyse statistique et pédagogique générée par le moteur Boursy 2.0 (Non-CIF).*"""

    def appeler_gemini_coach(question_utilisateur, code_audit=""):
        cle_gemini = ""
        if hasattr(st, "secrets"):
            for nom_secret in ["GEMINI_API_KEY", "GOOGLE_API_KEY", "GEMINI_KEY"]:
                val_s = str(st.secrets.get(nom_secret, "")).strip().strip('"').strip("'")
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
        prompt_complet = f"""Tu es Boursy Coach IA 2.0, un expert patrimonial et boursier de haut niveau spécialisé dans les stratégies PEA, CTO US et dividendes croissants en DCA.
Voici les données exactes en temps réel du portefeuille de l'utilisateur :
- Météo des marchés : CAC 40 = {cac_str}, S&P 500 = {sp_str}, VIX = {vix_val:.1f} ({etat_vix})
- Taux de change EUR/USD : 1 € = {TAUX_USD_EUR:.4f} $
- Valorisation totale : {valeur_totale_portefeuille:.2f} € (Capital investi : {cout_total_achat:.2f} €, Plus-value : {plus_value_glob:+.2f} €)
- Rente annuelle : {dividendes_bruts_totaux_eur:.2f} € brut / {dividendes_nets_totaux_eur:.2f} € net par an (soit {dividendes_nets_totaux_eur/12:.2f} € net/mois)
- Enveloppe DCA mensuelle : {BUDGET_MENSUEL:.0f} € / mois (condensée sur 1 à 2 lignes max)
- Détail des lignes du portefeuille (triées par poids décroissant) :
{chr(10).join(resume_pf) if resume_pf else 'Portefeuille vide'}
- Signaux techniques et fondamentaux du Radar Boursy aujourd'hui :
{chr(10).join(resume_radar)}

Mission demandée par l'utilisateur : {question_utilisateur}

Réponds en français avec une structure claire (titres, puces, chiffres précis tirés de son portefeuille, points forts, points de vigilance et plan d'action concret). Rappelle discrètement en fin de message qu'il s'agit d'un audit pédagogique et statistique (non-CIF).
"""
        modeles_candidats = []
        try:
            url_list = f"https://generativelanguage.googleapis.com/v1beta/models?key={cle_gemini}"
            req_list = urllib.request.Request(url_list, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req_list, timeout=8) as resp_l:
                data_l = json.loads(resp_l.read().decode("utf-8"))
                for m_info in data_l.get("models", []):
                    methodes = m_info.get("supportedGenerationMethods", [])
                    nom_m = m_info.get("name", "").replace("models/", "")
                    if "generateContent" in methodes and "gemini" in nom_m:
                        modeles_candidats.append(nom_m)
        except Exception:
            pass

        priorite_modeles = [
            "gemini-2.5-flash",
            "gemini-2.0-flash",
            "gemini-2.0-flash-lite",
            "gemini-1.5-flash",
            "gemini-1.5-flash-latest",
            "gemini-1.5-pro",
        ]
        for pm in priorite_modeles:
            if pm not in modeles_candidats:
                modeles_candidats.append(pm)

        modeles_ordonnes = sorted(
            modeles_candidats,
            key=lambda x: (0 if "2.5-flash" in x else (1 if "2.0-flash" in x else (2 if "flash" in x else 3)))
        )

        for mod in modeles_ordonnes[:5]:
            try:
                url_api = f"https://generativelanguage.googleapis.com/v1beta/models/{mod}:generateContent?key={cle_gemini}"
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

    if col_ia1.button("🔍 1. Audit Complet 360° & Fiscalité", use_container_width=True):
        titre_audit = "Audit Complet 360° & Fiscalité"
        code_audit_choisi = "AUDIT_1"
        prompt_choisi = "Réalise un audit 360° complet de mon portefeuille : équilibre sectoriel, exposition PEA (EUR) vs CTO (USD), analyse de mes PRU par rapport aux cours actuels, et optimisation fiscale de ma rente."
    if col_ia2.button("🛒 2. Plan d'Action DCA du Mois (VIX & RSI)", use_container_width=True):
        titre_audit = "Plan d'Action DCA du Mois"
        code_audit_choisi = "AUDIT_2"
        prompt_choisi = f"Compte tenu du VIX actuel ({vix_val:.1f}) et des indicateurs techniques du radar (RSI, Stochastique, EMA 2/12, écart au prix cible), comment dois-je répartir précisément mon budget DCA de {BUDGET_MENSUEL:.0f} € sur 1 ou 2 valeurs maximum ce mois-ci ?"
    if col_ia3.button("🌍 3. Arbitrage PEA (EUR) vs Actions US ($)", use_container_width=True):
        titre_audit = "Arbitrage PEA (EUR) vs Actions US ($)"
        code_audit_choisi = "AUDIT_3"
        prompt_choisi = "Analyse la pertinence d'arbitrer ou de renforcer mes valeurs européennes de rendement en PEA face aux géants américains en CTO compte tenu de la parité EUR/USD actuelle et de mes lignes."

    col_ia4, col_ia5 = st.columns(2)
    if col_ia4.button("🛡️ 4. Stress-Test, Risques & Diversification", use_container_width=True):
        titre_audit = "Stress-Test, Risques & Diversification"
        code_audit_choisi = "AUDIT_4"
        prompt_choisi = "Analyse les risques de concentration de mon portefeuille (poids de mes plus grosses lignes et secteurs dominants), fais un stress-test en cas de baisse de marché de 20% et donne-moi des pistes concrètes de diversification."
    if col_ia5.button("💵 5. Optimisation de la Rente & Boule de Neige", use_container_width=True):
        titre_audit = "Optimisation de la Rente & Calendrier"
        code_audit_choisi = "AUDIT_5"
        prompt_choisi = "Analyse la régularité de mes dividendes sur les 12 mois de l'année, identifie les mois creux à renforcer et propose une stratégie pour accélérer mon effet boule de neige vers 100 €/mois puis 500 €/mois de rente."

    st.markdown("---")
    col_q_input, col_q_btn, col_q_clear = st.columns([4, 1.3, 0.8])
    with col_q_input:
        question_libre = st.text_input(
            "💬 Posez une question personnalisée à votre Coach IA 2.0 :",
            placeholder="Ex: Que penses-tu de mon PRU sur Rubis et TotalEnergies ? À quel prix racheter Pernod Ricard ?",
            label_visibility="collapsed",
        )
    with col_q_btn:
        if st.button("✨ Lancer l'Analyse IA", type="primary", use_container_width=True):
            if question_libre.strip():
                titre_audit = f"Question libre : {question_libre.strip()}"
                code_audit_choisi = "LIBRE"
                prompt_choisi = question_libre.strip()
    with col_q_clear:
        if st.button("🗑️ Effacer", use_container_width=True):
            st.session_state["reponse_ia_coach"] = ""
            st.session_state["historique_chat_ia"] = []
            st.rerun()

    if prompt_choisi:
        if quota_restant <= 0:
            st.error("🔒 Vous avez atteint votre quota journalier d'analyses IA. Passez à l'offre Boursy Pro pour disposer de 15 audits par jour !")
        else:
            with st.spinner("🧠 Le Coach IA 2.0 analyse la météo des marchés, votre portefeuille et les indicateurs techniques en direct..."):
                reponse_texte = appeler_gemini_coach(prompt_choisi, code_audit_choisi)
                st.session_state["quota_ia_utilise"] = quota_utilise + 1
                st.session_state["reponse_ia_coach"] = reponse_texte
                st.session_state["historique_chat_ia"].insert(0, {
                    "heure": datetime.now().strftime("%H:%M"),
                    "titre": titre_audit,
                    "reponse": reponse_texte,
                })
                st.rerun()

    if st.session_state.get("reponse_ia_coach"):
        afficher_html("<div class='ia-box'><b>📋 Dernier Rapport d'Audit de votre Coach IA 2.0 :</b></div>")
        st.markdown(st.session_state["reponse_ia_coach"])

    if len(st.session_state.get("historique_chat_ia", [])) > 1:
        with st.expander(f"🕒 Consulter l'historique de vos {len(st.session_state['historique_chat_ia'])} analyses IA de la session", expanded=False):
            for idx_h, item_h in enumerate(st.session_state["historique_chat_ia"]):
                st.markdown(f"#### {idx_h + 1}. {item_h['titre']} *(à {item_h['heure']})*")
                st.markdown(item_h["reponse"])
                st.markdown("---")

# Footer & Mentions Légales
st.markdown("---")
with st.expander("⚖️ Mentions Légales, Fiscalité & Conditions Générales d'Utilisation (Non-CIF)"):
    st.caption(
        "**Avertissement légal :** La plateforme Boursy (`boursy.streamlit.app`) est un outil logiciel d'analyse statistique, "
        "technique et patrimoniale à vocation strictement pédagogique. Les scores algorithmiques, indicateurs (RSI, Stochastique, Bollinger, MACD, EMA) "
        "et réponses générées par l'intelligence artificielle ne constituent en aucun cas un Conseil en Investissement Financier (CIF) ni une incitation "
        "à l'achat ou à la vente d'instruments financiers. Les performances passées ne préjugent pas des performances futures."
    )
afficher_html("<div style='text-align: center; font-size: 0.82em; opacity: 0.72;'>⚖️ Boursy SaaS — Suite Boursière PEA, US & Dividendes | Version Argon Ultime Complète</div>")
 
