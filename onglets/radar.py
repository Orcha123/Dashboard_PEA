"""
Onglet 1 de Boursy : indicateurs du radar, achat du mois selon l'allocation cible, centre d'alertes et résumé
mensuel, tableaux 1 à 4 du radar, solidité des dividendes (étude pré-enregistrée) et bilan des signaux (rejeu
historique et journal en direct).

Toutes les informations venues du reste de l'application sont des paramètres nommés d'afficher() :
leur liste est la liste exacte des dépendances de l'onglet (vérifiée par tests/test_application.py).
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import bisect

import pandas as pd
import streamlit as st

from allocation_dca import lignes_detenues, normaliser_poids, statut_achat
from habillage import afficher_html, markdown_fr, nombres_fr
from moteur_signaux import ALGORITHMES_SIGNAUX, ecart_vs_autres_actions_du_mois, performance_apres
from resume_mensuel import JOURS_AVANT_ACHAT, construire_resume, date_en_toutes_lettres, fiches_valeurs, jour_dca_valide, prochaine_date_dca
from solidite_dividendes import (
    TAUX_MESURES, TAUX_MESURES_1_AN, categorie_projection, evaluer_suivi, evolution_dividende, rendement_median_solides,
    seuils as seuils_solidite,
)


def afficher(
    *,
    ADMIN_EMAIL,
    BUDGET_MENSUEL,
    CLES_TECHNIQUES_PF,
    TAUX_USD_EUR,
    WATCHLIST,
    WATCHLIST_DEFAUT,
    actions_autorisees,
    afficher_verrou_saas,
    alertes_detectees,
    allocation_personnalisee,
    analyse_solidite_dividendes,
    bilan_signaux_symbole,
    budget_courant,
    candidats_tries,
    detail_defaut_dca,
    donnees_t1,
    donnees_t2,
    donnees_t3,
    donnees_t4,
    droites_regression_dict,
    envoyer_apercu_resume_mensuel,
    envoyer_email_alerte,
    est_premium_ou_pro,
    est_pro_max,
    historique_long,
    libelle_allocation_dca,
    lire_signaux_mensuels,
    lire_suivi_solidite,
    mode_gratuit,
    montant_investi_dca,
    montant_tot_div_dca,
    plan_dca,
    prix_temps_reel,
    sauvegarder_dans_cloud,
):
    if mode_gratuit:
        st.warning("🌱 **Forfait Gratuit (0 €)** : 2 valeurs affichées. Passez à **Premium (4,90 €/mois)** ou **Pro (8,90 €/mois)** dans le menu de gauche pour débloquer l'ensemble du catalogue PEA & US !")

    nb_opportunites = sum(1 for d in donnees_t1 if "SIGNAL FORT" in d["Décision"] or "SIGNAL FAVORABLE" in d["Décision"])
    meilleure_opp = candidats_tries[0]["nom"] if candidats_tries else "Aucune"

    html_radar_kpi = f"""
    <div class="argon-grid">
        <div class="argon-card">
            <div class="argon-title">🎯 Signaux Favorables</div>
            <div class="argon-val" style="color: #2ecc71;">{nb_opportunites} / {len(actions_autorisees)}</div>
            <div class="argon-sub">Top Signal : <b>{meilleure_opp}</b></div>
        </div>
        <div class="argon-card">
            <div class="argon-title">💰 Enveloppe DCA Mensuelle</div>
            <div class="argon-val">{BUDGET_MENSUEL:.0f} €</div>
            <div class="argon-sub">Achat du mois : <b>{montant_investi_dca:.2f} €</b> (Reste {budget_courant:.2f} €)</div>
        </div>
        <div class="argon-card">
            <div class="argon-title">🌱 Gain de Rente DCA</div>
            <div class="argon-val" style="color: #3498db;">+{montant_tot_div_dca:.2f} € / an</div>
            <div class="argon-sub">{libelle_allocation_dca}</div>
        </div>
        <div class="argon-card">
            <div class="argon-title">🔔 Alertes Prix Cible / Achat</div>
            <div class="argon-val" style="color: #f39c12;">{len(alertes_detectees)} active(s)</div>
            <div class="argon-sub">Valeurs sous cible ou en signal fort</div>
        </div>
    </div>
    """
    afficher_html(html_radar_kpi)

    col_dca_exp, col_al_exp = st.columns(2)

    with col_dca_exp:
        with st.expander(f"🧭 Achat du mois selon votre allocation cible ({BUDGET_MENSUEL:.0f} €)", expanded=True):
            if allocation_personnalisee:
                st.caption("Allocation cible : la vôtre (modifiable plus bas, dans « Définir mon allocation cible »).")
            else:
                st.caption(f"Allocation par défaut : {detail_defaut_dca}. "
                           "Définissez la vôtre plus bas, dans « Définir mon allocation cible ».")
            lignes_affichees_dca = [l for l in plan_dca["lignes"] if l["poids_cible"] > 0 or l["qte_detenue"] > 0]
            if not lignes_affichees_dca:
                st.info("Ajoutez des valeurs à votre radar ou à votre portefeuille pour calculer l'achat du mois.")
            else:
                html_dca = (
                    "<table class='r-table'><thead><tr><th style='text-align:left;'>Valeur</th><th>Achat proposé</th>"
                    "<th>Poids actuel → après achat</th><th>Radar</th></tr></thead><tbody>"
                )
                for l_dca in sorted(lignes_affichees_dca, key=lambda x: (-x["cout_eur"], x["poids_actuel"] - x["poids_cible"])):
                    statut_dca = statut_achat(l_dca)
                    if statut_dca == "achat":
                        achat_dca_html = (f"<span class='b-green'>{l_dca['qte']} action(s)</span>"
                                          f"<br><span style='font-size:0.82em; opacity:0.8;'>{l_dca['cout_eur']:.2f} €</span>")
                    else:
                        achat_dca_html = {
                            "cours_indisponible": "<span class='b-neutral'>Cours indisponible</span>",
                            "trop_chere": "<span class='b-yellow'>1 action > enveloppe</span>",
                            "hors_cible": "<span class='b-neutral'>Hors cible</span>",
                            "mois_suivants": "<span class='b-blue'>Mois suivants</span>",  # en retard, mais l'enveloppe est épuisée
                            "au_dessus": "<span class='b-neutral'>Au-dessus de sa cible</span>",
                        }.get(statut_dca, "<span class='b-neutral'>À sa cible</span>")
                    decision_dca = str(l_dca["decision"])
                    radar_dca_html = (f"<span style='font-size:0.82em; opacity:0.8;'>{decision_dca.replace('SIGNAL ', '').capitalize() if decision_dca != '—' else '—'}</span>")
                    html_dca += (
                        f"<tr><td class='r-name'><b>{l_dca['nom']}</b></td>"
                        f"<td style='white-space:nowrap;'>{achat_dca_html}</td>"
                        f"<td style='white-space:nowrap;'>{l_dca['poids_actuel']:.1f} % → {l_dca['poids_apres']:.1f} %"
                        f"<br><span style='font-size:0.82em; opacity:0.8;'>cible <b>{l_dca['poids_cible']:.1f} %</b></span></td>"
                        f"<td>{radar_dca_html}</td></tr>"
                    )
                html_dca += "</tbody></table>"
                afficher_html(html_dca)
                resume_dca = f"Investi : {montant_investi_dca:.2f} €, reste {budget_courant:.2f} € gardé pour le mois suivant."
                if plan_dca["ecart_avant"] is not None and plan_dca["ecart_apres"] is not None:
                    resume_dca += (f" Écart à la cible : {plan_dca['ecart_avant']:.1f} % du portefeuille mal réparti avant cet achat, "
                                   f"{plan_dca['ecart_apres']:.1f} % après.")
                trop_cheres_dca = [l["nom"] for l in lignes_affichees_dca if l["trop_chere"]]
                if trop_cheres_dca:
                    resume_dca += (" Une action de " + ", ".join(trop_cheres_dca) + " coûte plus que l'enveloppe du mois : "
                                   "elle pourra être achetée un mois où vous cumulez deux enveloppes.")
                st.caption(nombres_fr(resume_dca))
            st.caption(
                "Calcul arithmétique à partir de vos poids cibles : l'enveloppe va d'abord aux lignes les plus en retard sur "
                "leur cible, en actions entières, sans jamais rien vendre. Le radar n'entre pas dans ce calcul : sur environ "
                "7 ans et 120 actions, ses signaux forts n'ont pas fait mieux, de façon démontrée, que les autres actions du "
                "même mois (voir le bilan des signaux). Ce n'est pas une recommandation d'achat."
            )

    with col_al_exp:
        with st.expander(f"🔔 Centre d'Alertes & Notification Email ({len(alertes_detectees)} signal/signaux)", expanded=True):
            if not est_pro_max:
                afficher_verrou_saas(
                    "Alertes Prix Cibles & Notifications Email",
                    "👑 Offre Pro (8,90 €/mois)",
                    "Recevez directement par email vos alertes dès qu'une action passe sous votre prix cible ou déclenche un signal technique fort, "
                    "et chaque mois, avant votre achat, le résumé de votre DCA."
                )
            elif not alertes_detectees:
                st.info("Aucune valeur n'est actuellement sous son prix cible ou en signal technique fort.")
            else:
                for al in alertes_detectees[:4]:
                    markdown_fr(f"• **{al['Actif']}** à **{al['Prix']}** (Cible : `{al['Cible']}`) — **{al['Motif']}**")
                email_dest = str(st.session_state["user"].email) if st.session_state.get("user") else ADMIN_EMAIL
                if st.button(f"📧 M'envoyer ce rapport d'alertes par email ({email_dest})", width="stretch"):
                    ok_mail, msg_mail = envoyer_email_alerte(email_dest, alertes_detectees)
                    if ok_mail:
                        st.success(msg_mail)
                    else:
                        st.info(msg_mail)

            # --- ALERTES AUTOMATIQUES : envoi chaque soir de bourse par la tâche planifiée (alertes_quotidiennes.py) ---
            if est_pro_max and st.session_state.get("user") is not None and isinstance(st.session_state.get("portefeuille"), dict):
                alertes_auto_actuel = bool(st.session_state["portefeuille"].get("_alertes_auto", False))
                alertes_auto_voulu = st.toggle(
                    "📬 Recevoir automatiquement un e-mail dès qu'une valeur de mon radar passe sous son prix cible",
                    value=alertes_auto_actuel,
                    help="Vérification chaque soir de bourse, même sans ouvrir Boursy. Un seul e-mail par valeur, "
                         "renvoyé au plus une fois par semaine tant qu'elle reste sous son prix cible.",
                )
                if alertes_auto_voulu != alertes_auto_actuel:
                    st.session_state["portefeuille"]["_alertes_auto"] = bool(alertes_auto_voulu)
                    sauvegarder_dans_cloud()

            # --- RÉSUMÉ MENSUEL DU DCA : envoyé avant le jour d'achat par la tâche planifiée (resume_mensuel.py) ---
            if est_pro_max and st.session_state.get("user") is not None and isinstance(st.session_state.get("portefeuille"), dict):
                pf_resume = st.session_state["portefeuille"]
                resume_actuel = bool(pf_resume.get("_resume_mensuel", False))
                resume_voulu = st.toggle(
                    "📅 Recevoir chaque mois, avant mon achat, le résumé de mon DCA par e-mail",
                    value=resume_actuel,
                    help="Achat proposé selon votre allocation cible, valeur du portefeuille, dividendes attendus et valeurs "
                         f"sous leur prix cible. Un e-mail par mois, le soir de bourse qui précède votre jour d'achat "
                         f"(jusqu'à {JOURS_AVANT_ACHAT} jours avant).",
                )
                if resume_voulu != resume_actuel:
                    pf_resume["_resume_mensuel"] = bool(resume_voulu)
                    sauvegarder_dans_cloud()
                if resume_voulu:
                    jour_dca_actuel = jour_dca_valide(pf_resume.get("_jour_dca", 1))
                    jour_dca_voulu = int(st.number_input(
                        "Jour de mon achat DCA, chaque mois (1 à 28)", min_value=1, max_value=28,
                        value=jour_dca_actuel, step=1, key="num_jour_dca",
                    ))
                    if jour_dca_voulu != jour_dca_actuel:
                        pf_resume["_jour_dca"] = jour_dca_voulu
                        sauvegarder_dans_cloud()
                    prochain_achat = prochaine_date_dca(datetime.now().date(), jour_dca_voulu)
                    deja_envoye = str(pf_resume.get("_resume_envoye") or "") == prochain_achat.strftime("%Y-%m")
                    st.caption(
                        f"Prochain achat le {date_en_toutes_lettres(prochain_achat)} : "
                        + ("le résumé de ce mois-ci est déjà parti." if deja_envoye
                           else f"le résumé partira le soir de bourse qui le précède (jusqu'à {JOURS_AVANT_ACHAT} jours avant).")
                    )
                    if st.button("👁️ M'envoyer un aperçu maintenant", width="stretch", key="btn_apercu_resume"):
                        fiches_apercu = fiches_valeurs(st.session_state.get("watchlist", {}))
                        symboles_detenus = sorted({str(fiches_apercu[n].get("symbole", "")).strip()
                                                   for n in lignes_detenues(pf_resume) if n in fiches_apercu})
                        with st.spinner("🛡️ Solidité de votre rente (étude des dividendes)..."):
                            analyse_apercu = analyse_solidite_dividendes(symboles_detenus, calculer=True)
                        def categorie_selon_analyse(symbole):
                            return categorie_projection((analyse_apercu["demandes"].get(symbole) or (None, None))[1])

                        # sans analyse (Yahoo indisponible), l'aperçu part sans la section solidité, comme l'e-mail du soir
                        categorie_apercu = categorie_selon_analyse if analyse_apercu else None
                        rendement_apercu = rendement_median_solides(analyse_apercu["catalogue"].values()) if analyse_apercu else 0.0
                        resume_apercu = construire_resume(
                            pf_resume, st.session_state.get("watchlist", {}), BUDGET_MENSUEL, prix_temps_reel, TAUX_USD_EUR,
                            prochain_achat, fiches_apercu, categorie_de=categorie_apercu, rendement_achats=rendement_apercu,
                        )
                        ok_apercu, msg_apercu = envoyer_apercu_resume_mensuel(str(st.session_state["user"].email), resume_apercu)
                        (st.success if ok_apercu else st.info)(msg_apercu)

    # --- ÉDITION DE L'ALLOCATION CIBLE (enregistrée dans le portefeuille, clé technique « _allocation_cible ») ---
    with st.expander("⚙️ Définir mon allocation cible", expanded=False):
        st.markdown(
            "Indiquez la part que chaque ligne devrait représenter dans votre portefeuille. Le total est ramené à 100 %. "
            "Mettez 0 pour ne plus renforcer une ligne : elle n'est jamais vendue, elle cesse seulement d'être achetée."
        )
        if mode_gratuit:
            st.caption("🌱 Forfait gratuit : l'allocation porte sur les 2 valeurs de votre radar affichées.")
        if not plan_dca["lignes"]:
            st.info("Ajoutez d'abord des valeurs à votre radar ou à votre portefeuille.")
        else:
            base_allocation = st.session_state.get("_base_allocation", "enregistree")
            valeur_lignes_dca = sum(l["valeur_eur"] for l in plan_dca["lignes"])
            if base_allocation == "actuelle" and valeur_lignes_dca > 0:
                poids_depart = {l["nom"]: round(l["poids_actuel"], 1) for l in plan_dca["lignes"]}
            elif base_allocation == "egale":
                poids_depart = {l["nom"]: round(100.0 / len(plan_dca["lignes"]), 1) for l in plan_dca["lignes"]}
            else:  # allocation enregistrée, ou allocation par défaut affichée au-dessus
                poids_depart = {l["nom"]: round(l["poids_cible"], 1) for l in plan_dca["lignes"]}
            df_allocation = pd.DataFrame([
                {"Valeur": l["nom"], "Poids actuel (%)": round(l["poids_actuel"], 1), "Poids cible (%)": poids_depart.get(l["nom"], 0.0)}
                for l in plan_dca["lignes"]
            ])
            df_allocation_saisie = st.data_editor(
                df_allocation, hide_index=True, width="stretch",
                key=f"editeur_allocation_{st.session_state.get('_compteur_allocation', 0)}",
                disabled=["Valeur", "Poids actuel (%)"],
                column_config={
                    "Poids actuel (%)": st.column_config.NumberColumn(format="%.1f"),
                    "Poids cible (%)": st.column_config.NumberColumn(min_value=0.0, max_value=100.0, step=0.5, format="%.1f"),
                },
            )
            total_saisi_allocation = float(pd.to_numeric(df_allocation_saisie["Poids cible (%)"], errors="coerce").fillna(0.0).sum())
            st.caption(nombres_fr(
                f"Total saisi : {total_saisi_allocation:.1f} %"
                + ("." if abs(total_saisi_allocation - 100.0) < 0.05 else " : il sera ramené à 100 % à l'enregistrement.")
            ))
            col_alloc_1, col_alloc_2, col_alloc_3, col_alloc_4 = st.columns(4)
            if col_alloc_1.button("💾 Enregistrer", type="primary", width="stretch", key="btn_enregistrer_allocation"):
                def _poids_saisi(valeur_saisie):
                    try:
                        nombre_saisi = float(valeur_saisie)
                    except (TypeError, ValueError):
                        return 0.0
                    return nombre_saisi if nombre_saisi == nombre_saisi else 0.0  # case vide (NaN) : 0

                poids_normalises = normaliser_poids({
                    str(r["Valeur"]): _poids_saisi(r["Poids cible (%)"]) for r in df_allocation_saisie.to_dict("records")
                })
                if not poids_normalises:
                    st.warning("Indiquez au moins un poids cible supérieur à 0.")
                else:
                    st.session_state["portefeuille"]["_allocation_cible"] = [
                        {"nom": n, "poids": round(p, 2)} for n, p in poids_normalises.items()
                    ]
                    st.session_state["_base_allocation"] = "enregistree"
                    st.session_state["_compteur_allocation"] = st.session_state.get("_compteur_allocation", 0) + 1
                    sauvegarder_dans_cloud()
                    st.rerun()
            if col_alloc_2.button("📊 Partir de mes poids actuels", width="stretch", key="btn_allocation_actuelle",
                                  disabled=valeur_lignes_dca <= 0):
                st.session_state["_base_allocation"] = "actuelle"
                st.session_state["_compteur_allocation"] = st.session_state.get("_compteur_allocation", 0) + 1
                st.rerun()
            if col_alloc_3.button("⚖️ Parts égales", width="stretch", key="btn_allocation_egale"):
                st.session_state["_base_allocation"] = "egale"
                st.session_state["_compteur_allocation"] = st.session_state.get("_compteur_allocation", 0) + 1
                st.rerun()
            if col_alloc_4.button("↺ Supprimer ma cible", width="stretch", key="btn_allocation_supprimer",
                                  disabled=not allocation_personnalisee,
                                  help="Revient à l'allocation par défaut : parts égales."):
                st.session_state["portefeuille"].pop("_allocation_cible", None)
                st.session_state["_base_allocation"] = "enregistree"
                st.session_state["_compteur_allocation"] = st.session_state.get("_compteur_allocation", 0) + 1
                sauvegarder_dans_cloud()
                st.rerun()
            st.caption("Les boutons « Partir de mes poids actuels » et « Parts égales » préremplissent le tableau : "
                       "rien n'est modifié tant que vous n'avez pas cliqué sur « Enregistrer ».")

    # --- TITRE DU TABLEAU 1 PLEINE LARGEUR (GAUCHE) + BOUTON ACTUALISER (DROITE) ---
    col_titre_t1, col_btn_t1 = st.columns([4, 1])
    with col_titre_t1:
        st.markdown(
            "<h3 style='margin: 12px 0 6px 0; padding: 0;'>📊 Tableau 1 : Timing, Momentum & Score Algorithmique (EUR & US)</h3>",
            unsafe_allow_html=True
        )
    with col_btn_t1:
        st.markdown("<div style='margin-top: 8px;'></div>", unsafe_allow_html=True)
        if st.button("🔄 Actualiser les cours", width="stretch", key="btn_actu_radar_t1"):
            st.cache_data.clear()
            if "prix_temps_reel" in st.session_state:
                st.session_state["prix_temps_reel"] = {}
            st.rerun()

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
        dec_html = f"<span class='b-green'>{dec}</span>" if "SIGNAL FORT" in dec else (f"<span class='b-blue'>{dec}</span>" if "SIGNAL FAVORABLE" in dec else (f"<span class='b-red'>{dec}</span>" if "ZONE HAUTE" in dec else f"<span class='b-neutral'>{dec}</span>"))

        rsi_v = d["RSI"]
        rsi_badge = f"<span class='b-green'>{rsi_v}</span>" if rsi_v <= 35 else (f"<span class='b-red'>{rsi_v}</span>" if rsi_v >= 70 else f"<b>{rsi_v}</b>")

        stoch_v = int(d["Stoch"])
        stoch_badge = f"<span class='b-green'>{stoch_v}%</span>" if stoch_v <= 20 else (f"<span class='b-red'>{stoch_v}%</span>" if stoch_v >= 80 else f"{stoch_v}%")

        html_t1 += f"""
        <tr>
            <td class="r-name">{d['Actif']}</td>
            <td><b>{d['Prix']}</b>{f' <span style="opacity:0.7; font-size:0.86em;">({d["PrixEUR"]})</span>' if '$' in d['Prix'] else ''}</td>
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
    st.caption(
        "📏 Ce que valent ces signaux : sur environ 7 ans et 120 actions du catalogue, les actions en signal fort n'ont "
        "pas fait mieux, de façon démontrée, que les autres actions du même mois (voir « Bilan des signaux » plus bas). "
        "Le score décrit une situation (baisse récente, survente, dividende solide) : ce n'est pas une prévision."
    )

    tab_val, tab_tech, tab_div = st.tabs([
        "📐 Tableau 2 : Analyse Value & Canal 3 Ans",
        "🎯 Tableau 3 : Indicateurs Techniques Avancés (Bollinger, Stoch, ATR)",
        "🛡️ Tableau 4 : Sûreté & Croissance des Dividendes",
    ])

    with tab_val:
        if mode_gratuit:
            afficher_verrou_saas(
                "Tableau 2 : Analyse Value & Canal de Régression Linéaire sur 3 Ans",
                "⚡ Offre Premium (4,90 €/mois) ou 👑 Pro (8,90 €/mois)",
                "Repérez instantanément les actions historiquement décotées par rapport à leur tendance centrale à 3 ans."
            )
        else:
            st.caption("📉 **Classement Value automatique :** Trié de la **plus forte décote** (en haut) jusqu'aux valeurs **les plus chères** (en bas).")
            donnees_t2_triees = sorted(donnees_t2, key=lambda x: (x["OrdreStatut"], x["EcartNum"]))
            html_t2 = "<table class='r-table'><thead><tr><th style='width:65px;'>Rang</th><th style='text-align: left;'>Actif</th><th>Cours Actuel</th><th>Tendance Linéaire 3A</th><th>Écart à la Tendance</th><th>Diagnostic Value</th></tr></thead><tbody>"
            for rang_idx, d in enumerate(donnees_t2_triees, start=1):
                st_val = d["Statut Value"]
                b_val = "b-green" if "DÉCOTE" in st_val else ("b-yellow" if "SOUS-ÉVALUÉE" in st_val else "b-neutral")
                c_ecart = "#2ecc71" if d["EcartNum"] <= -10 else ("#f39c12" if d["EcartNum"] < 0 else "#e74c3c")
                badge_rang = f"<span class='b-green'>#{rang_idx}</span>" if d["OrdreStatut"] == 0 else (f"<span class='b-yellow'>#{rang_idx}</span>" if d["OrdreStatut"] == 1 else f"<span class='b-neutral'>#{rang_idx}</span>")
                html_t2 += f"<tr><td>{badge_rang}</td><td class='r-name'>{d['Actif']}</td><td><b>{d['Prix']}</b></td><td>{d['Tendance 3A']}</td><td style='color:{c_ecart}; font-weight:800;'>{d['Écart %']}</td><td><span class='{b_val}'>{st_val}</span></td></tr>"
            html_t2 += "</tbody></table>"
            afficher_html(html_t2)

            if droites_regression_dict:
                st.markdown("#### 📈 Visualisation du Canal de Régression Linéaire sur 3 Ans")
                noms_tries_value = [d["NomBrut"] for d in donnees_t2_triees if d["NomBrut"] in droites_regression_dict]
                act_choisie_graph = st.selectbox("Choisir une action à inspecter graphiquement (classées par décote) :", noms_tries_value)
                closes_g, reg_g, std_g, sym_g = droites_regression_dict[act_choisie_graph]
                df_graph = pd.DataFrame({
                    "Cours Clôture": closes_g,
                    "Tendance Centrale 3A": reg_g,
                    "Borne Haute (+2σ)": [r + 2 * std_g for r in reg_g],
                    "Borne Basse d'Achat (-2σ)": [r - 2 * std_g for r in reg_g],
                })
                st.line_chart(df_graph)

    with tab_tech:
        if mode_gratuit:
            afficher_verrou_saas(
                "Tableau 3 : Indicateurs Techniques Avancés (Supports 30J, Bollinger, Stochastique & ATR)",
                "⚡ Offre Premium (4,90 €/mois) ou 👑 Pro (8,90 €/mois)",
                "Situez chaque action dans ses fourchettes récentes : canal de 30 jours, bandes de Bollinger, stochastique et volatilité."
            )
        else:
            html_guide_tech = """
            <div class="argon-grid" style="margin-bottom: 14px;">
                <div class="argon-card" style="text-align:left; padding:12px 15px;">
                    <div class="argon-title" style="color:#2ecc71;">📏 1. Canal 30 Jours (Support / Résistance)</div>
                    <div style="font-size:0.82em; opacity:0.9; line-height:1.45;">Le <b>support</b> est le plus bas des 30 derniers jours, la <b>résistance</b> le plus haut. La jauge situe le cours entre les deux : <b>0 %</b> au plus bas, <b>100 %</b> au plus haut.</div>
                </div>
                <div class="argon-card" style="text-align:left; padding:12px 15px;">
                    <div class="argon-title" style="color:#3498db;">🌊 2. Bandes de Bollinger (20 Jours)</div>
                    <div style="font-size:0.82em; opacity:0.9; line-height:1.45;">Moyenne des 20 derniers jours, plus ou moins deux écarts-types. Un cours près de la <b>bande basse</b> est bas par rapport à ses dernières semaines : cela ne dit pas qu'il va remonter.</div>
                </div>
                <div class="argon-card" style="text-align:left; padding:12px 15px;">
                    <div class="argon-title" style="color:#f39c12;">⚡ 3. Oscillateur Stochastique (14J)</div>
                    <div style="font-size:0.82em; opacity:0.9; line-height:1.45;">Situe la clôture dans la fourchette des 14 derniers jours. <b>&lt; 20 %</b> : près du bas (« survente »). <b>&gt; 80 %</b> : près du haut (« surachat »). Ni l'un ni l'autre n'annonce la suite.</div>
                </div>
                <div class="argon-card" style="text-align:left; padding:12px 15px;">
                    <div class="argon-title" style="color:#9b59b6;">⚡ 4. ATR (Volatilité)</div>
                    <div style="font-size:0.82em; opacity:0.9; line-height:1.45;">L'<b>ATR</b> mesure l'amplitude moyenne d'une journée, en % du cours : plus il est élevé, plus le titre bouge d'un jour à l'autre.</div>
                </div>
            </div>
            """
            afficher_html(html_guide_tech)
            st.caption(
                "📍 **Classement par position :** des cours **les plus bas dans leurs fourchettes récentes (#1 en haut)** "
                "aux **plus hauts (en bas)**. Ces indicateurs décrivent où en est le cours par rapport à ses dernières "
                "semaines ; ils ne prévoient pas la suite. Le score du radar, qui utilise notamment la survente du "
                "stochastique, n'a pas fait mieux, de façon démontrée, que les autres actions du même mois (sur environ "
                "7 ans et 120 actions, voir « Bilan des signaux »)."
            )

            donnees_t4_enrichies = []
            for d in donnees_t4:
                try:
                    parts_prix = d["Prix"].split()
                    prix_f = float(parts_prix[0])
                    sym_dev = parts_prix[1] if len(parts_prix) > 1 else "€"
                    sup_f = float(d["Support 30J"].split()[0])
                    res_f = float(d["Résistance 30J"].split()[0])
                except Exception:
                    prix_f, sym_dev, sup_f, res_f = 50.0, "€", 45.0, 55.0

                try:
                    bloc_b = d["Bollinger (20J)"].split("]")[0].replace("[", "")
                    b_inf_s, b_sup_s = bloc_b.split(" - ")
                    borne_inf_f, borne_sup_f = float(b_inf_s), float(b_sup_s)
                except Exception:
                    borne_inf_f, borne_sup_f = sup_f, res_f

                try:
                    stoch_f = float(d["Stochastique"].split("%")[0])
                except Exception:
                    stoch_f = 50.0

                try:
                    atr_f = float(d["Volatilité ATR"].split("%")[0])
                except Exception:
                    atr_f = 1.5

                amp_30j = max(0.01, res_f - sup_f)
                pos_canal_pct = max(0.0, min(100.0, ((prix_f - sup_f) / amp_30j) * 100.0))

                amp_boll = max(0.01, borne_sup_f - borne_inf_f)
                pos_boll_pct = max(0.0, min(100.0, ((prix_f - borne_inf_f) / amp_boll) * 100.0))

                ecart_haut_pct = ((res_f - prix_f) / prix_f * 100.0) if prix_f > 0 else 0.0

                # 100 : cours au plus bas de ses fourchettes récentes ; 0 : au plus haut (description, pas une prévision)
                score_position = int(round(100.0 - (0.40 * pos_canal_pct + 0.35 * stoch_f + 0.25 * pos_boll_pct)))
                score_position = max(5, min(98, score_position))

                if pos_boll_pct <= 22:
                    diag_boll = f"<span class='b-blue'>🔵 Bande basse ({borne_inf_f:.1f} {sym_dev})</span><br><span style='font-size:0.78em; opacity:0.8;'>Cours près de la bande basse</span>"
                elif pos_boll_pct >= 82:
                    diag_boll = f"<span class='b-yellow'>🟡 Bande haute ({borne_sup_f:.1f} {sym_dev})</span><br><span style='font-size:0.78em; opacity:0.8;'>Cours près de la bande haute</span>"
                else:
                    diag_boll = f"<span class='b-neutral'>⚪ Entre les bandes [{borne_inf_f:.1f} - {borne_sup_f:.1f}]</span><br><span style='font-size:0.78em; opacity:0.8;'>Position : {pos_boll_pct:.0f} % de l'écart entre les bandes</span>"

                if stoch_f <= 20:
                    diag_stoch = f"<span class='b-blue'>🔵 {stoch_f:.0f}% (Survente)</span><br><span style='font-size:0.78em; opacity:0.8;'>Près du bas des 14 derniers jours</span>"
                elif stoch_f <= 38:
                    diag_stoch = f"<span class='b-neutral'>⚪ {stoch_f:.0f}% (Zone basse)</span><br><span style='font-size:0.78em; opacity:0.8;'>Bas de la fourchette des 14 jours</span>"
                elif stoch_f >= 80:
                    diag_stoch = f"<span class='b-yellow'>🟡 {stoch_f:.0f}% (Surachat)</span><br><span style='font-size:0.78em; opacity:0.8;'>Près du haut des 14 derniers jours</span>"
                else:
                    diag_stoch = f"<span class='b-neutral'>⚪ {stoch_f:.0f}% (Neutre)</span><br><span style='font-size:0.78em; opacity:0.8;'>Milieu de la fourchette des 14 jours</span>"

                if atr_f < 1.3:
                    profil_atr = "🛡️ Calme"
                elif atr_f <= 2.2:
                    profil_atr = "⚖️ Modérée"
                else:
                    profil_atr = "⚡ Nerveuse"

                if score_position >= 68:
                    ordre_statut = 0
                    action_tech = "<span class='b-blue'>🔵 COURS BAS DANS SES FOURCHETTES</span><br><span style='font-size:0.80em;'>Près des plus bas des dernières semaines</span>"
                elif score_position >= 50:
                    ordre_statut = 1
                    action_tech = "<span class='b-neutral'>⚪ PLUTÔT BAS</span><br><span style='font-size:0.80em;'>Sous le milieu de ses fourchettes récentes</span>"
                elif score_position >= 33:
                    ordre_statut = 2
                    action_tech = "<span class='b-neutral'>⚪ MILIEU DES FOURCHETTES</span><br><span style='font-size:0.80em;'>Ni près des plus bas, ni près des plus hauts</span>"
                else:
                    ordre_statut = 3
                    action_tech = "<span class='b-yellow'>🟡 COURS HAUT DANS SES FOURCHETTES</span><br><span style='font-size:0.80em;'>Près des plus hauts des dernières semaines</span>"

                donnees_t4_enrichies.append({
                    "Actif": d["Actif"],
                    "Prix": d["Prix"],
                    "Support": d["Support 30J"],
                    "Resistance": d["Résistance 30J"],
                    "PosCanal": pos_canal_pct,
                    "EcartHautPct": ecart_haut_pct,
                    "DiagBoll": diag_boll,
                    "DiagStoch": diag_stoch,
                    "ATR": f"{atr_f:.2f}% / j ({profil_atr})",
                    "ScorePosition": score_position,
                    "OrdreStatut": ordre_statut,
                    "ActionTech": action_tech,
                })

            donnees_t4_enrichies.sort(key=lambda x: (x["OrdreStatut"], -x["ScorePosition"]))

            html_t4 = """
            <table class='r-table'>
            <thead>
                <tr>
                    <th style='width:46px;'>Rang</th>
                    <th style='text-align: left;'>Actif</th>
                    <th style='width:180px;'>Position dans le Canal 30J<br><span style='font-size:0.82em; opacity:0.75;'>(Support ➔ Cours ➔ Résistance)</span></th>
                    <th>Écart au plus haut 30J</th>
                    <th>Diagnostic Bollinger (20J)</th>
                    <th>Momentum Stochastique</th>
                    <th>Volatilité (ATR)</th>
                    <th style='width:105px;'>Score de position<br><span style='font-size:0.82em; opacity:0.75;'>(100 = au plus bas)</span></th>
                    <th>Lecture (descriptive, pas une prévision)</th>
                </tr>
            </thead>
            <tbody>
            """
            for idx_r, item_t in enumerate(donnees_t4_enrichies, start=1):
                pos_c = item_t["PosCanal"]
                sc_t = item_t["ScorePosition"]

                html_t4 += f"""
                <tr>
                    <td><span class='b-neutral'>#{idx_r}</span></td>
                    <td class='r-name'>{item_t['Actif']}<br><span style='font-size:0.84em; opacity:0.8;'>Cours : <b>{item_t['Prix']}</b></span></td>
                    <td>
                        <div style='display:flex; justify-content:space-between; font-size:0.78em; font-weight:700;'>
                            <span>Sup: {item_t['Support']}</span>
                            <span>{pos_c:.0f}%</span>
                            <span>Rés: {item_t['Resistance']}</span>
                        </div>
                        <div class='score-bg'><div style='width:{max(4, min(100, pos_c))}%; background:#3498db; height:100%;'></div></div>
                    </td>
                    <td style='font-weight:800;'>+{item_t['EcartHautPct']:.1f}%<br><span style='font-size:0.76em; opacity:0.75; font-weight:600;'>jusqu'au plus haut 30J</span></td>
                    <td>{item_t['DiagBoll']}</td>
                    <td>{item_t['DiagStoch']}</td>
                    <td><span class='b-purple'>{item_t['ATR']}</span></td>
                    <td>
                        <div style='font-weight:800; font-size:0.9em;'>{sc_t} / 100</div>
                        <div class='score-bg'><div style='width:{sc_t}%; background:#3498db; height:100%;'></div></div>
                    </td>
                    <td>{item_t['ActionTech']}</td>
                </tr>
                """
            html_t4 += "</tbody></table>"
            afficher_html(html_t4)

    with tab_div:
        if mode_gratuit:
            afficher_verrou_saas(
                "Tableau 4 : Sûreté des Dividendes, Payout Ratio & Détecteur de Yield Trap",
                "⚡ Offre Premium (4,90 €/mois) ou 👑 Pro (8,90 €/mois)",
                "Vérifiez la solidité du Payout Ratio, la croissance sur 5 ans et les pièges à rendement sur l'ensemble du catalogue."
            )
        else:
            taux_eleve, taux_autres = (f"{x * 100:.0f} %" for x in TAUX_MESURES["rendement_eleve"])
            html_guide_div = f"""
            <div class="argon-grid" style="margin-bottom: 14px;">
                <div class="argon-card" style="text-align:left; padding:12px 15px;">
                    <div class="argon-title" style="color:#2ecc71;">💰 1. Rendement & Gain pour 1 000 €</div>
                    <div style="font-size:0.82em; opacity:0.9; line-height:1.45;">Revenu annuel pour <b>1 000 € investis</b> au cours actuel. Un rendement très élevé est un <b>signal d'alerte</b> : dans l'étude de Boursy, {taux_eleve} des 20 % de rendements les plus élevés ont baissé leur dividende dans les 3 ans, contre {taux_autres} des autres.</div>
                </div>
                <div class="argon-card" style="text-align:left; padding:12px 15px;">
                    <div class="argon-title" style="color:#3498db;">🧮 2. Payout Ratio (Part des bénéfices versée)</div>
                    <div style="font-size:0.82em; opacity:0.9; line-height:1.45;"><b>&le; 55 %</b> : marge confortable (l'entreprise garde des bénéfices pour investir). <b>&gt; 75 %</b> : dividende sous tension. Repère usuel des analystes, non testé par l'étude de Boursy.</div>
                </div>
                <div class="argon-card" style="text-align:left; padding:12px 15px;">
                    <div class="argon-title" style="color:#f39c12;">📈 3. Croissance passée (5 ans) & YoC</div>
                    <div style="font-size:0.82em; opacity:0.9; line-height:1.45;">Hausse annuelle moyenne du dividende sur 5 ans. Le <b>YoC 5 ans</b> montre ce que deviendrait le rendement sur le prix d'aujourd'hui <b>si cette hausse continuait</b> : une hypothèse, pas une prévision. Dans l'étude, la croissance passée seule n'a pas rendu le dividende plus fiable.</div>
                </div>
                <div class="argon-card" style="text-align:left; padding:12px 15px;">
                    <div class="argon-title" style="color:#9b59b6;">🏆 4. Score Rente (/100) & Profil</div>
                    <div style="font-size:0.82em; opacity:0.9; line-height:1.45;">Combine <b>payout (40 %)</b>, <b>rendement (35 %)</b> et <b>croissance passée (25 %)</b>. Indicateur descriptif : au-delà du seuil des 20 % de rendements les plus élevés, le rendement n'ajoute plus de points et la ligne passe en bas du tableau, signalée ⚠️.</div>
                </div>
            </div>
            """
            afficher_html(html_guide_div)

            # Seuil des 20 % de rendements les plus élevés : celui de l'étude (catalogue au 31/12) si l'analyse de
            # solidité du jour existe, sinon le même classement appliqué aux rendements actuels de ce tableau.
            def _pourcentage(texte, defaut):
                try:
                    return float(str(texte).replace("+", "").replace("%", "").replace("/an", "").strip())
                except Exception:
                    return defaut

            def _symbole_et_etf(actif):
                info_a = WATCHLIST.get(actif.rsplit(" (", 1)[0], WATCHLIST_DEFAUT.get(actif.rsplit(" (", 1)[0], {}))
                return str(info_a.get("symbole", "")).strip(), "ETF" in str(info_a.get("secteur", ""))

            analyse_div = analyse_solidite_dividendes([])  # sans calcul : seulement si l'analyse du jour existe
            seuil_eleve_pct, source_seuil, verdicts_div = None, "", {}
            if analyse_div:
                verdicts_div = {sym: statut_s for sym, (_valeurs, statut_s) in analyse_div["catalogue"].items()}
                if analyse_div["seuils"].get("H"):
                    seuil_eleve_pct = analyse_div["seuils"]["H"] * 100.0
                    source_seuil = f"seuil de l'étude : {seuil_eleve_pct:.2f} % au 31/12/{analyse_div['annee']}".replace(".", ",")
            if seuil_eleve_pct is None:
                rendements_actions = {
                    d["Actif"]: {"retenue": True, "H": _pourcentage(d["Rendement"], 0.0)}
                    for d in donnees_t3 if not _symbole_et_etf(d["Actif"])[1]
                }
                seuil_tableau = seuils_solidite(rendements_actions).get("H")
                if seuil_tableau is not None:
                    seuil_eleve_pct = seuil_tableau
                    source_seuil = f"{seuil_eleve_pct:.2f} % et plus, estimé sur ce tableau".replace(".", ",")
            st.caption(
                "🏆 **Classement par profil de rente :** trié par profil, puis par score (#1 en haut). "
                + (f"Les rendements parmi les 20 % les plus élevés ({source_seuil}) sont signalés ⚠️ et placés en bas. "
                   if seuil_eleve_pct is not None else "")
                + "Pour la fiabilité du dividende, la mesure démontrée par l'étude est la **solidité** "
                + ("(verdict rappelé dans la dernière colonne)." if analyse_div
                   else "(lancez l'analyse « 🛡️ Solidité des dividendes » plus bas pour voir le verdict de chaque action ici).")
            )

            donnees_t3_enrichies = []
            for d in donnees_t3:
                nom_pur = d["Actif"].rsplit(" (", 1)[0]
                info_w = WATCHLIST.get(nom_pur, WATCHLIST_DEFAUT.get(nom_pur, {}))
                mois_v = info_w.get("mois_div", ["Mai"])
                if len(mois_v) == 12:
                    freq_str = "📅 Mensuel (12x/an)"
                elif len(mois_v) == 4:
                    freq_str = f"📅 Trimestriel ({', '.join(mois_v)})"
                elif len(mois_v) > 1:
                    freq_str = f"📅 {len(mois_v)}x/an ({', '.join(mois_v)})"
                else:
                    freq_str = f"📅 Annuel ({mois_v[0] if mois_v else 'Mai'})"

                rend_pct = _pourcentage(d["Rendement"], 3.0)
                payout_pct = _pourcentage(d["Payout"], 55.0)
                croiss_pct = _pourcentage(d["Croissance 5a"], 5.0)
                symbole_d, est_etf_d = _symbole_et_etf(d["Actif"])
                rendement_tres_eleve = not est_etf_d and seuil_eleve_pct is not None and rend_pct >= seuil_eleve_pct

                rente_1000 = rend_pct * 10.0
                taux_c_borne = max(0.0, min(20.0, croiss_pct))
                yoc_5a = rend_pct * ((1.0 + taux_c_borne / 100.0) ** 5)

                if payout_pct <= 50:
                    pts_payout = 40.0
                elif payout_pct <= 60:
                    pts_payout = 35.0
                elif payout_pct <= 72:
                    pts_payout = 27.0
                elif payout_pct <= 85:
                    pts_payout = 18.0
                else:
                    pts_payout = 8.0

                # au-delà du seuil des rendements les plus élevés, plus aucun point : c'est un signal d'alerte (étude)
                rend_note = min(rend_pct, seuil_eleve_pct) if seuil_eleve_pct is not None and not est_etf_d else rend_pct
                pts_rend = min(35.0, max(5.0, rend_note * 5.2))
                pts_croiss = min(25.0, max(3.0, taux_c_borne * 2.5))
                score_rente = int(round(min(99.0, max(15.0, pts_payout + pts_rend + pts_croiss))))

                if payout_pct <= 55:
                    c_pay = "#2ecc71"
                    diag_payout = f"<span style='color:#2ecc71; font-weight:800;'>Marge confortable ({payout_pct:.0f}%)</span><br><span style='font-size:0.76em; opacity:0.8;'>{100 - payout_pct:.0f}% des bénéfices conservés</span>"
                elif payout_pct <= 72:
                    c_pay = "#3498db"
                    diag_payout = f"<span style='color:#3498db; font-weight:800;'>Bien couvert ({payout_pct:.0f}%)</span><br><span style='font-size:0.76em; opacity:0.8;'>Distribution couverte par les bénéfices</span>"
                else:
                    c_pay = "#f39c12" if payout_pct <= 85 else "#e74c3c"
                    diag_payout = f"<span style='color:{c_pay}; font-weight:800;'>🟡 Élevé ({payout_pct:.0f}%)</span><br><span style='font-size:0.76em; opacity:0.8;'>Marge de manœuvre réduite</span>"

                if croiss_pct >= 8.0:
                    diag_croiss = f"<span class='b-green'>🚀 +{croiss_pct:.1f}% / an</span><br><span style='font-size:0.76em; opacity:0.8;'>Forte hausse passée</span>"
                elif croiss_pct >= 4.5:
                    diag_croiss = f"<span class='b-blue'>📈 +{croiss_pct:.1f}% / an</span><br><span style='font-size:0.76em; opacity:0.8;'>Hausse passée &gt; inflation</span>"
                else:
                    diag_croiss = f"<span class='b-neutral'>🐢 +{croiss_pct:.1f}% / an</span><br><span style='font-size:0.76em; opacity:0.8;'>Hausse passée modérée</span>"

                if rendement_tres_eleve:
                    ordre_div = 4
                    decision_div = f"<span class='b-yellow'>⚠️ RENDEMENT TRÈS ÉLEVÉ</span><br><span style='font-size:0.80em;'>Parmi les 20 % les plus élevés : {taux_eleve} ont baissé leur dividende en 3 ans dans l'étude</span>"
                elif score_rente >= 76 and payout_pct <= 65:
                    ordre_div = 0
                    decision_div = "<span class='b-green'>👑 PROFIL COMPLET</span><br><span style='font-size:0.80em;'>Rendement, payout couvert et hausse passée réunis</span>"
                elif rend_pct >= 5.0 and payout_pct <= 75:
                    ordre_div = 1
                    decision_div = "<span class='b-blue'>💵 BON RENDEMENT</span><br><span style='font-size:0.80em;'>Payout maîtrisé</span>"
                elif croiss_pct >= 7.5 and payout_pct <= 60:
                    ordre_div = 2
                    decision_div = "<span class='b-purple'>🚀 CROISSANCE DU DIVIDENDE</span><br><span style='font-size:0.80em;'>Hausse rapide du coupon sur 5 ans</span>"
                else:
                    ordre_div = 3
                    decision_div = "<span class='b-neutral'>⚖️ PROFIL MODÉRÉ</span><br><span style='font-size:0.80em;'>Critères partiellement réunis</span>"
                verdict_div = verdicts_div.get(symbole_d)
                if verdict_div and not verdict_div["libelle"].startswith("—"):
                    decision_div += f"<br><span style='font-size:0.76em; opacity:0.85;'>Étude : {verdict_div['libelle']}</span>"

                donnees_t3_enrichies.append({
                    "Actif": d["Actif"],
                    "FreqStr": freq_str,
                    "DivAct": d["Div/Act"],
                    "RendPct": rend_pct,
                    "Rente1000": rente_1000,
                    "YoC5A": yoc_5a,
                    "PayoutPct": payout_pct,
                    "CouleurPay": c_pay,
                    "DiagPayout": diag_payout,
                    "DiagCroiss": diag_croiss,
                    "ScoreRente": score_rente,
                    "OrdreDiv": ordre_div,
                    "DecisionDiv": decision_div,
                })

            donnees_t3_enrichies.sort(key=lambda x: (x["OrdreDiv"], -x["ScoreRente"]))

            html_t3 = """
            <table class='r-table'>
            <thead>
                <tr>
                    <th style='width:55px;'>Rang</th>
                    <th style='text-align: left;'>Actif & Calendrier</th>
                    <th>Dividende / Action<br><span style='font-size:0.82em; opacity:0.75;'>(& Gain pour 1 000 €)</span></th>
                    <th>Rendement Actuel<br><span style='font-size:0.82em; opacity:0.75;'>(➔ YoC 5A si la hausse passée continuait)</span></th>
                    <th style='width:210px;'>Jauge Payout Ratio<br><span style='font-size:0.82em; opacity:0.75;'>(Part des bénéfices versée)</span></th>
                    <th>Dynamique 5 Ans</th>
                    <th style='width:125px;'>Score Rente</th>
                    <th>Profil de Rente</th>
                </tr>
            </thead>
            <tbody>
            """
            for idx_d, item_d in enumerate(donnees_t3_enrichies, start=1):
                sc_r = item_d["ScoreRente"]
                c_sc_r = "#2ecc71" if sc_r >= 75 else ("#3498db" if sc_r >= 60 else "#f39c12")
                b_rang_d = {0: "b-green", 1: "b-blue", 2: "b-purple", 4: "b-yellow"}.get(item_d["OrdreDiv"], "b-neutral")
                pay_w = max(5.0, min(100.0, item_d["PayoutPct"]))

                html_t3 += f"""
                <tr>
                    <td><span class='{b_rang_d}'>#{idx_d}</span></td>
                    <td class='r-name'>{item_d['Actif']}<br><span style='font-size:0.78em; opacity:0.75; font-weight:600;'>{item_d['FreqStr']}</span></td>
                    <td><b>{item_d['DivAct']}</b><br><span style='font-size:0.80em; color:#2ecc71; font-weight:700;'>+{item_d['Rente1000']:.1f} €/an pour 1 000 €</span></td>
                    <td>
                        <span style='color:#2ecc71; font-weight:900; font-size:1.05em;'>{item_d['RendPct']:.2f}%</span><br>
                        <span style='font-size:0.78em; opacity:0.85;'>➔ YoC 5A (hypothèse) : <b>{item_d['YoC5A']:.2f}%</b></span>
                    </td>
                    <td>
                        {item_d['DiagPayout']}
                        <div class='score-bg'><div style='width:{pay_w}%; background:{item_d['CouleurPay']}; height:100%;'></div></div>
                    </td>
                    <td>{item_d['DiagCroiss']}</td>
                    <td>
                        <div style='font-weight:800; font-size:0.9em;'>{sc_r} / 100</div>
                        <div class='score-bg'><div style='width:{sc_r}%; background:{c_sc_r}; height:100%;'></div></div>
                    </td>
                    <td>{item_d['DecisionDiv']}</td>
                </tr>
                """
            html_t3 += "</tbody></table>"
            afficher_html(html_t3)

            # --- DÉTECTEUR DE YIELD TRAP (PIÈGES À RENDEMENT) & BONUS NOMINATIF +10% ---
            valeurs_nominatif_eligibles = {"Air Liquide", "L'Oréal", "Engie", "Seb", "Crédit Agricole"}
            alertes_yield_trap = []
            pistes_nominatif = []
            map_t2_trap = {d["Actif"]: d for d in donnees_t2}

            for item_d in donnees_t3_enrichies:
                nom_pur_d = item_d["Actif"].rsplit(" (", 1)[0]
                ecart_3a_d = float(map_t2_trap.get(item_d["Actif"], {}).get("EcartNum", 0.0))
                rend_d = item_d["RendPct"]
                pay_d = item_d["PayoutPct"]

                if rend_d >= 7.8 and (pay_d >= 75.0 or ecart_3a_d <= -12.0):
                    motif_trap = f"Rendement élevé ({rend_d:.2f}%) avec Payout tendu ({pay_d:.0f}%)" if pay_d >= 75.0 else f"Rendement facial ({rend_d:.2f}%) gonflé par une chute du cours ({ecart_3a_d:+.1f}% vs 3A)"
                    alertes_yield_trap.append(f"<li><b>{item_d['Actif']}</b> : {motif_trap} — <i>dans l'étude, {taux_eleve} des rendements les plus élevés ont baissé leur dividende dans les 3 ans.</i></li>")

                if nom_pur_d in valeurs_nominatif_eligibles:
                    rend_boost = rend_d * 1.10
                    pistes_nominatif.append(
                        f"<span class='cal-pill' style='border:1px solid rgba(46,204,113,0.4);'>"
                        f"🏅 <b>{nom_pur_d}</b> : {rend_d:.2f}% ➔ <b style='color:#2ecc71;'>{rend_boost:.2f}%</b> au Nominatif (+10%)"
                        f"</span>"
                    )

            html_trap = (
                "<ul style='margin:6px 0 0 18px; padding:0; font-size:0.84em; line-height:1.5;'>" + "".join(alertes_yield_trap) + "</ul>"
                if alertes_yield_trap
                else "<div style='font-size:0.84em; color:#2ecc71; font-weight:700; margin-top:4px;'>✅ Aucun rendement extrême (7,8 % ou plus) avec payout tendu ou chute du cours dans votre sélection. Les rendements parmi les 20 % les plus élevés restent signalés ⚠️ dans le tableau.</div>"
            )
            html_nom_pills = "".join(pistes_nominatif) if pistes_nominatif else "<span style='font-size:0.84em; opacity:0.7;'>Aucune valeur éligible au bonus +10% dans le radar.</span>"

            html_radar_pro = f"""
            <div class="argon-grid" style="margin-top: 10px;">
                <div class="argon-card" style="text-align:left; border-left: 4px solid {'#e74c3c' if alertes_yield_trap else '#2ecc71'};">
                    <div class="argon-title" style="color:{'#e74c3c' if alertes_yield_trap else '#2ecc71'};">🚨 Détecteur Algorithmique de "Yield Trap" (Piège à Rendement)</div>
                    {html_trap}
                </div>
                <div class="argon-card" style="text-align:left; border-left: 4px solid #f39c12;">
                    <div class="argon-title" style="color:#f39c12;">🏅 Valeurs du Radar Éligibles à la Prime de Fidélité (+10% Dividende au Nominatif Administré)</div>
                    <div style="margin-top:6px;">{html_nom_pills}</div>
                </div>
            </div>
            """
            afficher_html(html_radar_pro)

    # ==========================================================================
    # SOLIDITÉ DES DIVIDENDES (ÉTUDE PRÉ-ENREGISTRÉE)
    # ==========================================================================
    with st.expander("🛡️ Solidité des dividendes : les rentes qui tiennent dans la durée", expanded=False):
        if not est_premium_ou_pro:
            afficher_verrou_saas(
                "Solidité des dividendes et alertes de rendement",
                "⚡ Offre Premium (4,90 €/mois) ou 👑 Pro (8,90 €/mois)",
                "Repérez les dividendes les plus fiables pour une rente, et ceux dont le rendement élevé annonce souvent une baisse.",
            )
        else:
            def part_sol(x):
                return f"{x * 100:.0f} %"

            solide_groupe, solide_autres = (part_sol(x) for x in TAUX_MESURES["solide"])
            eleve_groupe, eleve_autres = (part_sol(x) for x in TAUX_MESURES["rendement_eleve"])
            st.caption(
                "Issu de l'étude de Boursy sur l'historique des dividendes du catalogue, avec un protocole écrit avant les "
                f"calculs. Sur la période de test (2015-2022, 2020 compris), {solide_groupe} des dividendes « solides » ont "
                f"baissé au moins une fois dans les 3 ans, contre {solide_autres} des autres ; parmi les 20 % de rendements "
                f"les plus élevés, {eleve_groupe} ont baissé, contre {eleve_autres}. Le rendement total des actions "
                "solides n'a pas été meilleur de façon démontrée : c'est la rente qui est plus sûre, pas la performance."
            )
            symboles_radar_sol = {
                nom_s: info_s["symbole"].strip() for nom_s, info_s in st.session_state["watchlist"].items()
                if nom_s in actions_autorisees and isinstance(info_s, dict) and info_s.get("symbole")
                and "ETF" not in str(info_s.get("secteur", ""))
            }
            liste_symboles_sol = sorted(set(symboles_radar_sol.values()))
            analyse_sol = analyse_solidite_dividendes(liste_symboles_sol)
            if analyse_sol is None:
                if st.button("🛡️ Analyser la solidité des dividendes", type="primary", key="btn_solidite_dividendes"):
                    with st.spinner("📥 Lecture de l'historique des dividendes du catalogue..."):
                        analyse_sol = analyse_solidite_dividendes(liste_symboles_sol, calculer=True)
                    if analyse_sol is None:
                        st.warning("Historiques indisponibles pour le moment (Yahoo Finance). Réessayez dans quelques minutes.")
                else:
                    st.caption("Le premier calcul du jour lit l'historique de tout le catalogue (une vingtaine de secondes) ; "
                               "il s'affiche ensuite d'emblée, pour tous les utilisateurs, jusqu'au lendemain.")
            if analyse_sol:
                annee_sol, seuils_sol = analyse_sol["annee"], analyse_sol["seuils"]
                non_classee = {"libelle": "— Non classée", "explication": "historique indisponible", "alertes": [], "solide": False}

                def rendement_sol(valeurs_s):
                    return f"{valeurs_s['H'] * 100:.1f} %".replace(".", ",") if valeurs_s and valeurs_s.get("retenue") else "—"

                st.markdown(f"##### Votre radar : situation au 31/12/{annee_sol}")
                lignes_sol = []
                for nom_s, symbole_s in sorted(symboles_radar_sol.items()):
                    valeurs_s, verdict_s = analyse_sol["demandes"].get(symbole_s) or (None, non_classee)
                    lignes_sol.append({
                        "Valeur": nom_s,
                        "Verdict": verdict_s["libelle"],
                        f"Dividende par action {annee_sol - 5} → {annee_sol}": evolution_dividende(valeurs_s, annee_sol),
                        f"Rendement au 31/12/{annee_sol}": rendement_sol(valeurs_s),
                        "Pourquoi": verdict_s["explication"],
                    })
                if lignes_sol:
                    st.dataframe(pd.DataFrame(lignes_sol), width="stretch", hide_index=True)
                else:
                    st.info("Aucune action dans votre radar (les ETF ne sont pas classés).")
                a_risque_sol = [l["Valeur"] for l in lignes_sol if "⚠️" in l["Verdict"]]
                if a_risque_sol:
                    st.warning(
                        f"⚠️ **Dividendes à surveiller dans votre radar** : {', '.join(a_risque_sol)}. Dans l'étude, "
                        f"{eleve_groupe} des rendements les plus élevés ont baissé leur dividende dans les 3 années "
                        "suivantes : un rendement très élevé annonce souvent une baisse déjà attendue par le marché."
                    )
                if "H" in seuils_sol:
                    seuil_sol = f"{seuils_sol['H'] * 100:.2f}".replace(".", ",")
                    st.caption(
                        f"Rendement élevé : {seuil_sol} % ou plus au 31/12/{annee_sol} (les 20 % les plus élevés du "
                        "catalogue). Comme dans l'étude, le classement porte sur la dernière année complète ; il change chaque "
                        "début d'année. Dividendes dans la devise de l'action."
                    )

                st.markdown("##### Les dividendes solides du catalogue")
                solides_sol = []
                for symbole_s, (valeurs_s, verdict_s) in analyse_sol["catalogue"].items():
                    if not verdict_s["solide"]:
                        continue
                    nom_s, secteur_s, _devise_s = analyse_sol["noms"].get(symbole_s, (symbole_s, "", ""))
                    croissance_s = valeurs_s.get("G")
                    solides_sol.append({
                        "Valeur": nom_s,
                        "Secteur": secteur_s,
                        f"Rendement au 31/12/{annee_sol}": rendement_sol(valeurs_s),
                        "Croissance du dividende (5 ans)": (f"{croissance_s * 100:+.1f} % / an".replace(".", ",")
                                                            if croissance_s is not None else "—"),
                        "Verdict": verdict_s["libelle"],
                        "_tri": valeurs_s["H"],
                    })
                classees_sol = sum(1 for valeurs_s, _ in analyse_sol["catalogue"].values() if valeurs_s and valeurs_s.get("retenue"))
                if solides_sol:
                    solides_sol.sort(key=lambda l: -l["_tri"])
                    st.dataframe(pd.DataFrame(solides_sol).drop(columns="_tri"), width="stretch", hide_index=True)
                st.caption(
                    f"{len(solides_sol)} dividendes solides sur {classees_sol} actions du catalogue classées, du rendement le plus "
                    "élevé au plus faible. Ce n'est pas une liste d'achat : même parmi les solides, environ une sur cinq a baissé "
                    "son dividende dans les 3 ans pendant l'étude. Diversifiez (secteurs, pays) et, pour un PEA, vérifiez "
                    "l'éligibilité de la valeur : les dividendes étrangers y subissent une retenue à la source non récupérable."
                )

            # --- SUIVI EN CONDITIONS RÉELLES (etudes/protocole_suivi_dividendes.md) ---
            st.markdown("##### 📒 Suivi en conditions réelles : le test qui compte")
            st.caption(
                "L'étude ne porte que sur des entreprises qui existent encore. Pour lever ce biais, la tâche planifiée enregistre "
                "chaque mois de janvier le classement de tout le catalogue, avant de connaître la suite, et continue de suivre "
                "chaque action même si elle quitte le catalogue. Personne ne peut modifier un classement après coup."
            )
            if st.toggle("Afficher le suivi en conditions réelles", key="tog_suivi_solidite"):
                try:
                    lignes_suivi = lire_suivi_solidite()
                except Exception:
                    lignes_suivi = None
                if lignes_suivi is None:
                    st.info("Le suivi n'est pas lisible : vérifiez le secret SUPABASE_SERVICE_KEY et la table suivi_solidite "
                            "(voir README).")
                elif not lignes_suivi:
                    st.info("Aucun classement enregistré pour l'instant. Le premier (au 31/12/2026) sera enregistré en janvier "
                            "2027 ; premiers résultats à 1 an en janvier 2028, à 3 ans en janvier 2030.")
                else:
                    resultats_suivi = evaluer_suivi(lignes_suivi)
                    annees_suivi = sorted(resultats_suivi["cohortes"])

                    def taux_suivi(comptes, categorie):
                        baisses, mesurees = comptes.get(categorie, (0, 0))
                        return f"{baisses / mesurees * 100:.0f} % ({baisses} sur {mesurees})" if mesurees else "—"

                    lignes_tableau_suivi = []
                    for annee_s in annees_suivi:
                        for horizon_s, mesure_s in sorted(resultats_suivi["cohortes"][annee_s].items()):
                            lignes_tableau_suivi.append({
                                "Classement au": f"31/12/{annee_s}",
                                "Horizon": f"{horizon_s} an{'s' if horizon_s > 1 else ''}",
                                "Solides : baisse": taux_suivi(mesure_s["comptes"], "solide"),
                                "Neutres : baisse": taux_suivi(mesure_s["comptes"], "neutre"),
                                "À surveiller : baisse": taux_suivi(mesure_s["comptes"], "alerte"),
                                "Illisibles": mesure_s["illisibles"],
                            })
                    if lignes_tableau_suivi:
                        st.dataframe(pd.DataFrame(lignes_tableau_suivi), width="stretch", hide_index=True)
                    else:
                        st.info("Classement enregistré ; il faut attendre l'enregistrement de janvier suivant pour mesurer les "
                                "premières baisses à 1 an.")
                    solide_1, autres_1 = (f"{x * 100:.0f} %" for x in TAUX_MESURES_1_AN["solide"])
                    st.caption(
                        f"{len(annees_suivi)} classement(s) enregistré(s) depuis le 31/12/{annees_suivi[0]}. Dans l'étude (période "
                        f"de test), baisses à 1 an : solides {solide_1}, autres {autres_1} ; à 3 ans : solides "
                        f"{TAUX_MESURES['solide'][0] * 100:.0f} %, autres {TAUX_MESURES['solide'][1] * 100:.0f} %, rendements les "
                        f"plus élevés {TAUX_MESURES['rendement_eleve'][0] * 100:.0f} %. Résultats provisoires tant que trois "
                        "classements n'ont pas été mesurés à 3 ans (janvier 2032)."
                    )

    # ==========================================================================
    # BILAN DES SIGNAUX : L'ALGORITHME REJOUÉ SUR LE PASSÉ
    # ==========================================================================
    with st.expander("🔬 Bilan des signaux : qu'ont fait les actions après chaque signal du radar ?", expanded=False):
        if not est_premium_ou_pro:
            afficher_verrou_saas(
                "Bilan des signaux de l'algorithme rejoué sur le passé",
                "⚡ Offre Premium (4,90 €/mois) ou 👑 Pro (8,90 €/mois)",
                "Vérifiez si les signaux du radar ont été suivis, dans le passé, de meilleures performances que la moyenne."
            )
        else:
            st.caption(
                "Boursy rejoue ses algorithmes une fois par mois sur l'historique de chaque valeur (jusqu'à 7 ans), "
                "avec uniquement les cours et les dividendes connus à chaque date, puis mesure ce que l'action a fait "
                "dans les 1, 3 et 6 mois suivants, dividendes inclus."
            )
            if not st.session_state.get("_bilan_signaux_demande"):
                if st.button("🔬 Calculer le bilan des signaux", type="primary", key="btn_bilan_signaux"):
                    st.session_state["_bilan_signaux_demande"] = True
            if st.session_state.get("_bilan_signaux_demande"):
                valeurs_radar_bilan = [
                    (nom_b, info_b) for nom_b, info_b in st.session_state["watchlist"].items()
                    if nom_b in actions_autorisees and isinstance(info_b, dict) and info_b.get("symbole")
                ]
                # Catalogue complet : toutes les actions connues (hors ETF), une seule fois par symbole
                valeurs_catalogue_bilan, symboles_vus_bilan = [], set()
                for nom_b, info_b in sorted(WATCHLIST_DEFAUT.items()):
                    if (nom_b in CLES_TECHNIQUES_PF or not isinstance(info_b, dict) or not info_b.get("symbole")
                            or "ETF" in str(info_b.get("secteur", "")) or info_b["symbole"] in symboles_vus_bilan):
                        continue
                    symboles_vus_bilan.add(info_b["symbole"])
                    valeurs_catalogue_bilan.append((nom_b, info_b))
                choix_univers_bilan = st.radio(
                    "Valeurs étudiées :", ["Mon radar", "Tout le catalogue"], horizontal=True, key="rad_univers_bilan",
                    help="Le catalogue complet donne beaucoup plus d'observations, donc des fourchettes plus étroites, et ne se limite "
                         "pas aux valeurs que vous avez choisies. Le premier calcul prend plus de temps (une fois toutes les 6 heures).",
                )
                valeurs_bilan = valeurs_catalogue_bilan if choix_univers_bilan == "Tout le catalogue" else valeurs_radar_bilan
                st.caption(f"{len(valeurs_bilan)} valeur(s) étudiée(s)" + (" (actions du catalogue, hors ETF)." if choix_univers_bilan == "Tout le catalogue" else " (votre radar)."))

                # Téléchargement des historiques en parallèle (mis en cache 6 heures), puis rejeu valeur par valeur
                with st.spinner("📥 Chargement des historiques de cours..."):
                    with ThreadPoolExecutor(max_workers=6) as executeur_bilan:
                        list(executeur_bilan.map(historique_long, sorted({info_b["symbole"] for _, info_b in valeurs_bilan})))
                observations_bilan, valeurs_sans_historique = [], []
                barre_bilan = st.progress(0.0, text="🔬 Rejeu de l'algorithme sur l'historique...")
                for rang_b, (nom_b, info_b) in enumerate(valeurs_bilan, start=1):
                    obs_b = bilan_signaux_symbole(info_b["symbole"], float(info_b.get("payout_ratio", 0.60)))
                    barre_bilan.progress(rang_b / max(1, len(valeurs_bilan)), text=f"🔬 Rejeu de l'algorithme : {nom_b} ({rang_b}/{len(valeurs_bilan)})")
                    if obs_b is None:
                        valeurs_sans_historique.append(nom_b)
                        continue
                    for o in obs_b:
                        observations_bilan.append(dict(o, action=nom_b))
                barre_bilan.empty()

                choix_algorithme_bilan = st.radio(
                    "Algorithme étudié :", list(ALGORITHMES_SIGNAUX.values()), horizontal=True, key="rad_algorithme_bilan",
                    help="Score actuel : celui du radar. Filtre de tendance : pas de signal fort sous la moyenne mobile à 200 jours. "
                         "Nouveau score : tendance, momentum 12-1 mois, faible volatilité, rendement et régularité du dividende.",
                )
                cle_algorithme_bilan = next(k for k, v in ALGORITHMES_SIGNAUX.items() if v == choix_algorithme_bilan)
                observations_bilan = [dict(o, decision=o.get(cle_algorithme_bilan, o["decision"])) for o in observations_bilan]

                if not observations_bilan:
                    st.warning("Aucun historique suffisant (au moins 3 ans de cours) n'a pu être chargé pour les valeurs de votre radar.")
                else:
                    def _moyenne(valeurs):
                        valeurs = [v for v in valeurs if v is not None]
                        return (sum(valeurs) / len(valeurs)) if valeurs else None

                    choix_periode_bilan = st.radio(
                        "Période étudiée :", ["Tout l'historique", "Sans l'année 2020 (krach du Covid et rebond)"],
                        horizontal=True, key="rad_periode_bilan",
                    )
                    observations_toutes = observations_bilan
                    if choix_periode_bilan.startswith("Sans"):
                        observations_bilan = [o for o in observations_toutes if not str(o["date"]).startswith("2020")] or observations_toutes

                    categories_bilan = ["🟢 SIGNAL FORT", "🔵 SIGNAL FAVORABLE", "⚪ SIGNAL NEUTRE"]
                    lignes_bilan = []
                    for categorie in categories_bilan + ["Toutes les observations"]:
                        obs_c = observations_bilan if categorie == "Toutes les observations" else [o for o in observations_bilan if o["decision"] == categorie]
                        r6_c = [o["r6"] for o in obs_c if o["r6"] is not None]
                        lignes_bilan.append({
                            "categorie": categorie, "nombre": len(obs_c),
                            "r1": _moyenne(o["r1"] for o in obs_c), "r3": _moyenne(o["r3"] for o in obs_c), "r6": _moyenne(r6_c),
                            "positifs": (sum(1 for r in r6_c if r > 0) / len(r6_c)) if r6_c else None,
                        })
                    reference_r6 = lignes_bilan[-1]["r6"]

                    def _cellule_perf(valeur):
                        if valeur is None:
                            return "<td>—</td>"
                        couleur = "#2ecc71" if valeur >= 0 else "#e74c3c"
                        return f"<td style='color:{couleur}; font-weight:800;'>{valeur * 100:+.1f} %</td>"

                    html_bilan = (
                        "<table class='r-table'><thead><tr><th style='text-align:left;'>Signal du radar</th><th>Observations</th>"
                        "<th>1 mois après</th><th>3 mois après</th><th>6 mois après</th><th>Écart à 6 mois vs ensemble</th>"
                        "<th>Part de hausses à 6 mois</th></tr></thead><tbody>"
                    )
                    for ligne_b in lignes_bilan:
                        ecart_b = (ligne_b["r6"] - reference_r6) if (ligne_b["r6"] is not None and reference_r6 is not None) else None
                        if ligne_b["categorie"] == "Toutes les observations":
                            cellule_ecart = "<td>référence</td>"
                        elif ecart_b is None:
                            cellule_ecart = "<td>—</td>"
                        else:
                            cellule_ecart = f"<td><span class='{'b-green' if ecart_b >= 0 else 'b-red'}'>{ecart_b * 100:+.1f} pt</span></td>"
                        html_bilan += (
                            f"<tr><td class='r-name'>{ligne_b['categorie']}</td><td>{ligne_b['nombre']}</td>"
                            + _cellule_perf(ligne_b["r1"]) + _cellule_perf(ligne_b["r3"]) + _cellule_perf(ligne_b["r6"]) + cellule_ecart
                            + (f"<td>{ligne_b['positifs'] * 100:.0f} %</td>" if ligne_b["positifs"] is not None else "<td>—</td>")
                            + "</tr>"
                        )
                    html_bilan += "</tbody></table>"
                    afficher_html(html_bilan)

                    st.caption(
                        "La colonne « Écart à 6 mois vs ensemble » mélange toutes les valeurs : une valeur qui a beaucoup monté et "
                        "souvent signalé peut à elle seule faire paraître le signal meilleur. Les vérifications ci-dessous sont plus fiables."
                    )

                    # --- VÉRIFICATIONS 2 ET 3 : COMPARAISON AUX AUTRES ACTIONS DU MÊME MOIS, AVEC UNE FOURCHETTE D'INCERTITUDE ---
                    # (voir ecart_vs_autres_actions_du_mois dans moteur_signaux.py : pourquoi ce choix, et sa calibration)
                    def _ecart_ajuste(categorie, cle_r, horizon_mois, cle_decision="decision"):
                        return ecart_vs_autres_actions_du_mois(observations_bilan, categorie, cle_r, horizon_mois, cle_decision)

                    def _pt(valeur):
                        """Écart en points avec signe, sans « -0,0 »."""
                        arrondi = round(valeur * 100, 1)
                        return f"{(0.0 if arrondi == 0 else arrondi):+.1f}"

                    def _cellule_ecart(resultat):
                        if resultat is None:
                            return "<td>—</td>"
                        couleur = "#2ecc71" if resultat["moyenne"] >= 0 else "#e74c3c"
                        fourchette = (f"<br><span style='font-size:0.8em; opacity:0.75;'>[{_pt(resultat['bas'])} ; {_pt(resultat['haut'])}]</span>"
                                      if resultat["bas"] is not None else "")
                        return f"<td><b style='color:{couleur};'>{_pt(resultat['moyenne'])} pt</b>{fourchette}</td>"

                    def _verdict(resultat):
                        if resultat is None or resultat["bas"] is None or resultat["nombre"] < 30:
                            return "<span class='b-neutral'>Trop peu de données</span>"
                        if resultat["bas"] > 0:
                            return "<span class='b-green'>✅ Avantage net</span>"
                        if resultat["haut"] < 0:
                            return "<span class='b-red'>❌ Désavantage net</span>"
                        return "<span class='b-yellow'>〰️ Dans la marge d'incertitude</span>"

                    st.markdown("##### 🧪 Vérification : comparaison aux autres actions du même mois")
                    verifications_bilan = {c: (_ecart_ajuste(c, "r1", 1), _ecart_ajuste(c, "r6", 6)) for c in categories_bilan}
                    html_verif = (
                        "<table class='r-table'><thead><tr><th style='text-align:left;'>Signal du radar</th>"
                        "<th>Écart à 1 mois vs les autres actions<br><span style='font-size:0.82em; opacity:0.75;'>[fourchette à 95 %]</span></th>"
                        "<th>Lecture à 1 mois</th>"
                        "<th>Écart à 6 mois vs les autres actions<br><span style='font-size:0.82em; opacity:0.75;'>[fourchette à 95 %]</span></th>"
                        "<th>Lecture à 6 mois</th></tr></thead><tbody>"
                    )
                    for categorie in categories_bilan:
                        v1, v6 = verifications_bilan[categorie]
                        html_verif += (f"<tr><td class='r-name'>{categorie}</td>" + _cellule_ecart(v1) + f"<td>{_verdict(v1)}</td>"
                                       + _cellule_ecart(v6) + f"<td>{_verdict(v6)}</td></tr>")
                    html_verif += "</tbody></table>"
                    afficher_html(html_verif)
                    st.caption(
                        "Chaque signal est comparé aux autres actions étudiées le même mois : l'effet du marché du moment est "
                        "neutralisé, et la question posée est celle du DCA : ce mois-ci, quelle action acheter ? Une version "
                        "précédente comparait chaque action à sa propre moyenne ; une simulation sur des cours imprévisibles a montré "
                        "que cette mesure flattait mécaniquement les achats après une baisse (environ +1 point à 6 mois) et pénalisait "
                        "les signaux de tendance (environ -3 points). La mesure actuelle n'a pas ce défaut."
                    )

                    st.markdown("##### ⚖️ Comparaison des trois algorithmes (signal fort, comparé aux autres actions du même mois)")
                    html_comparaison = (
                        "<table class='r-table'><thead><tr><th style='text-align:left;'>Algorithme</th><th>Signaux forts</th>"
                        "<th>Écart à 1 mois<br><span style='font-size:0.82em; opacity:0.75;'>[fourchette à 95 %]</span></th>"
                        "<th>Écart à 6 mois<br><span style='font-size:0.82em; opacity:0.75;'>[fourchette à 95 %]</span></th>"
                        "<th>Lecture à 6 mois</th></tr></thead><tbody>"
                    )
                    for cle_algo, libelle_algo in ALGORITHMES_SIGNAUX.items():
                        c1 = _ecart_ajuste(categories_bilan[0], "r1", 1, cle_algo)
                        c6 = _ecart_ajuste(categories_bilan[0], "r6", 6, cle_algo)
                        nb_forts_algo = sum(1 for o in observations_bilan if o.get(cle_algo) == categories_bilan[0])
                        marque = " 👈" if cle_algo == cle_algorithme_bilan else ""
                        html_comparaison += (f"<tr><td class='r-name'>{libelle_algo}{marque}</td><td>{nb_forts_algo}</td>"
                                             + _cellule_ecart(c1) + _cellule_ecart(c6) + f"<td>{_verdict(c6)}</td></tr>")
                    html_comparaison += "</tbody></table>"
                    afficher_html(html_comparaison)
                    st.caption(
                        "Les trois algorithmes sont mesurés sur les mêmes valeurs et la même période. La variante et le nouveau score "
                        "ont été définis avant de regarder leurs résultats, avec des paramètres standards ; seul le suivi en direct, "
                        "ci-dessous, permettra de les juger sans aucun ajustement possible."
                    )

                    # Lecture factuelle, fondée sur la comparaison aux autres actions du même mois
                    v_fort_1, v_fort_6 = verifications_bilan[categories_bilan[0]]
                    if v_fort_6 is None or v_fort_6["bas"] is None or v_fort_6["nombre"] < 30:
                        nb_fort_r6 = v_fort_6["nombre"] if v_fort_6 else 0
                        lecture_b = (f"Trop peu de signaux forts suivis de 6 mois d'historique ({nb_fort_r6}) pour en tirer une conclusion : "
                                     + ("cet algorithme en émet trop peu, même sur tout le catalogue." if choix_univers_bilan == "Tout le catalogue"
                                        else "choisissez « Tout le catalogue » ci-dessus, ou revenez quand l'historique sera plus long."))
                    else:
                        lecture_b = (f"Comparés aux autres actions du même mois, les signaux forts ont été suivis à 6 mois d'un écart moyen de "
                                     f"{_pt(v_fort_6['moyenne'])} point(s) (fourchette à 95 % : {_pt(v_fort_6['bas'])} à {_pt(v_fort_6['haut'])}). ")
                        if v_fort_6["bas"] > 0:
                            lecture_b += "Même le bas de la fourchette est positif : l'avantage est net sur cette période."
                        elif v_fort_6["haut"] < 0:
                            lecture_b += "Même le haut de la fourchette est négatif : sur cette période, le signal a desservi."
                        else:
                            lecture_b += "La fourchette contient zéro : l'avantage n'est pas démontré, il peut venir du hasard."
                        if v_fort_1 is not None and v_fort_1["bas"] is not None and v_fort_1["nombre"] >= 30:
                            lecture_b += (f" À 1 mois : {_pt(v_fort_1['moyenne'])} point(s) (fourchette {_pt(v_fort_1['bas'])} "
                                          f"à {_pt(v_fort_1['haut'])}), " + ("avantage net." if v_fort_1["bas"] > 0 else "non démontré."))
                    lecture_b += f" (Algorithme : {choix_algorithme_bilan.lower()}" + ("; période : sans l'année 2020.)" if choix_periode_bilan.startswith("Sans") else ".)")
                    st.info(nombres_fr("📊 " + lecture_b))

                    # --- VÉRIFICATION 1 : ANNÉE PAR ANNÉE (comparaison dans la même année, donc dans le même contexte de marché) ---
                    st.markdown("##### 📅 Année par année")
                    html_annees = (
                        "<table class='r-table'><thead><tr><th>Année</th><th>Observations</th><th>Signaux forts</th>"
                        "<th>6 mois après un signal fort</th><th>6 mois, toutes les observations de l'année</th><th>Écart</th></tr></thead><tbody>"
                    )
                    for annee_b in sorted({str(o["date"])[:4] for o in observations_toutes}):
                        obs_a = [o for o in observations_toutes if str(o["date"]).startswith(annee_b)]
                        forts_a = [o for o in obs_a if o["decision"] == categories_bilan[0]]
                        r6_fort_a = _moyenne(o["r6"] for o in forts_a)
                        r6_tous_a = _moyenne(o["r6"] for o in obs_a)
                        ecart_a = (r6_fort_a - r6_tous_a) if (r6_fort_a is not None and r6_tous_a is not None) else None
                        cellule_ecart_a = ("<td>—</td>" if ecart_a is None else
                                           f"<td><span class='{'b-green' if ecart_a >= 0 else 'b-red'}'>{ecart_a * 100:+.1f} pt</span></td>")
                        html_annees += (f"<tr><td><b>{annee_b}</b></td><td>{len(obs_a)}</td><td>{len(forts_a)}</td>"
                                        + _cellule_perf(r6_fort_a) + _cellule_perf(r6_tous_a) + cellule_ecart_a + "</tr>")
                    html_annees += "</tbody></table>"
                    afficher_html(html_annees)
                    st.caption(
                        "Chaque année compare les signaux forts aux autres observations de la même année : l'effet du marché de "
                        "l'époque est ainsi neutralisé. Un avantage qui ne vient que d'une ou deux années est fragile. La dernière "
                        "année est incomplète : ses signaux récents n'ont pas encore 6 mois de recul."
                    )

                    if st.toggle("Voir le détail par valeur", key="tog_bilan_detail"):
                        lignes_detail = []
                        for nom_d in sorted({o["action"] for o in observations_bilan},
                                            key=lambda n: (-sum(1 for o in observations_bilan if o["action"] == n and o["decision"] == categories_bilan[0]), n)):
                            obs_d = [o for o in observations_bilan if o["action"] == nom_d]
                            forts_d = [o for o in obs_d if o["decision"] == categories_bilan[0]]
                            moyenne_toutes = _moyenne(o["r6"] for o in obs_d)
                            moyenne_forts = _moyenne(o["r6"] for o in forts_d)
                            lignes_detail.append({
                                "Valeur": nom_d,
                                "Depuis": f"{obs_d[0]['date'][8:10]}/{obs_d[0]['date'][5:7]}/{obs_d[0]['date'][0:4]}",
                                "Observations": len(obs_d),
                                "Signaux forts": len(forts_d),
                                "Perf. 6 mois après un signal fort": nombres_fr(f"{moyenne_forts * 100:+.1f} %") if moyenne_forts is not None else "—",
                                "Perf. 6 mois, toutes dates": nombres_fr(f"{moyenne_toutes * 100:+.1f} %") if moyenne_toutes is not None else "—",
                            })
                        st.caption("Classement : valeurs ayant reçu le plus de signaux forts en premier.")
                        st.dataframe(pd.DataFrame(lignes_detail), width="stretch", hide_index=True)

                    if valeurs_sans_historique:
                        st.caption("Valeurs sans historique suffisant, non comptées : " + ", ".join(valeurs_sans_historique) + ".")
                    st.caption(
                        "Limites : le critère « prix cible » n'est pas compté (Boursy ne connaît pas vos prix cibles passés) ; sans lui, le score "
                        "actuel plafonne à 85 sur 100, et ses signaux forts sont plus rares que dans le radar en direct. Le payout ratio "
                        "est la valeur actuelle, et les valeurs étudiées sont "
                        + ("les actions du catalogue d'aujourd'hui" if choix_univers_bilan == "Tout le catalogue" else "celles de votre radar d'aujourd'hui")
                        + ", qui ont par définition survécu jusqu'ici. Les observations mensuelles à 6 mois se chevauchent : elles ne sont "
                        "pas indépendantes. Ce bilan décrit le passé ; il ne garantit rien pour l'avenir."
                    )

                    # --- SIGNAUX ENREGISTRÉS EN DIRECT : LE TEST SANS RETOUCHE POSSIBLE ---
                    st.markdown("##### 📒 Signaux enregistrés en direct : le test qui compte")
                    st.caption(
                        "Chaque mois, la tâche planifiée enregistre les signaux des trois algorithmes sur tout le catalogue, avant de "
                        "connaître la suite. Personne ne peut les modifier après coup : au fil des mois, ce tableau dira lequel a "
                        "réellement fonctionné."
                    )
                    if st.toggle("Afficher les signaux enregistrés en direct", key="tog_journal_signaux"):
                        try:
                            lignes_journal = lire_signaux_mensuels()
                        except Exception:
                            lignes_journal = None
                        if lignes_journal is None:
                            st.info("Le journal n'est pas lisible : vérifiez le secret SUPABASE_SERVICE_KEY et la table signaux_mensuels (voir README).")
                        elif not lignes_journal:
                            st.info("Aucun signal enregistré pour l'instant : le premier enregistrement aura lieu lors de la prochaine exécution de la tâche planifiée (chaque soir de bourse).")
                        else:
                            mois_journal = sorted({l["mois"] for l in lignes_journal})
                            with st.spinner("📥 Mesure de ce qui a suivi chaque signal enregistré..."):
                                with ThreadPoolExecutor(max_workers=6) as executeur_journal:
                                    historiques_journal = dict(zip(
                                        sorted({l["symbole"] for l in lignes_journal}),
                                        executeur_journal.map(historique_long, sorted({l["symbole"] for l in lignes_journal})),
                                    ))
                            mesures_journal = []
                            for l in lignes_journal:
                                hist_j = historiques_journal.get(l["symbole"])
                                if hist_j is None:
                                    continue
                                rang_j = bisect.bisect_right(hist_j[0], str(l["date_cours"])[:10]) - 1
                                if rang_j < 0:
                                    continue
                                mesures_journal.append(dict(
                                    l,
                                    r1=performance_apres(hist_j[0], hist_j[1], hist_j[2], rang_j, 21),
                                    r6=performance_apres(hist_j[0], hist_j[1], hist_j[2], rang_j, 126),
                                ))
                            html_journal = (
                                "<table class='r-table'><thead><tr><th style='text-align:left;'>Algorithme</th><th>Signaux forts enregistrés</th>"
                                "<th>1 mois après un signal fort</th><th>1 mois, toutes les actions</th>"
                                "<th>6 mois après un signal fort</th><th>6 mois, toutes les actions</th></tr></thead><tbody>"
                            )
                            for cle_algo, libelle_algo in ALGORITHMES_SIGNAUX.items():
                                forts_j = [m for m in mesures_journal if m.get(cle_algo) == categories_bilan[0]]
                                n1 = sum(1 for m in forts_j if m["r1"] is not None)
                                n6 = sum(1 for m in forts_j if m["r6"] is not None)
                                html_journal += (
                                    f"<tr><td class='r-name'>{libelle_algo}</td><td>{len(forts_j)}</td>"
                                    + _cellule_perf(_moyenne(m["r1"] for m in forts_j)).replace("</td>", f"<br><span style='font-size:0.78em; color:#9aa5b1; font-weight:600;'>{n1} mesurable(s)</span></td>")
                                    + _cellule_perf(_moyenne(m["r1"] for m in mesures_journal))
                                    + _cellule_perf(_moyenne(m["r6"] for m in forts_j)).replace("</td>", f"<br><span style='font-size:0.78em; color:#9aa5b1; font-weight:600;'>{n6} mesurable(s)</span></td>")
                                    + _cellule_perf(_moyenne(m["r6"] for m in mesures_journal))
                                    + "</tr>"
                                )
                            html_journal += "</tbody></table>"
                            afficher_html(html_journal)
                            premier_mois_j = mois_journal[0]
                            st.caption(nombres_fr(
                                f"{len(lignes_journal)} signaux enregistrés sur {len(mois_journal)} mois (depuis {premier_mois_j[5:7]}/{premier_mois_j[0:4]}). "
                                "Les mesures à 6 mois apparaissent 6 mois après chaque enregistrement. Résultats indicatifs : "
                                "il faudra au moins 12 mois d'enregistrements pour commencer à conclure."
                            ))

