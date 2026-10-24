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
</style>
"""
afficher_html(STYLE_ARGON)

# ==============================================================================
# CONNEXION SUPABASE, STRIPE & EMAILS D'ALERTE
# ==============================================================================
@st.cache_resource
def init_supabase():
    try:
        url = st.secrets["SUPABASE_URL"]
        key = st.secrets["SUPABASE_KEY"]
        return create_client(url, key)
    except Exception:
        return None

supabase = init_supabase()

def verifier_abonnement_stripe(email_client):
    """Vérifie via l'API REST Stripe si l'email possède un abonnement actif."""
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
    """Envoie un email récapitulatif des alertes boursières via SMTP."""
    if not hasattr(st, "secrets"):
        return False, "Secrets Streamlit non disponibles."
    smtp_user = str(st.secrets.get("SMTP_EMAIL", "")).strip()
    smtp_pass = str(st.secrets.get("SMTP_PASSWORD", "")).strip()
    if not smtp_user or not smtp_pass:
        return False, "Pour activer l'envoi d'emails, ajoutez `SMTP_EMAIL` et `SMTP_PASSWORD` (mot de passe d'application Gmail) dans vos Secrets Streamlit."

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
    """Récupère le taux de change EUR/USD en direct via Yahoo Finance (1 EUR = X USD)."""
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
    """Récupère le niveau et la variation journalière d'un indice boursier."""
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
    "AXA": {"symbole": "CS.PA", "prix_cible": 32.0, "secteur": "Assurance", "div_eur": 1.98, "payout_ratio": 0.55, "croissance_5a": "+9.2%", "mois_div": ["Mai"], "devise": "EUR"},
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
    # Europe / PEA (EUR)
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
    # États-Unis / CTO (USD)
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
    val_reg = droite_regression[-1]
    ecart_pct = ((clotures[-1] - val_reg) / val_reg) * 100 if val_reg != 0 else 0.0
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
            • 🌍 <b>Suivi Multidevises (EUR / USD), Fiscalité Nette & Export Excel :</b> Conversion automatique en Euros (€) de vos valeurs.<br>
            • 🤖 <b>Coach IA 2.0 & Alertes Email :</b> Audits patrimoniaux, signaux de prix cible et calendrier de rente sur 12 mois.<br>
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

for nom, info in WATCHLIST.items():
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

    # --- ALGORITHME DE SCORING ÉLEVÉ (/100) ---
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

    donnees_t2.append({
        "Actif": f"{nom} ({devise})",
        "Prix": f"{prix_actuel:.2f} {symbole_devise}",
        "Tendance 3A": f"{val_reg:.2f} {symbole_devise}",
        "Écart %": f"{ecart_reg_pct:+.1f}%",
        "Statut Value": "🟢 FORTE DÉCOTE" if ecart_reg_pct <= -10 else ("🟡 SOUS-ÉVALUÉE" if ecart_reg_pct < 0 else "⚪ PRIX NORMAL / CHER"),
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

# Allocation DCA intelligente en Euros
candidats_tries = sorted(resultats_analysed, key=lambda x: x["score"], reverse=True)
budget_courant = BUDGET_MENSUEL
achats_simules = {item["nom"]: 0 for item in candidats_tries}

continuer = True
while continuer:
    continuer = False
    for item in candidats_tries:
        if budget_courant >= item["prix_eur"] and item["prix_eur"] > 0:
            achats_simules[item["nom"]] += 1
            budget_courant -= item["prix_eur"]
            continuer = True

montant_investi_dca = BUDGET_MENSUEL - budget_courant
montant_tot_div_dca = sum(achats_simules[item["nom"]] * item["div_eur"] for item in candidats_tries)

# ==============================================================================
# NAVIGATION PAR ONGLETS
# ==============================================================================
onglet_radar, onglet_portefeuille, onglet_dividendes, onglet_ia = st.tabs([
    "🔍 1. Radar, DCA & Alertes",
    "💼 2. Portefeuille, Fiscalité & Export CSV",
    "📅 3. Calendrier des Dividendes & Projection",
    "🤖 4. Coach & Audit IA 2.0 (Gemini)",
])

# ------------------------------------------------------------------------------
# ONGLET 1 : RADAR ALGORITHMIQUE, ALLOCATION DCA & CENTRE D'ALERTES EMAIL
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
            <div class="argon-sub">Généré par vos achats du mois</div>
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
        with st.expander(f"🛒 Plan d'Achat DCA du mois ({BUDGET_MENSUEL:.0f} €)", expanded=True):
            achats_retenus = [item for item in candidats_tries if achats_simules.get(item["nom"], 0) > 0]
            if not achats_retenus:
                st.info("Aucune action ne remplit actuellement les critères d'achat DCA.")
            else:
                html_dca = "<table class='r-table'><thead><tr><th style='text-align:left;'>Action</th><th>Score</th><th>Qté</th><th>Coût (€)</th><th>+Div/an</th></tr></thead><tbody>"
                for item in achats_retenus:
                    q_sim = achats_simules[item["nom"]]
                    cout_tot = q_sim * item["prix_eur"]
                    div_gagne = q_sim * item["div_eur"]
                    html_dca += f"<tr><td class='r-name'><b>{item['nom']}</b></td><td><span class='b-green'>{item['score']}</span></td><td><b>{q_sim}</b></td><td>{cout_tot:.1f} €</td><td style='color:#2ecc71; font-weight:700;'>+{div_gagne:.2f} €</td></tr>"
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
        html_t2 = "<table class='r-table'><thead><tr><th style='text-align: left;'>Actif</th><th>Cours Actuel</th><th>Tendance Linéaire 3A</th><th>Écart à la Tendance</th><th>Diagnostic Value</th></tr></thead><tbody>"
        for d in donnees_t2:
            st_val = d["Statut Value"]
            b_val = "b-green" if "DÉCOTE" in st_val else ("b-yellow" if "SOUS-ÉVALUÉE" in st_val else "b-neutral")
            html_t2 += f"<tr><td class='r-name'>{d['Actif']}</td><td><b>{d['Prix']}</b></td><td>{d['Tendance 3A']}</td><td><b>{d['Écart %']}</b></td><td><span class='{b_val}'>{st_val}</span></td></tr>"
        html_t2 += "</tbody></table>"
        afficher_html(html_t2)

        if droites_regression_dict:
            st.markdown("#### 📈 Visualisation du Canal de Régression Linéaire sur 3 Ans")
            act_choisie_graph = st.selectbox("Choisir une action à inspecter graphiquement :", list(droites_regression_dict.keys()))
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
# ONGLET 2 : PORTEFEUILLE, BILAN FISCAL NET (PEA/CTO) & EXPORT CSV
# ------------------------------------------------------------------------------
with onglet_portefeuille:
    st.subheader("💼 Gestionnaire de Portefeuille Multidevises, Fiscalité & Export")

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

        for idx, (nom_act, info_act) in enumerate(WATCHLIST.items()):
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
        taux_net_usd = 0.70  # Flat tax 30% (incluant crédit d'impôt retenue US 15%)

        valeur_totale_portefeuille = 0.0
        cout_total_achat = 0.0
        dividendes_bruts_totaux_eur = 0.0
        dividendes_nets_totaux_eur = 0.0
        repartition_secteurs = {}
        exposition_eur = 0.0
        exposition_usd = 0.0
        lignes_export_csv = []

        for nom_act, data_pos in portefeuille_utilisateur.items():
            if nom_act == "Espèces":
                val_especes = float(data_pos["pru"])
                valeur_totale_portefeuille += val_especes
                cout_total_achat += val_especes
                exposition_eur += val_especes
                repartition_secteurs["Liquidités (€)"] = val_especes
                lignes_export_csv.append({
                    "Actif": "Espèces", "Enveloppe": "Liquidités", "Devise": "EUR", "Quantite": 1,
                    "PRU_Devise": val_especes, "Cours_Actuel_Devise": val_especes,
                    "Valorisation_EUR": round(val_especes, 2), "Plus_Value_EUR": 0.0,
                    "Dividende_Brut_EUR": 0.0, "Dividende_Net_EUR": 0.0
                })
                continue

            if nom_act not in WATCHLIST:
                continue

            qte = float(data_pos["qte"])
            pru = float(data_pos["pru"])
            info_act = WATCHLIST[nom_act]
            devise = info_act.get("devise", "EUR")
            facteur = (1.0 / TAUX_USD_EUR) if devise == "USD" else 1.0
            prix_jour = float(prix_temps_reel.get(nom_act, info_act["prix_cible"]))

            val_ligne_eur = qte * prix_jour * facteur
            cout_ligne_eur = qte * pru * facteur
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

            lignes_export_csv.append({
                "Actif": nom_act,
                "Enveloppe": "CTO (US)" if devise == "USD" else "PEA (EUR)",
                "Devise": devise,
                "Quantite": int(qte),
                "PRU_Devise": round(pru, 2),
                "Cours_Actuel_Devise": round(prix_jour, 2),
                "Valorisation_EUR": round(val_ligne_eur, 2),
                "Plus_Value_EUR": round(val_ligne_eur - cout_ligne_eur, 2),
                "Dividende_Brut_EUR": round(div_brut_eur, 2),
                "Dividende_Net_EUR": round(div_net_eur, 2),
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
            st.subheader("📋 Détail de mes lignes & Fiscalité Nette (€)")
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

        html_port = "<table class='r-table'><thead><tr><th style='text-align: left;'>Actif (Enveloppe)</th><th>Qté</th><th>PRU ➔ Cours</th><th>Valorisation (€)</th><th>+/- Value (€ & %)</th><th>Div. Brut / Net (€)</th><th>Poids</th></tr></thead><tbody>"

        for nom_act, data_pos in portefeuille_utilisateur.items():
            if nom_act == "Espèces":
                v_esp = float(data_pos["pru"])
                poids_esp = (v_esp / valeur_totale_portefeuille * 100) if valeur_totale_portefeuille > 0 else 0
                html_port += f"<tr><td class='r-name'>💶 Espèces (Liquidités)</td><td>-</td><td>-</td><td><b>{v_esp:,.2f} €</b></td><td><span class='b-neutral'>0.00 €</span></td><td>-</td><td><b>{poids_esp:.1f}%</b></td></tr>"
                continue
            if nom_act not in WATCHLIST:
                continue
            qte = float(data_pos["qte"])
            pru = float(data_pos["pru"])
            info_act = WATCHLIST[nom_act]
            devise = info_act.get("devise", "EUR")
            sym = "$" if devise == "USD" else "€"
            env_label = "CTO US" if devise == "USD" else "PEA"
            facteur = (1.0 / TAUX_USD_EUR) if devise == "USD" else 1.0
            prix_jour = float(prix_temps_reel.get(nom_act, info_act["prix_cible"]))

            val_eur = qte * prix_jour * facteur
            cout_eur = qte * pru * facteur
            pv_eur = val_eur - cout_eur
            pv_pct = (pv_eur / cout_eur * 100) if cout_eur > 0 else 0.0
            div_brut_l = qte * float(info_act["div_eur"]) * facteur
            div_net_l = div_brut_l * (taux_net_usd if devise == "USD" else taux_net_eur)
            poids = (val_eur / valeur_totale_portefeuille * 100) if valeur_totale_portefeuille > 0 else 0.0
            b_pv = "b-green" if pv_eur >= 0 else "b-red"

            html_port += f"""
            <tr>
                <td class="r-name">{nom_act} <span class="b-neutral" style="font-size:0.75em;">{env_label}</span></td>
                <td><b>{int(qte)}</b></td>
                <td>{pru:.2f} {sym} ➔ <b>{prix_jour:.2f} {sym}</b></td>
                <td><b>{val_eur:,.2f} €</b></td>
                <td><span class="{b_pv}">{pv_eur:+,.2f} € ({pv_pct:+.1f}%)</span></td>
                <td><span style="opacity:0.75;">{div_brut_l:.1f} €</span> ➔ <b style="color:#2ecc71;">{div_net_l:.2f} € net</b></td>
                <td><b>{poids:.1f}%</b></td>
            </tr>
            """
        html_port += "</tbody></table>"
        afficher_html(html_port)

        col_sec, col_hist = st.columns(2)

        with col_sec:
            st.subheader("🍩 Répartition Sectorielle")
            html_sec = "<div style='background:rgba(128,128,128,0.04); padding:16px; border-radius:12px; border:1px solid rgba(128,128,128,0.18);'>"
            for sec, montant_s in sorted(repartition_secteurs.items(), key=lambda x: x[1], reverse=True):
                pct_s = (montant_s / valeur_totale_portefeuille * 100) if valeur_totale_portefeuille > 0 else 0
                c_sec = "#e74c3c" if pct_s > 35 else ("#f39c12" if pct_s > 25 else "#3498db")
                html_sec += f"""
                <div style="margin-bottom: 12px;">
                    <div style="display:flex; justify-content:space-between; font-size:0.9em; font-weight:700; margin-bottom:4px;">
                        <span>{sec}</span>
                        <span>{montant_s:,.0f} € ({pct_s:.1f}%)</span>
                    </div>
                    <div class="score-bg"><div style="width:{min(100, pct_s)}%; background:{c_sec}; height:100%;"></div></div>
                </div>
                """
            html_sec += "</div>"
            afficher_html(html_sec)

        with col_hist:
            st.subheader("📸 Évolution Patrimoniale (Snapshots Cloud)")
            if supabase and st.session_state["user"]:
                try:
                    res_h = supabase.table("portfolio_history").select("*").eq("user_id", str(st.session_state["user"].id)).order("date", desc=False).execute()
                    if res_h.data and len(res_h.data) >= 1:
                        df_h = pd.DataFrame(res_h.data)
                        df_h_chart = df_h.set_index("date")[["valorisation_pea", "capital_investi"]].rename(
                            columns={"valorisation_pea": "Valorisation Totale (€)", "capital_investi": "Capital Investi (€)"}
                        )
                        st.line_chart(df_h_chart)
                    else:
                        st.info("Cliquez sur « 💾 Sauver » dans la barre latérale pour enregistrer votre premier point d'historique Cloud.")
                except Exception:
                    st.info("Historique Cloud en attente de synchronisation.")
            else:
                st.info("Connectez-vous à votre compte pour visualiser la courbe d'évolution de votre patrimoine dans le temps.")


# ------------------------------------------------------------------------------
# ONGLET 3 : CALENDRIER DES DIVIDENDES SUR 12 MOIS & PROJECTION
# ------------------------------------------------------------------------------
with onglet_dividendes:
    st.subheader("📅 Calendrier Annuel des Dividendes & Effet Boule de Neige")

    if not portefeuille_utilisateur:
        st.warning("Ajoutez des actions dans votre portefeuille pour générer votre calendrier de revenus passifs.")
    else:
        mois_ordre = ["Jan", "Fév", "Mar", "Avr", "Mai", "Juin", "Juil", "Août", "Sep", "Oct", "Nov", "Déc"]
        revenus_par_mois = {m: 0.0 for m in mois_ordre}
        details_par_mois = {m: [] for m in mois_ordre}
        total_annuel_div = 0.0

        for nom_act, data_pos in portefeuille_utilisateur.items():
            if nom_act == "Espèces" or nom_act not in WATCHLIST:
                continue
            qte = float(data_pos["qte"])
            info_act = WATCHLIST[nom_act]
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
                        details_par_mois[m].append(f"{nom_act} ({montant_par_versement:.1f} €)")

        rente_mensuelle_moy = total_annuel_div / 12.0
        meilleur_mois = max(revenus_par_mois.items(), key=lambda x: x[1]) if total_annuel_div > 0 else ("Mai", 0.0)

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
                <div class="argon-sub">Lissé sur 12 mois</div>
            </div>
            <div class="argon-card">
                <div class="argon-title">🏆 Mois Record</div>
                <div class="argon-val">{meilleur_mois[0]} ({meilleur_mois[1]:.1f} €)</div>
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

        st.markdown("#### 🗓️ Répartition Mensuelle des Versements (Janvier à Décembre)")
        html_cal = "<table class='r-table'><thead><tr><th style='text-align:left;'>Mois</th><th>Montant Estimé (€)</th><th style='text-align:left;'>Détail des Entreprises Payeuses</th><th style='width:220px;'>Poids Mensuel</th></tr></thead><tbody>"
        max_m = max(revenus_par_mois.values()) if max(revenus_par_mois.values()) > 0 else 1.0
        for m in mois_ordre:
            val_m = revenus_par_mois[m]
            det_str = ", ".join(details_par_mois[m]) if details_par_mois[m] else "<span style='opacity:0.5;'>Aucun détachement</span>"
            pct_bar = (val_m / max_m * 100) if max_m > 0 else 0
            badge_m = f"<span class='b-green'>{val_m:.2f} €</span>" if val_m > 0 else "<span class='b-neutral'>0.00 €</span>"
            html_cal += f"""
            <tr>
                <td class="r-name">{m}</td>
                <td>{badge_m}</td>
                <td style="text-align:left; font-size:0.9em;">{det_str}</td>
                <td><div class="score-bg"><div style="width:{pct_bar}%; background:#2ecc71; height:100%;"></div></div></td>
            </tr>
            """
        html_cal += "</tbody></table>"
        afficher_html(html_cal)

        st.markdown("#### ❄️ Simulateur d'Effet Boule de Neige sur 10 Ans (DCA + Dividendes Réinvestis)")
        rendement_moy_proj = (total_annuel_div / valeur_totale_portefeuille) if valeur_totale_portefeuille > 0 else 0.045
        rendement_moy_proj = max(0.03, min(0.09, rendement_moy_proj))

        cap_proj = valeur_totale_portefeuille
        lignes_proj = []
        for annee in range(1, 11):
            apport_an = BUDGET_MENSUEL * 12
            div_an = (cap_proj + apport_an / 2) * rendement_moy_proj
            cap_proj = cap_proj + apport_an + div_an
            lignes_proj.append({
                "Horizon": f"Année +{annee} ({datetime.now().year + annee})",
                "Capital Cumulé Estimé": f"{cap_proj:,.0f} €",
                "Rente Annuelle Estimée": f"{div_an:,.0f} € / an",
                "Rente Mensuelle Moyenne": f"{div_an/12:,.1f} € / mois",
            })

        html_proj = "<table class='r-table'><thead><tr><th style='text-align:left;'>Horizon</th><th>Capital Projeté (€)</th><th>Rente Annuelle (€/an)</th><th>Rente Mensuelle (€/mois)</th></tr></thead><tbody>"
        for lp in lignes_proj:
            html_proj += f"<tr><td class='r-name'>{lp['Horizon']}</td><td><b>{lp['Capital Cumulé Estimé']}</b></td><td style='color:#2ecc71; font-weight:800;'>{lp['Rente Annuelle Estimée']}</td><td><span class='b-blue'>{lp['Rente Mensuelle Moyenne']}</span></td></tr>"
        html_proj += "</tbody></table>"
        afficher_html(html_proj)


# ------------------------------------------------------------------------------
# ONGLET 4 : COACH & AUDIT IA 2.0 (CONNECTÉ À L'API GEMINI PRO)
# ------------------------------------------------------------------------------
with onglet_ia:
    st.subheader("🤖 Coach & Audit IA 2.0 (Propulsé par Google Gemini)")

    quota_utilise = st.session_state.get("quota_ia_utilise", 0)
    quota_restant = max(0, quota_ia_max - quota_utilise)

    html_ia_header = f"""
    <div class="argon-grid">
        <div class="argon-card">
            <div class="argon-title">⚡ Crédits d'Audit IA du Jour</div>
            <div class="argon-val" style="color:#9b59b6;">{quota_restant} / {quota_ia_max} disponibles</div>
            <div class="argon-sub">{'Offre Découverte (2/j)' if mode_gratuit else 'Abonné Boursy Pro (15/j)'}</div>
        </div>
        <div class="argon-card">
            <div class="argon-title">🧠 Contexte Transmis au Coach</div>
            <div class="argon-val">{len(portefeuille_utilisateur)} lignes & {len(donnees_t1)} signaux</div>
            <div class="argon-sub">Météo VIX ({vix_val:.1f}), EUR/USD ({TAUX_USD_EUR:.3f}) & Indicateurs inclus</div>
        </div>
    </div>
    """
    afficher_html(html_ia_header)

    def appeler_gemini_coach(question_utilisateur):
        cle_gemini = str(st.secrets.get("GEMINI_API_KEY", "")).strip().strip('"').strip("'") if hasattr(st, "secrets") else ""
        if not cle_gemini:
            return "⚠️ Clé `GEMINI_API_KEY` absente des Secrets Streamlit Cloud. Veuillez vérifier vos paramètres."

        resume_pf = []
        for nom_a, d_pos in portefeuille_utilisateur.items():
            if nom_a == "Espèces":
                resume_pf.append(f"- Espèces : {d_pos['pru']} €")
            elif nom_a in WATCHLIST:
                dev_a = WATCHLIST[nom_a].get("devise", "EUR")
                cours_a = prix_temps_reel.get(nom_a, WATCHLIST[nom_a]["prix_cible"])
                resume_pf.append(f"- {nom_a} ({dev_a}) : Qté={d_pos['qte']}, PRU={d_pos['pru']} {dev_a}, Cours={cours_a:.2f} {dev_a}, Div={WATCHLIST[nom_a]['div_eur']} {dev_a}")

        resume_radar = [f"- {d['Actif']} : Prix={d['Prix']}, Cible={d['Prix Cible']}, RSI={d['RSI']}, Stoch={d['Stoch']}%, EMA={d['EMA 2/12']}, Score={d['Score']}/100 ({d['Décision']})" for d in donnees_t1[:12]]

        prompt_complet = f"""Tu es Boursy Coach IA 2.0, un expert pédagogique en gestion de portefeuille PEA, actions internationales (US) et stratégie DCA à dividendes.
Voici les données en direct de l'utilisateur :
- Météo des marchés : CAC 40 = {cac_str}, S&P 500 = {sp_str}, VIX = {vix_val:.1f} ({etat_vix})
- Budget DCA mensuel : {BUDGET_MENSUEL} €
- Taux de change EUR/USD : 1 € = {TAUX_USD_EUR:.4f} $
- Portefeuille actuel :
{chr(10).join(resume_pf) if resume_pf else 'Portefeuille vide'}
- Radar technique et fondamental du jour :
{chr(10).join(resume_radar)}

Demande de l'utilisateur : {question_utilisateur}

Réponds en français de manière structurée, concrète, chiffrée et bienveillante (rappelle brièvement qu'il s'agit d'une analyse pédagogique et non d'un conseil en investissement financier réglementé).
"""
        modeles_test = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]
        for mod in modeles_test:
            try:
                url_api = f"https://generativelanguage.googleapis.com/v1beta/models/{mod}:generateContent?key={cle_gemini}"
                payload_ia = json.dumps({"contents": [{"parts": [{"text": prompt_complet}]}]}).encode("utf-8")
                req_ia = urllib.request.Request(url_api, data=payload_ia, headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req_ia, timeout=25) as resp_ia:
                    res_json = json.loads(resp_ia.read().decode("utf-8"))
                    texte_rep = res_json["candidates"][0]["content"]["parts"][0]["text"]
                    return texte_rep
            except Exception:
                continue
        return "❌ Impossible de joindre l'API Gemini pour le moment. Vérifiez que votre clé API Gemini est valide dans les Secrets Streamlit."

    st.markdown("#### 🚀 Lancer un Audit Intelligent en 1 Clic")
    col_ia1, col_ia2, col_ia3 = st.columns(3)

    prompt_choisi = None
    if col_ia1.button("🔍 1. Audit Complet & Fiscalité", use_container_width=True):
        prompt_choisi = "Réalise un audit complet de mon portefeuille actuel : équilibre sectoriel, exposition PEA (EUR) vs CTO (USD), lignes en plus ou moins-value, et optimisation de ma rente."
    if col_ia2.button("🛒 2. Optimiser mon DCA selon le VIX", use_container_width=True):
        prompt_choisi = f"Compte tenu du niveau actuel du VIX ({vix_val:.1f}) et des scores techniques (RSI, Stochastique, EMA 2/12), comment répartir au mieux mon budget DCA de {BUDGET_MENSUEL:.0f} € ce mois-ci ?"
    if col_ia3.button("🌍 3. Arbitrage PEA (EUR) vs Actions US ($)", use_container_width=True):
        prompt_choisi = "Analyse l'intérêt d'arbitrer ou de renforcer mes valeurs européennes de rendement face aux valeurs de croissance américaines compte tenu du taux EUR/USD actuel."

    question_libre = st.text_input("💬 Ou posez votre propre question boursière au Coach IA :", placeholder="Ex: Que penses-tu de mon PRU sur Rubis et TotalEnergies ? Dois-je renforcer Microsoft ?")
    if st.button("✨ Analyser ma question avec Gemini", type="primary"):
        if question_libre.strip():
            prompt_choisi = question_libre.strip()

    if prompt_choisi:
        if quota_restant <= 0:
            st.error("🔒 Vous avez atteint votre quota journalier d'analyses IA. Passez à l'offre Boursy Pro pour disposer de 15 audits par jour !")
        else:
            with st.spinner("🧠 Le Coach IA 2.0 analyse la météo des marchés, votre portefeuille et les indicateurs techniques..."):
                reponse_texte = appeler_gemini_coach(prompt_choisi)
                st.session_state["quota_ia_utilise"] = quota_utilise + 1
                st.session_state["reponse_ia_coach"] = reponse_texte
                st.rerun()

    if st.session_state.get("reponse_ia_coach"):
        st.markdown("---")
        st.markdown("### 📋 Rapport d'Analyse de votre Coach IA 2.0")
        st.markdown(st.session_state["reponse_ia_coach"])

# Footer & Mentions Légales
st.markdown("---")
with st.expander("⚖️ Mentions Légales, Fiscalité & Conditions Générales d'Utilisation (Non-CIF)"):
    st.caption(
        "**Avertissement légal :** La plateforme Boursy (`boursy.streamlit.app`) est un outil logiciel d'analyse statistique, "
        "technique et patrimoniale à vocation strictement pédagogique. Les scores algorithmiques, indicateurs (RSI, Stochastique, Bollinger, MACD, EMA) "
        "et réponses générées par l'intelligence artificielle ne constituent en aucun cas un Conseil en Investissement Financier (CIF) ni une incitation "
        "à l'achat ou à la vente d'instruments financiers. Les performances passées ne préjugent pas des performances futures."
    )
afficher_html("<div style='text-align: center; font-size: 0.82em; opacity: 0.72;'>⚖️ Boursy SaaS — Suite Boursière PEA, US & Dividendes | Version Argon Ultime</div>")
 
