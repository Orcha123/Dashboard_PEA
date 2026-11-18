"""
Onglet 3 de Boursy : jauge d'objectif de rente, calendrier des dividendes sur 12 mois, prochains détachements,
projection prudente de la rente (étude des dividendes) et simulateur « boule de neige ».

Toutes les informations venues du reste de l'application sont des paramètres nommés d'afficher() :
leur liste est la liste exacte des dépendances de l'onglet (vérifiée par tests/test_application.py).
"""
from datetime import datetime
import math

import pandas as pd
import streamlit as st

from donnees_marche import prochain_detachement
from habillage import afficher_html, nombres_fr
from solidite_dividendes import (
    CHOC_CRISE, EVOLUTION_REVENU, HORIZONS_PROJECTION, INFLATION_HYPOTHESE, categorie_projection, en_euros_courants,
    facteur_relatif, projeter_rente, rendement_median_solides,
)


def afficher(
    *,
    BUDGET_MENSUEL,
    CLES_TECHNIQUES_PF,
    TAUX_USD_EUR,
    WATCHLIST_DEFAUT,
    actions_actives_pf,
    afficher_verrou_saas,
    analyse_solidite_dividendes,
    cout_total_achat,
    est_premium_ou_pro,
    est_pro_max,
    lignes_triees,
    mode_gratuit,
    portefeuille_utilisateur,
    sauvegarder_dans_cloud,
    valeur_totale_portefeuille,
):
    st.subheader("📅 Calendrier Annuel des Dividendes & Simulateur Effet Boule de Neige")

    if not actions_actives_pf:
        st.warning("Ajoutez des actions dans votre portefeuille pour générer votre calendrier de revenus passifs.")
    else:
        # --- TABLEAU DES PROCHAINS DÉTACHEMENTS (90J - EXCLUSIF PRO 8,90 €) ---
        @st.cache_data(ttl=3600)
        def recuperer_prochain_detachement_90j(symbole):
            return prochain_detachement(symbole)

        if est_pro_max:
            lignes_detachement_90j = []
            source_actions = st.session_state.get("watchlist", WATCHLIST_DEFAUT)
            for nom_d, pos_d in portefeuille_utilisateur.items():
                if nom_d in CLES_TECHNIQUES_PF or not isinstance(pos_d, dict) or float(pos_d.get("qte", 0)) <= 0:
                    continue
                info_d = source_actions.get(nom_d, WATCHLIST_DEFAUT.get(nom_d, {}))
                sym_d = info_d.get("symbole", "")
                if not sym_d:
                    continue
                nb_j, date_ex, mt_unit = recuperer_prochain_detachement_90j(sym_d)
                if date_ex is not None:
                    qte_d = float(pos_d.get("qte", 0))
                    dev_d = "$" if info_d.get("devise") == "USD" else "€"
                    lignes_detachement_90j.append({
                        "jours": nb_j,
                        "Action": nom_d,
                        "Date Ex-Dividende": date_ex.strftime("%d/%m/%Y"),
                        "Échéance": f"J-{nb_j}" if nb_j > 0 else "⚡ Aujourd'hui",
                        "Coupon unitaire": f"{mt_unit:.2f} {dev_d}",
                        "Total estimé": f"{mt_unit * qte_d:.2f} {dev_d}"
                    })

            if lignes_detachement_90j:
                lignes_detachement_90j.sort(key=lambda x: x["jours"])
                html_90j = """
                <div style="margin-bottom: 8px; display:flex; justify-content:space-between; align-items:center;">
                    <span style="font-size:0.85em; font-weight:800; text-transform:uppercase; color:#3498db;">📌 Prochains Détachements de Dividendes (Horizon 90 Jours)</span>
                    <span class="b-blue">{nb} détachement(s) détecté(s)</span>
                </div>
                <table class="r-table">
                <thead>
                    <tr>
                        <th style="text-align:left;">Action</th>
                        <th>Date Ex-Dividende Estimée</th>
                        <th>Échéance</th>
                        <th>Coupon Unitaire</th>
                        <th>Montant Estimé</th>
                    </tr>
                </thead>
                <tbody>
                """.format(nb=len(lignes_detachement_90j))

                for item_d in lignes_detachement_90j:
                    j_rest = item_d.get("jours", 90)
                    b_ech = "b-red" if j_rest <= 15 else ("b-blue" if j_rest <= 45 else "b-neutral")
                    html_90j += f"""
                    <tr>
                        <td class="r-name">🏢 {item_d['Action']}</td>
                        <td><b>📅 {item_d['Date Ex-Dividende']}</b></td>
                        <td><span class="{b_ech}">⏳ {item_d['Échéance']}</span></td>
                        <td>{item_d['Coupon unitaire']} / action</td>
                        <td><span class="b-green">+{item_d['Total estimé']}</span></td>
                    </tr>
                    """
                html_90j += "</tbody></table>"
                afficher_html(html_90j)

        # --- GUICHET D'ENCAISSEMENT DES DIVIDENDES VERS LA POCHE ESPÈCES (PREMIUM & PRO) ---
        def encaisser_dividende_vers_especes():
            act_enc = st.session_state.get("sel_act_enc_div")
            mt_enc = float(st.session_state.get("input_mt_enc_div", 0.0))
            if act_enc and mt_enc > 0:
                esp_actuel = float(st.session_state.get("pru_Espèces", st.session_state["portefeuille"].get("Espèces", {}).get("pru", 0.0))) if isinstance(st.session_state["portefeuille"].get("Espèces"), dict) else float(st.session_state.get("pru_Espèces", 0.0))
                nouveau_esp = round(esp_actuel + mt_enc, 2)
                st.session_state["pru_Espèces"] = nouveau_esp
                st.session_state["qte_Espèces"] = 1
                st.session_state["portefeuille"]["Espèces"] = {"qte": 1, "pru": nouveau_esp}
                st.session_state["dividendes_encaisses_cumul"] = round(float(st.session_state.get("dividendes_encaisses_cumul", 0.0)) + mt_enc, 2)
                sauvegarder_dans_cloud()
                st.session_state["_notif_div_encaisse"] = f"✅ +{mt_enc:,.2f} € de dividendes ({act_enc}) crédités dans votre poche Espèces (Nouveau solde Espèces : {nouveau_esp:,.2f} €) !"

        if st.session_state.get("_notif_div_encaisse"):
            st.success(nombres_fr(st.session_state.pop("_notif_div_encaisse")))

        actions_div_pf = [
            k for k, v in portefeuille_utilisateur.items()
            if k not in CLES_TECHNIQUES_PF and isinstance(v, dict) and float(v.get("qte", 0)) > 0
        ]
        if actions_div_pf:
            with st.expander("📥 Guichet d'Encaissement en 1 Clic : Créditer un dividende détaché dans ma poche Espèces", expanded=False):
                if mode_gratuit:
                    afficher_verrou_saas(
                        "Guichet d'Encaissement Automatique des Dividendes vers la Poche Espèces",
                        "⚡ Offre Premium (4,90 €/mois) ou 👑 Pro (8,90 €/mois)",
                        "Créditez vos coupons détachés directement dans vos liquidités PEA/CTO en 1 clic."
                    )
                else:
                    col_ed1, col_ed2, col_ed3 = st.columns([2, 1.5, 1.5])
                    with col_ed1:
                        act_choisie_div = st.selectbox("Action ayant versé son dividende :", actions_div_pf, key="sel_act_enc_div")
                    info_ed = WATCHLIST_DEFAUT.get(act_choisie_div, {})
                    qte_ed = float(portefeuille_utilisateur.get(act_choisie_div, {}).get("qte", 0))
                    fact_ed = (1.0 / TAUX_USD_EUR) if info_ed.get("devise") == "USD" else 1.0
                    nb_vers_ed = max(1, len(info_ed.get("mois_div", ["Mai"])))
                    bonus_nom_ed = 1.10 if act_choisie_div in st.session_state.get("actions_nominatif", []) else 1.0
                    montant_coupon_defaut = round((qte_ed * float(info_ed.get("div_eur", 0.0)) * fact_ed * bonus_nom_ed) / nb_vers_ed, 2)

                    with col_ed2:
                        st.number_input("Montant net reçu (€) :", min_value=0.01, value=max(0.01, montant_coupon_defaut), step=1.0, key="input_mt_enc_div")
                    with col_ed3:
                        st.markdown("<div style='margin-top:28px;'></div>", unsafe_allow_html=True)
                        st.button(
                            "💶 Créditer mes Espèces",
                            type="primary",
                            width="stretch",
                            on_click=encaisser_dividende_vers_especes,
                        )

        mois_ordre = ["Jan", "Fév", "Mar", "Avr", "Mai", "Juin", "Juil", "Août", "Sep", "Oct", "Nov", "Déc"]
        noms_mois_complets = {
            "Jan": "Janvier", "Fév": "Février", "Mar": "Mars", "Avr": "Avril",
            "Mai": "Mai", "Juin": "Juin", "Juil": "Juillet", "Août": "Août",
            "Sep": "Septembre", "Oct": "Octobre", "Nov": "Novembre", "Déc": "Décembre"
        }
        revenus_par_mois = {m: 0.0 for m in mois_ordre}
        details_par_mois = {m: [] for m in mois_ordre}
        total_annuel_div = 0.0
        lignes_rente = []  # (nom, symbole, dividende annuel en euros) pour la projection prudente

        noms_retenus_div = [l["nom_act"] for l in lignes_triees if not l["est_especes"]]
        for nom_act in noms_retenus_div:
            data_pos = portefeuille_utilisateur.get(nom_act, {})
            if not isinstance(data_pos, dict) or nom_act not in WATCHLIST_DEFAUT:
                continue
            qte = float(data_pos.get("qte", 0.0))
            if qte <= 0:
                continue
            info_act = WATCHLIST_DEFAUT[nom_act]
            devise = info_act.get("devise", "EUR")
            facteur = (1.0 / TAUX_USD_EUR) if devise == "USD" else 1.0
            div_annuel_eur = qte * float(info_act.get("div_eur", 0.0)) * facteur
            total_annuel_div += div_annuel_eur
            lignes_rente.append((nom_act, str(info_act.get("symbole", "")).strip(), div_annuel_eur))

            mois_versement = info_act.get("mois_div", ["Mai"])
            if mois_versement:
                montant_par_versement = div_annuel_eur / len(mois_versement)
                for m in mois_versement:
                    if m in revenus_par_mois:
                        revenus_par_mois[m] += montant_par_versement
                        details_par_mois[m].append((nom_act, montant_par_versement))

        rente_mensuelle_moy = total_annuel_div / 12.0
        meilleur_mois = max(revenus_par_mois.items(), key=lambda x: x[1]) if total_annuel_div > 0 else ("Mai", 0.0)
        nb_mois_actifs = sum(1 for v in revenus_par_mois.values() if v > 0)

        html_div_kpi = f"""
        <div class="argon-grid">
            <div class="argon-card">
                <div class="argon-title">💵 Rente Annuelle Globale</div>
                <div class="argon-val" style="color:#2ecc71;">{total_annuel_div:,.2f} € / an</div>
                <div class="argon-sub">Dividendes convertis en Euros (€)</div>
            </div>
            <div class="argon-card">
                <div class="argon-title">🗓️ Revenu Mensuel Moyen</div>
                <div class="argon-val" style="color:#3498db;">{rente_mensuelle_moy:,.2f} € / mois</div>
                <div class="argon-sub">{nb_mois_actifs} / 12 mois avec versement</div>
            </div>
            <div class="argon-card">
                <div class="argon-title">🏆 Mois Record</div>
                <div class="argon-val">{noms_mois_complets[meilleur_mois[0]]} ({meilleur_mois[1]:.1f} €)</div>
                <div class="argon-sub">Pic de détachement annuel</div>
            </div>
            <div class="argon-card">
                <div class="argon-title">🔄 Force de Frappe DCA + Div.</div>
                <div class="argon-val">+{total_annuel_div + (BUDGET_MENSUEL*12):,.0f} € / an</div>
                <div class="argon-sub">Capacité d'investissement annuelle</div>
            </div>
        </div>
        """
        afficher_html(html_div_kpi)

        paliers_rente = [
            (50.0, "🥉 Palier 1 : 50 € / mois"),
            (100.0, "🥈 Palier 2 : 100 € / mois"),
            (250.0, "🥇 Palier 3 : 250 € / mois"),
            (500.0, "💎 Palier 4 : 500 € / mois"),
            (1000.0, "👑 Palier 5 : 1 000 € / mois"),
        ]
        prochain_palier_val = 1000.0
        prochain_palier_nom = "👑 Palier 5 : 1 000 € / mois"
        for val_p, nom_p in paliers_rente:
            if rente_mensuelle_moy < val_p:
                prochain_palier_val = val_p
                prochain_palier_nom = nom_p
                break

        pct_jauge = min(100.0, max(2.0, (rente_mensuelle_moy / prochain_palier_val) * 100.0)) if prochain_palier_val > 0 else 100.0
        manque_mensuel = max(0.0, prochain_palier_val - rente_mensuelle_moy)
        manque_annuel = manque_mensuel * 12.0
        rendement_moy_pf = (total_annuel_div / valeur_totale_portefeuille) if valeur_totale_portefeuille > 0 and total_annuel_div > 0 else 0.052
        rendement_moy_pf = max(0.035, min(0.10, rendement_moy_pf))
        capital_requis_palier = manque_annuel / rendement_moy_pf
        epargne_mensuelle_totale = max(50.0, BUDGET_MENSUEL + rente_mensuelle_moy)
        mois_estimes_palier = max(1, int(math.ceil(capital_requis_palier / epargne_mensuelle_totale))) if manque_mensuel > 0 else 0

        steps_html = ""
        for val_p, nom_p in paliers_rente:
            if rente_mensuelle_moy >= val_p:
                steps_html += f"<div class='goal-step' style='border-color:#2ecc71; background:rgba(46,204,113,0.16); color:#2ecc71;'>✅ {nom_p}<br><span style='font-size:0.8em;'>Validé !</span></div>"
            elif val_p == prochain_palier_val:
                steps_html += f"<div class='goal-step' style='border-color:#3498db; background:rgba(52,152,219,0.18); color:#3498db;'>🎯 {nom_p}<br><span style='font-size:0.8em;'>En cours ({pct_jauge:.1f}%)</span></div>"
            else:
                steps_html += f"<div class='goal-step' style='opacity:0.65;'>🔒 {nom_p}<br><span style='font-size:0.8em;'>À débloquer</span></div>"

        html_jauge_rente = f"""
        <div class="goal-box">
            <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px;">
                <div>
                    <div style="font-size:0.80em; font-weight:800; text-transform:uppercase; letter-spacing:0.7px; color:#2ecc71;">🎯 Jauge d'Objectif de Rente Mensuelle</div>
                    <div style="font-size:1.22em; font-weight:900; margin-top:2px;">Cap actuel : {prochain_palier_nom} — <span style="color:#2ecc71;">{rente_mensuelle_moy:.2f} €</span> / {prochain_palier_val:.0f} € par mois</div>
                </div>
                <div style="text-align:right;">
                    <span class="b-green" style="font-size:0.95em;">Progression : {pct_jauge:.1f}%</span>
                </div>
            </div>
            <div class="goal-bar-bg">
                <div style="width:{pct_jauge:.1f}%; height:100%; background:linear-gradient(90deg, #2ecc71 0%, #3498db 100%); border-radius:10px;"></div>
            </div>
            <div style="display:flex; justify-content:space-between; font-size:0.88em; margin-bottom:12px; flex-wrap:wrap; gap:8px;">
                <span>💡 Il vous manque <b>+{manque_mensuel:.2f} € / mois</b> (soit <b>+{manque_annuel:.0f} € / an</b> de dividendes) pour valider ce palier.</span>
                <span>⏱️ <b>Estimation au rythme DCA actuel ({BUDGET_MENSUEL:.0f} €/mois) :</b> atteint dans env. <b>{mois_estimes_palier} mois</b> (~{capital_requis_palier:,.0f} € à investir).</span>
            </div>
            <div class="goal-steps">{steps_html}</div>
        </div>
        """
        afficher_html(html_jauge_rente)

        st.markdown("#### 🗓️ Calendrier Mois par Mois des Dividendes Versés sur l'Année")
        html_grille_12mois = "<div class='cal-grid'>"
        for idx_m, m_code in enumerate(mois_ordre, start=1):
            montant_m = revenus_par_mois[m_code]
            liste_ent = details_par_mois[m_code]
            classe_carte = "cal-card-active" if montant_m > 0 else "cal-card"
            couleur_montant = "#2ecc71" if montant_m > 0 else "rgba(128,128,128,0.5)"

            if liste_ent:
                pills_html = "".join(f"<span class='cal-pill'><b>{nom_e}</b> : {val_e:.1f} €</span>" for nom_e, val_e in liste_ent)
            else:
                pills_html = "<span style='font-size:0.82em; opacity:0.45; font-style:italic;'>Aucun détachement prévu</span>"

            html_grille_12mois += f"""
            <div class="{classe_carte}">
                <div>
                    <div class="cal-month">
                        <span>{idx_m:02d}. {noms_mois_complets[m_code]}</span>
                        <span style="font-size:0.85em;">{'💰' if montant_m > 0 else '⚪'}</span>
                    </div>
                    <div style="margin-bottom:10px;">{pills_html}</div>
                </div>
                <div style="text-align:right; border-top:1px dashed rgba(128,128,128,0.2); padding-top:6px;">
                    <span style="font-size:0.78em; opacity:0.75; margin-right:6px;">Total :</span>
                    <span class="cal-total" style="color:{couleur_montant};">{montant_m:,.2f} €</span>
                </div>
            </div>
            """
        html_grille_12mois += "</div>"
        afficher_html(html_grille_12mois)

        st.markdown("#### 📊 Diagramme en Bâtons des Dividendes par Mois (€)")
        df_bar_div = pd.DataFrame([
            {"Ordre": i, "Mois": noms_mois_complets[m], "Dividendes (€)": round(revenus_par_mois[m], 2)}
            for i, m in enumerate(mois_ordre)
        ])
        spec_bar_div = {
            "height": 300,
            "mark": {"type": "bar", "cornerRadiusTopLeft": 6, "cornerRadiusTopRight": 6, "color": "#2ecc71"},
            "encoding": {
                "x": {"field": "Mois", "type": "nominal", "sort": list(noms_mois_complets.values()), "axis": {"labelAngle": 0, "title": "Mois de l'année"}},
                "y": {"field": "Dividendes (€)", "type": "quantitative", "axis": {"title": "Montant versé (€)"}},
                "tooltip": [
                    {"field": "Mois", "type": "nominal"},
                    {"field": "Dividendes (€)", "type": "quantitative", "format": ",.2f"},
                ],
            },
        }
        st.vega_lite_chart(df_bar_div, spec_bar_div, width="stretch")

        # --- PROJECTION PRUDENTE DE LA RENTE (ÉTUDE DES DIVIDENDES) ---
        st.markdown("---")
        st.markdown("#### 🛡️ Projection Prudente de votre Rente")
        if not est_premium_ou_pro:
            afficher_verrou_saas(
                "Projection prudente de la rente",
                "⚡ Offre Premium (4,90 €/mois) ou 👑 Pro (8,90 €/mois)",
                "Ce que votre rente pourrait devenir avec des hypothèses prudentes tirées de l'étude des dividendes de Boursy, "
                "et ce qu'une crise comme celle de 2020 lui ferait.",
            )
        else:
            def euros(x):
                return f"{x:,.0f}".replace(",", " ") + " €"

            def virgule(x, decimales=1):
                return f"{x:.{decimales}f}".replace(".", ",")

            symboles_rente = sorted({sym for _, sym, _ in lignes_rente if sym})
            analyse_rente = analyse_solidite_dividendes(symboles_rente)
            if analyse_rente is None:
                if st.button("🛡️ Calculer la projection prudente", type="primary", key="btn_projection_rente"):
                    with st.spinner("📥 Classement des dividendes du catalogue (solides, neutres, à surveiller)..."):
                        analyse_rente = analyse_solidite_dividendes(symboles_rente, calculer=True)
                    if analyse_rente is None:
                        st.warning("Historiques indisponibles pour le moment (Yahoo Finance). Réessayez dans quelques minutes.")
                else:
                    st.caption("La projection classe d'abord vos lignes (solides, neutres, à surveiller). Le premier calcul du "
                               "jour lit l'historique de tout le catalogue (une vingtaine de secondes) ; il sert ensuite à tous.")
            if analyse_rente:
                montants_categories = {"solide": 0.0, "neutre": 0.0, "alerte": 0.0}
                lignes_prudentes = []
                for _nom_r, symbole_r, revenu_r in lignes_rente:
                    verdict_r = (analyse_rente["demandes"].get(symbole_r) or (None, None))[1]
                    categorie_r = categorie_projection(verdict_r)
                    montants_categories[categorie_r] += revenu_r
                    lignes_prudentes.append((revenu_r, categorie_r))
                rendement_achats = rendement_median_solides(analyse_rente["catalogue"].values())

                col_pr1, col_pr2 = st.columns(2)
                with col_pr1:
                    apport_prudent = st.number_input(
                        "💶 Apport mensuel investi en dividendes solides (€)", min_value=0, max_value=100000,
                        value=int(max(0, BUDGET_MENSUEL)), step=50, key="nb_apport_rente_prudente",
                    )
                with col_pr2:
                    reinvestir_prudent = st.toggle("🔁 Réinvestir les dividendes", value=True, key="tg_reinvestir_rente_prudente")
                projection_prudente = projeter_rente(
                    lignes_prudentes, apport_annuel=12.0 * apport_prudent, rendement_achats=rendement_achats,
                    reinvestir=reinvestir_prudent, annees=max(HORIZONS_PROJECTION),
                )
                annee_actuelle = datetime.now().year
                lignes_tableau_prudent = [
                    {
                        "Horizon": f"Dans {n} an{'s' if n > 1 else ''} ({annee_actuelle + n})",
                        "Rente prudente (euros d'aujourd'hui)": f"{euros(rente)} / an",
                        "Par mois": f"{euros(rente / 12.0)} / mois",
                        f"En euros de l'époque (inflation {INFLATION_HYPOTHESE * 100:.0f} %/an)": f"{euros(en_euros_courants(rente, n))} / an",
                        "L'année d'une crise comme 2020": f"{euros(crise)} / an",
                    }
                    for n, rente, crise in projection_prudente if n in HORIZONS_PROJECTION
                ]
                st.caption(
                    f"Point de départ : {euros(total_annuel_div)} / an de dividendes attendus sur vos lignes (montants du "
                    f"catalogue), dont {euros(montants_categories['solide'])} solides, {euros(montants_categories['neutre'])} "
                    f"neutres ou non classés et {euros(montants_categories['alerte'])} à surveiller."
                )
                st.dataframe(pd.DataFrame(lignes_tableau_prudent), width="stretch", hide_index=True)
                st.bar_chart(
                    pd.DataFrame({"Rente prudente (€/an, euros d'aujourd'hui)": [round(r) for _, r, _ in projection_prudente]},
                                 index=[str(annee_actuelle + n) for n, _, _ in projection_prudente]),
                    height=260,
                )
                ecart_1 = (1.0 - facteur_relatif("alerte", 1)) * 100
                ecart_10 = (1.0 - facteur_relatif("alerte", 10)) * 100
                croissance_passee = (EVOLUTION_REVENU["solide"][10][0] ** 0.1 - 1.0) * 100
                st.caption(
                    "Hypothèses prudentes, en euros d'aujourd'hui : le dividende des lignes solides et neutres suit seulement "
                    f"l'inflation ; celui des lignes à surveiller perd l'écart mesuré dans l'étude par rapport aux solides "
                    f"(−{ecart_1:.0f} % au bout d'un an, −{ecart_10:.0f} % au bout de 10 ans) ; vos apports"
                    + (", et vos dividendes réinvestis," if reinvestir_prudent else "")
                    + f" achètent des dividendes solides au rendement médian actuel de la liste ({virgule(rendement_achats * 100)} %). "
                    "Dernière colonne : l'année d'une crise comme 2020, la pire année mesurée (solides "
                    f"{virgule(CHOC_CRISE['solide'] * 100, 0)} %, neutres {virgule(CHOC_CRISE['neutre'] * 100, 0)} %, à surveiller "
                    f"{virgule(CHOC_CRISE['alerte'] * 100, 0)} %) : gardez une réserve pour une telle année.".replace("-", "−")
                )
                st.caption(
                    f"Pourquoi pas la croissance passée ? Les dividendes solides du catalogue ont progressé de "
                    f"{virgule(croissance_passee)} % par an sur 10 ans (médiane des départs 2010-2015), mais le catalogue ne "
                    "contient que des entreprises qui existent encore, et la période a suivi la crise de 2009 : ce n'est pas "
                    "une base prudente. Le simulateur ci-dessous vous laisse choisir vos propres hypothèses."
                )

        st.markdown("---")
        st.markdown("#### ❄️ Simulateur Interactif d'Effet Boule de Neige (DCA + Dividendes Réinvestis)")

        rendement_actuel_pf = (total_annuel_div / valeur_totale_portefeuille * 100.0) if valeur_totale_portefeuille > 0 else 4.8
        rendement_defaut_slider = float(max(1.5, min(10.0, round(rendement_actuel_pf, 1))))

        col_sl1, col_sl2, col_sl3, col_sl4 = st.columns(4)
        with col_sl1:
            horizon_annees = st.slider("⏳ Horizon (Années)", min_value=5, max_value=30, value=15, step=1)
        with col_sl2:
            dca_simule = st.slider("💶 Apport DCA Mensuel (€)", min_value=0, max_value=10000, value=int(min(10000, max(0, BUDGET_MENSUEL))), step=50)
        with col_sl3:
            rendement_simule_pct = st.slider("🌱 Rendement Dividende (%)", min_value=1.0, max_value=12.0, value=rendement_defaut_slider, step=0.2)
        with col_sl4:
            croissance_annuelle_pct = st.slider("📈 Croissance Annuelle Cours/Div (%)", min_value=0.0, max_value=10.0, value=3.0, step=0.5)

        cap_courant = valeur_totale_portefeuille
        cap_investi_cumule = cout_total_achat if cout_total_achat > 0 else valeur_totale_portefeuille
        lignes_proj = []
        donnees_graph_boule = []

        for annee in range(1, horizon_annees + 1):
            apport_annuel = float(dca_simule * 12)
            cap_investi_cumule += apport_annuel
            plus_value_croissance = cap_courant * (croissance_annuelle_pct / 100.0)
            div_annee = (cap_courant + apport_annuel / 2.0) * (rendement_simule_pct / 100.0)
            cap_courant = cap_courant + apport_annuel + plus_value_croissance + div_annee
            rente_mensuelle_an = div_annee / 12.0

            annee_cal = datetime.now().year + annee
            donnees_graph_boule.append({
                "Année": f"{annee_cal}",
                "Capital Total Boule de Neige (€)": round(cap_courant, 0),
                "Total Apports Personnels (€)": round(cap_investi_cumule, 0),
                "Rente Annuelle (€/an)": round(div_annee, 0),
            })
            lignes_proj.append({
                "Horizon": f"Année +{annee} ({annee_cal})",
                "Apports Cumulés": f"{cap_investi_cumule:,.0f} €",
                "Capital Projeté": f"{cap_courant:,.0f} €",
                "Gains & Dividendes Réinvestis": f"+{cap_courant - cap_investi_cumule:,.0f} €",
                "Rente Annuelle": f"{div_annee:,.0f} € / an",
                "Rente Mensuelle": f"{rente_mensuelle_an:,.1f} € / mois",
            })

        dernier_pt = donnees_graph_boule[-1]
        gain_pur_interets = dernier_pt["Capital Total Boule de Neige (€)"] - dernier_pt["Total Apports Personnels (€)"]

        html_kpi_snow = f"""
        <div class="argon-grid">
            <div class="argon-card">
                <div class="argon-title">🏔️ Capital Final à {horizon_annees} Ans</div>
                <div class="argon-val" style="color:#2ecc71;">{dernier_pt['Capital Total Boule de Neige (€)']:,.0f} €</div>
                <div class="argon-sub">Dont Apports : <b>{dernier_pt['Total Apports Personnels (€)']:,.0f} €</b></div>
            </div>
            <div class="argon-card">
                <div class="argon-title">✨ Intérêts Composés Gagnés</div>
                <div class="argon-val" style="color:#9b59b6;">+{gain_pur_interets:,.0f} €</div>
                <div class="argon-sub">Dividendes réinvestis + Croissance</div>
            </div>
            <div class="argon-card">
                <div class="argon-title">💵 Future Rente Annuelle</div>
                <div class="argon-val" style="color:#3498db;">{dernier_pt['Rente Annuelle (€/an)']:,.0f} € / an</div>
                <div class="argon-sub">En {dernier_pt['Année']}</div>
            </div>
            <div class="argon-card">
                <div class="argon-title">🏖️ Future Rente Mensuelle</div>
                <div class="argon-val" style="color:#f39c12;">{dernier_pt['Rente Annuelle (€/an)']/12.0:,.0f} € / mois</div>
                <div class="argon-sub">Revenu passif mensuel estimé</div>
            </div>
        </div>
        """
        afficher_html(html_kpi_snow)

        col_g_snow1, col_g_snow2 = st.columns(2)
        df_snow_chart = pd.DataFrame(donnees_graph_boule).set_index("Année")
        with col_g_snow1:
            st.markdown("**📈 Courbe d'Accélération : Capital Total vs Apports Personnels (€)**")
            st.area_chart(df_snow_chart[["Capital Total Boule de Neige (€)", "Total Apports Personnels (€)"]], height=300)
        with col_g_snow2:
            st.markdown("**💵 Progression de votre Rente Annuelle de Dividendes (€/an)**")
            st.bar_chart(df_snow_chart[["Rente Annuelle (€/an)"]], height=300)

        with st.expander(f"📋 Voir le tableau détaillé année par année sur {horizon_annees} ans", expanded=True):
            html_proj = "<table class='r-table'><thead><tr><th style='text-align:left;'>Horizon</th><th>Apports Cumulés</th><th>Capital Projeté (€)</th><th>Intérêts Composés</th><th>Rente Annuelle</th><th>Rente Mensuelle</th></tr></thead><tbody>"
            for lp in lignes_proj:
                html_proj += f"<tr><td class='r-name'>{lp['Horizon']}</td><td>{lp['Apports Cumulés']}</td><td><b>{lp['Capital Projeté']}</b></td><td style='color:#9b59b6; font-weight:700;'>{lp['Gains & Dividendes Réinvestis']}</td><td style='color:#2ecc71; font-weight:800;'>{lp['Rente Annuelle']}</td><td><span class='b-blue'>{lp['Rente Mensuelle']}</span></td></tr>"
            html_proj += "</tbody></table>"
            afficher_html(html_proj)

