import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import requests
from supabase import create_client, Client

# 1. Configuration de la page
st.set_page_config(page_title="Boursy - Pilote PEA (Value & Technique)", page_icon="📈", layout="wide")

# 2. Connexion à Supabase via les Secrets Streamlit
@st.cache_resource
def init_supabase() -> Client:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

supabase = init_supabase()

# 3. Fonction d'analyse complète : Indicateurs VALUE + MOMENTS TECHNIQUES
def analyser_valeur_complete(ticker_code, objectif_prix=0.0):
    try:
        t = yf.Ticker(ticker_code)
        info = t.info
        hist = t.history(period="1y")

        # Cours actuel
        prix = info.get("currentPrice") or info.get("regularMarketPrice")
        if not prix and not hist.empty:
            prix = float(hist["Close"].iloc[-1])
        prix = round(float(prix), 2) if prix else 0.0

        # --- INDICATEURS VALUE ---
        per = info.get("trailingPE") or info.get("forwardPE") or 0.0
        per = round(float(per), 1) if per else 0.0

        pb = info.get("priceToBook") or 0.0
        pb = round(float(pb), 2) if pb else 0.0

        div_yield = (info.get("dividendYield") or 0.0) * 100
        div_yield = round(float(div_yield), 2)

        payout = (info.get("payoutRatio") or 0.0) * 100
        payout = round(float(payout), 1)

        secteur = info.get("sector", "Bourse PEA")

        # --- MOMENTS TECHNIQUES (RSI 14j, MM50, MM200) ---
        if not hist.empty and len(hist) >= 50:
            close = hist["Close"]
            mm50 = round(float(close.rolling(window=50).mean().iloc[-1]), 2)
            mm200 = round(float(close.rolling(window=200).mean().iloc[-1]), 2) if len(hist) >= 200 else mm50

            # Calcul du RSI 14 jours
            delta = close.diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss.replace(0, np.nan)
            rsi_series = 100 - (100 / (1 + rs))
            rsi = round(float(rsi_series.iloc[-1]), 1) if not np.isnan(rsi_series.iloc[-1]) else 50.0

            plus_bas_52 = round(float(close.min()), 2)
            plus_haut_52 = round(float(close.max()), 2)
        else:
            mm50, mm200, rsi, plus_bas_52, plus_haut_52 = prix, prix, 50.0, prix, prix

        # --- SYNTHÈSE DU SIGNAL (VALUE + TECHNIQUE) ---
        signaux = []
        if objectif_prix > 0 and prix <= objectif_prix:
            signaux.append("🎯 Sous Cible")
        if 0 < per < 15:
            signaux.append("💎 Value (PER bas)")
        if rsi < 35:
            signaux.append("🟢 Survente (RSI < 35)")
        elif rsi > 70:
            signaux.append("🟠 Surchauffe (RSI > 70)")

        if prix > mm50 and mm50 >= mm200:
            signaux.append("📈 Momentum Haussier")
        elif prix < mm200:
            signaux.append("📉 Sous MM200")

        signal_texte = " | ".join(signaux) if signaux else "⏳ Neutre / Attente"

        return {
            "prix": prix,
            "per": per,
            "pb": pb,
            "rendement": div_yield,
            "payout": payout,
            "secteur": secteur,
            "rsi": rsi,
            "mm50": mm50,
            "mm200": mm200,
            "plus_bas_52": plus_bas_52,
            "plus_haut_52": plus_haut_52,
            "signal": signal_texte
        }
    except Exception:
        return {
            "prix": 0.0, "per": 0.0, "pb": 0.0, "rendement": 0.0, "payout": 0.0,
            "secteur": "N/A", "rsi": 50.0, "mm50": 0.0, "mm200": 0.0,
            "plus_bas_52": 0.0, "plus_haut_52": 0.0, "signal": "⚠️ Données indisponibles"
        }

# 4. Initialisation de la mémoire de session (Session State)
if "user_email" not in st.session_state:
    st.session_state.user_email = ""

if "liquidites" not in st.session_state:
    st.session_state.liquidites = 0.0

if "df_portefeuille" not in st.session_state:
    st.session_state.df_portefeuille = pd.DataFrame([
        {"Action": "TotalEnergies", "Ticker": "TTE.PA", "Quantité": 15.0, "PRU": 58.50, "Cours Actuel": 62.00, "Dividende/Action": 3.22},
        {"Action": "Air Liquide", "Ticker": "AI.PA", "Quantité": 6.0, "PRU": 165.00, "Cours Actuel": 172.00, "Dividende/Action": 3.20},
        {"Action": "Rubis", "Ticker": "RUI.PA", "Quantité": 30.0, "PRU": 24.50, "Cours Actuel": 24.10, "Dividende/Action": 1.98},
        {"Action": "Vinci", "Ticker": "DG.PA", "Quantité": 8.0, "PRU": 104.00, "Cours Actuel": 108.50, "Dividende/Action": 4.50},
        {"Action": "Engie", "Ticker": "ENGI.PA", "Quantité": 45.0, "PRU": 14.80, "Cours Actuel": 15.60, "Dividende/Action": 1.43}
    ])

if "df_radar" not in st.session_state:
    st.session_state.df_radar = pd.DataFrame([
        {"Action": "Rubis", "Ticker": "RUI.PA", "Prix Actuel": 24.10, "Objectif Achat": 24.00, "Rendement (%)": 8.2, "PER (Value)": 8.5, "P/B (Value)": 1.1, "RSI (14j)": 42.0, "MM50": 24.50, "MM200": 25.10, "Signal Value & Technique": "💎 Value (PER bas)"},
        {"Action": "Pernod Ricard", "Ticker": "RI.PA", "Prix Actuel": 74.50, "Objectif Achat": 70.00, "Rendement (%)": 5.9, "PER (Value)": 13.2, "P/B (Value)": 1.8, "RSI (14j)": 34.0, "MM50": 78.00, "MM200": 85.00, "Signal Value & Technique": "🟢 Survente (RSI < 35) | 💎 Value"},
        {"Action": "Sanofi", "Ticker": "SAN.PA", "Prix Actuel": 96.00, "Objectif Achat": 90.00, "Rendement (%)": 3.9, "PER (Value)": 14.5, "P/B (Value)": 1.9, "RSI (14j)": 51.0, "MM50": 95.00, "MM200": 92.00, "Signal Value & Technique": "📈 Momentum Haussier"}
    ])

if "messages_ia" not in st.session_state:
    st.session_state.messages_ia = []

# 5. Fonctions de Chargement et Sauvegarde Supabase
def charger_portefeuille(email_utilisateur):
    try:
        reponse = supabase.table("portefeuille").select("*").eq("email", email_utilisateur).execute()
        if reponse.data:
            lignes = []
            for row in reponse.data:
                if row.get("action") == "LIQUIDITES_PEA":
                    st.session_state.liquidites = float(row.get("pru", 0.0))
                else:
                    lignes.append({
                        "Action": row.get("action", ""),
                        "Ticker": row.get("ticker", ""),
                        "Quantité": float(row.get("quantite", 0.0)),
                        "PRU": float(row.get("pru", 0.0)),
                        "Cours Actuel": float(row.get("cours_actuel", 0.0)),
                        "Dividende/Action": float(row.get("dividende", 0.0))
                    })
            if lignes:
                st.session_state.df_portefeuille = pd.DataFrame(lignes)
            st.toast("Portefeuille et espèces chargés depuis le Cloud !", icon="✅")
        else:
            st.toast("Aucune sauvegarde trouvée pour cet e-mail.", icon="ℹ️")
    except Exception as e:
        st.error(f"Erreur lors du chargement Supabase : {e}")

def sauvegarder_portefeuille(email_utilisateur, df, especes):
    try:
        supabase.table("portefeuille").delete().eq("email", email_utilisateur).execute()
        lignes_a_inserer = []
        for _, row in df.iterrows():
            lignes_a_inserer.append({
                "email": email_utilisateur,
                "action": str(row["Action"]),
                "ticker": str(row["Ticker"]),
                "quantite": float(row["Quantité"]),
                "pru": float(row["PRU"]),
                "cours_actuel": float(row["Cours Actuel"]),
                "dividende": float(row["Dividende/Action"])
            })
        lignes_a_inserer.append({
            "email": email_utilisateur,
            "action": "LIQUIDITES_PEA",
            "ticker": "CASH",
            "quantite": 1.0,
            "pru": float(especes),
            "cours_actuel": float(especes),
            "dividende": 0.0
        })
        supabase.table("portefeuille").insert(lignes_a_inserer).execute()
        st.toast("Portefeuille et espèces sauvegardés avec succès !", icon="💾")
    except Exception as e:
        st.error(f"Erreur lors de la sauvegarde Supabase : {e}")

# 6. Barre Latérale : Connexion, Liquidités et Sauvegarde
with st.sidebar:
    st.title("📈 Boursy 2.0")
    st.caption("Pilotage PEA • Value & Moments Techniques")
    st.divider()

    email_saisi = st.text_input("📧 Votre adresse e-mail :", value=st.session_state.user_email, placeholder="votre@email.com")

    col_b1, col_b2 = st.columns(2)
    with col_b1:
        if st.button("🔄 Charger", use_container_width=True):
            if email_saisi:
                st.session_state.user_email = email_saisi.strip().lower()
                charger_portefeuille(st.session_state.user_email)
            else:
                st.warning("Saisissez votre e-mail.")
    with col_b2:
        if st.button("💾 Sauver", type="primary", use_container_width=True):
            if email_saisi:
                st.session_state.user_email = email_saisi.strip().lower()
                sauvegarder_portefeuille(st.session_state.user_email, st.session_state.df_portefeuille, st.session_state.liquidites)
            else:
                st.warning("Saisissez votre e-mail.")

    st.divider()
    st.subheader("💶 Poche de Liquidités (Espèces)")
    st.session_state.liquidites = st.number_input(
        "Espèces disponibles sur le PEA (€) :",
        min_value=0.0,
        value=float(st.session_state.liquidites),
        step=25.0
    )# 7. Création des 4 onglets principaux
tab_portefeuille, tab_radar, tab_dca, tab_audit_ia = st.tabs([
    "💼 Mon Portefeuille PEA",
    "📡 Radar Value & Moments Techniques",
    "🎯 Stratégie DCA & Dividendes",
    "🤖 Audit IA (Premium)"
])

# --- ONGLET 1 : MON PORTEFEUILLE PEA ---
with tab_portefeuille:
    st.header("💼 Tableau de Bord du Portefeuille PEA")

    col_act1, col_act2 = st.columns([1, 2])
    with col_act1:
        if st.button("⚡ Actualiser tous les cours en direct (Yahoo Finance)", type="primary"):
            with st.spinner("Synchronisation des cours avec la Bourse de Paris..."):
                df_temp = st.session_state.df_portefeuille.copy()
                for idx, row in df_temp.iterrows():
                    t_code = str(row["Ticker"]).strip()
                    if t_code:
                        res = analyser_valeur_complete(t_code)
                        if res["prix"] > 0:
                            df_temp.at[idx, "Cours Actuel"] = res["prix"]
                st.session_state.df_portefeuille = df_temp
                st.toast("Cours du portefeuille actualisés en direct !", icon="⚡")

    st.subheader("✏️ Saisie et ajustement de vos lignes")
    df_edite = st.data_editor(
        st.session_state.df_portefeuille,
        num_rows="dynamic",
        use_container_width=True,
        key="editeur_pea"
    )
    st.session_state.df_portefeuille = df_edite

    # Calculs détaillés ligne par ligne
    df_analyse = df_edite.copy()
    if not df_analyse.empty:
        df_analyse["Investi (€)"] = (df_analyse["Quantité"] * df_analyse["PRU"]).round(2)
        df_analyse["Valorisation (€)"] = (df_analyse["Quantité"] * df_analyse["Cours Actuel"]).round(2)
        df_analyse["+/- Value (€)"] = (df_analyse["Valorisation (€)"] - df_analyse["Investi (€)"]).round(2)
        df_analyse["+/- Value (%)"] = np.where(
            df_analyse["Investi (€)"] > 0,
            ((df_analyse["+/- Value (€)"] / df_analyse["Investi (€)"]) * 100).round(2),
            0.0
        )
        df_analyse["Rendement sur PRU (%)"] = np.where(
            df_analyse["PRU"] > 0,
            ((df_analyse["Dividende/Action"] / df_analyse["PRU"]) * 100).round(2),
            0.0
        )
        df_analyse["Rente Annuelle (€)"] = (df_analyse["Quantité"] * df_analyse["Dividende/Action"]).round(2)
        df_analyse["Rente Mensuelle (€)"] = (df_analyse["Rente Annuelle (€)"] / 12).round(2)

        investi_total = df_analyse["Investi (€)"].sum()
        valo_actions = df_analyse["Valorisation (€)"].sum()
        valo_totale_pea = valo_actions + st.session_state.liquidites
        plus_value_totale = valo_actions - investi_total
        plus_value_pct = (plus_value_totale / investi_total * 100) if investi_total > 0 else 0.0
        rente_annuelle_totale = df_analyse["Rente Annuelle (€)"].sum()
        rente_mensuelle_totale = rente_annuelle_totale / 12
        yoc_global = (rente_annuelle_totale / investi_total * 100) if investi_total > 0 else 0.0

        df_analyse["Poids PEA (%)"] = np.where(
            valo_totale_pea > 0,
            ((df_analyse["Valorisation (€)"] / valo_totale_pea) * 100).round(1),
            0.0
        )
    else:
        investi_total = valo_actions = plus_value_totale = plus_value_pct = rente_annuelle_totale = rente_mensuelle_totale = yoc_global = 0.0
        valo_totale_pea = st.session_state.liquidites

    st.divider()
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Valeur Totale PEA (Actions + Espèces)", f"{valo_totale_pea:,.2f} €", f"Investi : {investi_total:,.2f} €")
    k2.metric("Valorisation Actions", f"{valo_actions:,.2f} €", f"{plus_value_totale:+,.2f} € ({plus_value_pct:+.2f} %)")
    k3.metric("Poche Espèces Disponible", f"{st.session_state.liquidites:,.2f} €", f"{(st.session_state.liquidites / valo_totale_pea * 100 if valo_totale_pea > 0 else 0):.1f} % du PEA")
    k4.metric("Rente Dividendes Mensuelle", f"{rente_mensuelle_totale:,.2f} € / mois", f"{rente_annuelle_totale:,.2f} € / an (Rdt PRU : {yoc_global:.2f} %)")

    st.subheader("📊 Synthèse analytique de vos lignes (Rentabilité, Poids & Dividendes)")
    st.dataframe(df_analyse, use_container_width=True, hide_index=True)
# --- ONGLET 2 : RADAR VALUE & MOMENTS TECHNIQUES ---
with tab_radar:
    st.header("📡 Radar Pro : Analyse Value & Moments Techniques")

    catalogue_pea = {
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

    col_r1, col_r2, col_r3 = st.columns([2, 1, 1])
    with col_r1:
        choix_action = st.selectbox(
            "🔍 Sélectionnez une action du PEA à analyser en direct :",
            options=["-- Choisir une valeur --"] + sorted(catalogue_pea.keys())
        )
    with col_r2:
        ticker_libre = st.text_input("Ou Ticker Yahoo libre (ex: ASML.AS) :", value="")
    with col_r3:
        cible_achat = st.number_input("🎯 Votre Objectif d'Achat (€) :", min_value=0.0, value=25.0, step=1.0)

    nom_analyse = None
    ticker_analyse = None
    if ticker_libre.strip():
        ticker_analyse = ticker_libre.strip().upper()
        nom_analyse = ticker_analyse
    elif choix_action != "-- Choisir une valeur --":
        nom_analyse = choix_action
        ticker_analyse = catalogue_pea[choix_action]

    if ticker_analyse:
        with st.spinner(f"Calcul des indicateurs Value et Moments Techniques pour {nom_analyse}..."):
            data_yf = analyser_valeur_complete(ticker_analyse, cible_achat)

            st.markdown(f"#### 🔎 Diagnostic en direct : **{nom_analyse}** (`{ticker_analyse}`) — Signal : **{data_yf['signal']}**")

            # Ligne 1 : Indicateurs VALUE & Dividende
            st.caption("💎 **Indicateurs Fondamentaux (Value & Rendement)**")
            v1, v2, v3, v4, v5 = st.columns(5)
            ecart_cible = ((data_yf["prix"] - cible_achat) / cible_achat * 100) if cible_achat > 0 else 0.0
            v1.metric("Cours en Direct", f"{data_yf['prix']:.2f} €", f"{ecart_cible:+.1f} % vs Cible ({cible_achat:.0f} €)", delta_color="inverse")
            v2.metric("Rendement Dividende", f"{data_yf['rendement']:.2f} %")
            v3.metric("PER (Price/Earnings)", f"{data_yf['per']}x", "Value < 15x" if 0 < data_yf["per"] < 15 else "Standard")
            v4.metric("Price-to-Book (P/B)", f"{data_yf['pb']}x")
            v5.metric("Payout Ratio", f"{data_yf['payout']:.1f} %")

            # Ligne 2 : MOMENTS TECHNIQUES (Momentum)
            st.caption("📈 **Moments Techniques (RSI 14j, Moyennes Mobiles & Extrêmes 52 semaines)**")
            t1, t2, t3, t4, t5 = st.columns(5)
            etat_rsi = "Survente (Achat)" if data_yf["rsi"] < 35 else ("Surchauffe" if data_yf["rsi"] > 70 else "Zone Neutre")
            t1.metric("RSI (14 jours)", f"{data_yf['rsi']}", etat_rsi)
            t2.metric("Moyenne Mobile 50j", f"{data_yf['mm50']:.2f} €", f"{data_yf['prix'] - data_yf['mm50']:+.2f} €")
            t3.metric("Moyenne Mobile 200j", f"{data_yf['mm200']:.2f} €", f"{data_yf['prix'] - data_yf['mm200']:+.2f} €")
            t4.metric("Plus Bas 52 sem.", f"{data_yf['plus_bas_52']:.2f} €")
            t5.metric("Plus Haut 52 sem.", f"{data_yf['plus_haut_52']:.2f} €")

            if st.button(f"➕ Ajouter / Mettre à jour {nom_analyse} dans le tableau Radar", type="primary"):
                nouvelle_ligne_radar = pd.DataFrame([{
                    "Action": nom_analyse,
                    "Ticker": ticker_analyse,
                    "Prix Actuel": data_yf["prix"],
                    "Objectif Achat": cible_achat,
                    "Rendement (%)": data_yf["rendement"],
                    "PER (Value)": data_yf["per"],
                    "P/B (Value)": data_yf["pb"],
                    "RSI (14j)": data_yf["rsi"],
                    "MM50": data_yf["mm50"],
                    "MM200": data_yf["mm200"],
                    "Signal Value & Technique": data_yf["signal"]
                }])
                df_r = st.session_state.df_radar
                df_r = df_r[df_r["Ticker"] != ticker_analyse]
                st.session_state.df_radar = pd.concat([df_r, nouvelle_ligne_radar], ignore_index=True)
                st.toast(f"{nom_analyse} enregistré dans votre Radar Pro !", icon="📡")

    st.divider()
    col_rad_head1, col_rad_head2 = st.columns([2, 1])
    with col_rad_head1:
        st.subheader("📋 Votre Watchlist Radar (Value & Moments Techniques)")
    with col_rad_head2:
        if st.button("🔄 Scanner tout le Radar en direct"):
            with st.spinner("Mise à jour des indicateurs Value et RSI/MM de toute la Watchlist..."):
                df_scan = st.session_state.df_radar.copy()
                for i, r in df_scan.iterrows():
                    tk = str(r["Ticker"]).strip()
                    obj = float(r.get("Objectif Achat", 0.0))
                    if tk:
                        res = analyser_valeur_complete(tk, obj)
                        if res["prix"] > 0:
                            df_scan.at[i, "Prix Actuel"] = res["prix"]
                            df_scan.at[i, "Rendement (%)"] = res["rendement"]
                            df_scan.at[i, "PER (Value)"] = res["per"]
                            df_scan.at[i, "P/B (Value)"] = res["pb"]
                            df_scan.at[i, "RSI (14j)"] = res["rsi"]
                            df_scan.at[i, "MM50"] = res["mm50"]
                            df_scan.at[i, "MM200"] = res["mm200"]
                            df_scan.at[i, "Signal Value & Technique"] = res["signal"]
                st.session_state.df_radar = df_scan
                st.toast("Tous les indicateurs Value & Techniques du Radar sont à jour !", icon="✅")

    st.session_state.df_radar = st.data_editor(
        st.session_state.df_radar,
        num_rows="dynamic",
        use_container_width=True,
        key="editeur_radar_complet"
    )

# --- ONGLET 3 : STRATÉGIE DCA & DIVIDENDES ---
with tab_dca:
    st.header("🎯 Pilotage du DCA Mensuel & Objectif de Rente")

    c_dca1, c_dca2, c_dca3 = st.columns(3)
    with c_dca1:
        budget_dca = st.number_input("💶 Enveloppe DCA mensuelle (€) :", min_value=50.0, value=450.0, step=25.0)
    with c_dca2:
        rente_actuelle_ref = st.number_input("📌 Rente mensuelle de référence (€) :", min_value=0.0, value=float(round(rente_mensuelle_totale, 2)) if rente_mensuelle_totale > 0 else 68.70, step=1.0)
    with c_dca3:
        objectif_rente_12m = st.number_input("🚀 Objectif de rente mensuelle à 12 mois (€) :", min_value=10.0, value=89.40, step=5.0)

    ratio_prog = min(rente_actuelle_ref / objectif_rente_12m, 1.0) if objectif_rente_12m > 0 else 0.0
    st.progress(ratio_prog, text=f"Progression vers l'objectif : {rente_actuelle_ref:.2f} € / {objectif_rente_12m:.2f} € par mois ({ratio_prog*100:.1f} %)")

    st.divider()
    st.subheader("🧮 Simulateur d'impact DCA sur PRU et Dividendes")
    if not df_edite.empty:
        action_dca = st.selectbox("Sélectionnez la ligne à renforcer avec votre DCA :", df_edite["Action"].tolist())
        ligne_sel = df_edite[df_edite["Action"] == action_dca].iloc[0]

        qte_actuelle = float(ligne_sel["Quantité"])
        pru_actuel = float(ligne_sel["PRU"])
        cours_act = float(ligne_sel["Cours Actuel"])
        div_act = float(ligne_sel["Dividende/Action"])

        if cours_act > 0:
            nb_achat = int(budget_dca // cours_act)
            montant_utilise = nb_achat * cours_act
            reste_especes = budget_dca - montant_utilise
            nouvelle_qte = qte_actuelle + nb_achat
            nouveau_pru = ((qte_actuelle * pru_actuel) + montant_utilise) / nouvelle_qte if nouvelle_qte > 0 else pru_actuel
            gain_div_annuel = nb_achat * div_act
            gain_div_mensuel = gain_div_annuel / 12

            s1, s2, s3, s4 = st.columns(4)
            s1.metric("Actions achetables", f"+{nb_achat} titres", f"Coût : {montant_utilise:.2f} € (Reste : {reste_especes:.2f} €)")
            s2.metric("Nouveau PRU après achat", f"{nouveau_pru:.2f} €", f"{nouveau_pru - pru_actuel:+.2f} € vs PRU actuel", delta_color="inverse")
            s3.metric("Gain Rente Annuelle", f"+{gain_div_annuel:.2f} € / an")
            s4.metric("Gain Rente Mensuelle", f"+{gain_div_mensuel:.2f} € / mois", f"Nouvelle rente : {rente_actuelle_ref + gain_div_mensuel:.2f} €/mois")
# --- ONGLET 4 : AUDIT IA (ISOLÉ DANS CET ONGLET & SANS ERREUR DE MODULE) ---
def interroger_gemini(prompt_texte):
    api_key = st.secrets["GEMINI_API_KEY"]
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [{"parts": [{"text": prompt_texte}]}]
    }
    reponse = requests.post(url, headers=headers, json=payload, timeout=30)
    if reponse.status_code == 200:
        data = reponse.json()
        return data["candidates"][0]["content"]["parts"][0]["text"]
    else:
        raise Exception(f"Erreur API Gemini ({reponse.status_code}) : {reponse.text}")

with tab_audit_ia:
    st.header("🤖 Coach & Audit IA du Portefeuille (Offre Premium)")
    st.caption("Analyse croisée de votre PEA, de vos liquidités et des indicateurs Value & Moments Techniques de votre Radar.")

    if st.button("🚀 Lancer un Audit Complet (Portefeuille + Value + Moments Techniques)", type="primary"):
        resume_pea = st.session_state.df_portefeuille.to_string(index=False)
        resume_radar = st.session_state.df_radar.to_string(index=False)
        prompt_audit = (
            f"Tu es un expert en investissement PEA orienté dividendes, analyse Value et Momentum technique.\n"
            f"Voici mon portefeuille PEA actuel :\n{resume_pea}\n\n"
            f"Liquidités (Espèces) disponibles sur le PEA : {st.session_state.liquidites} €.\n"
            f"Ma stratégie : investir 450 € par mois en DCA sur des actions solides à dividendes (objectif de passer de 68,70 €/mois à 89,40 €/mois sur 12 mois).\n"
            f"Voici ma liste Radar avec les indicateurs Value (PER, P/B) et Moments Techniques (RSI 14j, MM50, MM200) :\n{resume_radar}\n\n"
            f"Réalise un audit structuré : 1) Équilibre et rendement du portefeuille, 2) Analyse des PRU et utilisation des espèces, "
            f"3) Quelles actions renforcer ce mois-ci avec mes 450 € selon les signaux Value et Techniques (RSI/MM)."
        )
        st.session_state.messages_ia.append({"role": "user", "content": "Peux-tu réaliser un audit complet de mon PEA (Value, Moments Techniques et DCA) ?"})

        with st.spinner("L'Agent IA analyse vos lignes, vos indicateurs Value et vos Moments Techniques..."):
            try:
                texte_ia = interroger_gemini(prompt_audit)
                st.session_state.messages_ia.append({"role": "assistant", "content": texte_ia})
            except Exception as e:
                st.error(f"Impossible de joindre l'IA : {e}")

    st.divider()

    for msg in st.session_state.messages_ia:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    with st.form(key="form_chat_audit_ia", clear_on_submit=True):
        question_user = st.text_input("💬 Posez une question précise à votre Coach IA (ex: Est-ce le bon moment technique pour renforcer Rubis ou Pernod Ricard ?) :")
        envoyer = st.form_submit_button("Envoyer à l'IA")

        if envoyer and question_user:
            st.session_state.messages_ia.append({"role": "user", "content": question_user})
            contexte_global = (
                f"Portefeuille PEA :\n{st.session_state.df_portefeuille.to_string(index=False)}\n"
                f"Espèces disponibles : {st.session_state.liquidites} €\n"
                f"Radar Value & Technique :\n{st.session_state.df_radar.to_string(index=False)}\n"
                f"Question de l'investisseur : {question_user}"
            )
            with st.spinner("Analyse de votre question en cours..."):
                try:
                    rep_texte = interroger_gemini(contexte_global)
                    st.session_state.messages_ia.append({"role": "assistant", "content": rep_texte})
                    st.rerun()
                except Exception as e:
                    st.error(f"Erreur IA : {e}")
