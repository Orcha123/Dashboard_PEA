from datetime import datetime
import json
import math
import urllib.request
import plotly.express as px
import streamlit as st

# Configuration de la page
st.set_page_config(
    page_title="Suite Boursière PEA & Dividendes",
    page_icon="📈",
    layout="wide",
)

st.title("📈 Plateforme Boursière PEA - Aide à la Décision & Patrimoine")
st.caption(
    "Dernière mise à jour des marchés :"
    f" {datetime.now().strftime('%d/%m/%Y à %H:%M')}"
)

# --- WATCHLIST PEA ---
WATCHLIST = {
    "TotalEnergies": {
        "symbole": "TTE.PA",
        "prix_cible": 50.0,
        "secteur": "Énergie",
        "div_eur": 3.22,
        "payout_ratio": 0.42,
        "croissance_5a": "+6.1%",
    },
    "Air Liquide": {
        "symbole": "AI.PA",
        "prix_cible": 140.0,
        "secteur": "Chimie/Industrie",
        "div_eur": 3.12,
        "payout_ratio": 0.55,
        "croissance_5a": "+8.5%",
    },
    "Vinci": {
        "symbole": "DG.PA",
        "prix_cible": 95.0,
        "secteur": "Concessions/BTP",
        "div_eur": 4.50,
        "payout_ratio": 0.58,
        "croissance_5a": "+7.0%",
    },
    "Engie": {
        "symbole": "ENGI.PA",
        "prix_cible": 18.0,
        "secteur": "Utilités/Énergie",
        "div_eur": 1.43,
        "payout_ratio": 0.68,
        "croissance_5a": "+5.0%",
    },
    "Sanofi": {
        "symbole": "SAN.PA",
        "prix_cible": 70.0,
        "secteur": "Santé",
        "div_eur": 3.76,
        "payout_ratio": 0.65,
        "croissance_5a": "+4.8%",
    },
    "LVMH": {
        "symbole": "MC.PA",
        "prix_cible": 380.0,
        "secteur": "Luxe",
        "div_eur": 13.00,
        "payout_ratio": 0.48,
        "croissance_5a": "+12.0%",
    },
    "Pernod Ricard": {
        "symbole": "RI.PA",
        "prix_cible": 60.0,
        "secteur": "Consommation",
        "div_eur": 4.70,
        "payout_ratio": 0.52,
        "croissance_5a": "+6.5%",
    },
    "Rubis": {
        "symbole": "RUI.PA",
        "prix_cible": 24.0,
        "secteur": "Énergie/Stockage",
        "div_eur": 1.92,
        "payout_ratio": 0.72,
        "croissance_5a": "+3.2%",
    },
    "BNP Paribas": {
        "symbole": "BNP.PA",
        "prix_cible": 55.0,
        "secteur": "Finance",
        "div_eur": 4.60,
        "payout_ratio": 0.50,
        "croissance_5a": "+8.0%",
    },
    "Schneider Electric": {
        "symbole": "SU.PA",
        "prix_cible": 180.0,
        "secteur": "Industrie/Tech",
        "div_eur": 3.50,
        "payout_ratio": 0.50,
        "croissance_5a": "+9.2%",
    },
    "Veolia": {
        "symbole": "VIE.PA",
        "prix_cible": 28.0,
        "secteur": "Utilités/Environnement",
        "div_eur": 1.25,
        "payout_ratio": 0.62,
        "croissance_5a": "+5.5%",
    },
}

# --- PORTEFEUILLE PAR DÉFAUT ---
PORTEFEUILLE_DEFAUT = {
    "TotalEnergies": {"qte": 25, "pru": 54.0},
    "Air Liquide": {"qte": 10, "pru": 155.0},
    "Vinci": {"qte": 12, "pru": 98.0},
    "Sanofi": {"qte": 10, "pru": 86.0},
    "BNP Paribas": {"qte": 15, "pru": 58.0},
}

# --- BARRE LATÉRALE ---
st.sidebar.header("⚙️ Paramètres DCA")
BUDGET_MENSUEL = st.sidebar.number_input(
    "Enveloppe Mensuelle (€)",
    min_value=50.0,
    max_value=5000.0,
    value=450.0,
    step=50.0,
)

st.sidebar.markdown("---")
st.sidebar.header("🔐 Mode d'accès (Test)")
mode_gratuit = st.sidebar.checkbox(
    "Simuler la vue Visiteur Gratuit (Freemium)", value=False
)

if mode_gratuit:
  actions_autorisees = ["TotalEnergies", "Air Liquide"]
  st.sidebar.info(
      f"🔒 **Mode Découverte actif** : 2 valeurs débloquées sur {len(WATCHLIST)}."
  )
else:
  actions_autorisees = list(WATCHLIST.keys())
  st.sidebar.success(
      f"💎 **Mode Abonné Pro actif** : {len(WATCHLIST)} valeurs débloquées."
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

  rendement_actuel = info["div_eur"] / prix_actuel
  prix_cible = info["prix_cible"]
  plus_haut_52s = max(hauts) if hauts else prix_actuel
  rsi = calculer_rsi(closes)
  borne_inf, borne_sup = calculer_bollinger(closes)
  macd_val, macd_sig = calculer_macd(closes)
  croisement_2_12 = verifier_croisement_2_12(closes)
  val_reg, ecart_reg_pct, droite_reg = calculer_regression_lineaire(closes)
