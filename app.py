import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf

# Imports optionnels (Supabase & Gemini IA) avec sécurité anti-plantage
try:
    from supabase import create_client
    SUPABASE_DISPO = True
except ImportError:
    SUPABASE_DISPO = False

try:
    import google.generativeai as genai
    GEMINI_DISPO = True
except ImportError:
    GEMINI_DISPO = False

# ==========================================
# 1. CONFIGURATION DE LA PAGE & CSS PRO
# ==========================================
st.set_page_config(
    page_title="Boursy - Gestion PEA & Analyse Value",
    page_icon="📈",
    layout="wide"
)

st.markdown("""
<style>
    .r-table {
        width: 100%;
        border-collapse: collapse;
        margin: 12px 0;
        font-size: 0.94rem;
        background-color: rgba(15, 23, 42, 0.65);
        border-radius: 8px;
        overflow: hidden;
    }
    .r-table th {
        background-color: rgba(30, 41, 59, 0.95);
        color: #cbd5e1;
        padding: 11px 12px;
        text-align: center;
        font-weight: 600;
        border-bottom: 1px solid rgba(255, 255, 255, 0.12);
    }
    .r-table td {
        padding: 10px 12px;
        text-align: center;
        border-bottom: 1px solid rgba(255, 255, 255, 0.06);
        color: #f8fafc;
    }
    .r-table tr:hover {
        background-color: rgba(255, 255, 255, 0.04);
    }
    .r-name {
        text-align: left !important;
        font-weight: 600;
        color: #38bdf8 !important;
    }
    .b-green {
        background-color: rgba(34, 197, 94, 0.2);
        color: #22c55e;
        padding: 4px 10px;
        border-radius: 6px;
        font-weight: 700;
        display: inline-block;
    }
    .b-yellow {
        background-color: rgba(234, 179, 8, 0.2);
        color: #eab308;
        padding: 4px 10px;
        border-radius: 6px;
        font-weight: 700;
        display: inline-block;
    }
    .b-red {
        background-color: rgba(239, 68, 68, 0.2);
        color: #ef4444;
        padding: 4px 10px;
        border-radius: 6px;
        font-weight: 700;
        display: inline-block;
    }
    .b-white {
        background-color: rgba(255, 255, 255, 0.12);
        color: #f8fafc;
        padding: 4px 10px;
        border-radius: 6px;
        font-weight: 700;
        display: inline-block;
    }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 2. RÉFÉRENTIEL DES ACTIONS & CALENDRIER
# ==========================================
CATALOGUE_ACTIONS = {
    "TotalEnergies": {"ticker": "TTE.PA", "div": 3.22, "fondamentaux": 33, "secteur": "Énergie"},
    "Air Liquide": {"ticker": "AI.PA", "div": 3.30, "fondamentaux": 35, "secteur": "Chimie / Gaz"},
    "AXA": {"ticker": "CS.PA", "div": 2.15, "fondamentaux": 32, "secteur": "Assurance"},
    "Vinci": {"ticker": "DG.PA", "div": 4.50, "fondamentaux": 33, "secteur": "Infrastructures"},
    "Engie": {"ticker": "ENGI.PA", "div": 1.43, "fondamentaux": 28, "secteur": "Utilities"},
    "LVMH": {"ticker": "MC.PA", "div": 13.00, "fondamentaux": 34, "secteur": "Luxe"},
    "Sanofi": {"ticker": "SAN.PA", "div": 3.76, "fondamentaux": 31, "secteur": "Santé"},
    "Rubis": {"ticker": "RUI.PA", "div": 1.98, "fondamentaux": 27, "secteur": "Énergie"},
    "Pernod Ricard": {"ticker": "RI.PA", "div": 4.70, "fondamentaux": 29, "secteur": "Spiritueux"},
    "Schneider Electric": {"ticker": "SU.PA", "div": 3.80, "fondamentaux": 34, "secteur": "Industrie"},
    "BNP Paribas": {"ticker": "BNP.PA", "div": 4.60, "fondamentaux": 30, "secteur": "Banque"},
    "Veolia": {"ticker": "VIE.PA", "div": 1.25, "fondamentaux": 28, "secteur": "Environnement"},
}

CALENDRIER_VERSEMENTS = {
    "TotalEnergies": {1: 0.25, 4: 0.25, 7: 0.25, 10: 0.25},
    "Air Liquide": {5: 1.0},
    "AXA": {5: 1.0},
    "BNP Paribas": {5: 1.0},
    "Vinci": {4: 0.75, 11: 0.25},
    "Engie": {5: 1.0},
    "LVMH": {4: 0.60, 12: 0.40},
    "Sanofi": {5: 1.0},
    "Rubis": {6: 1.0},
    "Pernod Ricard": {7: 0.50, 11: 0.50},
    "Schneider Electric": {5: 1.0},
    "Veolia": {5: 1.0},
}

PORTEFEUILLE_DEFAUT = {
    "TotalEnergies": {"qte": 25.0, "pru": 58.50},
    "Air Liquide": {"qte": 12.0, "pru": 162.00},
    "AXA": {"qte": 45.0, "pru": 29.80},
    "Vinci": {"qte": 15.0, "pru": 104.00},
    "Engie": {"qte": 60.0, "pru": 14.50},
    "LVMH": {"qte": 2.0, "pru": 680.00},
    "Sanofi": {"qte": 12.0, "pru": 88.00},
    "Rubis": {"qte": 35.0, "pru": 24.20},
    "Pernod Ricard": {"qte": 0.0, "pru": 0.00},
    "Schneider Electric": {"qte": 6.0, "pru": 195.00},
    "BNP Paribas": {"qte": 18.0, "pru": 61.00},
    "Veolia": {"qte": 20.0, "pru": 27.50},
}

# ==========================================
# 3. CONNEXION SUPABASE & GESTION DU ZÉRO
# ==========================================
def init_supabase():
    if not SUPABASE_DISPO:
        return None
    try:
        url = st.secrets.get("SUPABASE_URL") or st.secrets.get("supabase", {}).get("url")
        key = st.secrets.get("SUPABASE_KEY") or st.secrets.get("supabase", {}).get("key")
        if url and key:
            return create_client(url, key)
    except Exception:
        pass
    return None

supabase_client = init_supabase()

def charger_donnees_cloud(email_user):
    """Charge le portefeuille et les espèces sans jamais remplacer un 0 par la valeur par défaut."""
    if not supabase_client or not email_user:
        return None
    try:
        res = supabase_client.table("utilisateurs").select("*").eq("email", email_user).execute()
        if res.data and len(res.data) > 0:
            return res.data[0]
    except Exception:
        pass
    return None

def sauvegarder_donnees_cloud(email_user, portefeuille_dict, especes_val, watchlist_list):
    """Enregistre explicitement toutes les lignes (y compris celles à 0) et les espèces."""
    if not supabase_client or not email_user:
        return False
    try:
        # Nettoyage strict conservant les quantités à 0.0
        pf_propre = {}
        for nom, vals in portefeuille_dict.items():
            q = float(vals.get("qte", 0.0))
            p = float(vals.get("pru", 0.0))
            pf_propre[nom] = {
                "qte": q,
                "pru": p if q > 0 else 0.0
            }

        payload = {
            "email": email_user,
            "portefeuille": pf_propre,
            "especes": float(especes_val),
            "watchlist": list(watchlist_list)
        }
        supabase_client.table("utilisateurs").upsert(payload, on_conflict="email").execute()
        return True
    except Exception as e:
        st.sidebar.error(f"Erreur Cloud : {e}")
        return False

# ==========================================
# 4. INITIALISATION DU SESSION STATE
# ==========================================
if "email_user" not in st.session_state:
    st.session_state["email_user"] = st.secrets.get("DEFAULT_EMAIL", "investisseur@boursy.fr") if hasattr(st, "secrets") else "investisseur@boursy.fr"

if "cloud_charge" not in st.session_state:
    donnees_cloud = charger_donnees_cloud(st.session_state["email_user"])
    if donnees_cloud is not None:
        # Respect strict du 0 grâce au test "is not None"
        pf_cloud = donnees_cloud.get("portefeuille")
        if pf_cloud is not None and isinstance(pf_cloud, dict):
            pf_init = {}
            for k, def_v in PORTEFEUILLE_DEFAUT.items():
                if k in pf_cloud and pf_cloud[k] is not None:
                    q_c = pf_cloud[k].get("qte")
                    p_c = pf_cloud[k].get("pru")
                    pf_init[k] = {
                        "qte": float(q_c) if q_c is not None else 0.0,
                        "pru": float(p_c) if p_c is not None else 0.0
                    }
                else:
                    pf_init[k] = {"qte": 0.0, "pru": 0.0}
            st.session_state["portefeuille"] = pf_init
        else:
            st.session_state["portefeuille"] = PORTEFEUILLE_DEFAUT.copy()

        esp_cloud = donnees_cloud.get("especes")
        st.session_state["especes"] = float(esp_cloud) if esp_cloud is not None else 0.0

        wl_cloud = donnees_cloud.get("watchlist")
        st.session_state["watchlist"] = wl_cloud if (wl_cloud is not None and len(wl_cloud) > 0) else list(CATALOGUE_ACTIONS.keys())
        st.session_state["est_abonne_pro"] = bool(donnees_cloud.get("est_abonne_pro", True))
    else:
        st.session_state["portefeuille"] = PORTEFEUILLE_DEFAUT.copy()
        st.session_state["especes"] = 0.0
        st.session_state["watchlist"] = list(CATALOGUE_ACTIONS.keys())
        st.session_state["est_abonne_pro"] = True

    st.session_state["cloud_charge"] = True

# ==========================================
# 5. MOTEUR D'ANALYSE VALUE & TECHNIQUE
# ==========================================
@st.cache_data(ttl=900)
def calculer_indicateurs_marche(watchlist_tuple):
    resultats = []
    for nom in watchlist_tuple:
        infos = CATALOGUE_ACTIONS.get(nom, {"ticker": "TTE.PA", "div": 2.0, "fondamentaux": 28, "secteur": "Autre"})
        ticker = infos["ticker"]
        try:
            hist = yf.Ticker(ticker).history(period="3y")
            if hist.empty or len(hist) < 30:
                raise ValueError("Historique insuffisant")

            close = hist["Close"].dropna()
            prix_actuel = float(close.iloc[-1])

            # 1. Régression linéaire sur 3 ans (Cible Value)
            y = close.values
            x = np.arange(len(y))
            pente, ordonnee = np.polyfit(x, y, 1)
            juste_prix = float(pente * (len(y) - 1) + ordonnee)
            ecart_pct = ((prix_actuel - juste_prix) / juste_prix * 100.0) if juste_prix > 0 else 0.0

            # 2. EMA 2 et EMA 12
            ema2 = float(close.ewm(span=2, adjust=False).mean().iloc[-1])
            ema12 = float(close.ewm(span=12, adjust=False).mean().iloc[-1])

            # 3. RSI (14 jours)
            delta = close.diff()
            gain = delta.where(delta > 0, 0.0).rolling(window=14).mean()
            perte = (-delta.where(delta < 0, 0.0)).rolling(window=14).mean()
            rs = gain / perte.replace(0, np.nan)
            rsi_series = 100.0 - (100.0 / (1.0 + rs))
            rsi_val = float(rsi_series.iloc[-1]) if not np.isnan(rsi_series.iloc[-1]) else 50.0

            # 4. MACD (12, 26, Signal 9)
            ema_fast = close.ewm(span=12, adjust=False).mean()
            ema_slow = close.ewm(span=26, adjust=False).mean()
            macd_line = ema_fast - ema_slow
            signal_line = macd_line.ewm(span=9, adjust=False).mean()
            hist_macd = float(macd_line.iloc[-1] - signal_line.iloc[-1])
            if hist_macd > 0.02:
                macd_statut = "Haussier"
            elif hist_macd < -0.02:
                macd_statut = "Baissier"
            else:
                macd_statut = "Neutre"

        except Exception:
            # Valeurs de secours si Yahoo Finance est indisponible
            pru_ref = PORTEFEUILLE_DEFAUT.get(nom, {}).get("pru", 50.0)
            prix_actuel = pru_ref if pru_ref > 0 else 50.0
            juste_prix = prix_actuel * 1.05
            ecart_pct = -4.76
            ema2 = prix_actuel
            ema12 = prix_actuel
            rsi_val = 48.0
            macd_statut = "Neutre"

        resultats.append({
            "Actif": nom,
            "Ticker": ticker,
            "Secteur": infos["secteur"],
            "Prix (€)": round(prix_actuel, 2),
            "Cible Value (€)": round(juste_prix, 2),
            "Écart_Num": round(ecart_pct, 2),
            "Écart %": f"{ecart_pct:+.1f}%",
            "EMA 2": round(ema2, 2),
            "EMA 12": round(ema12, 2),
            "RSI": round(rsi_val, 1),
            "MACD": macd_statut,
            "Div_Unitaire": float(infos["div"]),
            "Score_Fondamentaux": float(infos["fondamentaux"])
        })

    # Tri automatique par plus forte décote Value (Écart_Num croissant)
    resultats_tries = sorted(resultats, key=lambda item: item["Écart_Num"])
    return resultats_tries

# ==========================================
# 6. BARRE LATÉRALE (PROFIL & WATCHLIST)
# ==========================================
with st.sidebar:
    st.title("📈 Boursy Pro")
    st.caption("Pilotage PEA, Value & Dividendes")

    email_saisi = st.text_input("📧 Identifiant Cloud", value=st.session_state["email_user"])
    if email_saisi != st.session_state["email_user"]:
        st.session_state["email_user"] = email_saisi
        del st.session_state["cloud_charge"]
        st.rerun()

    statut_abo = "🌟 Compte PRO Actif" if st.session_state.get("est_abonne_pro", True) else "🔒 Compte Standard"
    st.info(statut_abo)

    st.markdown("---")
    watchlist_selection = st.multiselect(
        "🔍 Valeurs suivies (Watchlist)",
        options=list(CATALOGUE_ACTIONS.keys()),
        default=st.session_state["watchlist"]
    )
    if watchlist_selection != st.session_state["watchlist"]:
        st.session_state["watchlist"] = watchlist_selection

    budget_dca_mensuel = st.number_input(
        "💶 Budget DCA mensuel (€)",
        min_value=50.0,
        value=450.0,
        step=25.0
    )

    if st.button("🔄 Actualiser les cours", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

# Calcul des données de marché triées par décote
t2_filtre = calculer_indicateurs_marche(tuple(st.session_state["watchlist"]))
t3_filtre = t2_filtre.copy()

# ==========================================
# 7. NAVIGATION PRINCIPALE (4 ONGLETS)
# ==========================================
st.title("📊 Boursy — Tableau de Bord Stratégique PEA")

tab_portefeuille, tab_dca, tab_div, tab_ia = st.tabs([
    "💼 1. Portefeuille & Espèces",
    "🎯 2. Analyse Value, Timing & DCA",
    "📅 3. Dividendes & Calendrier",
    "🤖 4. Audit & Agent IA"
])

# ------------------------------------------------------------------
# ONGLET 1 : PORTEFEUILLE & GESTION DES ESPÈCES (AVEC FIX DU ZÉRO)
# ------------------------------------------------------------------
with tab_portefeuille:
    st.subheader("💼 Mon Portefeuille PEA & Liquidités")

    col_edit, col_resume = st.columns([2.2, 1])

    with col_edit:
        st.caption("Modifiez vos quantités, vos PRU et votre poche d'espèces. Une quantité mise à 0 reste bien à 0 après sauvegarde.")
        lignes_editeur = []
        for nom in st.session_state["watchlist"]:
            donnees_p = st.session_state["portefeuille"].get(nom, {"qte": 0.0, "pru": 0.0})
            lignes_editeur.append({
                "Actif": nom,
                "Quantité": float(donnees_p.get("qte", 0.0)),
                "PRU (€)": float(donnees_p.get("pru", 0.0))
            })

        df_editeur = pd.DataFrame(lignes_editeur)
        df_modifie = st.data_editor(
            df_editeur,
            use_container_width=True,
            hide_index=True,
            disabled=["Actif"],
            key="editeur_pea"
        )

        nouvelle_poche_especes = st.number_input(
            "💶 Poche d'Espèces / Liquidités disponibles sur le PEA (€)",
            min_value=0.0,
            value=float(st.session_state.get("especes", 0.0)),
            step=10.0
        )

        if st.button("💾 Enregistrer mon Portefeuille & mes Espèces", type="primary", use_container_width=True):
            nouveau_pf = {}
            for _, row in df_modifie.iterrows():
                act_nom = str(row["Actif"])
                q_val = float(row["Quantité"]) if pd.notna(row["Quantité"]) else 0.0
                p_val = float(row["PRU (€)"]) if pd.notna(row["PRU (€)"]) else 0.0
                nouveau_pf[act_nom] = {
                    "qte": q_val,
                    "pru": p_val if q_val > 0 else 0.0
                }

            st.session_state["portefeuille"] = nouveau_pf
            st.session_state["especes"] = float(nouvelle_poche_especes)

            ok_cloud = sauvegarder_donnees_cloud(
                st.session_state["email_user"],
                nouveau_pf,
                nouvelle_poche_especes,
                st.session_state["watchlist"]
            )
            if ok_cloud:
                st.success("✅ Portefeuille et Espèces sauvegardés dans le Cloud (les lignes à 0 sont bien verrouillées à 0) !")
            else:
                st.success("✅ Portefeuille et Espèces mis à jour dans votre session !")
            st.rerun()

    # Calcul temps réel de la valorisation du portefeuille
    lignes_valorisees = []
    total_actions_val = 0.0
    total_investi_actions = 0.0
    total_div_annuel = 0.0

    prix_map = {d["Actif"]: d["Prix (€)"] for d in t2_filtre}

    for nom, vals in st.session_state["portefeuille"].items():
        qte = float(vals.get("qte", 0.0))
        pru = float(vals.get("pru", 0.0))
        if qte > 0 and nom in st.session_state["watchlist"]:
            cours = float(prix_map.get(nom, pru))
            val_ligne = qte * cours
            inv_ligne = qte * pru
            pv_eur = val_ligne - inv_ligne
            pv_pct = ((cours - pru) / pru * 100.0) if pru > 0 else 0.0
            div_u = float(CATALOGUE_ACTIONS.get(nom, {}).get("div", 0.0))
            div_tot = qte * div_u
            yoc_ligne = (div_u / pru * 100.0) if pru > 0 else 0.0

            total_actions_val += val_ligne
            total_investi_actions += inv_ligne
            total_div_annuel += div_tot

            lignes_valorisees.append({
                "Actif": nom,
                "Qté": int(qte) if qte.is_integer() else qte,
                "PRU (€)": pru,
                "Cours (€)": cours,
                "Valorisation (€)": val_ligne,
                "+/- Value (€)": pv_eur,
                "+/- Value (%)": pv_pct,
                "Dividende Annuel (€)": div_tot,
                "YoC (%)": yoc_ligne
            })

    st.session_state["total_dividendes_annuels"] = total_div_annuel
    df_portefeuille = pd.DataFrame(lignes_valorisees)
    especes_actuelles = float(st.session_state.get("especes", 0.0))
    patrimoine_total_pea = total_actions_val + especes_actuelles
    pv_globale = total_actions_val - total_investi_actions
    pv_globale_pct = (pv_globale / total_investi_actions * 100.0) if total_investi_actions > 0 else 0.0

    with col_resume:
        st.markdown("#### 📌 Synthèse Globale PEA")
        st.metric("💼 Patrimoine Total (Actions + Espèces)", f"{patrimoine_total_pea:,.2f} €")
        st.metric("📈 Valorisation Actions", f"{total_actions_val:,.2f} €", f"{pv_globale:+.2f} € ({pv_globale_pct:+.2f}%)")
        st.metric("💶 Poche d'Espèces Disponible", f"{especes_actuelles:,.2f} €")
        st.metric("🎁 Rente Dividendes Annuelle", f"{total_div_annuel:,.2f} € / an", f"{total_div_annuel/12:.2f} € / mois")

# ------------------------------------------------------------------
# ONGLET 2 : ANALYSE VALUE, TIMING 3 ÉTATS & SIMULATEUR D'IMPACT PRU
# ------------------------------------------------------------------
with tab_dca:
    sous_tab_value, sous_tab_tech, sous_tab_sim = st.tabs([
        "💎 1. Décotes Value (Triées)",
        "🎯 2. Signaux Techniques & Score / 100",
        "🧮 3. Simulateur d'Impact PRU & DCA"
    ])

    with sous_tab_value:
        st.caption("Classement automatique de la plus forte décote à la plus faible (écart par rapport à la droite de régression linéaire 3 ans) :")
        html_t2 = """
        <table class="r-table">
        <thead>
            <tr>
                <th style="text-align: left;">Actif</th>
                <th>Secteur</th>
                <th>Cours Actuel</th>
                <th>Juste Prix (3 ans)</th>
                <th>Décote / Écart %</th>
                <th>Statut Value</th>
            </tr>
        </thead>
        <tbody>
        """
        for d in t2_filtre:
            ec = d["Écart_Num"]
            if ec <= -8.0:
                statut_v = "<span class='b-green'>💎 Forte Décote</span>"
            elif ec <= -2.0:
                statut_v = "<span class='b-green'>🟢 Sous-évaluée</span>"
            elif ec <= 5.0:
                statut_v = "<span class='b-white'>⚪ Prix Juste</span>"
            else:
                statut_v = "<span class='b-red'>🟠 Surévaluée</span>"

            html_t2 += f"""
            <tr>
                <td class="r-name">{d['Actif']}</td>
                <td>{d['Secteur']}</td>
                <td><b>{d['Prix (€)']:.2f} €</b></td>
                <td>{d['Cible Value (€)']:.2f} €</td>
                <td><b>{d['Écart %']}</b></td>
                <td>{statut_v}</td>
            </tr>
            """
        html_t2 += "</tbody></table>"
        st.markdown(html_t2, unsafe_allow_html=True)

    with sous_tab_tech:
        st.caption("Signaux de Timing Court Terme (EMA 2/12 à 3 états : Vert / Blanc / Rouge), RSI (14j), MACD et Score Global sur 100 :")
        html_t3 = """
        <table class="r-table">
        <thead>
            <tr>
                <th style="text-align: left;">Actif</th>
                <th>Cours</th>
                <th>EMA 2 / EMA 12</th>
                <th>RSI (14j)</th>
                <th>MACD</th>
                <th>Signal Timing (EMA 2/12)</th>
                <th>Score / 100</th>
            </tr>
        </thead>
        <tbody>
        """

        donnees_tech = t3_filtre if "t3_filtre" in locals() else t2_filtre

        for d in donnees_tech:
            prix = float(d.get("Prix (€)", 0.0))
            ema2 = float(d.get("EMA 2", d.get("EMA2", prix)))
            ema12 = float(d.get("EMA 12", d.get("EMA12", prix)))
            rsi = float(d.get("RSI", 50.0))
            macd_val = str(d.get("MACD", "Neutre"))

            # --- 1. LOGIQUE DU SIGNAL 3 ÉTATS (VERT / BLANC / ROUGE) ---
            ecart_ema_pct = ((ema2 - ema12) / ema12 * 100) if ema12 > 0 else 0.0

            if ema2 > ema12 and ecart_ema_pct >= 0.15:
                badge_signal = "<span class='b-green'>🟢 ACHAT (Haussier)</span>"
                pts_ema = 15
            elif ema2 < ema12 and ecart_ema_pct <= -0.15:
                badge_signal = "<span class='b-red'>🔴 VENTE (Croisement Baissier)</span>"
                pts_ema = 2
            else:
                badge_signal = "<span class='b-white'>⚪ NEUTRE (Attente)</span>"
                pts_ema = 8

            # --- 2. BONUS / MALUS RSI & MACD (SUR 20 POINTS) ---
            if rsi < 30:
                pts_rsi = 12
                rsi_txt = f"<span style='color: #22c55e; font-weight: bold;'>{rsi:.1f} (Survente)</span>"
            elif rsi < 45:
                pts_rsi = 9
                rsi_txt = f"<span style='color: #86efac;'>{rsi:.1f}</span>"
            elif rsi > 70:
                pts_rsi = 2
                rsi_txt = f"<span style='color: #ef4444; font-weight: bold;'>{rsi:.1f} (Surachat)</span>"
            else:
                pts_rsi = 6
                rsi_txt = f"{rsi:.1f}"

            if "Haussier" in macd_val or "Positif" in macd_val or "+" in macd_val:
                pts_macd = 8
                macd_txt = "<span style='color: #22c55e; font-weight: bold;'>Haussier ↗</span>"
            elif "Baissier" in macd_val or "Négatif" in macd_val or "-" in macd_val:
                pts_macd = 2
                macd_txt = "<span style='color: #ef4444; font-weight: bold;'>Baissier ↘</span>"
            else:
                pts_macd = 5
                macd_txt = "<span style='color: #94a3b8;'>Neutre ➡</span>"

            # --- 3. CALCUL DU SCORE GLOBAL SUR 100 ---
            pts_fondamentaux = float(d.get("Score_Fondamentaux", 28.0))
            ecart_reg = float(str(d.get("Écart %", "0")).replace("%", "").replace("+", ""))
            if ecart_reg <= -10:
                pts_value = 30
            elif ecart_reg <= -3:
                pts_value = 24
            elif ecart_reg <= 5:
                pts_value = 15
            else:
                pts_value = 6

            pts_tech = pts_ema + pts_rsi + pts_macd
            score_100 = int(min(100, max(0, pts_fondamentaux + pts_value + pts_tech)))

            if score_100 >= 75:
                badge_score = f"<span class='b-green'>{score_100} / 100</span>"
            elif score_100 >= 55:
                badge_score = f"<span class='b-yellow'>{score_100} / 100</span>"
            else:
                badge_score = f"<span class='b-red'>{score_100} / 100</span>"

            html_t3 += f"""
            <tr>
                <td class="r-name">{d['Actif']}</td>
                <td><b>{prix:.2f} €</b></td>
                <td>{ema2:.2f} € / {ema12:.2f} €</td>
                <td>{rsi_txt}</td>
                <td>{macd_txt}</td>
                <td>{badge_signal}</td>
                <td>{badge_score}</td>
            </tr>
            """
        html_t3 += "</tbody></table>"
        st.markdown(html_t3, unsafe_allow_html=True)

    with sous_tab_sim:
        st.subheader("🧮 Simulateur d'Impact PRU (Avant Achat)")
        st.caption("Simulez l'effet d'un renforcement sur votre PRU, votre rendement (YoC), vos espèces et la pondération de votre PEA :")

        liste_actifs_sim = [d["Actif"] for d in t2_filtre] if len(t2_filtre) > 0 else list(CATALOGUE_ACTIONS.keys())

        col_s1, col_s2, col_s3 = st.columns(3)
        with col_s1:
            actif_sim = st.selectbox("🎯 Action à renforcer", liste_actifs_sim, key="sim_actif")
            prix_marche_defaut = float(prix_map.get(actif_sim, 50.0))
            infos_pf_sim = st.session_state["portefeuille"].get(actif_sim, {"qte": 0.0, "pru": prix_marche_defaut})
            div_defaut = float(CATALOGUE_ACTIONS.get(actif_sim, {}).get("div", 2.50))

            prix_achat_sim = st.number_input("Prix d'exécution estimé (€)", min_value=0.01, value=float(prix_marche_defaut), step=0.10, key="sim_prix")

        with col_s2:
            qte_actuelle_sim = st.number_input("Quantité actuelle en portefeuille", min_value=0, value=int(infos_pf_sim.get("qte", 0)), step=1, key="sim_qte_act")
            pru_init = float(infos_pf_sim.get("pru", 0.0))
            pru_actuel_sim = st.number_input("PRU actuel (€)", min_value=0.0, value=float(pru_init if pru_init > 0 else prix_marche_defaut), step=0.10, key="sim_pru_act")
            div_action_sim = st.number_input("Dividende annuel / action (€)", min_value=0.0, value=div_defaut, step=0.05, key="sim_div")

        with col_s3:
            qte_achat_sim = st.number_input("➕ Nombre d'actions à acheter", min_value=1, value=5, step=1, key="sim_qte_buy")
            budget_dispo_defaut = float(st.session_state.get("especes", 0.0)) + budget_dca_mensuel
            cash_dispo_sim = st.number_input("💶 Espèces + Budget DCA dispo (€)", min_value=0.0, value=float(budget_dispo_defaut), step=10.0, key="sim_cash")
            val_totale_pea_sim = st.number_input("💼 Valorisation totale du PEA (€)", min_value=100.0, value=float(max(1000.0, patrimoine_total_pea)), step=100.0, key="sim_val_pea")

        # Calculs en temps réel
        cout_ordre = qte_achat_sim * prix_achat_sim
        nouvelle_qte = qte_actuelle_sim + qte_achat_sim
        ancien_investissement = qte_actuelle_sim * pru_actuel_sim
        nouvel_investissement = ancien_investissement + cout_ordre
        nouveau_pru = nouvel_investissement / nouvelle_qte if nouvelle_qte > 0 else 0.0
        diff_pru_pct = ((nouveau_pru - pru_actuel_sim) / pru_actuel_sim * 100) if pru_actuel_sim > 0 else 0.0

        ancien_yoc = (div_action_sim / pru_actuel_sim * 100) if pru_actuel_sim > 0 else 0.0
        nouveau_yoc = (div_action_sim / nouveau_pru * 100) if nouveau_pru > 0 else 0.0
        gain_rente_annuelle = qte_achat_sim * div_action_sim

        nouveau_poids_ligne = (nouvel_investissement / (val_totale_pea_sim + cout_ordre) * 100) if (val_totale_pea_sim + cout_ordre) > 0 else 0.0
        cash_restant = cash_dispo_sim - cout_ordre

        st.markdown("#### 📊 Résultat de votre simulation")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Nouveau PRU", f"{nouveau_pru:.2f} €", f"{diff_pru_pct:+.2f} %", delta_color="inverse")
        m2.metric("Nouveau Rendement (YoC)", f"{nouveau_yoc:.2f} %", f"{nouveau_yoc - ancien_yoc:+.2f} % vs avant")
        m3.metric("Poids de la ligne", f"{nouveau_poids_ligne:.1f} %", "Seuil max : 25%", delta_color="off")
        m4.metric("Liquidités restantes", f"{cash_restant:.2f} €", f"-{cout_ordre:.2f} € (Coût ordre)", delta_color="normal")

        if cash_restant < 0:
            st.error(f"⚠️ **Budget insuffisant** : Il vous manque **{abs(cash_restant):.2f} €** de liquidités pour passer cet ordre de {qte_achat_sim} actions.")
        elif nouveau_poids_ligne > 25.0:
            st.warning(f"⚠️ **Alerte Concentration** : Cet achat porte la ligne **{actif_sim}** à **{nouveau_poids_ligne:.1f} %** de votre portefeuille (au-dessus du seuil de sécurité de 25 %).")
        else:
            st.success(f"✅ **Ordre validé par le simulateur** : Cet achat ajoute **+{gain_rente_annuelle:.2f} €/an** (+{gain_rente_annuelle/12:.2f} €/mois) à votre rente de dividendes tout en respectant vos règles de gestion !")

# ------------------------------------------------------------------
# ONGLET 3 : DIVIDENDES & DIAGRAMME EN BÂTONS MOIS PAR MOIS
# ------------------------------------------------------------------
with tab_div:
    st.subheader("📅 Calendrier Annuel des Versements (Mois par Mois)")
    st.caption("Répartition estimée de vos flux de trésorerie selon le calendrier réel de détachement des dividendes :")

    noms_mois = ["01 - Jan", "02 - Fév", "03 - Mar", "04 - Avr", "05 - Mai", "06 - Juin", "07 - Juil", "08 - Août", "09 - Sep", "10 - Oct", "11 - Nov", "12 - Déc"]
    revenus_mensuels = {m: 0.0 for m in range(1, 13)}

    div_annuel_total = float(st.session_state.get("total_dividendes_annuels", 824.40))

    if not df_portefeuille.empty:
        for _, row in df_portefeuille.iterrows():
            nom_act = str(row.get("Actif", ""))
            div_ligne = float(row.get("Dividende Annuel (€)", 0.0))
            repartition = CALENDRIER_VERSEMENTS.get(nom_act, {5: 1.0})
            for mois_num, poids_m in repartition.items():
                revenus_mensuels[mois_num] += div_ligne * poids_m
    else:
        profil_pea_type = {1: 0.06, 2: 0.01, 3: 0.02, 4: 0.12, 5: 0.42, 6: 0.14, 7: 0.07, 8: 0.01, 9: 0.02, 10: 0.06, 11: 0.04, 12: 0.03}
        for mois_num, poids_m in profil_pea_type.items():
            revenus_mensuels[mois_num] = round(div_annuel_total * poids_m, 2)

    df_cal_div = pd.DataFrame({
        "Mois": noms_mois,
        "Dividendes (€)": [round(revenus_mensuels[m], 2) for m in range(1, 13)]
    }).set_index("Mois")

    st.bar_chart(df_cal_div, color="#22c55e", height=320)

    total_cal = sum(revenus_mensuels.values())
    moyenne_lissee = total_cal / 12.0
    mois_max_idx = max(revenus_mensuels, key=revenus_mensuels.get)

    c_d1, c_d2, c_d3 = st.columns(3)
    c_d1.metric("💰 Total Annuel Estimé", f"{total_cal:.2f} €")
    c_d2.metric("📆 Moyenne Mensuelle Lissée", f"{moyenne_lissee:.2f} € / mois")
    c_d3.metric("🚀 Mois le plus fort", f"{noms_mois[mois_max_idx - 1]} ({revenus_mensuels[mois_max_idx]:.2f} €)")

    if not df_portefeuille.empty:
        st.markdown("---")
        st.markdown("#### 📋 Détail des Dividendes et Rendements sur Coût (YoC) par Ligne")
        st.dataframe(
            df_portefeuille[["Actif", "Qté", "PRU (€)", "Cours (€)", "Dividende Annuel (€)", "YoC (%)"]],
            use_container_width=True,
            hide_index=True
        )

# ------------------------------------------------------------------
# ONGLET 4 : AUDIT & AGENT IA (BARRE CONFINÉE + PLAN ESPÈCES AUTO)
# ------------------------------------------------------------------
with tab_ia:
    st.subheader("🤖 Audit du Portefeuille & Coach IA")
    st.caption("Analyse stratégique de votre PEA, déploiement intelligent de vos espèces disponibles et accompagnement DCA.")

    especes_dispo = float(st.session_state.get("especes", 0.0))

    opportunites_ia = []
    for d in t2_filtre:
        nom_a = d.get("Actif", "")
        prix_a = float(d.get("Prix (€)", 0.0))
        ecart_val = float(d.get("Écart_Num", 0.0))
        ema2_a = float(d.get("EMA 2", prix_a))
        ema12_a = float(d.get("EMA 12", prix_a))
        rsi_a = float(d.get("RSI", 50.0))

        if prix_a > 0:
            opportunites_ia.append({
                "Actif": nom_a,
                "Prix": prix_a,
                "Ecart": ecart_val,
                "RSI": rsi_a,
                "Timing_OK": ema2_a >= (ema12_a * 0.998)
            })

    opportunites_ia = sorted(opportunites_ia, key=lambda x: x["Ecart"])

    # --- PROPOSITION AUTOMATIQUE D'UTILISATION DES ESPÈCES (COMME LE DCA) ---
    if especes_dispo > 0 and len(opportunites_ia) > 0:
        st.markdown("### 💶 Plan d'utilisation de votre poche d'Espèces")
        st.info(f"Vous disposez actuellement de **{especes_dispo:.2f} €** de liquidités disponibles sur votre portefeuille. Voici la proposition d'allocation optimale de l'Agent IA selon les décotes et le timing actuels :")

        cibles_cash = [op for op in opportunites_ia if op["Prix"] <= especes_dispo][:3]

        if len(cibles_cash) > 0:
            budget_restant = especes_dispo
            repartition_poids = [0.50, 0.30, 0.20] if len(cibles_cash) == 3 else ([0.60, 0.40] if len(cibles_cash) == 2 else [1.0])

            lignes_plan = []
            for idx, cible in enumerate(cibles_cash):
                enveloppe_cible = especes_dispo * repartition_poids[idx]
                if enveloppe_cible < cible["Prix"] and budget_restant >= cible["Prix"]:
                    nb_actions = 1
                else:
                    nb_actions = int(min(enveloppe_cible, budget_restant) // cible["Prix"])

                if nb_actions > 0:
                    cout_ligne = nb_actions * cible["Prix"]
                    budget_restant -= cout_ligne
                    statut_t = "🟢 Timing Favorable" if cible["Timing_OK"] else "⚪ Accumulation sur repli"
                    lignes_plan.append(
                        f"- **{cible['Actif']}** (Décote `{cible['Ecart']:+.1f}%` | {statut_t}) 👉 **Acheter {nb_actions} action(s)** à {cible['Prix']:.2f} € = **{cout_ligne:.2f} €**"
                    )

            if len(lignes_plan) > 0:
                for l_p in lignes_plan:
                    st.markdown(l_p)
                st.caption(f"💰 **Total investi :** {especes_dispo - budget_restant:.2f} € | **Reliquat espèces conservé :** {budget_restant:.2f} €")
            else:
                st.warning("Vos espèces actuelles sont inférieures au prix unitaire des actions les plus décotées. Conservez-les pour les cumuler avec votre prochain versement DCA.")
        else:
            st.warning(f"Vos liquidités ({especes_dispo:.2f} €) ne permettent pas encore d'acheter une action entière parmi les cibles principales. Cumulez cette poche avec votre prochain DCA.")
    else:
        st.caption("ℹ️ *Aucune poche d'espèces disponible actuellement (0,00 €). Renseignez vos liquidités dans l'onglet 1 pour activer le plan de déploiement automatique.*")

    st.markdown("---")

    # --- CHATBOT IA STRICTEMENT CONFINÉ DANS L'ONGLET 4 ---
    if "messages_ia" not in st.session_state:
        st.session_state["messages_ia"] = []

    col_b1, col_b2 = st.columns(2)
    with col_b1:
        btn_audit_cash = st.button("✨ Générer une stratégie Espèces + DCA du mois", use_container_width=True)
    with col_b2:
        if st.button("🗑️ Effacer la conversation", use_container_width=True):
            st.session_state["messages_ia"] = []
            st.rerun()

    conteneur_chat = st.container()
    with conteneur_chat:
        for msg in st.session_state["messages_ia"]:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

    with st.form(key="form_agent_ia", clear_on_submit=True):
        col_input, col_btn = st.columns([5, 1])
        with col_input:
            question_user = st.text_input(
                "Votre question à l'Agent IA :",
                placeholder="Ex : Comment combiner mes espèces et mon DCA de 450 € ce mois-ci ?",
                label_visibility="collapsed"
            )
        with col_btn:
            envoyer_ia = st.form_submit_button("Envoyer 🚀", use_container_width=True)

    requete_finale = None
    if btn_audit_cash:
        requete_finale = f"Propose-moi une stratégie précise pour utiliser ma poche d'espèces de {especes_dispo:.2f} € combinée avec mon DCA de {budget_dca_mensuel:.0f} € selon les meilleures décotes Value et les signaux techniques actuels."
    elif envoyer_ia and question_user:
        requete_finale = question_user

    if requete_finale:
        st.session_state["messages_ia"].append({"role": "user", "content": requete_finale})
        resume_opps = ", ".join([f"{op['Actif']} (Cours: {op['Prix']:.2f}€, Décote: {op['Ecart']:+.1f}%, RSI: {op['RSI']:.0f})" for op in opportunites_ia[:5]])

        prompt_enrichi = (
            f"Tu es le Coach IA expert du portefeuille PEA Boursy. "
            f"Poche d'espèces immédiatement disponible : {especes_dispo:.2f} €. "
            f"Budget DCA mensuel : {budget_dca_mensuel:.2f} €. "
            f"Top 5 des opportunités Value et Techniques actuelles : {resume_opps}. "
            f"Propose toujours une répartition chiffrée (nombre d'actions à acheter, coût exact et reliquat) en respectant la limite de 25 % maximum par ligne. "
            f"Question : {requete_finale}"
        )

        with st.spinner("Analyse de votre portefeuille par l'Agent IA..."):
            reponse_ia = None
            if GEMINI_DISPO and hasattr(st, "secrets"):
                api_key = st.secrets.get("GEMINI_API_KEY") or st.secrets.get("GOOGLE_API_KEY")
                if api_key:
                    try:
                        genai.configure(api_key=api_key)
                        model = genai.GenerativeModel("gemini-1.5-flash")
                        reponse_ia = model.generate_content(prompt_enrichi).text
                    except Exception:
                        reponse_ia = None

            if not reponse_ia:
                enveloppe_totale = especes_dispo + budget_dca_mensuel
                cibles_synthese = opportunites_ia[:3]
                details_conseil = "\n".join([
                    f"- **{c['Actif']}** (Cours : `{c['Prix']:.2f} €` | Décote : `{c['Ecart']:+.1f}%` | RSI : `{c['RSI']:.0f}`)"
                    for c in cibles_synthese
                ])
                reponse_ia = (
                    f"📊 **Analyse Stratégique Boursy (Espèces + DCA = {enveloppe_totale:.2f} €) :**\n\n"
                    f"**1. Cibles prioritaires identifiées aujourd'hui :**\n{details_conseil}\n\n"
                    f"**2. Recommandation d'exécution :**\n"
                    f"- Déployez en priorité votre poche d'espèces (**{especes_dispo:.2f} €**) et votre DCA (**{budget_dca_mensuel:.0f} €**) sur les 2 premières valeurs ci-dessus qui cumulent décote Value et RSI hors surachat.\n"
                    f"- Vérifiez l'ordre dans l'onglet **Simulateur d'Impact PRU** avant validation pour confirmer l'amélioration de votre rendement sur coût (YoC)."
                )

        st.session_state["messages_ia"].append({"role": "assistant", "content": reponse_ia})
        st.rerun()
