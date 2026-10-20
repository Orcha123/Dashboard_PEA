from datetime import datetime
import json
import math
import urllib.request
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
      e26 = (prix * k26) + (e26 * (1 - k
