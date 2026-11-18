"""
Onglet 5 de Boursy : arbitrages, ventes enregistrées et calendrier 12 mois des plus-values actées (réservé au Pro).

Toutes les informations venues du reste de l'application sont des paramètres nommés d'afficher() :
leur liste est la liste exacte des dépendances de l'onglet (vérifiée par tests/test_application.py).
"""
from datetime import datetime

import streamlit as st

from carnet_decisions import LONGUEUR_NOTE_MAX, RAISONS
from habillage import afficher_html, markdown_fr, nombres_fr


def afficher(
    *,
    CLES_TECHNIQUES_PF,
    TAUX_USD_EUR,
    WATCHLIST_DEFAUT,
    afficher_verrou_saas,
    construire_position,
    est_pro_max,
    facteur_cout_usd,
    noter_dans_carnet,
    plus_value_globale,
    portefeuille_utilisateur,
    sauvegarder_dans_cloud,
    supabase,
    valeur_totale_portefeuille,
):
    st.subheader("💰 Journal des Arbitrages & Calendrier 12 Mois des Plus-Values Actées")

    if not est_pro_max:
        afficher_verrou_saas(
            "Journal des Arbitrages, Crédit Espèces Auto & Calendrier 12 Mois des Plus-Values Actées",
            "👑 Offre Pro (8,90 €/mois)",
            "Ce module exclusif Pro déduit automatiquement vos actions vendues du portefeuille, crédite votre poche Espèces en 1 clic et calcule votre calendrier mensuel Argon de plus-values réalisées ainsi que votre Win Rate."
        )
        afficher_html("""
        <div class="argon-grid" style="opacity:0.45; pointer-events:none; filter:blur(2px);">
            <div class="argon-card" style="border-top: 3px solid #2ecc71;">
                <div class="argon-title">💰 Total Plus/Moins-Values Actées</div>
                <div class="argon-val" style="color:#2ecc71;">+1 420,00 €</div>
                <div class="argon-sub">Aperçu réservé aux membres Pro</div>
            </div>
            <div class="argon-card" style="border-top: 3px solid #3498db;">
                <div class="argon-title">📈 Performance d'Extraction Réelle</div>
                <div class="argon-val" style="color:#2ecc71;">+18,40%</div>
                <div class="argon-sub">Calcul automatique sur PRU</div>
            </div>
            <div class="argon-card" style="border-top: 3px solid #2ecc71;">
                <div class="argon-title">🎯 Taux de Réussite (Win Rate)</div>
                <div class="argon-val" style="color:#3498db;">88%</div>
                <div class="argon-sub">Suivi des arbitrages gagnants</div>
            </div>
            <div class="argon-card" style="border-top: 3px solid #9b59b6;">
                <div class="argon-title">💵 Cash Total Extrait (Cessions)</div>
                <div class="argon-val" style="color:#9b59b6;">9 140,00 €</div>
                <div class="argon-sub">Crédit Espèces automatique</div>
            </div>
        </div>
        """)
    else:
        st.caption("Enregistrez vos cessions : vos actions sont immédiatement déduites du portefeuille, le cash net rejoint vos Espèces (si coché) et vos plus/moins-values s'additionnent mois par mois dans le calendrier Argon.")

        # --- RECHARGEMENT AUTOMATIQUE DES VENTES DEPUIS SUPABASE À LA CONNEXION ---
        if supabase and st.session_state.get("user"):
            uid_connecte = str(st.session_state["user"].id)
            # Une seule tentative par compte et par session (avant : une requête Supabase à CHAQUE rafraîchissement
            # tant que l'historique des ventes était vide)
            if (
                not st.session_state.get("historique_ventes")
                and not st.session_state.get("_ventes_videes_volontairement", False)
                and st.session_state.get("_ventes_rechargees_pour") != uid_connecte
            ):
                st.session_state["_ventes_rechargees_pour"] = uid_connecte
                try:
                    rep_v = supabase.table("user_data").select("portefeuille").eq("user_id", uid_connecte).execute()
                    if rep_v.data and len(rep_v.data) > 0:
                        pf_cloud = rep_v.data[0].get("portefeuille") or {}
                        if isinstance(pf_cloud, dict) and isinstance(pf_cloud.get("_historique_ventes"), list):
                            st.session_state["historique_ventes"] = list(pf_cloud["_historique_ventes"])
                except Exception:
                    pass

        def executer_vente_portefeuille(act_v, qte_det_v, pru_v, dev_sym_v):
            qte_vendue = int(st.session_state.get(f"input_qte_v_{act_v}", 1))
            prix_vente = float(st.session_state.get(f"input_prix_v_{act_v}", pru_v))
            frais_v = float(st.session_state.get(f"input_frais_v_{act_v}", 0.0))
            date_v = st.session_state.get(f"input_date_v_{act_v}", datetime.now().date())
            crediter_esp = bool(st.session_state.get(f"input_cred_esp_{act_v}", True))

            facteur_v = (1.0 / TAUX_USD_EUR) if dev_sym_v == "$" else 1.0
            montant_brut_eur = qte_vendue * prix_vente * facteur_v
            montant_net_eur = round(montant_brut_eur - frais_v, 2)
            # Coût d'achat au taux €/$ du jour de l'achat (s'il est renseigné) : la plus-value actée inclut l'effet de change
            pos_avant_vente = st.session_state["portefeuille"].get(act_v)
            facteur_cout_v = facteur_cout_usd(pos_avant_vente) if dev_sym_v == "$" else 1.0
            taux_achat_v = pos_avant_vente.get("taux_achat") if isinstance(pos_avant_vente, dict) else None
            cout_init_eur = round(qte_vendue * pru_v * facteur_cout_v, 2)
            pv_eur = round(montant_net_eur - cout_init_eur, 2)
            perf_pct = round((pv_eur / cout_init_eur * 100.0) if cout_init_eur > 0 else 0.0, 2)

            nouvelle_vente = {
                "id": datetime.now().strftime("%Y%m%d%H%M%S"),
                "date": date_v.strftime("%Y-%m-%d"),
                "annee": date_v.strftime("%Y"),
                "mois_num": int(date_v.strftime("%m")),
                "mois_annee": date_v.strftime("%Y-%m"),
                "action": act_v,
                "qte": qte_vendue,
                "pru": float(pru_v),
                "prix_vente": float(prix_vente),
                "frais_eur": float(frais_v),
                "devise": dev_sym_v,
                "montant_eur": montant_net_eur,
                "cout_initial_eur": cout_init_eur,
                "plus_value_eur": pv_eur,
                "perf_pct": perf_pct,
                "credite_especes": crediter_esp,
            }
            if taux_achat_v:
                nouvelle_vente["taux_achat"] = taux_achat_v
            if "historique_ventes" not in st.session_state or not isinstance(st.session_state["historique_ventes"], list):
                st.session_state["historique_ventes"] = []
            st.session_state["historique_ventes"].insert(0, nouvelle_vente)
            st.session_state["portefeuille"]["_historique_ventes"] = st.session_state["historique_ventes"]
            st.session_state["_ventes_videes_volontairement"] = False

 
           # 1. Déduction immédiate des actions dans l'Onglet 2
            nouvelle_qte = max(0, int(qte_det_v) - qte_vendue)
            st.session_state[f"qte_{act_v}"] = nouvelle_qte
            if nouvelle_qte <= 0:
                st.session_state["portefeuille"].pop(act_v, None)
            else:
                if act_v in st.session_state["portefeuille"] and isinstance(st.session_state["portefeuille"][act_v], dict):
                    st.session_state["portefeuille"][act_v]["qte"] = nouvelle_qte
                else:
                    st.session_state["portefeuille"][act_v] = construire_position(act_v, nouvelle_qte, float(pru_v))

            # 2. Crédit automatique de la poche Espèces
            if crediter_esp:
                esp_dict = st.session_state["portefeuille"].get("Espèces", {})
                esp_actuel = float(st.session_state.get("pru_Espèces", esp_dict.get("pru", 0.0) if isinstance(esp_dict, dict) else 0.0))
                nouveau_esp = round(max(0.0, esp_actuel + montant_net_eur), 2)
                st.session_state["pru_Espèces"] = nouveau_esp
                st.session_state["qte_Espèces"] = 1 if nouveau_esp > 0 else 0
                if nouveau_esp > 0:
                    st.session_state["portefeuille"]["Espèces"] = {"qte": 1, "pru": nouveau_esp}

            vente_notee = noter_dans_carnet("vente", act_v, date_v, st.session_state.get(f"input_raison_v_{act_v}"),
                                            st.session_state.get(f"input_note_v_{act_v}"), "vente", qte_vendue, prix_vente)
            st.session_state[f"input_note_v_{act_v}"] = ""
            st.session_state[f"input_raison_v_{act_v}"] = "—"
            sauvegarder_dans_cloud()
            st.session_state["_derniere_notif_vente"] = (
                f"✅ Vente actée : -{qte_vendue} {act_v} (Reste : {nouvelle_qte}) | "
                f"Plus/Moins-Value actée : {pv_eur:+,.2f} € ({perf_pct:+.2f}%)"
                + (f" | +{montant_net_eur:,.2f} € crédités dans vos Espèces !" if crediter_esp else "")
                + (" | Raison notée dans le carnet de décisions." if vente_notee else "")
            )

        def annuler_vente_portefeuille(idx_v):
            hist = st.session_state.get("historique_ventes", [])
            if 0 <= idx_v < len(hist):
                v_suppr = hist.pop(idx_v)
                st.session_state["portefeuille"]["_historique_ventes"] = hist
                if len(hist) == 0:
                    st.session_state["_ventes_videes_volontairement"] = True

                act_s = v_suppr.get("action", "")
                qte_s = int(v_suppr.get("qte", 0))
                pru_s = float(v_suppr.get("pru", 0.0))
                mt_s = float(v_suppr.get("montant_eur", 0.0))
                avait_credite_esp = bool(v_suppr.get("credite_especes", False))

                if act_s and qte_s > 0:
                    pos_s = st.session_state["portefeuille"].get(act_s, {})
                    qte_actuelle = int(st.session_state.get(f"qte_{act_s}", pos_s.get("qte", 0) if isinstance(pos_s, dict) else 0))
                    qte_restauree = qte_actuelle + qte_s
                    pru_rest = float(st.session_state.get(f"pru_{act_s}", pru_s))
                    st.session_state[f"qte_{act_s}"] = qte_restauree
                    st.session_state[f"pru_{act_s}"] = pru_rest
                    pos_restauree = construire_position(act_s, qte_restauree, pru_rest)
                    if v_suppr.get("taux_achat") and "taux_achat" not in pos_restauree:
                        # La ligne avait été entièrement vendue : on lui rend le taux €/$ d'achat mémorisé avec la vente
                        pos_restauree["taux_achat"] = v_suppr["taux_achat"]
                        try:
                            st.session_state[f"txa_{act_s}"] = min(5.0, max(0.0, float(v_suppr["taux_achat"])))
                        except Exception:
                            pass
                    st.session_state["portefeuille"][act_s] = pos_restauree

                if avait_credite_esp and mt_s > 0:
                    esp_d = st.session_state["portefeuille"].get("Espèces", {})
                    esp_act = float(st.session_state.get("pru_Espèces", esp_d.get("pru", 0.0) if isinstance(esp_d, dict) else 0.0))
                    nouv_esp = round(max(0.0, esp_act - mt_s), 2)
                    st.session_state["pru_Espèces"] = nouv_esp
                    if nouv_esp > 0:
                        st.session_state["portefeuille"]["Espèces"] = {"qte": 1, "pru": nouv_esp}
                    else:
                        st.session_state["portefeuille"].pop("Espèces", None)
                        st.session_state["qte_Espèces"] = 0

                sauvegarder_dans_cloud()
                st.session_state["_derniere_notif_vente"] = f"🔄 Arbitrage annulé : +{qte_s} action(s) {act_s} restaurée(s) en portefeuille."

        if st.session_state.get("_derniere_notif_vente"):
            st.success(nombres_fr(st.session_state.pop("_derniere_notif_vente")))

        # --- BANDEAU DE CONTRÔLE EN DIRECT (ACTIONS vs ESPÈCES vs TOTAL) ---
        esp_dispo_actuel = float(portefeuille_utilisateur.get("Espèces", {}).get("pru", 0.0)) if isinstance(portefeuille_utilisateur.get("Espèces"), dict) else 0.0
        val_actions_seules = max(0.0, valeur_totale_portefeuille - esp_dispo_actuel)

        html_bar_synchro = f"""
        <div class="meteo-bar" style="margin-bottom: 16px;">
            <div class="meteo-item" style="border-left-color:#3498db;">
                <div>
                    <div style="font-size:0.74em; font-weight:800; opacity:0.75;">📈 VALORISATION ACTIONS SEULES</div>
                    <div style="font-size:1.05em; font-weight:900;">{val_actions_seules:,.2f} €</div>
                </div>
            </div>
            <div class="meteo-item" style="border-left-color:#2ecc71;">
                <div>
                    <div style="font-size:0.74em; font-weight:800; opacity:0.75;">💶 POCHE ESPÈCES DISPONIBLE</div>
                    <div style="font-size:1.05em; font-weight:900; color:#2ecc71;">{esp_dispo_actuel:,.2f} €</div>
                </div>
            </div>
            <div class="meteo-item" style="border-left-color:#9b59b6;">
                <div>
                    <div style="font-size:0.74em; font-weight:800; opacity:0.75;">💼 PATRIMOINE TOTAL (ACTIONS + ESPÈCES)</div>
                    <div style="font-size:1.05em; font-weight:900;">{valeur_totale_portefeuille:,.2f} € <span style="font-size:0.82em; opacity:0.8;">(PV Latente : {plus_value_globale:+,.2f} €)</span></div>
                </div>
            </div>
        </div>
        """
        afficher_html(html_bar_synchro)

        # --- GUICHET D'ENREGISTREMENT D'UNE VENTE ---
        actions_vendables = [
            k for k, v in portefeuille_utilisateur.items()
            if k not in CLES_TECHNIQUES_PF and isinstance(v, dict) and float(v.get("qte", 0)) > 0
        ]

        with st.expander("➕ Enregistrer une nouvelle vente d'action (Déduction Actions & Crédit Espèces automatiques)", expanded=not bool(st.session_state.get("historique_ventes"))):
            if not actions_vendables:
                st.info("Vous ne possédez actuellement aucune action en portefeuille à vendre. Renseignez d'abord vos lignes dans l'onglet 2.")
            else:
                action_vendue = st.selectbox("1️⃣ Choisissez l'action vendue :", actions_vendables, key="sel_action_vente")

                pos_actuelle_v = portefeuille_utilisateur.get(action_vendue, {})
                qte_detenue = int(pos_actuelle_v.get("qte", 1))
                pru_actuel = float(pos_actuelle_v.get("pru", 0.0))
                info_w_v = WATCHLIST_DEFAUT.get(action_vendue, {})
                dev_v = "$" if info_w_v.get("devise") == "USD" else "€"
                cours_actuel_v = float(st.session_state.get("prix_temps_reel", {}).get(action_vendue, pru_actuel))

                markdown_fr(
                    f"<div style='background:rgba(52,152,219,0.08); border-left:4px solid #3498db; padding:8px 12px; border-radius:6px; margin-bottom:12px; font-size:0.9em;'>"
                    f"📌 En portefeuille : <b>{qte_detenue} action(s) {action_vendue}</b> | Votre PRU : <b>{pru_actuel:.2f} {dev_v}</b> | Cours actuel : <b>{cours_actuel_v:.2f} {dev_v}</b>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

                col_v1, col_v2, col_v3, col_v4 = st.columns(4)
                with col_v1:
                    qte_a_vendre = st.number_input("Quantité vendue :", min_value=1, max_value=qte_detenue, value=min(1, qte_detenue), step=1, key=f"input_qte_v_{action_vendue}")
                with col_v2:
                    prix_vente_saisi = st.number_input(f"Prix de vente unitaire ({dev_v}) :", min_value=0.01, value=float(round(cours_actuel_v, 2)), step=0.5, key=f"input_prix_v_{action_vendue}")
                with col_v3:
                    frais_vente_eur = st.number_input("Frais de courtage (€) :", min_value=0.0, value=0.0, step=0.5, key=f"input_frais_v_{action_vendue}")
                with col_v4:
                    st.date_input("Date de la vente :", value=datetime.now(), key=f"input_date_v_{action_vendue}")

                col_v5, col_v6 = st.columns([1, 2])
                with col_v5:
                    st.selectbox("📓 Pourquoi cette vente ? (facultatif)", ["—"] + RAISONS["vente"], key=f"input_raison_v_{action_vendue}",
                                 help="Noté dans le carnet de décisions (onglet 2) : plus tard, Boursy vous montrera ce qu'est devenue la valeur.")
                with col_v6:
                    st.text_input("En une phrase (facultatif) :", max_chars=LONGUEUR_NOTE_MAX, key=f"input_note_v_{action_vendue}",
                                  placeholder="Ex. : objectif atteint, la ligne pesait 30 % du portefeuille.")

                st.checkbox(
                    "💶 Créditer automatiquement le montant net encaissé dans ma poche Espèces (Liquidités)",
                    value=True,
                    key=f"input_cred_esp_{action_vendue}",
                )

                facteur_apercu = (1.0 / TAUX_USD_EUR) if dev_v == "$" else 1.0
                net_apercu_eur = round((qte_a_vendre * prix_vente_saisi * facteur_apercu) - frais_vente_eur, 2)
                facteur_cout_apercu = facteur_cout_usd(pos_actuelle_v) if dev_v == "$" else 1.0
                cout_apercu_eur = round(qte_a_vendre * pru_actuel * facteur_cout_apercu, 2)
                pv_apercu_eur = round(net_apercu_eur - cout_apercu_eur, 2)
                perf_apercu_pct = (pv_apercu_eur / cout_apercu_eur * 100.0) if cout_apercu_eur > 0 else 0.0
                c_apercu = "#2ecc71" if pv_apercu_eur >= 0 else "#e74c3c"

                markdown_fr(
                    f"<div style='background:rgba(128,128,128,0.05); border:1px dashed {c_apercu}; padding:10px 14px; border-radius:8px; margin:8px 0 12px 0; font-size:0.88em;'>"
                    f"🔎 <b>Aperçu de l'opération :</b> Reste après vente : <b>{qte_detenue - qte_a_vendre} titre(s) {action_vendue}</b> | "
                    f"Cash net encaissé : <b>+{net_apercu_eur:,.2f} €</b> | "
                    f"Plus/Moins-Value actée : <span style='color:{c_apercu}; font-weight:800;'>{pv_apercu_eur:+,.2f} € ({perf_apercu_pct:+.2f}%)</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

                st.button(
                    "🚀 Valider la vente & Ajouter au Calendrier des Plus-Values",
                    type="primary",
                    width="stretch",
                    on_click=executer_vente_portefeuille,
                    args=(action_vendue, qte_detenue, pru_actuel, dev_v),
                )

        historique_v = st.session_state.get("historique_ventes", [])

        if not historique_v:
            st.info("💡 Aucune vente enregistrée pour le moment. Dès que vous validerez une vente ci-dessus, votre calendrier 12 mois Argon s'affichera automatiquement.")
        else:
            total_pv_actee = sum(float(v.get("plus_value_eur", 0.0)) for v in historique_v)
            total_montant_vendu = sum(float(v.get("montant_eur", 0.0)) for v in historique_v)
            total_cout_initial = sum(float(v.get("cout_initial_eur", float(v.get("montant_eur", 0.0)) - float(v.get("plus_value_eur", 0.0)))) for v in historique_v)
            perf_globale_actee_pct = (total_pv_actee / total_cout_initial * 100.0) if total_cout_initial > 0 else 0.0

            nb_gagnantes = sum(1 for v in historique_v if float(v.get("plus_value_eur", 0.0)) >= 0)
            nb_perdantes = len(historique_v) - nb_gagnantes
            win_rate = (nb_gagnantes / len(historique_v) * 100.0) if historique_v else 0.0
            c_pv_act = "#2ecc71" if total_pv_actee >= 0 else "#e74c3c"

            # --- 4 CARTES KPI ARGON ---
            html_kpi_ventes = f"""
            <div class="argon-grid">
                <div class="argon-card" style="border-top: 3px solid {c_pv_act};">
                    <div class="argon-title">💰 Total Plus/Moins-Values Actées</div>
                    <div class="argon-val" style="color:{c_pv_act};">{total_pv_actee:+,.2f} €</div>
                    <div class="argon-sub">Solde net réalisé sur {len(historique_v)} opération(s)</div>
                </div>
                <div class="argon-card" style="border-top: 3px solid #3498db;">
                    <div class="argon-title">📈 Performance d'Extraction Réelle</div>
                    <div class="argon-val" style="color:{c_pv_act};">{perf_globale_actee_pct:+.2f}%</div>
                    <div class="argon-sub">Sur {total_cout_initial:,.0f} € de capital initial cédé</div>
                </div>
                <div class="argon-card" style="border-top: 3px solid #2ecc71;">
                    <div class="argon-title">🎯 Taux de Réussite (Win Rate)</div>
                    <div class="argon-val" style="color:#3498db;">{win_rate:.0f}%</div>
                    <div class="argon-sub"><span style="color:#2ecc71; font-weight:700;">{nb_gagnantes} gagnante(s)</span> / <span style="color:#e74c3c; font-weight:700;">{nb_perdantes} perdante(s)</span></div>
                </div>
                <div class="argon-card" style="border-top: 3px solid #9b59b6;">
                    <div class="argon-title">💵 Cash Total Extrait (Cessions)</div>
                    <div class="argon-val" style="color:#9b59b6;">{total_montant_vendu:,.2f} €</div>
                    <div class="argon-sub">Poche Espèces actuelle : <b>{esp_dispo_actuel:,.2f} €</b></div>
                </div>
            </div>
            """
            afficher_html(html_kpi_ventes)

            # ======================================================================
            # CALENDRIER 12 MOIS ARGON DES PLUS & MOINS-VALUES ACTÉES
            # ======================================================================
            annees_dispo = sorted(list({str(v.get("date", str(datetime.now().year)))[:4] for v in historique_v}), reverse=True)
            if not annees_dispo:
                annees_dispo = [str(datetime.now().year)]
            options_filtre_annee = annees_dispo + (["Toutes les années (Cumul)"] if len(annees_dispo) > 1 else [])

            col_an_t, col_an_sel = st.columns([2.8, 1.2])
            with col_an_t:
                st.markdown("#### 🗓️ Calendrier Mensuel des Plus & Moins-Values Actées (Style Argon)")
                st.caption("Somme automatique mois par mois de toutes vos plus-values et moins-values réalisées selon la date de vente.")
            with col_an_sel:
                annee_choisie_v = st.selectbox("Période affichée :", options_filtre_annee, key="sel_annee_cal_ventes")

            mois_noms_12 = [
                (1, "Janvier"), (2, "Février"), (3, "Mars"), (4, "Avril"),
                (5, "Mai"), (6, "Juin"), (7, "Juillet"), (8, "Août"),
                (9, "Septembre"), (10, "Octobre"), (11, "Novembre"), (12, "Décembre"),
            ]
            pv_par_mois_12 = {m_idx: 0.0 for m_idx, _ in mois_noms_12}
            cout_par_mois_12 = {m_idx: 0.0 for m_idx, _ in mois_noms_12}
            encaisse_par_mois_12 = {m_idx: 0.0 for m_idx, _ in mois_noms_12}
            pills_par_mois_12 = {m_idx: [] for m_idx, _ in mois_noms_12}

            for v in historique_v:
                date_s = str(v.get("date", ""))
                if annee_choisie_v == "Toutes les années (Cumul)" or date_s.startswith(str(annee_choisie_v)):
                    try:
                        m_num = int(date_s.split("-")[1])
                    except Exception:
                        m_num = int(v.get("mois_num", 1))
                    pv_v = float(v.get("plus_value_eur", 0.0))
                    mt_v = float(v.get("montant_eur", 0.0))
                    cout_v = float(v.get("cout_initial_eur", mt_v - pv_v))
                    pv_par_mois_12[m_num] += pv_v
                    cout_par_mois_12[m_num] += cout_v
                    encaisse_par_mois_12[m_num] += mt_v
                    pills_par_mois_12[m_num].append((v["action"], v["qte"], pv_v, date_s[8:10] + "/" + date_s[5:7]))

            max_abs_mois = max([abs(val) for val in pv_par_mois_12.values()] + [1.0])
            total_periode_sel = sum(pv_par_mois_12.values())
            nb_mois_verts = sum(1 for m_i in pv_par_mois_12 if pills_par_mois_12[m_i] and pv_par_mois_12[m_i] >= 0)
            nb_mois_rouges = sum(1 for m_i in pv_par_mois_12 if pills_par_mois_12[m_i] and pv_par_mois_12[m_i] < 0)
            meilleur_mois_idx = max(pv_par_mois_12, key=lambda k: pv_par_mois_12[k]) if any(pills_par_mois_12.values()) else None
            txt_meilleur_mois = f"{dict(mois_noms_12)[meilleur_mois_idx]} ({pv_par_mois_12[meilleur_mois_idx]:+,.2f} €)" if (meilleur_mois_idx and pv_par_mois_12[meilleur_mois_idx] != 0) else "N/A"
            c_tot_per = "#2ecc71" if total_periode_sel >= 0 else "#e74c3c"

            html_resume_cal = f"""
            <div class="meteo-bar" style="margin-bottom: 14px;">
                <div class="meteo-item" style="border-left-color:{c_tot_per};">
                    <div>
                        <div style="font-size:0.72em; font-weight:800; opacity:0.75;">📊 BILAN NET ({annee_choisie_v})</div>
                        <div style="font-size:0.98em; font-weight:900; color:{c_tot_per};">{total_periode_sel:+,.2f} € actés</div>
                    </div>
                </div>
                <div class="meteo-item" style="border-left-color:#2ecc71;">
                    <div>
                        <div style="font-size:0.72em; font-weight:800; opacity:0.75;">🟢 MOIS GAGNANTS VS 🔴 PERDANTS</div>
                        <div style="font-size:0.95em; font-weight:800;"><span style="color:#2ecc71;">{nb_mois_verts} mois vert(s)</span> / <span style="color:#e74c3c;">{nb_mois_rouges} mois rouge(s)</span></div>
                    </div>
                </div>
                <div class="meteo-item" style="border-left-color:#f39c12;">
                    <div>
                        <div style="font-size:0.72em; font-weight:800; opacity:0.75;">🏆 MEILLEUR MOIS D'EXTRACTION</div>
                        <div style="font-size:0.95em; font-weight:800;">{txt_meilleur_mois}</div>
                    </div>
                </div>
            </div>
            """
            afficher_html(html_resume_cal)

            libelle_an_court = "" if annee_choisie_v == "Toutes les années (Cumul)" else str(annee_choisie_v)
            html_cal_ventes = "<div class='cal-grid'>"
            for m_idx, m_label in mois_noms_12:
                tot_m = pv_par_mois_12[m_idx]
                cout_m = cout_par_mois_12[m_idx]
                enc_m = encaisse_par_mois_12[m_idx]
                perf_m = (tot_m / cout_m * 100.0) if cout_m > 0 else 0.0
                liste_p = pills_par_mois_12[m_idx]
                pct_barre = min(100.0, max(6.0, (abs(tot_m) / max_abs_mois) * 100.0)) if liste_p else 0.0

                if liste_p:
                    classe_c = "cal-card-active"
                    c_tot = "#2ecc71" if tot_m >= 0 else "#e74c3c"
                    bord_top = f"border-top: 3px solid {c_tot};"
                    badge_m = f"<span class='{'b-green' if tot_m >= 0 else 'b-red'}' style='font-size:0.72em; padding:2px 7px;'>{perf_m:+.1f}%</span>"
                    pills_str = "".join(
                        f"<span class='cal-pill' style='border-left: 3px solid {'#2ecc71' if pv_p >= 0 else '#e74c3c'};'>"
                        f"<b>{act_p}</b> (x{q_p}) : <span style='color:{'#2ecc71' if pv_p >= 0 else '#e74c3c'}; font-weight:800;'>{pv_p:+,.1f} €</span>"
                        f"</span>"
                        for act_p, q_p, pv_p, _ in liste_p
                    )
                    barre_html = f"<div class='score-bg' style='height:5px; margin:6px 0 4px 0;'><div style='width:{pct_barre:.0f}%; background:{c_tot}; height:100%;'></div></div>"
                    sous_info_m = f"<div style='font-size:0.72em; opacity:0.7; display:flex; justify-content:space-between;'><span>{len(liste_p)} vente(s)</span><span>Cash : {enc_m:,.0f} €</span></div>"
                else:
                    classe_c = "cal-card"
                    c_tot = "rgba(128,128,128,0.45)"
                    bord_top = ""
                    badge_m = "<span style='font-size:0.75em; opacity:0.4;'>⚪</span>"
                    pills_str = "<span style='font-size:0.80em; opacity:0.42; font-style:italic;'>Aucune vente ce mois</span>"
                    barre_html = ""
                    sous_info_m = ""

                html_cal_ventes += f"""
                <div class="{classe_c}" style="{bord_top}">
                    <div>
                        <div class="cal-month">
                            <span>{m_idx:02d}. {m_label} {libelle_an_court}</span>
                            {badge_m}
                        </div>
                        <div style="margin-bottom:8px;">{pills_str}</div>
                    </div>
                    <div>
                        {sous_info_m}
                        {barre_html}
                        <div style="text-align:right; border-top:1px dashed rgba(128,128,128,0.2); padding-top:6px; margin-top:4px;">
                            <span style="font-size:0.75em; opacity:0.75; margin-right:4px;">Net mois :</span>
                            <span class="cal-total" style="color:{c_tot};">{tot_m:+,.2f} €</span>
                        </div>
                    </div>
                </div>
                """
            html_cal_ventes += "</div>"
            afficher_html(html_cal_ventes)

            # --- TABLEAU RÉCAPITULATIF MOIS PAR MOIS ---
            st.markdown("#### 📊 Tableau Récapitulatif d'Extraction de Performance Mois par Mois")
            agregation_mois = {}
            for v in historique_v:
                m_key = v.get("mois_annee", str(v.get("date", ""))[:7])
                if m_key not in agregation_mois:
                    agregation_mois[m_key] = {"nb_ventes": 0, "montant_total": 0.0, "cout_total": 0.0, "pv_totale": 0.0}
                pv_val = float(v.get("plus_value_eur", 0.0))
                mt_val = float(v.get("montant_eur", 0.0))
                ct_val = float(v.get("cout_initial_eur", mt_val - pv_val))
                agregation_mois[m_key]["nb_ventes"] += 1
                agregation_mois[m_key]["montant_total"] += mt_val
                agregation_mois[m_key]["cout_total"] += ct_val
                agregation_mois[m_key]["pv_totale"] += pv_val

            html_t_mois = "<table class='r-table'><thead><tr><th style='text-align:left;'>Mois (Année-Mois)</th><th>Opérations</th><th>Capital Initial Vendu (€)</th><th>Cash Net Encaissé (€)</th><th>Plus/Moins-Value Actée (€)</th><th>Performance Extraite (%)</th></tr></thead><tbody>"
            for m_k in sorted(agregation_mois.keys(), reverse=True):
                d_m = agregation_mois[m_k]
                p_m_pct = (d_m["pv_totale"] / d_m["cout_total"] * 100.0) if d_m["cout_total"] > 0 else 0.0
                b_m = "b-green" if d_m["pv_totale"] >= 0 else "b-red"
                c_m_col = "#2ecc71" if d_m["pv_totale"] >= 0 else "#e74c3c"

                html_t_mois += f"""
                <tr>
                    <td class='r-name'>📅 {m_k}</td>
                    <td><b>{d_m['nb_ventes']}</b> vente(s)</td>
                    <td>{d_m['cout_total']:,.2f} €</td>
                    <td><b>{d_m['montant_total']:,.2f} €</b></td>
                    <td><span class='{b_m}'>{d_m['pv_totale']:+,.2f} €</span></td>
                    <td style='color:{c_m_col}; font-weight:800;'>{p_m_pct:+.2f}%</td>
                </tr>
                """
            html_t_mois += "</tbody></table>"
            afficher_html(html_t_mois)

            with st.expander("📋 Historique détaillé de chaque vente & Annulation (Restauration)", expanded=False):
                for idx_h, item_h in enumerate(historique_v):
                    col_h1, col_h2, col_h3 = st.columns([3, 2, 1])
                    with col_h1:
                        badge_esp = "💶 Crédité en Espèces" if item_h.get("credite_especes") else "📤 Hors Espèces"
                        markdown_fr(f"**{item_h['action']}** — **{item_h['qte']} action(s)** vendue(s) à **{item_h['prix_vente']:.2f} {item_h['devise']}** *(PRU : {item_h['pru']:.2f} {item_h['devise']})*")
                        st.caption(nombres_fr(f"Date : {item_h['date']} | Encaissé net : {item_h['montant_eur']:,.2f} € ({badge_esp})"))
                    with col_h2:
                        col_pv_s = "#2ecc71" if item_h["plus_value_eur"] >= 0 else "#e74c3c"
                        markdown_fr(f"Plus/Moins-Value : <span style='color:{col_pv_s}; font-weight:800;'>{item_h['plus_value_eur']:+,.2f} € ({item_h['perf_pct']:+.2f}%)</span>", unsafe_allow_html=True)
                    with col_h3:
                        st.button(
                            "🗑️ Annuler",
                            key=f"suppr_vente_{item_h['id']}_{idx_h}",
                            on_click=annuler_vente_portefeuille,
                            args=(idx_h,),
                            width="stretch",
                        )
                    st.markdown("---")

