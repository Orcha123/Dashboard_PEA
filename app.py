import urllib.request
import urllib.parse
import json
import math
import re
from datetime import datetime
import streamlit as st
from supabase import create_client

# Configuration de la page
st.set_page_config(
    page_title="Suite Boursière PEA & Dividendes",
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

# --- FONCTION DE SAUVEGARDE CLOUD ---
def sauvegarder_dans_cloud():
    if supabase and st.session_state["user"]:
        try:
            payload = {
                "user_id": st.session_state["user"].id,
                "email": st.session_state["user"].email,
                "budget_dca": st.session_state["budget_dca"],
                "watchlist": st.session_state["watchlist"],
                "portefeuille": st.session_state["portefeuille"],
                "updated_at": datetime.utcnow().isoformat()
            }
            supabase.table("user_data").upsert(payload).execute()
            return True
        except Exception as e:
            st.sidebar.error(f"Erreur de sauvegarde Cloud : {e}")
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
                   
                    # Récupération du profil dans la base de données
                    data = supabase.table("user_data").select("*").eq("user_id", res.user.id).execute()
                    if data.data:
                        profil = data.data[0]
                        st.session_state["watchlist"] = profil.get("watchlist") or WATCHLIST_DEFAUT.copy()
                        st.session_state["portefeuille"] = profil.get("portefeuille") or PORTEFEUILLE_DEFAUT.copy()
                        st.session_state["budget_dca"] = float(profil.get("budget_dca") or 450.0)
                        st.session_state["est_abonne_pro"] = bool(profil.get("est_abonne_pro", False))
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
        col_btn1, col_btn2 = st.sidebar.columns(2)
        if col_btn1.button("💾 Sauver", use_container_width=True):
            if sauvegarder_dans_cloud():
                st.sidebar.toast("✅ Profil sauvegardé dans le Cloud !")
        if col_btn2.button("🚪 Sortir", use_container_width=True):
            supabase.auth.sign_out()
            st.session_state["user"] = None
            st.rerun()

WATCHLIST = st.session_state["watchlist"]

st.title("📈 Plateforme Boursière PEA - Aide à la Décision & Patrimoine")
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

# --- RECHERCHE INTELLIGENTE & AJOUT (HYBRIDE) ---
def chercher_sur_yahoo(query):
    if not query:
        return []
    url = f"https://query2.finance.yahoo.com/v1/finance/search?q={urllib.parse.quote(query)}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())
            quotes = data.get("quotes", [])
            resultats = []
            for q in quotes:
                if q.get("quoteType") in ["EQUITY", "ETF"]:
                    nom = q.get("shortname", q.get("longname", "Inconnu"))
                    symbole = q.get("symbol", "")
                    bourse = q.get("exchDisp", "")
                    resultats.append(f"{nom} ({symbole}) - {bourse}")
            return resultats
    except Exception:
        return []

st.sidebar.markdown("---")
st.sidebar.subheader("🔍 Ajouter / Gérer les actions")

recherche_query = st.sidebar.text_input("1. Rechercher une entreprise :", placeholder="ex: Apple, Total, Axa...")

if recherche_query:
    resultats_recherche = chercher_sur_yahoo(recherche_query)
   
    if resultats_recherche:
        with st.sidebar.form("formulaire_hybride"):
            choix_action = st.selectbox("2. Confirmez l'action :", resultats_recherche)
           
            st.markdown("**3. Personnalisez vos données :**")
            nouveau_secteur = st.text_input("Secteur (ex: Tech, Banque)", value="À définir")
            nouveau_cible = st.number_input("Prix cible (€ ou $)", min_value=0.0, value=0.0, step=1.0)
            nouveau_div = st.number_input("Dividende annuel (€)", min_value=0.0, value=0.0, step=0.1)
            nouveau_payout = st.number_input("Payout Ratio (ex: 0.50)", min_value=0.0, max_value=2.0, value=0.0, step=0.05)
           
            liste_mois_possibles = ["Jan", "Fév", "Mar", "Avr", "Mai", "Juin", "Juil", "Août", "Sep", "Oct", "Nov", "Déc"]
            nouveau_mois = st.multiselect("Mois de versement :", liste_mois_possibles)
           
            submit_ajout = st.form_submit_button("➕ Ajouter et Sauvegarder")
           
            if submit_ajout:
                match = re.search(r"^(.*) \((.*?)\)", choix_action)
                if match:
                    nom_trouve = match.group(1).strip()
                    symbole_trouve = match.group(2).strip()
                   
                    st.session_state["watchlist"][nom_trouve] = {
                        "symbole": symbole_trouve,
                        "prix_cible": nouveau_cible,
                        "secteur": nouveau_secteur,
                        "div_eur": nouveau_div,
                        "payout_ratio": nouveau_payout,
                        "croissance_5a": "N/A",
                        "mois_div": nouveau_mois
                    }
                    sauvegarder_dans_cloud()
                    st.rerun()
    else:
        st.sidebar.warning("Aucune action trouvée. Essayez un autre mot-clé.")

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
