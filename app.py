import urllib.request
import urllib.parse
import json
import math
import re
from datetime import datetime
import streamlit as st
import yfinance as yf
from supabase import create_client

# Configuration de la page
st.set_page_config(
    page_title="Boursy - Suite Boursière PEA & Dividendes",
    page_icon="📈",
    layout="wide",
)

# --- CONNEXION À SUPABASE ---
@st.cache_resource
def init_supabase():
    try:
        url = st.secrets["SUPABASE_URL"]
        key = st.secrets["SUPABASE_KEY"]
        return create_client(url, key)
    except Exception:
        return None

supabase = init_supabase()

# --- VALEURS PAR DÉFAUT (NOUVEAUX COMPTES & VISITEURS) ---
WATCHLIST_DEFAUT = {
    "TotalEnergies": {"symbole": "TTE.PA", "prix_cible": 50.0, "secteur": "Énergie", "div_eur": 3.22, "payout_ratio": 0.42, "croissance_5a": "+6.1%", "mois_div": ["Mar", "Juin", "Sep", "Déc"]},
    "Air Liquide": {"symbole": "AI.PA", "prix_cible": 140.0, "secteur": "Chimie/Industrie", "div_eur": 3.12, "payout_ratio": 0.55, "croissance_5a": "+8.5%", "mois_div": ["Mai"]},
    "Vinci": {"symbole": "DG.PA", "prix_cible": 95.0, "secteur": "Concessions/BTP", "div_eur": 4.50, "payout_ratio": 0.58, "croissance_5a": "+7.0%", "mois_div": ["Avr", "Nov"]},
    "Engie": {"symbole": "ENGI.PA", "prix_cible": 18.0, "secteur": "Utilités/Énergie", "div_eur": 1.43, "payout_ratio": 0.68, "croissance_5a": "+5.0%", "mois_div": ["Mai"]},
    "Sanofi": {"symbole": "SAN.PA", "prix_cible": 70.0, "secteur": "Santé", "div_eur": 3.76, "payout_ratio": 0.65, "croissance_5a": "+4.8%", "mois_div": ["Mai"]},
    "LVMH": {"symbole": "MC.PA", "prix_cible": 380.0, "secteur": "Luxe", "div_eur": 13.00, "payout_ratio": 0.48, "croissance_5a": "+12.0%", "mois_div": ["Avr", "Déc"]},
    "Pernod Ricard": {"symbole": "RI.PA", "prix_cible": 60.0, "secteur": "Consommation", "div_eur": 4.70, "payout_ratio": 0.52, "croissance_5a": "+6.5%", "mois_div": ["Juil", "Nov"]},
    "Rubis": {"symbole": "RUI.PA", "prix_cible": 24.0, "secteur": "Énergie/Stockage", "div_eur": 1.92, "payout_ratio": 0.72, "croissance_5a": "+3.2%", "mois_div": ["Mai"]},
    "BNP Paribas": {"symbole": "BNP.PA", "prix_cible": 55.0, "secteur": "Finance", "div_eur": 4.60, "payout_ratio": 0.50, "croissance_5a": "+8.0%", "mois_div": ["Mai"]},
    "Schneider Electric": {"symbole": "SU.PA", "prix_cible": 180.0, "secteur": "Industrie/Tech", "div_eur": 3.50, "payout_ratio": 0.50, "croissance_5a": "+9.2%", "mois_div": ["Mai"]},
    "Veolia": {"symbole": "VIE.PA", "prix_cible": 28.0, "secteur": "Utilités/Environnement", "div_eur": 1.25, "payout_ratio": 0.62, "croissance_5a": "+5.5%", "mois_div": ["Mai"]},
    "AXA": {"symbole": "CS.PA", "prix_cible": 35.0, "secteur": "Finance/Assurance", "div_eur": 1.98, "payout_ratio": 0.55, "croissance_5a": "+5.0%", "mois_div": ["Mai"]},
}

PORTEFEUILLE_DEFAUT = {
    "TotalEnergies": {"qte": 25, "pru": 54.0},
    "Air Liquide": {"qte": 10, "pru": 155.0},
    "Vinci": {"qte": 12, "pru": 98.0},
    "Sanofi": {"qte": 10, "pru": 86.0},
    "BNP Paribas": {"qte": 15, "pru": 58.0},
}

# --- INITIALISATION DE LA SESSION ---
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

# --- FONCTION DE SAUVEGARDE CLOUD CORRIGÉE AVEC AFFICHAGE DES ERREURS ---
def sauvegarder_dans_cloud():
    if supabase and st.session_state["user"]:
        try:
            payload = {
                "user_id": str(st.session_state["user"].id),
                "email": str(st.session_state["user"].email),
                "budget_dca": float(st.session_state["budget_dca"]),
                "watchlist": dict(st.session_state["watchlist"]),
                "portefeuille": dict(st.session_state["portefeuille"]),
                "updated_at": datetime.utcnow().isoformat()
            }
            # Exécution de la requête Supabase
            res = supabase.table("user_data").upsert(payload).execute()
            st.sidebar.success("✅ Sauvegardé avec succès !")
            return True
        except Exception as e:
            # Affichage de l'erreur exacte pour comprendre ce qui bloque
            st.sidebar.error(f"Erreur Supabase détaillée : {e}")
            return False
    else:
        st.sidebar.warning("⚠️ Impossible de sauver : utilisateur non connecté ou Supabase absent.")
        return False

    return False

# --- ESPACE MEMBRE (BARRE LATÉRALE) ---
st.sidebar.header("👤 Espace Membre")

if supabase is None:
    st.sidebar.warning("⚠️ Base de données non connectée (Vérifiez vos Secrets Streamlit). Mode local actif.")
else:
    if st.session_state["user"] is None:
        choix_auth = st.sidebar.radio("Accès :", ["Se connecter", "Créer un compte"], horizontal=True)
        email_input = st.sidebar.text_input("Email")
        password_input = st.sidebar.text_input("Mot de passe", type="password")
       
        if choix_auth == "Se connecter":
            if st.sidebar.button("🔓 Connexion", use_container_width=True):
                try:
                    res = supabase.auth.sign_in_with_password({"email": email_input, "password": password_input})
                    st.session_state["user"] = res.user
                   
                    data = supabase.table("user_data").select("*").eq("user_id", res.user.id).execute()
                    if data.data:
                        profil = data.data[0]
                        st.session_state["watchlist"] = profil.get("watchlist") or WATCHLIST_DEFAUT.copy()
                        portefeuille_cloud = profil.get("portefeuille") or PORTEFEUILLE_DEFAUT.copy()
                        st.session_state["portefeuille"] = portefeuille_cloud
                        st.session_state["budget_dca"] = float(profil.get("budget_dca") or 450.0)
                        st.session_state["est_abonne_pro"] = bool(profil.get("est_abonne_pro", False))
                       
                        # On force les cases de l'interface à prendre les valeurs téléchargées
                        for nom_act, data_pos in portefeuille_cloud.items():
                            st.session_state[f"qte_{nom_act}"] = int(data_pos.get("qte", 0))
                            st.session_state[f"pru_{nom_act}"] = float(data_pos.get("pru", 0.0))
                           
                    else:
                        sauvegarder_dans_cloud()
                    st.rerun()
                except Exception:
                    st.sidebar.error("Identifiants incorrects ou compte inexistant.")
        else:
            if st.sidebar.button("✨ S'inscrire gratuitement", use_container_width=True):
                try:
                    res = supabase.auth.sign_up({"email": email_input, "password": password_input})
                    if res.user:
                        st.session_state["user"] = res.user
                        st.session_state["watchlist"] = WATCHLIST_DEFAUT.copy()
                        st.session_state["portefeuille"] = PORTEFEUILLE_DEFAUT.copy()
                        sauvegarder_dans_cloud()
                        st.sidebar.success("Compte créé avec succès !")
                        st.rerun()
                except Exception as e:
                    st.sidebar.error(f"Erreur d'inscription (mot de passe de 6 caractères min.) : {e}")
    else:
        st.sidebar.success(f"Connecté : **{st.session_state['user'].email}**")
       
        if st.sidebar.button("🔄 Charger mes données", type="primary", use_container_width=True):
            try:
                reponse = supabase.table("user_data").select("*").eq("user_id", st.session_state["user"].id).execute()
                if reponse.data:
                    profil = reponse.data[0]
                    st.session_state["watchlist"] = profil.get("watchlist") or WATCHLIST_DEFAUT.copy()
                    portefeuille_cloud = profil.get("portefeuille") or PORTEFEUILLE_DEFAUT.copy()
                    st.session_state["portefeuille"] = portefeuille_cloud
                    st.session_state["budget_dca"] = float(profil.get("budget_dca") or 450.0)
                    st.session_state["est_abonne_pro"] = bool(profil.get("est_abonne_pro", False))
                   
                    for nom_act, data_pos in portefeuille_cloud.items():
                        st.session_state[f"qte_{nom_act}"] = int(data_pos.get("qte", 0))
                        st.session_state[f"pru_{nom_act}"] = float(data_pos.get("pru", 0.0))
                       
                    st.sidebar.success("✅ Données récupérées et appliquées !")
                    st.rerun()
                else:
                    st.sidebar.warning("⚠️ La base de données n'a rien renvoyé.")
            except Exception as e:
                st.sidebar.error(f"Erreur : {e}")

        col_btn1, col_btn2 = st.sidebar.columns(2)
        if col_btn1.button("💾 Sauver", use_container_width=True):
            if sauvegarder_dans_cloud():
                st.toast("✅ Profil sauvegardé dans le Cloud !")
        if col_btn2.button("🚪 Sortir", use_container_width=True):
            supabase.auth.sign_out()
            st.session_state["user"] = None
            st.rerun()

WATCHLIST = st.session_state["watchlist"]

st.title("📈 Boursy - Plateforme Boursière PEA & Dividendes")
st.caption(f"Dernière mise à jour des marchés : {datetime.now().strftime('%d/%m/%Y à %H:%M')}")

# --- PARAMÈTRES DCA ---
st.sidebar.markdown("---")
st.sidebar.header("⚙️ Paramètres DCA")
nouveau_budget = st.sidebar.number_input(
    "Enveloppe Mensuelle (€)",
    min_value=50.0,
    max_value=5000.0,
    value=float(st.session_state["budget_dca"]),
    step=50.0,
)
if nouveau_budget != st.session_state["budget_dca"]:
    st.session_state["budget_dca"] = nouveau_budget
    sauvegarder_dans_cloud()

BUDGET_MENSUEL = st.session_state["budget_dca"]

# --- RECHERCHE PAR MENU DÉROULANT YFINANCE (SBF120) & AJOUT PERSONNALISÉ ---
st.sidebar.markdown("---")
st.sidebar.subheader("🔍 Ajouter / Gérer les actions")

catalogue_sbf120 = {
    "Air Liquide": "AI.PA", "AXA": "CS.PA", "BNP Paribas": "BNP.PA",
    "Bouygues": "EN.PA", "Capgemini": "CAP.PA", "Crédit Agricole": "ACA.PA",
    "Danone": "BN.PA", "Edenred": "EDEN.PA", "Eiffage": "FGR.PA",
    "Engie": "ENGI.PA", "EssilorLuxottica": "EL.PA", "GTT": "GTT.PA",
    "Hermès": "RMS.PA", "Kering": "KER.PA", "L'Oréal": "OR.PA",
    "Legrand": "LR.PA", "LVMH": "MC.PA", "Michelin": "ML.PA",
    "Orange": "ORA.PA", "Pernod Ricard": "RI.PA", "Publicis": "PUB.PA",
    "Renault": "RNO.PA", "Rubis": "RUI.PA", "Safran": "SAF.PA",
    "Saint-Gobain": "SGO.PA", "Sanofi": "SAN.PA", "Schneider Electric": "SU.PA",
    "Société Générale": "GLE.PA", "Stellantis": "STLAP.PA", "Thales": "HO.PA",
    "TotalEnergies": "TTE.PA", "Veolia": "VIE.PA", "Vinci": "DG.PA"
}

choix_menu_yf = st.sidebar.selectbox("1. Sélectionner une action (SBF120) :", ["-- Choisir une valeur --"] + sorted(catalogue_sbf120.keys()))

if choix_menu_yf != "-- Choisir une valeur --":
    symbole_selectionne = catalogue_sbf120[choix_menu_yf]
    with st.sidebar.form("formulaire_menu_yf"):
        st.markdown(f"**Action :** {choix_menu_yf} (`{symbole_selectionne}`)")
        nouveau_secteur = st.text_input("Secteur (ex: Tech, Banque, Énergie)", value="À définir")
        nouveau_cible = st.number_input("Prix cible (€)", min_value=0.0, value=50.0, step=1.0)
        nouveau_div = st.number_input("Dividende annuel (€)", min_value=0.0, value=2.0, step=0.1)
        nouveau_payout = st.number_input("Payout Ratio (ex: 0.50)", min_value=0.0, max_value=2.0, value=0.5, step=0.05)
        
        liste_mois_possibles = ["Jan", "Fév", "Mar", "Avr", "Mai", "Juin", "Juil", "Août", "Sep", "Oct", "Nov", "Déc"]
        nouveau_mois = st.multiselect("Mois de versement :", liste_mois_possibles, default=["Mai"])
        
        submit_ajout = st.form_submit_button("➕ Ajouter à Boursy")
        
        if submit_ajout:
            st.session_state["watchlist"][choix_menu_yf] = {
                "symbole": symbole_selectionne,
                "prix_cible": nouveau_cible,
                "secteur": nouveau_secteur,
                "div_eur": nouveau_div,
                "payout_ratio": nouveau_payout,
                "croissance_5a": "N/A",
                "mois_div": nouveau_mois
            }
            sauvegarder_dans_cloud()
            st.rerun()

with st.sidebar.expander("🗑️ Supprimer une action du radar"):
    action_a_suppr = st.selectbox("Choisir l'action à retirer :", list(WATCHLIST.keys()))
    if st.button("Supprimer définitivement"):
        if action_a_suppr in st.session_state["watchlist"]:
            del st.session_state["watchlist"][action_a_suppr]
        if action_a_suppr in st.session_state["portefeuille"]:
            del st.session_state["portefeuille"][action_a_suppr]
        sauvegarder_dans_cloud()
        st.rerun()

st.sidebar.markdown("---")
st.sidebar.header("🔐 Mode d'accès (Test)")
mode_gratuit = st.sidebar.checkbox(
    "Simuler la vue Visiteur Gratuit (Freemium)", value=False
)

if mode_gratuit:
    actions_autorisees = list(WATCHLIST.keys())[:2]
    st.sidebar.info("🔒 **Mode Découverte actif** : 2 valeurs débloquées.")
else:
    actions_autorisees = list(WATCHLIST.keys())
    st.sidebar.success(f"💎 **Mode Abonné Pro actif** : {len(WATCHLIST)} valeurs débloquées.")

# --- CALCULS TECHNIQUES ---
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

def calculer_bollinger(clotures, periode=20):
  if len(clotures) < periode:
    return clotures[-1], clotures[-1]
  fenetre = clotures[-periode:]
  moyenne = sum(fenetre) / periode
  variance = sum((x - moyenne) ** 2 for x in fenetre) / periode
  ecart_type = math.sqrt(variance)
  return moyenne - (2 * ecart_type), moyenne + (2 * ecart_type)

def calculer_macd(clotures):
  if len(clotures) < 35:
    return 0, 0
  k12, k26, k9 = 2 / 13, 2 / 27, 2 / 10
  e12, e26 = sum(clotures[:12]) / 12, sum(clotures[:26]) / 26
  macds = []
  for i, prix in enumerate(clotures):
    if i >= 12:
      e12 = (prix * k12) + (e12 * (1 - k12))
    if i >= 26:
      e26 = (prix * k26) + (e26 * (1 - k26))
    if i >= 26:
      macds.append(e12 - e26)
  if len(macds) < 9:
    return macds[-1], 0
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

def verifier_croisement_2_12(clotures):
  if len(clotures) < 15:
    return False
  ema2_serie = calculer_ema_serie(clotures, 2)
  ema12_serie = calculer_ema_serie(clotures, 12)
  valides = [
      (e2, e12)
      for e2, e12 in zip(ema2_serie, ema12_serie)
      if e2 is not None and e12 is not None
  ]
  if len(valides) < 2:
    return False
  veille_e2, veille_e12 = valides[-2]
  jour_e2, jour_e12 = valides[-1]
  return veille_e2 <= veille_e12 and jour_e2 > jour_e12

def calculer_regression_lineaire(clotures):
  n = len(clotures)
  if n < 2:
    return clotures[-1], 0.0, []
  x = list(range(n))
  moy_x, moy_y = sum(x) / n, sum(clotures) / n
  numerateur = sum((x[i] - moy_x) * (clotures[i] - moy_y) for i in range(n))
  denominateur = sum((x[i] - moy_x) ** 2 for i in range(n))
  pente = numerateur / denominateur if denominateur != 0 else 0
  ordonnee = moy_y - (pente * moy_x)

  droite_regression = [(pente * i) + ordonnee for i in range(n)]
  val_reg = droite_regression[-1]
  ecart_pct = ((clotures[-1] - val_reg) / val_reg) * 100
  return val_reg, ecart_pct, droite_regression

@st.cache_data(ttl=3600)
def recuperer_donnees(symbole):
  url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbole}?range=3y&interval=1d"
  req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
  try:
    with urllib.request.urlopen(req, timeout=5) as response:
      data = json.loads(response.read().decode())
      result = data["chart"]["result"][0]
      prix_actuel = result["meta"]["regularMarketPrice"]
      closes = [
          p for p in result["indicators"]["quote"][0]["close"] if p is not None
      ]
      hauts = [
          h for h in result["indicators"]["quote"][0]["high"] if h is not None
      ]
      bas = [
          l for l in result["indicators"]["quote"][0]["low"] if l is not None
      ]
      return prix_actuel, closes, hauts, bas
  except Exception:
    return None, None, None, None

# --- TRAITEMENT GÉNÉRAL ---
resultats_analysed = []
donnees_t1, donnees_t2, donnees_t3, donnees_t4 = [], [], [], []
historiques_prix = {}
prix_temps_reel = {}

for nom, info in WATCHLIST.items():
  prix_actuel, closes, hauts, bas = recuperer_donnees(info["symbole"])
  if prix_actuel is None or not closes:
    continue

  prix_temps_reel[nom] = prix_actuel
  historiques_prix[nom] = closes

  if nom not in actions_autorisees:
    continue

  rendement_actuel = info["div_eur"] / prix_actuel if prix_actuel > 0 else 0.0
  prix_cible = info["prix_cible"]
  plus_haut_52s = max(hauts) if hauts else prix_actuel
  rsi = calculer_rsi(closes)
  borne_inf, borne_sup = calculer_bollinger(closes)
  macd_val, macd_sig = calculer_macd(closes)
  croisement_2_12 = verifier_croisement_2_12(closes)
  val_reg, ecart_reg_pct, droite_reg = calculer_regression_lineaire(closes)
  support_30j = min(bas[-30:]) if len(bas) >= 30 else min(bas)
  resistance_30j = max(hauts[-30:]) if len(hauts) >= 30 else max(hauts)

  if prix_cible > 0:
    distance_cible_pct = ((prix_actuel - prix_cible) / prix_cible) * 100
  else:
    distance_cible_pct = 0.0

  score = 0
  if prix_cible > 0 and prix_actuel <= prix_cible:
    score += 25
  elif prix_cible > 0 and prix_actuel <= prix_cible * 1.05:
    score += 12

  ecart_haut = ((prix_actuel - plus_haut_52s) / plus_haut_52s) * 100
  if ecart_haut <= -20:
    score += 20
  elif ecart_haut <= -10:
    score += 10

  if prix_actuel <= borne_inf:
    score += 15
  elif prix_actuel <= borne_inf * 1.02:
    score += 8

  if macd_val > macd_sig:
    score += 10
  if rsi <= 30:
    score += 15
  elif rsi <= 45:
    score += 8

  if croisement_2_12:
    score += 15

  est_surevalue = prix_cible > 0 and prix_actuel >= prix_cible * 1.20 and (
      rsi >= 70 or prix_actuel >= borne_sup
  )

  if est_surevalue:
    decision = "⚠️ ALLÈGEMENT"
  elif score >= 65:
    decision = "🔥 ACHAT FORT"
  elif score >= 40:
    decision = "✅ ACCUMULATION"
  else:
    decision = "⏸️ CONSERVATION"

  if distance_cible_pct <= 0:
    dist_str = f"🟢 {distance_cible_pct:+.1f}%"
  elif distance_cible_pct <= 5:
    dist_str = f"🟡 {distance_cible_pct:+.1f}%"
  else:
    dist_str = f"⚪ {distance_cible_pct:+.1f}%"

  donnees_t1.append({
      "Actif": nom,
      "Prix (€)": round(prix_actuel, 2),
      "Prix Cible (€)": round(prix_cible, 2) if prix_cible > 0 else "N/A",
      "Écart Cible (%)": dist_str if prix_cible > 0 else "N/A",
      "RSI": round(rsi, 1),
      "MACD": "🟢" if macd_val > macd_sig else "🔴",
      "EMA 2/12": "🟢 Croisement" if croisement_2_12 else "⚪ Neutre",
      "Score": score,
      "Décision": decision,
  })

  donnees_t2.append({
      "Actif": nom,
      "Prix (€)": round(prix_actuel, 2),
      "Droite Reg. (€)": round(val_reg, 2),
      "Écart %": f"{ecart_reg_pct:+.1f}%",
      "Statut Value": (
          "🟢 DÉCOTE"
          if ecart_reg_pct <= -10
          else ("🟡 SOUS-ÉV." if ecart_reg_pct < 0 else "⚪ NEUTRE")
      ),
  })

  donnees_t3.append({
      "Actif": nom,
      "Div/Act (€)": f"{info['div_eur']:.2f} €",
      "Rendement Réel": f"{rendement_actuel*100:.1f}%",
      "Payout": f"{info['payout_ratio']*100:.0f}%",
      "Croissance 5a": info.get("croissance_5a", "N/A"),
      "Sûreté": (
          "🛡️ ULTRA SÛR"
          if info["payout_ratio"] <= 0.55
          else (
              "✅ SOLIDE"
              if info["payout_ratio"] <= 0.70
              else "🟡 SURVEILLER"
          )
      ),
  })

  zone = (
      "🟢 SUR SUPPORT"
      if prix_actuel <= support_30j * 1.02
      else (
          "🔴 SUR RÉSISTANCE"
          if prix_actuel >= resistance_30j * 0.98
          else "⚪ EN CANAL"
      )
  )
  donnees_t4.append({
      "Actif": nom,
      "Prix (€)": round(prix_actuel, 2),
      "Support 30J (€)": round(support_30j, 2),
      "Résistance 30J (€)": round(resistance_30j, 2),
      "Zone": zone,
  })

  if score >= 40 and not est_surevalue:
    resultats_analysed.append({
        "nom": nom,
        "score": score,
        "rendement": rendement_actuel,
        "prix": prix_actuel,
        "div_eur": info["div_eur"],
    })

# --- SIMULATION ALLOCATION ---
candidats_tries = sorted(
    resultats_analysed, key=lambda x: x["score"], reverse=True
)
budget_courant = BUDGET_MENSUEL
achats_simules = {item["nom"]: 0 for item in candidats_tries}

continuer = True
while continuer:
  continuer = False
  for item in candidats_tries:
    if budget_courant >= item["prix"]:
      achats_simules[item["nom"]] += 1
      budget_courant -= item["prix"]
      continuer = True

montant_tot_div = sum(
    achats_simules[item["nom"]] * item["div_eur"] for item in candidats_tries
)
# ==============================================================================
# NAVIGATION PRINCIPALE : LES 4 ONGLETS
# ==============================================================================
onglet_radar, onglet_portefeuille, onglet_dividendes, onglet_ia = st.tabs([
    "🔍 1. Radar & Aide à l'Achat (DCA)",
    "💼 2. Mon Portefeuille & Secteurs",
    "📅 3. Dividendes & Calendrier",
    "🤖 4. Coach & Audit IA",
])

# ------------------------------------------------------------------------------
# ONGLET 1 : RADAR & AIDE À L'ACHAT (DESIGN PRO)
# ------------------------------------------------------------------------------
with onglet_radar:
  if mode_gratuit:
    st.warning(
        "🔒 **Aperçu Gratuit (Freemium)** : Vous visualisez actuellement 2"
        " actions de démonstration. Passez à l'abonnement complet pour"
        " débloquer toutes les valeurs du PEA !"
    )

  nb_opportunites = sum(
      1
      for d in donnees_t1
      if "ACHAT" in d["Décision"] or "ACCUMULATION" in d["Décision"]
  )
  nb_croisements = sum(1 for d in donnees_t1 if "Croisement" in d["EMA 2/12"])

  # --- 1. CARTES KPI DU RADAR (DESIGN PRO) ---
  html_radar_kpi = f"""
  <style>
  .rad-kpi-grid {{ display: flex; gap: 15px; margin: 10px 0 25px 0; flex-wrap: wrap; font-family: sans-serif; }}
  .rad-kpi-card {{ flex: 1; min-width: 200px; background: rgba(128,128,128,0.05); border: 1px solid rgba(128,128,128,0.2); border-radius: 12px; padding: 18px; text-align: center; }}
  .rad-kpi-highlight {{ flex: 1; min-width: 200px; background: rgba(46,204,113,0.12); border: 2px solid rgba(46,204,113,0.5); border-radius: 12px; padding: 18px; text-align: center; }}
  .rad-kpi-title {{ font-size: 0.82em; text-transform: uppercase; letter-spacing: 0.5px; opacity: 0.75; margin-bottom: 8px; font-weight: bold; }}
  .rad-kpi-val {{ font-size: 1.65em; font-weight: 900; margin-bottom: 5px; }}
  .rad-kpi-sub {{ font-size: 0.85em; font-weight: 600; opacity: 0.85; }}
  
  /* Styles généraux pour les tableaux Pro de l'Onglet 1 */
  .r-table {{ width: 100%; border-collapse: collapse; font-family: sans-serif; margin-bottom: 20px; font-size: 0.95em; }}
  .r-table th {{ border-bottom: 3px solid rgba(128,128,128,0.3); padding: 12px 10px; text-align: center; font-weight: 800; text-transform: uppercase; font-size: 0.83em; background-color: rgba(128,128,128,0.05); }}
  .r-table td {{ border-bottom: 1px solid rgba(128,128,128,0.15); padding: 12px 10px; text-align: center; vertical-align: middle; }}
  .r-name {{ font-weight: 800; font-size: 1.05em; text-align: left; }}
  .b-green {{ background: rgba(46,204,113,0.18); color: #2ecc71; padding: 5px 10px; border-radius: 6px; font-weight: bold; display: inline-block; font-size: 0.9em; }}
  .b-yellow {{ background: rgba(241,196,15,0.18); color: #f39c12; padding: 5px 10px; border-radius: 6px; font-weight: bold; display: inline-block; font-size: 0.9em; }}
  .b-red {{ background: rgba(231,76,60,0.18); color: #e74c3c; padding: 5px 10px; border-radius: 6px; font-weight: bold; display: inline-block; font-size: 0.9em; }}
  .b-neutral {{ background: rgba(128,128,128,0.15); opacity: 0.85; padding: 5px 10px; border-radius: 6px; font-weight: bold; display: inline-block; font-size: 0.9em; }}
  .score-bg {{ width: 100%; background: rgba(128,128,128,0.2); height: 8px; border-radius: 4px; overflow: hidden; margin-top: 5px; }}
  </style>

  <div class="rad-kpi-grid">
      <div class="rad-kpi-card">
          <div class="rad-kpi-title">🎯 Opportunités d'Achat</div>
          <div class="rad-kpi-val">{nb_opportunites} / {len(actions_autorisees)}</div>
          <div class="rad-kpi-sub" style="color: #2ecc71;">Scores techniques ≥ 40/100</div>
      </div>
      <div class="rad-kpi-card">
          <div class="rad-kpi-title">⚡ Signaux EMA 2/12</div>
          <div class="rad-kpi-val">{nb_croisements} Actif(s)</div>
          <div class="rad-kpi-sub">Croisement haussier court terme</div>
      </div>
      <div class="rad-kpi-card">
          <div class="rad-kpi-title">💰 Budget DCA Configuré</div>
          <div class="rad-kpi-val">{BUDGET_MENSUEL:.0f} €</div>
          <div class="rad-kpi-sub">Enveloppe mensuelle d'investissement</div>
      </div>
      <div class="rad-kpi-highlight">
          <div class="rad-kpi-title">🌱 Rente Mensuelle Créée</div>
          <div class="rad-kpi-val" style="color: #2ecc71;">+{montant_tot_div/12:.2f} €</div>
          <div class="rad-kpi-sub" style="color: #2ecc71;">Soit +{montant_tot_div:.2f} €/an avec ce DCA</div>
      </div>
  </div>
  """
  st.markdown(html_radar_kpi, unsafe_allow_html=True)

  # --- FILTRE DE RECHERCHE ---
  st.subheader("🔎 Filtrer ou rechercher une valeur")
  options_filtre = ["📋 Afficher toutes les actions"] + actions_autorisees
  choix_action = st.selectbox(
      "Choisissez une action dans la liste :",
      options=options_filtre,
  )

  if choix_action == "📋 Afficher toutes les actions":
    t1_filtre = donnees_t1
    t2_filtre = donnees_t2
    t3_filtre = donnees_t3
    t4_filtre = donnees_t4
  else:
    t1_filtre = [d for d in donnees_t1 if d["Actif"] == choix_action]
    t2_filtre = [d for d in donnees_t2 if d["Actif"] == choix_action]
    t3_filtre = [d for d in donnees_t3 if d["Actif"] == choix_action]
    t4_filtre = [d for d in donnees_t4 if d["Actif"] == choix_action]

  # --- 2. TABLEAU 1 : TIMING & MOMENTUM (DESIGN PRO) ---
  st.subheader("📊 Tableau 1 : Timing & Momentum (Aide à la Décision)")

  html_t1 = """
  <table class="r-table">
  <thead>
      <tr>
          <th style="text-align: left;">Actif</th>
          <th>Prix Actuel</th>
          <th>Prix Cible</th>
          <th>Écart Cible</th>
          <th>RSI (14J)</th>
          <th>MACD</th>
          <th>Signal EMA 2/12</th>
          <th style="width: 140px;">Score / 100</th>
          <th>Décision IA</th>
      </tr>
  </thead>
  <tbody>
  """

  for d in sorted(t1_filtre, key=lambda x: x["Score"], reverse=True):
    ecart_str = str(d["Écart Cible (%)"])
    if "🟢" in ecart_str:
      badge_ecart = f"<span class='b-green'>{ecart_str}</span>"
    elif "🟡" in ecart_str:
      badge_ecart = f"<span class='b-yellow'>{ecart_str}</span>"
    else:
      badge_ecart = f"<span class='b-neutral'>{ecart_str}</span>"

    rsi_v = d["RSI"]
    if rsi_v <= 35:
      rsi_html = f"<span style='color:#2ecc71; font-weight:900;'>{rsi_v} (Survendu)</span>"
    elif rsi_v >= 68:
      rsi_html = f"<span style='color:#e74c3c; font-weight:900;'>{rsi_v} (Chaud)</span>"
    else:
      rsi_html = f"<b>{rsi_v}</b>"

    ema_str = d["EMA 2/12"]
    ema_html = f"<span class='b-green'>{ema_str}</span>" if "Croisement" in ema_str else f"<span style='opacity:0.6;'>{ema_str}</span>"

    sc = d["Score"]
    c_bar = "#2ecc71" if sc >= 65 else ("#3498db" if sc >= 40 else "#95a5a6")

    dec = d["Décision"]
    if "ACHAT FORT" in dec:
      dec_html = f"<span class='b-green'>{dec}</span>"
    elif "ACCUMULATION" in dec:
      dec_html = f"<span class='b-yellow' style='color:#2ecc71; background:rgba(46,204,113,0.12);'>{dec}</span>"
    elif "ALLÈGEMENT" in dec:
      dec_html = f"<span class='b-red'>{dec}</span>"
    else:
      dec_html = f"<span class='b-neutral'>{dec}</span>"

    cible_aff = f"{d['Prix Cible (€)']:.2f} €" if isinstance(d["Prix Cible (€)"], (int, float)) else d["Prix Cible (€)"]

    html_t1 += f"""
    <tr>
        <td class="r-name">{d['Actif']}</td>
        <td><b>{d['Prix (€)']:.2f} €</b></td>
        <td style="opacity: 0.85;">{cible_aff}</td>
        <td>{badge_ecart}</td>
        <td>{rsi_html}</td>
        <td style="font-size: 1.15em;">{d['MACD']}</td>
        <td>{ema_html}</td>
        <td>
            <div style="font-weight: 800; font-size: 0.9em;">{sc} / 100</div>
            <div class="score-bg"><div style="width: {min(100, sc)}%; background: {c_bar}; height: 100%;"></div></div>
        </td>
        <td>{dec_html}</td>
    </tr>
    """

  html_t1 += "</tbody></table>"
  st.markdown(html_t1, unsafe_allow_html=True)

  st.markdown("---")

  # --- 3. SOUS-ONGLETS : ANALYSE APPROFONDIE & DCA ---
  st.subheader("📋 Tableaux d'Analyse Approfondie & DCA")
  tab_val, tab_tech, tab_div, tab_dca = st.tabs([
      "📐 Tableau 2 : Analyse Value",
      "🎯 Tableau 3 : Niveaux Techniques",
      "🛡️ Tableau 4 : Sûreté Dividendes",
      "💰 Allocation DCA du Mois",
  ])

  with tab_val:
    st.caption("Comparaison du cours actuel avec la tendance longue (droite de régression linéaire sur 3 ans) :")
    html_t2 = """
    <table class="r-table">
    <thead>
        <tr>
            <th style="text-align: left;">Actif</th>
            <th>Prix Actuel</th>
            <th>Valeur Tendance 3 Ans (Régression)</th>
            <th>Écart à la Tendance</th>
            <th>Diagnostic Value</th>
        </tr>
    </thead>
    <tbody>
    """
    for d in t2_filtre:
      st_val = d["Statut Value"]
      if "DÉCOTE" in st_val:
        b_val = f"<span class='b-green'>{st_val}</span>"
      elif "SOUS-ÉV" in st_val:
        b_val = f"<span class='b-yellow'>{st_val}</span>"
      else:
        b_val = f"<span class='b-neutral'>{st_val}</span>"

      html_t2 += f"""
      <tr>
          <td class="r-name">{d['Actif']}</td>
          <td><b>{d['Prix (€)']:.2f} €</b></td>
          <td>{d['Droite Reg. (€)']:.2f} €</td>
          <td><b>{d['Écart %']}</b></td>
          <td>{b_val}</td>
      </tr>
      """
    html_t2 += "</tbody></table>"
    st.markdown(html_t2, unsafe_allow_html=True)

    st.markdown("---")
    st.subheader("🔍 Analyse Visuelle & Droite de Régression (3 Ans)")
    
    index_defaut = (
        actions_autorisees.index(choix_action)
        if choix_action in actions_autorisees
        else 0
    )

    action_selectionnee = st.selectbox(
        "Sélectionnez l'action à analyser visuellement :",
        actions_autorisees,
        index=index_defaut,
    )

    if action_selectionnee in historiques_prix:
      closes = historiques_prix[action_selectionnee]
      _, _, droite_reg = calculer_regression_lineaire(closes)

      st.line_chart({
          "Cours Réel (€)": closes,
          "Tendance 3 Ans (Régression)": droite_reg,
      })

  with tab_tech:
    st.caption("Positionnement du cours par rapport aux plus bas (Support) et plus hauts (Résistance) des 30 derniers jours :")
    html_t4 = """
    <table class="r-table">
    <thead>
        <tr>
            <th style="text-align: left;">Actif</th>
            <th>Support 30J (Plus Bas)</th>
            <th>Prix Actuel</th>
            <th>Résistance 30J (Plus Haut)</th>
            <th>Zone Technique</th>
        </tr>
    </thead>
    <tbody>
    """
    for d in t4_filtre:
      z = d["Zone"]
      if "SUPPORT" in z:
        b_z = f"<span class='b-green'>{z}</span>"
      elif "RÉSISTANCE" in z:
        b_z = f"<span class='b-red'>{z}</span>"
      else:
        b_z = f"<span class='b-neutral'>{z}</span>"

      html_t4 += f"""
      <tr>
          <td class="r-name">{d['Actif']}</td>
          <td style="color: #2ecc71; font-weight: bold;">{d['Support 30J (€)']:.2f} €</td>
          <td><b>{d['Prix (€)']:.2f} €</b></td>
          <td style="color: #e74c3c; font-weight: bold;">{d['Résistance 30J (€)']:.2f} €</td>
          <td>{b_z}</td>
      </tr>
      """
    html_t4 += "</tbody></table>"
    st.markdown(html_t4, unsafe_allow_html=True)

  with tab_div:
    st.caption("Analyse du rendement, de la croissance et de la soutenabilité du dividende (Payout Ratio) :")
    html_t3 = """
    <table class="r-table">
    <thead>
        <tr>
            <th style="text-align: left;">Actif</th>
            <th>Dividende / Action</th>
            <th>Rendement Actuel</th>
            <th style="width: 150px;">Payout Ratio</th>
            <th>Croissance 5 Ans</th>
            <th>Sûreté du Dividende</th>
        </tr>
    </thead>
    <tbody>
    """
    for d in t3_filtre:
      sur = d["Sûreté"]
      if "ULTRA" in sur or "SOLIDE" in sur:
        b_sur = f"<span class='b-green'>{sur}</span>"
      else:
        b_sur = f"<span class='b-yellow'>{sur}</span>"

      try:
        p_num = int(str(d["Payout"]).replace("%", "").strip())
      except Exception:
        p_num = 50
      c_pay = "#2ecc71" if p_num <= 60 else ("#f39c12" if p_num <= 75 else "#e74c3c")

      html_t3 += f"""
      <tr>
          <td class="r-name">{d['Actif']}</td>
          <td><b>{d['Div/Act (€)']}</b></td>
          <td style="color: #2ecc71; font-weight: 800;">{d['Rendement Réel']}</td>
          <td>
              <div style="font-weight: bold; font-size: 0.9em;">{d['Payout']}</div>
              <div class="score-bg"><div style="width: {min(100, p_num)}%; background: {c_pay}; height: 100%;"></div></div>
          </td>
          <td><b>{d['Croissance 5a']}</b></td>
          <td>{b_sur}</td>
      </tr>
      """
    html_t3 += "</tbody></table>"
    st.markdown(html_t3, unsafe_allow_html=True)

  with tab_dca:
    st.caption(f"Répartition optimale de votre budget mensuel ({BUDGET_MENSUEL:.0f} €) sur les meilleures opportunités actuelles :")
    if not candidats_tries:
      st.warning(
          "Aucune action n'atteint le seuil d'achat ce mois-ci (Scores < 40)."
      )
    else:
      total_investi = 0
      total_div_an = 0
      lignes_dca_html = ""

      for item in candidats_tries:
        nb = achats_simules[item["nom"]]
        if nb > 0:
          montant_eff = nb * item["prix"]
          div_gen = nb * item["div_eur"]
          total_investi += montant_eff
          total_div_an += div_gen

          lignes_dca_html += f"""
          <tr>
              <td class="r-name">{item['nom']}</td>
              <td>{item['prix']:.2f} €</td>
              <td><span class="b-green" style="font-size: 1.05em;">🛒 {nb} action(s)</span></td>
              <td><b>{montant_eff:.2f} €</b></td>
              <td style="color: #2ecc71; font-weight: 800;">+{div_gen:.2f} € / an</td>
          </tr>
          """

      if lignes_dca_html:
        html_dca_box = f"""
        <div style="background: linear-gradient(90deg, rgba(46,204,113,0.15) 0%, rgba(52,152,219,0.15) 100%); border-left: 5px solid #2ecc71; padding: 15px 20px; border-radius: 8px; margin-bottom: 20px; font-family: sans-serif;">
            <div style="font-size: 1.05em;">💰 <b>Total investi ce mois-ci : {total_investi:.2f} €</b> sur {BUDGET_MENSUEL:.0f} € <span style="opacity: 0.85;">(Liquidités restantes : {budget_courant:.2f} €)</span></div>
            <div style="margin-top: 6px; font-size: 0.95em; color: #2ecc71; font-weight: bold;">📈 Nouvelle rente annuelle créée immédiatement : +{total_div_an:.2f} €/an (+{total_div_an/12:.2f} €/mois)</div>
        </div>
        <table class="r-table">
        <thead>
            <tr>
                <th style="text-align: left;">Actif Sélectionné</th>
                <th>Prix Unitaire</th>
                <th>Quantité à Acheter</th>
                <th>Montant Total Investi</th>
                <th>Rente Générée</th>
            </tr>
        </thead>
        <tbody>
            {lignes_dca_html}
        </tbody>
        </table>
        """
        st.markdown(html_dca_box, unsafe_allow_html=True)
      else:
        st.warning(
            "Le budget mensuel est trop faible pour acheter une action entière"
            " de ces valeurs."
        )


# ------------------------------------------------------------------------------
# ONGLET 2 : MON PORTEFEUILLE & SECTEURS
# ------------------------------------------------------------------------------
portefeuille_utilisateur = {}
with onglet_portefeuille:
  st.subheader("💼 Gestionnaire de Portefeuille & Analyse Sectorielle")

  if st.session_state["user"] is None:
    st.info(
        "💡 **Astuce Cloud** : Connectez-vous dans la barre latérale à gauche"
        " pour sauvegarder durablement vos quantités et vos PRU dans votre"
        " espace personnel."
    )

  with st.expander(
      "✏️ Saisir ou modifier mes actions détenues (Quantité & PRU)",
      expanded=False,
  ):
    st.caption(
        "Indiquez le nombre d'actions que vous possédez dans votre PEA et votre"
        " Prix de Revient Unitaire (PRU). Cliquez sur le bouton en bas du menu"
        " pour enregistrer vos modifications."
    )
    cols_saisie = st.columns(3)
    nouveau_portefeuille_temp = {}

    for idx, (nom_act, info_act) in enumerate(WATCHLIST.items()):
      col_active = cols_saisie[idx % 3]
      with col_active:
        st.markdown(f"**{nom_act}** *({info_act['secteur']})*")
        qte_defaut = st.session_state["portefeuille"].get(nom_act, {}).get("qte", 0)
        pru_defaut = st.session_state["portefeuille"].get(nom_act, {}).get(
            "pru", float(info_act["prix_cible"]) if info_act["prix_cible"] > 0 else 0.0
        )

        qte_saisie = st.number_input(
            f"Quantité ({nom_act})",
            min_value=0,
            max_value=10000,
            value=int(qte_defaut),
            step=1,
            key=f"qte_{nom_act}",
        )
        pru_saisi = st.number_input(
            f"PRU € ({nom_act})",
            min_value=0.0,
            max_value=5000.0,
            value=float(pru_defaut),
            step=0.5,
            key=f"pru_{nom_act}",
        )
        if qte_saisie > 0:
          nouveau_portefeuille_temp[nom_act] = {
              "qte": qte_saisie,
              "pru": pru_saisi,
          }
        st.markdown("---")

    portefeuille_utilisateur = nouveau_portefeuille_temp
    st.session_state["portefeuille"] = portefeuille_utilisateur

    if st.button("💾 Enregistrer mon portefeuille dans le Cloud", type="primary", use_container_width=True):
      if sauvegarder_dans_cloud():
        st.success("✅ Votre portefeuille a été sauvegardé dans votre compte Cloud !")
      else:
        st.warning("⚠️ Connectez-vous d'abord dans la barre latérale pour sauvegarder en ligne.")

  if not portefeuille_utilisateur:
    st.warning(
        "Votre portefeuille est vide. Cliquez sur le menu « ✏️ Saisir ou"
        " modifier mes actions détenues » juste au-dessus pour ajouter vos"
        " premières actions !"
    )
  else:
    repartition_secteurs = {}
    valeur_totale_portefeuille = 0.0
    cout_total_achat = 0.0
    dividendes_annuels_totaux = 0.0

    for nom_act, data_pos in portefeuille_utilisateur.items():
      if nom_act not in WATCHLIST:
        continue
      qte = data_pos["qte"]
      pru = data_pos["pru"]
      info_act = WATCHLIST[nom_act]
      prix_jour = prix_temps_reel.get(nom_act, info_act["prix_cible"])

      val_ligne = qte * prix_jour
      cout_ligne = qte * pru
      div_ligne = qte * info_act["div_eur"]

      valeur_totale_portefeuille += val_ligne
      cout_total_achat += cout_ligne
      dividendes_annuels_totaux += div_ligne

      secteur = info_act["secteur"]
      repartition_secteurs[secteur] = (
          repartition_secteurs.get(secteur, 0.0) + val_ligne
      )

    plus_value_globale = valeur_totale_portefeuille - cout_total_achat
    plus_value_pct = (
        (plus_value_globale / cout_total_achat) * 100
        if cout_total_achat > 0
        else 0.0
    )
    yoc_global = (
        (dividendes_annuels_totaux / cout_total_achat) * 100
        if cout_total_achat > 0
        else 0.0
    )

    couleur_pv_card = "rgba(46,204,113,0.12)" if plus_value_globale >= 0 else "rgba(231,76,60,0.12)"
    bordure_pv_card = "rgba(46,204,113,0.5)" if plus_value_globale >= 0 else "rgba(231,76,60,0.5)"
    texte_pv_color = "#2ecc71" if plus_value_globale >= 0 else "#e74c3c"

    html_kpi = f"""
    <style>
    .port-kpi-grid {{ display: flex; gap: 15px; margin: 10px 0 25px 0; flex-wrap: wrap; font-family: sans-serif; }}
    .port-kpi-card {{ flex: 1; min-width: 200px; background: rgba(128,128,128,0.05); border: 1px solid rgba(128,128,128,0.2); border-radius: 12px; padding: 18px; text-align: center; }}
    .port-kpi-title {{ font-size: 0.82em; text-transform: uppercase; letter-spacing: 0.5px; opacity: 0.75; margin-bottom: 8px; font-weight: bold; }}
    .port-kpi-val {{ font-size: 1.65em; font-weight: 900; margin-bottom: 5px; }}
    .port-kpi-sub {{ font-size: 0.88em; font-weight: 600; opacity: 0.85; }}
    </style>
    <div class="port-kpi-grid">
        <div class="port-kpi-card">
            <div class="port-kpi-title">🏦 Valorisation Totale PEA</div>
            <div class="port-kpi-val">{valeur_totale_portefeuille:,.2f} €</div>
            <div class="port-kpi-sub">Capital investi : {cout_total_achat:,.0f} €</div>
        </div>
        <div class="port-kpi-card" style="background: {couleur_pv_card}; border: 2px solid {bordure_pv_card};">
            <div class="port-kpi-title">📈 Plus/Moins-Value Latente</div>
            <div class="port-kpi-val" style="color: {texte_pv_color};">{plus_value_globale:+,.2f} €</div>
            <div class="port-kpi-sub" style="color: {texte_pv_color};">Performance : {plus_value_pct:+.1f} %</div>
        </div>
        <div class="port-kpi-card">
            <div class="port-kpi-title">💸 Dividendes Annuels</div>
            <div class="port-kpi-val">{dividendes_annuels_totaux:,.2f} €</div>
            <div class="port-kpi-sub" style="color: #2ecc71;">Soit {dividendes_annuels_totaux/12:,.2f} € / mois</div>
        </div>
        <div class="port-kpi-card">
            <div class="port-kpi-title">🎯 Rendement sur PRU (YoC)</div>
            <div class="port-kpi-val">{yoc_global:.2f} %</div>
            <div class="port-kpi-sub">Rendement réel sur coût d'achat</div>
        </div>
    </div>
    """
    st.markdown(html_kpi, unsafe_allow_html=True)

    st.subheader("📋 Détail de mes lignes en portefeuille")

    html_port = """
    <style>
    .p-table { width: 100%; border-collapse: collapse; font-family: sans-serif; margin-bottom: 20px; font-size: 0.95em; }
    .p-table th { border-bottom: 3px solid rgba(128,128,128,0.3); padding: 12px 10px; text-align: center; font-weight: 800; text-transform: uppercase; font-size: 0.85em; background-color: rgba(128,128,128,0.05); }
    .p-table td { border-bottom: 1px solid rgba(128,128,128,0.15); padding: 12px 10px; text-align: center; vertical-align: middle; }
    .p-action-name { font-weight: 800; font-size: 1.05em; text-align: left; }
    .p-sector-tag { display: inline-block; font-size: 0.75em; padding: 2px 8px; border-radius: 10px; background: rgba(128,128,128,0.15); opacity: 0.85; margin-top: 3px; }
    .badge-gain { background: rgba(46,204,113,0.18); color: #2ecc71; padding: 5px 10px; border-radius: 6px; font-weight: bold; display: inline-block; }
    .badge-loss { background: rgba(231,76,60,0.18); color: #e74c3c; padding: 5px 10px; border-radius: 6px; font-weight: bold; display: inline-block; }
    .bar-bg { width: 100%; background: rgba(128,128,128,0.2); height: 8px; border-radius: 4px; overflow: hidden; margin-top: 5px; }
    </style>
    <table class="p-table">
    <thead>
        <tr>
            <th style="text-align: left;">Action & Secteur</th>
            <th>Qté</th>
            <th>PRU ➔ Cours</th>
            <th>Valorisation</th>
            <th>+/- Value Latente</th>
            <th>Rente & YoC</th>
            <th style="width: 150px;">Poids PEA</th>
        </tr>
    </thead>
    <tbody>
    """

    alertes_concentration = []
    lignes_triees = sorted(
        portefeuille_utilisateur.items(),
        key=lambda x: x[1]["qte"] * prix_temps_reel.get(x[0], WATCHLIST.get(x[0], {}).get("prix_cible", 0)),
        reverse=True,
    )

    for nom_act, data_pos in lignes_triees:
      if nom_act not in WATCHLIST:
        continue
      qte = data_pos["qte"]
      pru = data_pos["pru"]
      info_act = WATCHLIST[nom_act]
      prix_jour = prix_temps_reel.get(nom_act, info_act["prix_cible"])

      val_ligne = qte * prix_jour
      cout_ligne = qte * pru
      pv_eur = val_ligne - cout_ligne
      pv_pct = ((pv_eur / cout_ligne) * 100) if cout_ligne > 0 else 0.0
      div_ligne = qte * info_act["div_eur"]
      yoc_ligne = ((info_act["div_eur"] / pru) * 100) if pru > 0 else 0.0
      poids_pct = (
          (val_ligne / valeur_totale_portefeuille) * 100
          if valeur_totale_portefeuille > 0
          else 0.0
      )

      if poids_pct > 25.0:
        alertes_concentration.append((nom_act, poids_pct))

      classe_pv = "badge-gain" if pv_eur >= 0 else "badge-loss"
      couleur_barre = "#e67e22" if poids_pct > 25.0 else "#3498db"
      largeur_barre = min(100, int(poids_pct))

      html_port += f"""
      <tr>
          <td style="text-align: left;">
              <div class="p-action-name">{nom_act}</div>
              <div class="p-sector-tag">{info_act['secteur']}</div>
          </td>
          <td><b>{qte}</b></td>
          <td>{pru:.2f} € ➔ <b>{prix_jour:.2f} €</b></td>
          <td><b>{val_ligne:,.2f} €</b></td>
          <td><span class="{classe_pv}">{pv_eur:+,.2f} € ({pv_pct:+.1f}%)</span></td>
          <td><b>{div_ligne:.2f} €/an</b><br><span style="font-size: 0.82em; opacity: 0.8;">YoC : {yoc_ligne:.2f}%</span></td>
          <td>
              <div style="font-weight: bold; font-size: 0.9em;">{poids_pct:.1f} %</div>
              <div class="bar-bg"><div style="width: {largeur_barre}%; background: {couleur_barre}; height: 100%;"></div></div>
          </td>
      </tr>
      """

    html_port += "</tbody></table>"
    st.markdown(html_port, unsafe_allow_html=True)

    if alertes_concentration:
      for nom_al, p_al in alertes_concentration:
        st.warning(
            f"⚠️ **Alerte de concentration** : La ligne **{nom_al}**"
            f" représente **{p_al:.1f}%** de votre portefeuille (seuil de"
            " prudence recommandé : < 25% par ligne)."
        )
    else:
      st.success(
          "✅ **Bonne diversification par ligne** : Aucune action ne dépasse"
          " 25% de la valeur totale de votre portefeuille."
      )

    st.markdown("---")

    st.subheader("🏭 Répartition Sectorielle de mon Portefeuille")
    col_camembert, col_tab_sec = st.columns([1.1, 1])

    with col_camembert:
      st.caption("Survolez le camembert pour voir le détail par secteur :")
      donnees_camembert = [
          {
              "Secteur": f"{sec} ({(val_sec / valeur_totale_portefeuille) * 100:.1f}%)",
              "Montant": round(val_sec, 2),
              "Poids": f"{(val_sec / valeur_totale_portefeuille) * 100:.1f} %",
          }
          for sec, val_sec in sorted(
              repartition_secteurs.items(), key=lambda x: x[1], reverse=True
          )
      ]

      st.vega_lite_chart(
          donnees_camembert,
          {
              "mark": {
                  "type": "arc",
                  "innerRadius": 65,
                  "outerRadius": 125,
                  "padAngle": 0.03,
                  "cornerRadius": 6,
              },
              "encoding": {
                  "theta": {"field": "Montant", "type": "quantitative"},
                  "color": {
                      "field": "Secteur",
                      "type": "nominal",
                      "scale": {"scheme": "category20"},
                      "legend": {
                          "title": "Secteurs & Poids",
                          "orient": "right",
                          "labelFontSize": 12,
                          "titleFontSize": 13,
                          "labelLimit": 220,
                      },
                  },
                  "tooltip": [
                      {"field": "Secteur", "type": "nominal", "title": "Secteur"},
                      {"field": "Montant", "type": "quantitative", "title": "Valorisation (€)"},
                      {"field": "Poids", "type": "nominal", "title": "Part du PEA"},
                  ],
              },
              "view": {"stroke": None},
              "height": 300,
          },
          use_container_width=True,
      )

    with col_tab_sec:
      st.caption("Diagnostic d'équilibre sectoriel :")
      tableau_secteurs = []
      for sec, val_sec in sorted(
          repartition_secteurs.items(), key=lambda x: x[1], reverse=True
      ):
        poids_sec = (val_sec / valeur_totale_portefeuille) * 100
        etat_sec = "⚠️ Fort (>35%)" if poids_sec > 35 else "✅ Équilibré"
        tableau_secteurs.append({
            "Secteur": sec,
            "Valorisation (€)": f"{val_sec:,.2f} €",
            "Poids (%)": f"{poids_sec:.1f}%",
            "Diagnostic": etat_sec,
        })
      st.dataframe(tableau_secteurs, use_container_width=True)


# ------------------------------------------------------------------------------
# ONGLET 3 : DIVIDENDES, CALENDRIER & SIMULATEUR BOULE DE NEIGE PRO
# ------------------------------------------------------------------------------
with onglet_dividendes:
  st.subheader("📅 Mes Revenus Passifs & Projections")

  if not portefeuille_utilisateur:
    st.warning(
        "Veuillez d'abord saisir vos actions dans l'onglet « 💼 Mon"
        " Portefeuille & Secteurs » pour afficher vos projections de"
        " dividendes."
    )
  else:
    total_div_an = sum(
        data["qte"] * WATCHLIST[nom]["div_eur"]
        for nom, data in portefeuille_utilisateur.items() if nom in WATCHLIST
    )
    total_div_mois = total_div_an / 12

    col_d1, col_d2, col_d3 = st.columns(3)
    col_d1.metric("Rente Annuelle Actuelle", f"{total_div_an:,.2f} € / an")
    col_d2.metric("Moyenne Mensuelle Actuelle", f"{total_div_mois:,.2f} € / mois")
    rendement_moyen_portefeuille = (
        (total_div_an / valeur_totale_portefeuille) * 100
        if valeur_totale_portefeuille > 0
        else 0
    )
    col_d3.metric(
        "Rendement Global du Portefeuille",
        f"{rendement_moyen_portefeuille:.2f} %",
    )

    st.markdown("---")

    st.subheader("🗓️ Calendrier Annuel des Détachements")
    st.caption("Repérez visuellement les mois de versements et les montants estimés pour chaque ligne de votre portefeuille.")

    liste_des_mois = ["Jan", "Fév", "Mar", "Avr", "Mai", "Juin", "Juil", "Août", "Sep", "Oct", "Nov", "Déc"]
    totaux_mensuels = {m: 0.0 for m in liste_des_mois}
   
    html_cal = """
    <style>
    .cal-table { width: 100%; border-collapse: collapse; text-align: center; margin-bottom: 20px; font-family: sans-serif; }
    .cal-table th { border-bottom: 3px solid rgba(128,128,128,0.4); padding: 15px 5px; font-weight: 900; font-size: 1.1em; background-color: rgba(128,128,128,0.05); text-transform: uppercase; }
    .cal-table td { border-bottom: 1px solid rgba(128,128,128,0.2); border-right: 1px dashed rgba(128,128,128,0.1); padding: 12px 5px; vertical-align: middle; }
    .cal-table td:last-child { border-right: none; }
    .cal-total { font-weight: 900; background-color: rgba(46,204,113,0.15); font-size: 1.1em; border-top: 2px solid rgba(46,204,113,0.5); }
    .cal-action { font-weight: bold; text-align: left !important; padding-left: 15px !important; background-color: rgba(128,128,128,0.02); }
    .badge-div { background-color: rgba(46,204,113,0.2); color: inherit; border-radius: 6px; padding: 5px 8px; font-size: 0.95em; font-weight: bold; display: inline-block; box-shadow: 0 1px 2px rgba(0,0,0,0.1); }
    </style>
    """
   
    html_cal += "<table class='cal-table'><thead><tr>"
    html_cal += "<th style='text-align: left; padding-left: 15px;'>Action</th>"
    for m in liste_des_mois:
        html_cal += f"<th>{m}</th>"
    html_cal += "</tr></thead><tbody>"

    for nom, data in portefeuille_utilisateur.items():
        if nom not in WATCHLIST:
            continue
        qte = data["qte"]
        div_annuel_unitaire = WATCHLIST[nom]["div_eur"]
        total_div_ligne = qte * div_annuel_unitaire
        mois_action = WATCHLIST[nom].get("mois_div", [])
       
        montant_par_versement = 0.0
        if len(mois_action) > 0:
            montant_par_versement = total_div_ligne / len(mois_action)
           
        html_cal += f"<tr><td class='cal-action'>{nom}</td>"
        for m in liste_des_mois:
            if m in mois_action:
                if montant_par_versement > 0:
                    html_cal += f"<td><div class='badge-div'>💸 {montant_par_versement:.2f} €</div></td>"
                    totaux_mensuels[m] += montant_par_versement
                else:
                    html_cal += "<td><div class='badge-div'>💸</div></td>"
            else:
                html_cal += "<td></td>"
        html_cal += "</tr>"
       
    html_cal += "<tr class='cal-total'><td class='cal-action'>💰 TOTAL MENSUEL</td>"
    for m in liste_des_mois:
        if totaux_mensuels[m] > 0:
            html_cal += f"<td>🟢 {totaux_mensuels[m]:.2f} €</td>"
        else:
            html_cal += "<td></td>"
    html_cal += "</tr></tbody></table>"

    st.markdown(html_cal, unsafe_allow_html=True)

    st.markdown("---")

    st.subheader("❄️ Machine à Intérêts Composés & Effet Boule de Neige")
    st.caption(
        "Simulez l'explosion de votre rente grâce au réinvestissement automatique des dividendes, "
        f"à votre DCA de {BUDGET_MENSUEL:.0f} €/mois et à la croissance annuelle des entreprises."
    )

    col_s1, col_s2, col_s3 = st.columns(3)
    with col_s1:
      objectif_rente = st.slider(
          "🎯 Objectif de rente mensuelle (€/mois)",
          min_value=100,
          max_value=5000,
          value=500,
          step=50,
      )
    with col_s2:
       annees_max = st.slider(
          "⏳ Horizon de placement (Années)",
          min_value=5,
          max_value=30,
          value=15,
          step=1,
      )
    with col_s3:
      croissance_annuelle_pct = st.slider(
          "📈 Croissance annuelle (Cours + Div.)",
          min_value=0.0,
          max_value=10.0,
          value=4.0,
          step=0.5,
      )

    rendement_base = (
        rendement_moyen_portefeuille / 100
        if rendement_moyen_portefeuille > 0
        else 0.045
    )
    taux_croissance = croissance_annuelle_pct / 100

    cap_total = valeur_totale_portefeuille
    effort_cumule = valeur_totale_portefeuille 
    gains_boule_de_neige = 0.0 

    annee_objectif_atteint = None
    annee_bascule_dca = None

    series_effort = []
    series_boule_de_neige = []
    series_rente_mensuelle = []
    tableau_croissance = []

    for an in range(1, annees_max + 1):
      div_reinvestis_cette_annee = 0.0
      for mois in range(12):
        div_du_mois = (cap_total * rendement_base) / 12
        div_reinvestis_cette_annee += div_du_mois
        gain_cours_mois = cap_total * (taux_croissance / 12)
       
        effort_cumule += BUDGET_MENSUEL
        gains_boule_de_neige += (div_du_mois + gain_cours_mois)
        cap_total = effort_cumule + gains_boule_de_neige

      rente_an = cap_total * rendement_base
      rente_mois = rente_an / 12

      if annee_objectif_atteint is None and rente_mois >= objectif_rente:
        annee_objectif_atteint = an

      if annee_bascule_dca is None and rente_mois >= BUDGET_MENSUEL:
        annee_bascule_dca = an

      series_effort.append(round(effort_cumule, 0))
      series_boule_de_neige.append(round(cap_total, 0))
      series_rente_mensuelle.append(round(rente_mois, 1))

      pct_obj = min(100, int((rente_mois / objectif_rente) * 100))
      nb_blocs = int(pct_obj / 10)
      barre_visuelle = "🟩" * nb_blocs + "⬜" * (10 - nb_blocs) + f" {pct_obj}%"

      tableau_croissance.append({
          "Horizon": f"Année {an} ({datetime.now().year + an})",
          "Votre Effort Cumulé": f"{effort_cumule:,.0f} €",
          "Gains Boule de Neige": f"+{gains_boule_de_neige:,.0f} €",
          "Patrimoine Total": f"{cap_total:,.0f} €",
          "Rente Mensuelle": f"{rente_mois:,.0f} € / mois",
          "Objectif Rente": barre_visuelle,
      })

    rente_finale_mois = (cap_total * rendement_base) / 12
    multiplicateur_rente = (rente_finale_mois / total_div_mois) if total_div_mois > 0 else 0
    part_gratuite_pct = (gains_boule_de_neige / cap_total * 100) if cap_total > 0 else 0

    texte_objectif = (
        f"🎉 Objectif de <b>{objectif_rente} €/mois</b> atteint dans <b>{annee_objectif_atteint} ans</b> (en {datetime.now().year + annee_objectif_atteint}) !"
        if annee_objectif_atteint
        else f"💪 À {annees_max} ans, vous atteindrez <b>{rente_finale_mois:.0f} €/mois</b> (soit {(rente_finale_mois/objectif_rente*100):.0f}% de votre objectif)."
    )
    texte_bascule = (
        f"⚡ <b>Point de Bascule en Année {annee_bascule_dca}</b> : Vos dividendes mensuels dépasseront votre effort d'épargne ({BUDGET_MENSUEL:.0f} €/mois) !"
        if annee_bascule_dca
        else f"💡 Continuez d'accumuler : l'effet boule de neige représentera déjà <b>{part_gratuite_pct:.0f}%</b> de votre patrimoine final."
    )

    html_snowball = f"""
    <style>
    .snow-container {{ display: flex; gap: 15px; margin: 15px 0 25px 0; flex-wrap: wrap; font-family: sans-serif; }}
    .snow-card {{ flex: 1; min-width: 200px; background: rgba(128,128,128,0.05); border: 1px solid rgba(128,128,128,0.2); border-radius: 12px; padding: 18px; text-align: center; }}
    .snow-card-highlight {{ flex: 1; min-width: 200px; background: rgba(46,204,113,0.12); border: 2px solid rgba(46,204,113,0.5); border-radius: 12px; padding: 18px; text-align: center; }}
    .snow-title {{ font-size: 0.85em; text-transform: uppercase; letter-spacing: 0.5px; opacity: 0.8; margin-bottom: 8px; font-weight: bold; }}
    .snow-value {{ font-size: 1.7em; font-weight: 900; margin-bottom: 5px; }}
    .snow-sub {{ font-size: 0.85em; opacity: 0.9; font-weight: 600; color: #2ecc71; }}
    .snow-banner {{ background: linear-gradient(90deg, rgba(46,204,113,0.15) 0%, rgba(52,152,219,0.15) 100%); border-left: 5px solid #2ecc71; padding: 15px 20px; border-radius: 8px; margin-bottom: 20px; font-size: 1.02em; }}
    </style>

    <div class="snow-banner">
        <div>{texte_objectif}</div>
        <div style="margin-top: 6px; font-size: 0.92em; opacity: 0.9;">{texte_bascule}</div>
    </div>

    <div class="snow-container">
        <div class="snow-card">
            <div class="snow-title">🏦 Patrimoine dans {annees_max} ans</div>
            <div class="snow-value">{cap_total:,.0f} €</div>
            <div class="snow-sub">Dont {effort_cumule:,.0f} € sortis de votre poche</div>
        </div>
        <div class="snow-card-highlight">
            <div class="snow-title">❄️ Gains Purs « Boule de Neige »</div>
            <div class="snow-value">+{gains_boule_de_neige:,.0f} €</div>
            <div class="snow-sub">🔥 {part_gratuite_pct:.1f}% du capital créé gratuitement</div>
        </div>
        <div class="snow-card-highlight">
            <div class="snow-title">💸 Future Rente Passive</div>
            <div class="snow-value">{rente_finale_mois:,.0f} € / mois</div>
            <div class="snow-sub">🚀 Multipliée par x{multiplicateur_rente:.1f} vs aujourd'hui</div>
        </div>
    </div>
    """
    st.markdown(html_snowball, unsafe_allow_html=True)

    col_g1, col_g2 = st.columns(2)
    with col_g1:
      st.markdown("**📈 L'Écart Magique : Patrimoine Total vs Votre Effort (DCA)**")
      st.caption("La zone supérieure représente la richesse créée uniquement par l'effet Boule de Neige :")
      st.area_chart({
          "1. Votre Effort d'Épargne Cumulé (€)": series_effort,
          "2. Patrimoine Total avec Boule de Neige (€)": series_boule_de_neige,
      })

    with col_g2:
      st.markdown("**💰 Explosion de votre Rente Mensuelle (€ / mois)**")
      st.caption(f"Accélération de vos dividendes mensuels face à votre objectif ({objectif_rente} €/mois) :")
      st.bar_chart({
          "Rente Mensuelle Générée (€/mois)": series_rente_mensuelle,
      })

    with st.expander("📋 Voir le détail chiffré année par année (Tableau des Paliers)", expanded=True):
      st.dataframe(tableau_croissance, use_container_width=True)


# ------------------------------------------------------------------------------
# ONGLET 4 : COACH QUANTITATIF & AGENT IA INTERACTIF
# ------------------------------------------------------------------------------
with onglet_ia:
  st.subheader("🤖 Audit Patrimonial Pointu & Agent IA Interactif")

  if not portefeuille_utilisateur:
    st.warning(
        "Veuillez d'abord renseigner votre portefeuille dans l'onglet 2 pour"
        " activer l'Audit Quantitatif et l'Agent IA."
    )
  else:
    lignes_valides = [nom for nom in portefeuille_utilisateur if nom in WATCHLIST]
    nb_lignes = len(lignes_valides)

    payouts_moy = (
        sum(WATCHLIST[nom]["payout_ratio"] for nom in lignes_valides) / nb_lignes
        if nb_lignes > 0 else 0
    )

    tous_les_mois = ["Jan", "Fév", "Mar", "Avr", "Mai", "Juin", "Juil", "Août", "Sep", "Oct", "Nov", "Déc"]
    mois_couverts = set()
    for nom in lignes_valides:
      for m in WATCHLIST[nom].get("mois_div", []):
        mois_couverts.add(m)
    mois_creux = [m for m in tous_les_mois if m not in mois_couverts]

    poids_max_nom, poids_max_val = "", 0.0
    analyse_detaillee_lignes = []
   
    tech_map = {d["Actif"]: d for d in donnees_t1}

    for nom in lignes_valides:
      qte = portefeuille_utilisateur[nom]["qte"]
      pru = portefeuille_utilisateur[nom]["pru"]
      prix_j = prix_temps_reel.get(nom, WATCHLIST[nom]["prix_cible"])
      val_l = qte * prix_j
      poids_l = (val_l / valeur_totale_portefeuille * 100) if valeur_totale_portefeuille > 0 else 0
      pv_l_pct = ((prix_j - pru) / pru * 100) if pru > 0 else 0
      yoc_l = (WATCHLIST[nom]["div_eur"] / pru * 100) if pru > 0 else 0
     
      if poids_l > poids_max_val:
        poids_max_val = poids_l
        poids_max_nom = nom

      rsi_actuel = tech_map.get(nom, {}).get("RSI", 50)
      score_actuel = tech_map.get(nom, {}).get("Score", 0)
      decision_actuelle = tech_map.get(nom, {}).get("Décision", "N/A")

      analyse_detaillee_lignes.append(
          f"- {nom} ({WATCHLIST[nom]['secteur']}) : {qte} actions | PRU: {pru}€ | Cours: {prix_j:.2f}€ "
          f"| Poids: {poids_l:.1f}% | P/V: {pv_l_pct:+.1f}% | Yield sur PRU: {yoc_l:.2f}% "
          f"| Payout: {WATCHLIST[nom]['payout_ratio']*100:.0f}% | RSI: {rsi_actuel} | Signal: {decision_actuelle}"
      )

    score_sante = 0
    score_sante += min(30, nb_lignes * 5) 
    score_sante += 30 if payouts_moy <= 0.60 else (15 if payouts_moy <= 0.75 else 5) 
    score_sante += 20 if poids_max_val <= 25 else (10 if poids_max_val <= 35 else 0) 
    score_sante += min(20, int(len(mois_couverts) * 1.7)) 

    c_ia1, c_ia2, c_ia3, c_ia4 = st.columns(4)
    c_ia1.metric("Score Santé Globale", f"{score_sante} / 100", "🌟 Solide" if score_sante >= 75 else "⚖️ Perfectible")
    c_ia2.metric("Sûreté Dividendes (Payout)", f"{payouts_moy*100:.1f} %", "🛡️ Sain (<60%)" if payouts_moy <= 0.60 else "⚠️ Élevé")
    c_ia3.metric("Plus Forte Concentration", f"{poids_max_val:.1f} %", f"Ligne : {poids_max_nom}")
    c_ia4.metric("Couverture Calendrier", f"{len(mois_couverts)} / 12 mois", f"{len(mois_creux)} mois sans versement")

    st.markdown("---")
    st.subheader("🔬 Rapports d'Analyse Croisée (Portefeuille vs Marché)")

    col_diag1, col_diag2 = st.columns(2)

    with col_diag1:
      st.markdown("#### 🎯 Diagnostic Structurel & Cash-Flow")
      if poids_max_val > 25:
        st.warning(
            f"**Risque de concentration sur {poids_max_nom} ({poids_max_val:.1f}%)** : "
            f"Évitez de renforcer cette ligne avec votre DCA de {BUDGET_MENSUEL:.0f} € tant que les autres positions n'ont pas rééquilibré le poids sous les 25 %."
        )
      else:
        st.success(
            f"**Allocation équilibrée** : Votre première ligne ({poids_max_nom}) pèse {poids_max_val:.1f} %, ce qui protège votre capital contre un choc spécifique."
        )

      if mois_creux:
        st.info(
            f"**Optimisation du Calendrier** : Vous ne touchez aucun dividende en **{', '.join(mois_creux)}**. "
            "Pour lisser votre rente, ciblez des entreprises à acomptes trimestriels ou décalés."
        )
      else:
        st.success("**Rente 12/12** : Votre portefeuille génère des flux financiers chaque mois de l'année.")

    with col_diag2:
      st.markdown("#### ⚡ Signaux Techniques sur vos Lignes Détenues")
      alertes_trouvees = False
      for nom in lignes_valides:
        qte = portefeuille_utilisateur[nom]["qte"]
        pru = portefeuille_utilisateur[nom]["pru"]
        prix_j = prix_temps_reel.get(nom, WATCHLIST[nom]["prix_cible"])
        rsi_j = tech_map.get(nom, {}).get("RSI", 50)
       
        if prix_j < pru and rsi_j < 40:
          st.success(
              f"🟢 **Opportunité de baisse de PRU sur {nom}** : Le cours actuel ({prix_j:.2f} €) est sous votre PRU ({pru:.2f} €) avec un RSI bas ({rsi_j}). Renforcer maintenant abaissera votre point mort tout en dopant votre rendement sur coût."
          )
          alertes_trouvees = True
        elif prix_j > pru * 1.25 and rsi_j > 68:
          st.warning(
              f"🔥 **Surchauffe sur {nom}** : Vous êtes à +{((prix_j-pru)/pru*100):.1f}% de plus-value avec un RSI tendu ({rsi_j}). Mettez le DCA en pause sur cette valeur."
          )
          alertes_trouvees = True

      if not alertes_trouvees:
        st.write("✅ Aucun excès technique majeur (surachat ou décote extrême sous PRU) détecté aujourd'hui sur vos lignes en portefeuille.")

    st.markdown("---")

    st.subheader("💬 Discuter avec votre Conseiller IA Privé")
    st.caption(
        "Posez n'importe quelle question : l'Agent IA connaît en temps réel vos lignes, vos PRU, vos dividendes et les indicateurs techniques du jour."
    )

    opportunites_radar = [
        f"{d['Actif']} (Prix: {d['Prix (€)']}€, Cible: {d['Prix Cible (€)']}€, RSI: {d['RSI']}, Score: {d['Score']}/100, Décision: {d['Décision']})"
        for d in donnees_t1
    ]

    contexte_systeme = f"""Tu es un ingénieur financier et gestionnaire de patrimoine expert du PEA (Plan d'Épargne en Actions) et des stratégies de rendement (Dividendes & DCA).
Tu t'adresses directement à l'utilisateur de la plateforme. Ton ton est professionnel, précis, chiffré, bienveillant et très structuré.

Voici les données EXACTES en temps réel du portefeuille de l'utilisateur :
- Valorisation totale : {valeur_totale_portefeuille:.2f} € (Capital investi : {cout_total_achat:.2f} €, Plus-value : {plus_value_globale:+.2f} € soit {plus_value_pct:+.1f}%)
- Dividendes annuels générés : {dividendes_annuels_totaux:.2f} €/an (soit {dividendes_annuels_totaux/12:.2f} €/mois) | Yield on Cost (Rendement sur PRU) : {yoc_global:.2f}%
- Budget DCA mensuel : {BUDGET_MENSUEL:.0f} €/mois
- Mois sans aucun dividende : {', '.join(mois_creux) if mois_creux else 'Aucun'}

Détail des lignes détenues en portefeuille :
{chr(10).join(analyse_detaillee_lignes)}

Radar complet des valeurs suivies aujourd'hui (avec indicateurs techniques temps réel) :
{chr(10).join(opportunites_radar)}

Réponds toujours en utilisant précisément ces chiffres. Donne des analyses pointues (marge de sécurité, effet sur le PRU, exposition sectorielle, pérennité du payout ratio) tout en rappelant brièvement que cela constitue une aide à la décision et non un conseil financier réglementé."""

    if "messages_ia" not in st.session_state:
      st.session_state["messages_ia"] = [
          {
              "role": "assistant",
              "content": (
                  f"Bonjour ! J'ai analysé vos **{nb_lignes} lignes** en portefeuille "
                  f"(valorisées à **{valeur_totale_portefeuille:,.0f} €** pour **{dividendes_annuels_totaux/12:.1f} €/mois** de dividendes). "
                  "Souhaitez-vous que l'on optimise l'investissement de vos prochains **"
                  f"{BUDGET_MENSUEL:.0f} €**, que l'on analyse une valeur précise, ou que l'on regarde comment combler vos mois creux ?"
              ),
          }
      ]

    col_q1, col_q2, col_q3 = st.columns(3)
    question_rapide = None
    if col_q1.button("💡 Optimiser mon DCA du mois", use_container_width=True):
      question_rapide = f"Avec mon budget DCA de {BUDGET_MENSUEL:.0f} € ce mois-ci, quelles actions précises dois-je acheter en priorité pour optimiser mon rendement et renforcer mes lignes sous leur PRU ?"
    if col_q2.button("🛡️ Analyser les risques de mon PEA", use_container_width=True):
      question_rapide = "Fais-moi un audit critique et sans complaisance des vulnérabilités de mon portefeuille actuel (concentration sectorielle, payout ratio, écart au PRU)."
    if col_q3.button("🗓️ Combler mes mois sans dividendes", use_container_width=True):
      question_rapide = f"Quelles valeurs de ma watchlist me permettraient de toucher des dividendes pendant mes mois creux ({', '.join(mois_creux)}) tout en ayant un bon score technique aujourd'hui ?"

    for msg in st.session_state["messages_ia"]:
      with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

user_prompt = st.chat_input("Posez votre question financière à l'Agent IA...")
question_finale = question_rapide or user_prompt

if question_finale:
    st.session_state["messages_ia"].append({"role": "user", "content": question_finale})
    with st.chat_message("user"):
        st.markdown(question_finale)

    with st.chat_message("assistant"):
        with st.spinner("Analyse des marchés et de votre portefeuille en cours..."):
            api_key = (
                str(st.secrets.get("GEMINI_API_KEY", "")).strip().strip('"').strip("'")
                if hasattr(st, "secrets")
                else ""
            )

            if not api_key:
                reponse_ia = (
                    "⚠️ **Clé API Gemini non détectée.** Pour activer mes réponses en direct, "
                    "ajoutez `GEMINI_API_KEY = \"votre_cle\"` dans les **Secrets** de Streamlit Cloud (gratuit sur aistudio.google.com)."
                )
            else:
                payload_ia = {
                    "system_instruction": {"parts": [{"text": contexte_systeme}]},
                    "contents": [
                        {
                            "role": "user" if m["role"] == "user" else "model",
                            "parts": [{"text": m["content"]}],
                        }
                        for m in st.session_state["messages_ia"]
                    ],
                }

                modeles_candidats = [
                    "gemini-2.5-flash",
                    "gemini-2.0-flash",
                    "gemini-flash-latest",
                    "gemini-2.5-pro",
                    "gemini-pro-latest",
                ]

                try:
                    url_liste = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
                    with urllib.request.urlopen(url_liste, timeout=10) as resp_liste:
                        data_liste = json.loads(resp_liste.read().decode("utf-8"))
                        for mod in data_liste.get("models", []):
                            nom_mod = mod.get("name", "").replace("models/", "")
                            methodes = mod.get("supportedGenerationMethods", [])
                            if "generateContent" in methodes and "gemini" in nom_mod:
                                if nom_mod not in modeles_candidats:
                                    modeles_candidats.append(nom_mod)
                except Exception:
                    pass

                reponse_ia = None
                derniere_erreur = ""

                for modele in modeles_candidats:
                    try:
                        url_gemini = f"https://generativelanguage.googleapis.com/v1beta/models/{modele}:generateContent?key={api_key}"
                        req_ia = urllib.request.Request(
                            url_gemini,
                            data=json.dumps(payload_ia).encode("utf-8"),
                            headers={"Content-Type": "application/json"},
                        )
                        with urllib.request.urlopen(req_ia, timeout=25) as resp_ia:
                            res_json = json.loads(resp_ia.read().decode("utf-8"))
                            reponse_ia = res_json["candidates"][0]["content"]["parts"][0]["text"]
                            break
                    except Exception as e:
                        derniere_erreur = str(e)
                        continue

                if not reponse_ia:
                    reponse_ia = f"❌ Erreur de communication avec le moteur IA : {derniere_erreur}"

            st.markdown(reponse_ia)
            st.session_state["messages_ia"].append({"role": "assistant", "content": reponse_ia})
