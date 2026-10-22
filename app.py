import streamlit as st
import pandas as pd
import yfinance as yf
from supabase import create_client, Client
import google.generativeai as genai

# 1. Configuration de la page
st.set_page_config(page_title="Boursy - Pilote PEA", page_icon="📈", layout="wide")

# 2. Connexion à Supabase et Gemini via les Secrets Streamlit
@st.cache_resource
def init_supabase() -> Client:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

supabase = init_supabase()
genai.configure(api_key=st.secrets["GEMINI_API_KEY"])

# 3. Initialisation de la mémoire de session (Session State)
if "user_email" not in st.session_state:
    st.session_state.user_email = ""

if "liquidites" not in st.session_state:
    st.session_state.liquidites = 0.0

if "df_portefeuille" not in st.session_state:
    st.session_state.df_portefeuille = pd.DataFrame(
        [
            {"Action": "TotalEnergies", "Ticker": "TTE.PA", "Quantité": 10, "PRU": 58.50, "Cours Actuel": 62.00, "Dividende/Action": 3.01},
            {"Action": "Air Liquide", "Ticker": "AI.PA", "Quantité": 5, "PRU": 165.00, "Cours Actuel": 172.00, "Dividende/Action": 3.20},
            {"Action": "Rubis", "Ticker": "RUI.PA", "Quantité": 25, "PRU": 24.50, "Cours Actuel": 24.10, "Dividende/Action": 1.98}
        ]
    )

if "df_radar" not in st.session_state:
    st.session_state.df_radar = pd.DataFrame(
        columns=["Action", "Ticker", "Prix Actuel", "Objectif Achat", "Rendement (%)", "Secteur"]
    )

if "messages_ia" not in st.session_state:
    st.session_state.messages_ia = []

# 4. Fonctions de Chargement et Sauvegarde Supabase
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
                        "Quantité": float(row.get("quantite", 0)),
                        "PRU": float(row.get("pru", 0.0)),
                        "Cours Actuel": float(row.get("cours_actuel", 0.0)),
                        "Dividende/Action": float(row.get("dividende", 0.0))
                    })
            if lignes:
                st.session_state.df_portefeuille = pd.DataFrame(lignes)
            st.toast("Portefeuille chargé avec succès depuis le Cloud !", icon="✅")
        else:
            st.toast("Aucun portefeuille enregistré pour cet e-mail. Modèle par défaut affiché.", icon="ℹ️")
    except Exception as e:
        st.error(f"Erreur lors du chargement Supabase : {e}")

def sauvegarder_portefeuille(email_utilisateur, df, especes):
    try:
        # Suppression des anciennes lignes de cet e-mail pour éviter les doublons
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
           
        # Enregistrement de la poche Espèces sous une ligne dédiée
        lignes_a_inserer.append({
            "email": email_utilisateur,
            "action": "LIQUIDITES_PEA",
            "ticker": "CASH",
            "quantite": 1,
            "pru": float(especes),
            "cours_actuel": float(especes),
            "dividende": 0.0
        })
       
        supabase.table("portefeuille").insert(lignes_a_inserer).execute()
        st.toast("Portefeuille et espèces sauvegardés dans le Cloud !", icon="💾")
    except Exception as e:
        st.error(f"Erreur lors de la sauvegarde Supabase : {e}")

# 5. Barre Latérale : Connexion, Liquidités et Sauvegarde
with st.sidebar:
    st.title("📈 Boursy")
    st.caption("Votre PEA sur pilote automatique")
    st.divider()
   
    email_saisi = st.text_input("📧 Votre adresse e-mail :", value=st.session_state.user_email, placeholder="exemple@email.com")
   
    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        if st.button("🔄 Charger", use_container_width=True):
            if email_saisi:
                st.session_state.user_email = email_saisi.strip().lower()
                charger_portefeuille(st.session_state.user_email)
            else:
                st.warning("Veuillez saisir votre e-mail.")
               
    with col_btn2:
        if st.button("💾 Sauver", type="primary", use_container_width=True):
            if email_saisi:
                st.session_state.user_email = email_saisi.strip().lower()
                sauvegarder_portefeuille(st.session_state.user_email, st.session_state.df_portefeuille, st.session_state.liquidites)
            else:
                st.warning("Veuillez saisir votre e-mail.")
               
    st.divider()
    st.subheader("💶 Poche de Liquidités")
    st.session_state.liquidites = st.number_input(
        "Espèces disponibles sur le PEA (€) :",
        min_value=0.0,
        value=float(st.session_state.liquidites),
        step=50.0
    )# 6. Création des 4 onglets principaux
tab_portefeuille, tab_dca, tab_radar, tab_audit_ia = st.tabs([
    "💼 Mon Portefeuille",
    "🎯 Stratégie DCA & Dividendes",
    "📡 Liste Radar Pro",
    "🤖 Audit IA (Premium)"
])

# --- ONGLET 1 : MON PORTEFEUILLE ---
with tab_portefeuille:
    st.header("💼 Vue d'ensemble du PEA")
   
    # Bouton de mise à jour des cours en direct via Yahoo Finance
    if st.button("⚡ Actualiser les cours en direct (Yahoo Finance)"):
        with st.spinner("Mise à jour des cours boursiers..."):
            df_temp = st.session_state.df_portefeuille.copy()
            for index, row in df_temp.iterrows():
                ticker_code = str(row["Ticker"]).strip()
                if ticker_code:
                    try:
                        info_yf = yf.Ticker(ticker_code).info
                        prix_live = info_yf.get("currentPrice", info_yf.get("regularMarketPrice", row["Cours Actuel"]))
                        if prix_live:
                            df_temp.at[index, "Cours Actuel"] = round(float(prix_live), 2)
                    except Exception:
                        pass
            st.session_state.df_portefeuille = df_temp
            st.toast("Cours boursiers mis à jour !", icon="⚡")

    # Tableau éditable du portefeuille
    df_edite = st.data_editor(
        st.session_state.df_portefeuille,
        num_rows="dynamic",
        use_container_width=True,
        key="editeur_portefeuille"
    )
    st.session_state.df_portefeuille = df_edite

    # Calculs globaux du portefeuille
    investi_actions = (df_edite["Quantité"] * df_edite["PRU"]).sum()
    valeur_actions = (df_edite["Quantité"] * df_edite["Cours Actuel"]).sum()
    plus_value = valeur_actions - investi_actions
    valeur_totale_pea = valeur_actions + st.session_state.liquidites
    dividendes_annuels = (df_edite["Quantité"] * df_edite["Dividende/Action"]).sum()
    dividendes_mensuels = dividendes_annuels / 12

    st.divider()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Valeur Totale PEA (avec Espèces)", f"{valeur_totale_pea:,.2f} €")
    c2.metric("Valorisation Actions", f"{valeur_actions:,.2f} €", f"{plus_value:+,.2f} €")
    c3.metric("Espèces Disponibles", f"{st.session_state.liquidites:,.2f} €")
    c4.metric("Revenu Passif Mensuel", f"{dividendes_mensuels:,.2f} € / mois", f"{dividendes_annuels:,.2f} € / an")

# --- ONGLET 2 : STRATÉGIE DCA & DIVIDENDES ---
with tab_dca:
    st.header("🎯 Pilotage du DCA & Objectif de Rente")
   
    col_dca1, col_dca2 = st.columns(2)
    with col_dca1:
        budget_dca = st.number_input("Enveloppe d'investissement mensuel (€) :", min_value=50.0, value=450.0, step=50.0)
    with col_dca2:
        objectif_mensuel = st.number_input("Objectif de dividendes mensuels à 12 mois (€) :", min_value=10.0, value=89.40, step=5.0)
       
    progression = min(dividendes_mensuels / objectif_mensuel, 1.0) if objectif_mensuel > 0 else 0.0
    st.progress(progression, text=f"Progression vers l'objectif : {dividendes_mensuels:.2f} € / {objectif_mensuel:.2f} € par mois ({progression*100:.1f} %)")
   
    st.subheader("Simulateur de renforcement mensuel")
    if not df_edite.empty:
        action_cible = st.selectbox("Choisissez une ligne à renforcer ce mois-ci :", df_edite["Action"].tolist())
        ligne_action = df_edite[df_edite["Action"] == action_cible].iloc[0]
        prix_actuel_dca = float(ligne_action["Cours Actuel"])
       
        if prix_actuel_dca > 0:
            nb_actions_achetables = int(budget_dca // prix_actuel_dca)
            cout_total = nb_actions_achetables * prix_actuel_dca
            nouveau_div_annuel = nb_actions_achetables * float(ligne_action["Dividende/Action"])
           
            st.info(
                f"Avec votre enveloppe de **{budget_dca:.0f} €**, vous pouvez acheter **{nb_actions_achetables} actions {action_cible}** "
                f"(coût : {cout_total:.2f} €). Cela augmentera vos dividendes de **+{nouveau_div_annuel:.2f} € / an**."
            )
# --- ONGLET 3 : LISTE RADAR PRO ---
with tab_radar:
    st.header("📡 Radar Pro - Recherche d'Opportunités PEA")
   
    actions_pea = {
        "Air Liquide": "AI.PA",
        "AXA": "CS.PA",
        "BNP Paribas": "BNP.PA",
        "Danone": "BN.PA",
        "Engie": "ENGI.PA",
        "Hermès": "RMS.PA",
        "L'Oréal": "OR.PA",
        "LVMH": "MC.PA",
        "Michelin": "ML.PA",
        "Pernod Ricard": "RI.PA",
        "Publicis": "PUB.PA",
        "Rubis": "RUI.PA",
        "Saint-Gobain": "SGO.PA",
        "Sanofi": "SAN.PA",
        "Schneider Electric": "SU.PA",
        "TotalEnergies": "TTE.PA",
        "Veolia": "VIE.PA",
        "Vinci": "DG.PA"
    }

    col_r1, col_r2 = st.columns([2, 1])
    with col_r1:
        nom_choisi = st.selectbox(
            "🔍 Tapez ou sélectionnez une valeur du SBF120 :",
            options=["-- Sélectionnez une action --"] + sorted(actions_pea.keys())
        )
    with col_r2:
        prix_cible = st.number_input("🎯 Votre objectif de prix d'achat (€) :", min_value=0.0, value=50.0, step=1.0)

    if nom_choisi != "-- Sélectionnez une action --":
        ticker_saisi = actions_pea[nom_choisi]
        with st.spinner(f"Aspiration des données financières pour {nom_choisi}..."):
            try:
                action_yf = yf.Ticker(ticker_saisi)
                info = action_yf.info
               
                prix_actuel = info.get("currentPrice", info.get("regularMarketPrice", 0.0))
                secteur = info.get("sector", "Non défini")
                dividende_yield = info.get("dividendYield", 0.0) * 100 if info.get("dividendYield") else 0.0
               
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Prix en direct", f"{prix_actuel} €")
                m2.metric("Votre Cible", f"{prix_cible} €")
                m3.metric("Rendement estimé", f"{dividende_yield:.2f} %")
                m4.metric("Secteur", secteur)
               
                if st.button(f"➕ Ajouter {nom_choisi} au Radar", type="primary"):
                    nouvelle_cible = pd.DataFrame([{
                        "Action": nom_choisi,
                        "Ticker": ticker_saisi,
                        "Prix Actuel": prix_actuel,
                        "Objectif Achat": prix_cible,
                        "Rendement (%)": round(dividende_yield, 2),
                        "Secteur": secteur
                    }])
                    st.session_state.df_radar = pd.concat([st.session_state.df_radar, nouvelle_cible], ignore_index=True)
                    st.toast(f"{nom_choisi} ajoutée à la liste radar !", icon="📡")
            except Exception as e:
                st.error(f"Impossible de récupérer les données Yahoo Finance : {e}")

    st.divider()
    st.subheader("📋 Vos valeurs sous surveillance")
    st.session_state.df_radar = st.data_editor(
        st.session_state.df_radar,
        num_rows="dynamic",
        use_container_width=True,
        key="editeur_radar"
    )# --- ONGLET 4 : AUDIT IA (EXCLUSIF À CET ONGLET) ---
with tab_audit_ia:
    st.header("🤖 Coach & Audit IA du Portefeuille")
    st.caption("Offre Premium — Analyse algorithmique personnalisée de vos lignes et de votre stratégie de dividendes.")
   
    # Bouton d'audit rapide en un clic
    if st.button("🚀 Lancer un Audit complet de mon PEA", type="primary"):
        resumé_portefeuille = st.session_state.df_portefeuille.to_string(index=False)
        prompt_auto = (
            f"Voici mon portefeuille PEA actuel :\n{resumé_portefeuille}\n"
            f"Liquidités disponibles : {st.session_state.liquidites} €.\n"
            f"Mon budget DCA mensuel est de 450 €. Analyse la répartition, les prix de revient (PRU), "
            f"et propose-moi des pistes d'optimisation pour maximiser mes dividendes à long terme."
        )
        st.session_state.messages_ia.append({"role": "user", "content": "Peux-tu réaliser un audit complet de mon portefeuille PEA ?"})
       
        with st.spinner("L'Agent IA analyse vos lignes et vos rendements..."):
            try:
                model = genai.GenerativeModel("gemini-1.5-flash")
                reponse_ia = model.generate_content(prompt_auto)
                st.session_state.messages_ia.append({"role": "assistant", "content": reponse_ia.text})
            except Exception as e:
                st.error(f"Erreur de communication avec l'IA : {e}")

    st.divider()

    # Affichage de l'historique des échanges uniquement dans cet onglet
    for msg in st.session_state.messages_ia:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # Formulaire de discussion isolé dans l'onglet Audit IA
    with st.form(key="formulaire_chat_ia", clear_on_submit=True):
        question_utilisateur = st.text_input(
            "Posez une question à votre Coach IA (ex: Que penses-tu de mon PRU sur Rubis ?) :"
        )
        bouton_envoyer = st.form_submit_button("Envoyer à l'IA")
       
        if bouton_envoyer and question_utilisateur:
            st.session_state.messages_ia.append({"role": "user", "content": question_utilisateur})
            contexte_pea = st.session_state.df_portefeuille.to_string(index=False)
            prompt_complet = (
                f"Contexte du portefeuille PEA de l'utilisateur :\n{contexte_pea}\n"
                f"Espèces disponibles : {st.session_state.liquidites} €.\n"
                f"Question de l'utilisateur : {question_utilisateur}"
            )
            with st.spinner("Réflexion de l'IA en cours..."):
                try:
                    model = genai.GenerativeModel("gemini-1.5-flash")
                    reponse = model.generate_content(prompt_complet)
                    st.session_state.messages_ia.append({"role": "assistant", "content": reponse.text})
                    st.rerun()
                except Exception as e:
                    st.error(f"Erreur IA : {e}")
