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
  support_30j = min(bas[-30:]) if len(bas) >= 30 else min(bas)
  resistance_30j = max(hauts[-30:]) if len(hauts) >= 30 else max(hauts)

  distance_cible_pct = ((prix_actuel - prix_cible) / prix_cible) * 100

  score = 0
  if prix_actuel <= prix_cible:
    score += 25
  elif prix_actuel <= prix_cible * 1.05:
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

  est_surevalue = prix_actuel >= prix_cible * 1.20 and (
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
      "Secteur": info["secteur"],
      "Prix (€)": round(prix_actuel, 2),
      "Prix Cible (€)": round(prix_cible, 2),
      "Écart Cible (%)": dist_str,
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
      "Croissance 5a": info["croissance_5a"],
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
    "📅 3. Dividendes & Boule de Neige",
    "🤖 4. Coach & Audit IA",
])

# ------------------------------------------------------------------------------
# ONGLET 1 : RADAR & AIDE À L'ACHAT
# ------------------------------------------------------------------------------
with onglet_radar:
  if mode_gratuit:
    st.warning(
        "🔒 **Aperçu Gratuit (Freemium)** : Vous visualisez actuellement 2"
        " actions de démonstration (TotalEnergies et Air Liquide). Passez à"
        " l'abonnement complet pour débloquer toutes les valeurs du PEA !"
    )

  col1, col2, col3, col4 = st.columns(4)
  nb_opportunites = sum(
      1
      for d in donnees_t1
      if "ACHAT" in d["Décision"] or "ACCUMULATION" in d["Décision"]
  )
  nb_croisements = sum(1 for d in donnees_t1 if "Croisement" in d["EMA 2/12"])

  col1.metric(
      "Opportunités d'Achat", f"{nb_opportunites} / {len(actions_autorisees)}"
  )
  col2.metric("Signaux EMA 2/12", f"{nb_croisements} Actif(s)")
  col3.metric("Budget DCA Configuré", f"{BUDGET_MENSUEL:.0f} €")
  col4.metric("Rente Mensuelle Générée", f"+{montant_tot_div/12:.2f} €/mois")

  st.markdown("---")

  st.subheader("🔎 Filtrer ou rechercher une valeur")
  options_filtre = ["📋 Afficher toutes les actions"] + actions_autorisees
  choix_action = st.selectbox(
      "Choisissez une action dans la liste (ou tapez son nom) :",
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

  st.subheader("📊 Tableau 1 : Timing & Momentum (Aide à la Décision)")
  st.dataframe(t1_filtre, use_container_width=True)

  st.markdown("---")

  st.subheader("📋 Tableaux d'Analyse Approfondie & DCA")
  tab_val, tab_tech, tab_div, tab_dca = st.tabs([
      "📐 Tableau 2 : Analyse Value",
      "🎯 Tableau 4 : Niveaux Techniques",
      "🛡️ Tableau 3 : Rente & Dividendes",
      "💰 Allocation DCA du Mois",
  ])

  with tab_val:
    st.subheader("📐 Écart à la Régression Linéaire")
    st.dataframe(t2_filtre, use_container_width=True)

  with tab_tech:
    st.subheader("🎯 Niveaux 30 Jours (Supports & Résistances)")
    st.dataframe(t4_filtre, use_container_width=True)

  with tab_div:
    st.subheader("🛡️ Sûreté des Dividendes & Payout Ratio")
    st.dataframe(t3_filtre, use_container_width=True)

  with tab_dca:
    st.subheader("💡 Allocation Suggérée en Actions Entières")
    if not candidats_tries:
      st.warning(
          "Aucune action n'atteint le seuil d'achat ce mois-ci (Scores < 40)."
      )
    else:
      allocation_data = []
      total_investi = 0
      total_div_an = 0

      for item in candidats_tries:
        nb = achats_simules[item["nom"]]
        if nb > 0:
          montant_eff = nb * item["prix"]
          div_gen = nb * item["div_eur"]
          total_investi += montant_eff
          total_div_an += div_gen

          allocation_data.append({
              "Actif": item["nom"],
              "Prix Actuel (€)": f"{item['prix']:.2f} €",
              "Actions à Acheter": nb,
              "Montant Effectif (€)": f"{montant_eff:.2f} €",
              "Rente Annuelle Générée (€)": f"+{div_gen:.2f} €/an",
          })

      if allocation_data:
        st.dataframe(allocation_data, use_container_width=True)
        st.success(
            f"💰 **Total investi ce mois-ci :** {total_investi:.2f} € /"
            f" {BUDGET_MENSUEL:.2f} € (Liquidités restantes :"
            f" {budget_courant:.2f} €)\n"
            f"📈 **Rente annuelle créée :** +{total_div_an:.2f} €/an"
        )
      else:
        st.warning(
            "Le budget mensuel est trop faible pour acheter une action entière"
            " de ces valeurs."
        )

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
        "Cours Réel": closes,
        "Tendance 3 Ans (Régression)": droite_reg,
    })

# ------------------------------------------------------------------------------
# ONGLET 2 : MON PORTEFEUILLE & SECTEURS
# ------------------------------------------------------------------------------
portefeuille_utilisateur = {}
with onglet_portefeuille:
  st.subheader("💼 Gestionnaire de Portefeuille & Répartition Sectorielle")

  if mode_gratuit:
    st.info(
        "💡 **Aperçu Pro** : En mode gratuit, vous pouvez tester le"
        " simulateur ci-dessous. L'abonnement permettra de sauvegarder votre"
        " portefeuille et de débloquer l'Audit IA."
    )

  with st.expander(
      "✏️ Saisir ou modifier mes actions détenues (Quantité & PRU)",
      expanded=False,
  ):
    st.caption(
        "Indiquez le nombre d'actions que vous possédez dans votre PEA et votre"
        " Prix de Revient Unitaire (PRU). Mettez 0 si vous ne possédez pas"
        " l'action."
    )
    cols_saisie = st.columns(3)

    for idx, (nom_act, info_act) in enumerate(WATCHLIST.items()):
      col_active = cols_saisie[idx % 3]
      with col_active:
        st.markdown(f"**{nom_act}** *({info_act['secteur']})*")
        qte_defaut = PORTEFEUILLE_DEFAUT.get(nom_act, {}).get("qte", 0)
        pru_defaut = PORTEFEUILLE_DEFAUT.get(nom_act, {}).get(
            "pru", float(info_act["prix_cible"])
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
            min_value=1.0,
            max_value=5000.0,
            value=float(pru_defaut),
            step=0.5,
            key=f"pru_{nom_act}",
        )
        if qte_saisie > 0:
          portefeuille_utilisateur[nom_act] = {
              "qte": qte_saisie,
              "pru": pru_saisi,
          }
        st.markdown("---")

  if not portefeuille_utilisateur:
    st.warning(
        "Votre portefeuille est vide. Cliquez sur le menu « ✏️ Saisir ou"
        " modifier mes actions détenues » juste au-dessus pour ajouter vos"
        " premières actions !"
    )
  else:
    lignes_portefeuille = []
    repartition_secteurs = {}
    valeur_totale_portefeuille = 0.0
    cout_total_achat = 0.0
    dividendes_annuels_totaux = 0.0

    for nom_act, data_pos in portefeuille_utilisateur.items():
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

    c_p1, c_p2, c_p3, c_p4 = st.columns(4)
    c_p1.metric(
        "Valorisation Totale PEA", f"{valeur_totale_portefeuille:,.2f} €"
    )
    c_p2.metric(
        "Plus/Moins-Value Latente",
        f"{plus_value_globale:+,.2f} €",
        f"{plus_value_pct:+.1f}%",
    )
    c_p3.metric(
        "Dividendes Annuels Estimés",
        f"{dividendes_annuels_totaux:,.2f} € / an",
        f"Soit {dividendes_annuels_totaux/12:.1f} €/mois",
    )
    c_p4.metric(
        "Rendement sur PRU (Yield on Cost)",
        f"{yoc_global:.2f} %",
        f"Capital investi : {cout_total_achat:,.0f} €",
    )

    st.markdown("---")

    alertes_concentration = []
    for nom_act, data_pos in portefeuille_utilisateur.items():
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

      statut_pv = "🟢" if pv_eur >= 0 else "🔴"

      lignes_portefeuille.append({
          "Action": nom_act,
          "Secteur": info_act["secteur"],
          "Qté": qte,
          "PRU (€)": round(pru, 2),
          "Cours Actuel (€)": round(prix_jour, 2),
          "Valorisation (€)": round(val_ligne, 2),
          "+/- Value (€)": f"{statut_pv} {pv_eur:+.2f} € ({pv_pct:+.1f}%)",
          "Rendement/PRU": f"{yoc_ligne:.2f}%",
          "Dividendes (€/an)": f"{div_ligne:.2f} €",
          "Poids (%)": f"{poids_pct:.1f}%",
      })

    st.subheader("📋 Détail de mes lignes en portefeuille")
    st.dataframe(lignes_portefeuille, use_container_width=True)

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
    col_graph, col_tab_sec = st.columns([3, 2])

    with col_graph:
      st.caption("Valorisation (€) par secteur d'activité :")
      st.bar_chart(repartition_secteurs)

    with col_tab_sec:
      st.caption("Poids de chaque secteur (%) :")
      tableau_secteurs = []
      for sec, val_sec in sorted(
          repartition_secteurs.items(), key=lambda x: x[1], reverse=True
      ):
        poids_sec = (val_sec / valeur_totale_portefeuille) * 100
        etat_sec = "⚠️ Fort (>35%)" if poids_sec > 35 else "✅ Équilibré"
        tableau_secteurs.append({
            "Secteur": sec,
            "Montant (€)": f"{val_sec:,.2f} €",
            "Poids (%)": f"{poids_sec:.1f}%",
            "Diagnostic": etat_sec,
        })
      st.dataframe(tableau_secteurs, use_container_width=True)

# ------------------------------------------------------------------------------
# ONGLET 3 : DIVIDENDES & BOULE DE NEIGE
# ------------------------------------------------------------------------------
with onglet_dividendes:
  st.subheader("📅 Calendrier des Dividendes & Projection Boule de Neige")

  if not portefeuille_utilisateur:
    st.warning(
        "Veuillez d'abord saisir vos actions dans l'onglet « 💼 Mon"
        " Portefeuille & Secteurs » pour afficher vos projections de"
        " dividendes."
    )
  else:
    # Calcul des dividendes totaux annuels et mensuels
    total_div_an = sum(
        data["qte"] * WATCHLIST[nom]["div_eur"]
        for nom, data in portefeuille_utilisateur.items()
    )
    total_div_mois = total_div_an / 12

    col_d1, col_d2, col_d3 = st.columns(3)
    col_d1.metric("Rente Annuelle Totale", f"{total_div_an:,.2f} € / an")
    col_d2.metric("Moyenne Mensuelle", f"{total_div_mois:,.2f} € / mois")
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

    st.subheader("📋 Répartition des versements annuels par action")
    tableau_dividendes_lignes = []
    for nom, data in portefeuille_utilisateur.items():
      qte = data["qte"]
      div_unit = WATCHLIST[nom]["div_eur"]
      total_ligne = qte * div_unit
      poids_div = (
          (total_ligne / total_div_an) * 100 if total_div_an > 0 else 0
      )
      tableau_dividendes_lignes.append({
          "Action": nom,
          "Secteur": WATCHLIST[nom]["secteur"],
          "Quantité": qte,
          "Dividende/Act. (€)": f"{div_unit:.2f} €",
          "Total Annuel (€)": f"{total_ligne:,.2f} €",
          "Part des Revenus (%)": f"{poids_div:.1f}%",
      })

    st.dataframe(tableau_dividendes_lignes, use_container_width=True)

    st.markdown("---")
    st.subheader(
        "🔮 Simulateur « Boule de Neige » (Projection à 5, 10 et 15 ans)"
    )
    st.caption(
        "Projection basée sur le réinvestissement automatique des dividendes et"
        f" votre effort d'épargne DCA mensuel ({BUDGET_MENSUEL:.0f} €/mois),"
        " avec un rendement moyen estimé à 5% par an."
    )

    annees_simulation = [5, 10, 15]
    resultats_boule_de_neige = []

    capital_actuel = valeur_totale_portefeuille
    rendement_estime = (
        rendement_moyen_portefeuille / 100
        if rendement_moyen_portefeuille > 0
        else 0.04
    )

    for an in annees_simulation:
      cap = capital_actuel
      div_an = total_div_an
      for mois in range(an * 12):
        epargne_mois = BUDGET_MENSUEL + (div_an / 12)
        cap += epargne_mois
        div_an = cap * rendement_estime

      resultats_boule_de_neige.append({
          "Horizon": f"À {an} ans",
          "Capital Estimé (€)": f"{cap:,.2f} €",
          "Rente Annuelle Estimée (€/an)": f"{div_an:,.2f} € / an",
          "Rente Mensuelle Équivalente": f"{div_an/12:,.2f} € / mois",
      })

    st.dataframe(resultats_boule_de_neige, use_container_width=True)

# ------------------------------------------------------------------------------
# ONGLET 4 : COACH & AUDIT IA
# ------------------------------------------------------------------------------
with onglet_ia:
  st.subheader("🤖 Diagnostic & Coach IA de votre Portefeuille")
  st.info(
      "🚧 **Prochaine étape de construction** : Un bouton vous permettra ici de"
      " lancer une analyse complète de votre portefeuille par Intelligence"
      " Artificielle (score de diversification, risques et pistes"
      " d'équilibrage)."
  )
