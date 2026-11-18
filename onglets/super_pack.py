"""
Super-Pack Pro de Boursy : sections ajoutées dans plusieurs onglets (architecture PEA/CTO, plafond PEA, rendement
sur PRU, duel face à l'ETF Monde, boost de coupon, prochains détachements, matrice de convergence et station
graphique 360°). Il reçoit les onglets Streamlit où il écrit (onglet_radar, onglet_portefeuille, onglet_dividendes).

app.py l'appelle dans un « try » : une erreur ici affiche un avertissement sans bloquer le reste de la page.

Toutes les informations venues du reste de l'application sont des paramètres nommés d'afficher() :
leur liste est la liste exacte des dépendances de l'onglet (vérifiée par tests/test_application.py).
"""
from datetime import datetime
import math

import pandas as pd
import streamlit as st

from habillage import afficher_html, nombres_fr


def afficher(
    *,
    CLES_TECHNIQUES_PF,
    TAUX_USD_EUR,
    WATCHLIST_DEFAUT,
    actions_autorisees,
    afficher_verrou_saas,
    donnees_t1,
    est_premium_ou_pro,
    est_pro_max,
    facteur_cout_usd,
    historiques_prix,
    mode_gratuit,
    onglet_dividendes,
    onglet_portefeuille,
    onglet_radar,
    recuperer_donnees,
    versements_nets_pea,
):
    pf_pack = st.session_state.get("portefeuille", {})
    wl_complet_pack = st.session_state.get("watchlist", WATCHLIST_DEFAUT)
    if mode_gratuit:
        wl_pack = {k: v for k, v in wl_complet_pack.items() if k in actions_autorisees}
    else:
        wl_pack = wl_complet_pack

    prix_tr_pack = st.session_state.get("prix_temps_reel", {})
    hist_ventes_pack = st.session_state.get("historique_ventes", [])
    liste_t1_pack = donnees_t1
    hist_prix_pack = historiques_prix
    budget_dca_pack = float(st.session_state.get("budget_dca", st.session_state.get("budget_mensuel", 450.0)))

    # --- EXTRACTEUR UNIVERSEL DE DIVIDENDES ET DE MOIS DE VERSEMENT ---
    def _extraire_infos_div_et_mois(nom_act, cours_actuel):
        inf_def = WATCHLIST_DEFAUT.get(nom_act, {})
        inf_usr = wl_complet_pack.get(nom_act, {})
        inf = {}
        if isinstance(inf_def, dict):
            inf.update(inf_def)
        if isinstance(inf_usr, dict):
            inf.update(inf_usr)

        div_val = 0.0
        for k_d in ("div_eur", "dividende", "div", "div_annuel", "dividende_eur", "coupon", "montant_div", "div_brut"):
            if inf.get(k_d) is not None:
                try:
                    v_d = float(str(inf.get(k_d)).replace("€", "").replace("$", "").replace(",", ".").strip())
                    if v_d > 0:
                        div_val = v_d
                        break
                except Exception:
                    pass

        if div_val <= 0 and cours_actuel > 0:
            for k_r in ("rendement", "rdt", "yield", "rendement_pct", "div_pct"):
                if inf.get(k_r) is not None:
                    try:
                        v_r = float(str(inf.get(k_r)).replace("%", "").replace(",", ".").strip())
                        if v_r > 0:
                            div_val = round(cours_actuel * (v_r / 100.0), 2)
                            break
                    except Exception:
                        pass

        raw_m = None
        for k_m in ("mois", "mois_div", "mois_versement", "mois_detachement", "mois_paiement", "versements", "calendrier", "dates_div"):
            if inf.get(k_m) is not None and inf.get(k_m) != [] and inf.get(k_m) != "":
                raw_m = inf.get(k_m)
                break
        if raw_m is None and isinstance(inf_def, dict):
            for k_m in ("mois", "mois_div", "mois_versement", "mois_detachement", "mois_paiement", "versements", "calendrier"):
                if inf_def.get(k_m):
                    raw_m = inf_def.get(k_m)
                    break
        if raw_m is None:
            for k_any, v_any in inf.items():
                if "mois" in str(k_any).lower() and v_any:
                    raw_m = v_any
                    break

        map_nom_m = {
            "jan": 1, "fev": 2, "fév": 2, "feb": 2, "mar": 3, "avr": 4, "apr": 4,
            "mai": 5, "may": 5, "juin": 6, "jun": 6, "juil": 7, "jul": 7,
            "aou": 8, "aoû": 8, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12, "déc": 12,
        }

        def _convertir_en_mois(item):
            res = []
            if isinstance(item, (int, float)):
                m_i = int(item)
                if 1 <= m_i <= 12:
                    res.append(m_i)
            elif isinstance(item, str):
                s_clean = item.lower().replace("/", " ").replace("-", " ").replace(";", ",").replace("|", ",")
                for morceau in s_clean.split(","):
                    morceau = morceau.strip()
                    if not morceau:
                        continue
                    if morceau.isdigit() and 1 <= int(morceau) <= 12:
                        res.append(int(morceau))
                    else:
                        for pref, num_m in map_nom_m.items():
                            if morceau.startswith(pref) or pref in morceau:
                                res.append(num_m)
                                break
            elif isinstance(item, dict):
                for k_sub in item.keys():
                    res.extend(_convertir_en_mois(k_sub))
            elif isinstance(item, (list, tuple, set)):
                for sub in item:
                    res.extend(_convertir_en_mois(sub))
            return res

        mois_extraits = sorted(list(set(_convertir_en_mois(raw_m)))) if raw_m is not None else [5]
        if not mois_extraits:
            mois_extraits = [5]

        return inf, div_val, mois_extraits

    _tab_portefeuille = onglet_portefeuille
    _tab_dividendes = onglet_dividendes

    # --------------------------------------------------------------------------
    # CALCULS CENTRAUX : SÉPARATION PEA (€) / CTO ($), YIELD ON COST & POIDS
    # --------------------------------------------------------------------------
    cap_inv_pea = 0.0
    val_act_pea = 0.0
    rente_pea = 0.0

    cap_inv_cto = 0.0
    val_act_cto = 0.0
    rente_cto = 0.0

    total_val_actions_pack = 0.0
    total_cout_actions_pack = 0.0
    total_rente_actions_pack = 0.0
    poids_actions_pack = {}
    lignes_yoc_details = []

    lignes_csv = ["\ufeff=== 1. MON PORTEFEUILLE ACTUEL (PEA & CTO) ==="]
    lignes_csv.append("Enveloppe;Action;Symbole;Quantite;PRU;Devise;Cours Actuel;Valorisation EUR;Plus-Value Latente EUR;Rendement Marche %;Rendement sur PRU (YoC) %;Rente Annuelle EUR")

    nb_lignes_pack_gratuit = 0
    for nom_p, pos_p in pf_pack.items():
        if (nom_p in CLES_TECHNIQUES_PF and nom_p != "Espèces") or not isinstance(pos_p, dict):
            continue
        q_p = float(pos_p.get("qte", 0.0))
        pru_p = float(pos_p.get("pru", 0.0))
        if q_p <= 0:
            continue

        # Forfait Gratuit : mêmes 2 premières lignes d'actions que le tableau de l'onglet Portefeuille
        if nom_p != "Espèces":
            if nom_p not in WATCHLIST_DEFAUT:
                continue
            if mode_gratuit and nb_lignes_pack_gratuit >= 2:
                continue
            nb_lignes_pack_gratuit += 1

        if nom_p == "Espèces":
            cap_inv_pea += pru_p
            val_act_pea += pru_p
            lignes_csv.append(f"PEA (EUR);Especes;CASH;1;{pru_p:.2f};EUR;{pru_p:.2f};{pru_p:.2f};0.00;0.00%;0.00%;0.00")
        else:
            inf_base = wl_complet_pack.get(nom_p, WATCHLIST_DEFAUT.get(nom_p, {}))
            cours_p = float(prix_tr_pack.get(nom_p, pru_p if pru_p > 0 else inf_base.get("prix_cible", 0.0)))
            inf_p, div_p, _ = _extraire_infos_div_et_mois(nom_p, cours_p)

            sym_p = inf_p.get("symbole", "")
            dev_p = inf_p.get("devise", "EUR")
            est_cto_usd = (dev_p == "USD")
            env_label = "CTO (USD)" if est_cto_usd else "PEA (EUR)"
            dev_sym_p = "$" if est_cto_usd else "€"
            fact_p = (1.0 / TAUX_USD_EUR) if est_cto_usd else 1.0

            val_eur_p = q_p * cours_p * fact_p
            cout_eur_p = q_p * pru_p * (facteur_cout_usd(pos_p) if est_cto_usd else 1.0)
            pv_lat_p = val_eur_p - cout_eur_p
            rente_eur_p = q_p * div_p * fact_p

            rdt_marche_p = (div_p / cours_p * 100.0) if cours_p > 0 else 0.0
            yoc_p = (div_p / pru_p * 100.0) if pru_p > 0 else 0.0
            payback_ans = (pru_p / div_p) if div_p > 0 else 0.0

            if est_cto_usd:
                cap_inv_cto += cout_eur_p
                val_act_cto += val_eur_p
                rente_cto += rente_eur_p
            else:
                cap_inv_pea += cout_eur_p
                val_act_pea += val_eur_p
                rente_pea += rente_eur_p

            total_val_actions_pack += val_eur_p
            total_cout_actions_pack += cout_eur_p
            total_rente_actions_pack += rente_eur_p
            poids_actions_pack[nom_p] = val_eur_p

            lignes_yoc_details.append({
                "nom": nom_p,
                "enveloppe": env_label,
                "qte": int(q_p),
                "pru": pru_p,
                "cours": cours_p,
                "dev_sym": dev_sym_p,
                "div_unitaire": div_p,
                "rdt_marche": rdt_marche_p,
                "yoc": yoc_p,
                "bonus_yoc": yoc_p - rdt_marche_p,
                "rente_eur": rente_eur_p,
                "val_eur": val_eur_p,
                "cout_eur": cout_eur_p,
                "payback": payback_ans,
            })

            lignes_csv.append(
                f"{env_label};{nom_p};{sym_p};{int(q_p)};{pru_p:.2f};{dev_p};{cours_p:.2f};{val_eur_p:.2f};{pv_lat_p:+.2f};{rdt_marche_p:.2f}%;{yoc_p:.2f}%;{rente_eur_p:.2f}"
            )

    # --------------------------------------------------------------------------
    # 1. BARRE LATÉRALE : MODE DISCRÉTION & EXPORT EXCEL / CSV ENRICHI
    # --------------------------------------------------------------------------
    st.sidebar.markdown("---")
    st.sidebar.subheader("🛡️ Outils Pro & Sécurité")

    mode_discret = st.sidebar.checkbox(
        "🕵️ Mode Discrétion (Flouter les €)",
        value=False,
        key="chk_mode_discretion_pro",
        help="Floute automatiquement vos montants en euros à l'écran (passez la souris sur une carte pour la lire).",
    )

    if mode_discret:
        st.markdown(
            """
            <style>
            .argon-val, .cal-total, .meteo-item div:nth-child(2),
            .r-table td:nth-child(4), .r-table td:nth-child(5), .r-table td:nth-child(6) {
                filter: blur(7px) !important;
                transition: filter 0.2s ease-in-out !important;
                cursor: pointer !important;
            }
            .argon-val:hover, .cal-total:hover, .meteo-item div:nth-child(2):hover,
            .r-table td:nth-child(4):hover, .r-table td:nth-child(5):hover, .r-table td:nth-child(6):hover {
                filter: none !important;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )

    lignes_csv.append("")
    lignes_csv.append("=== 2. JOURNAL DES PLUS-VALUES ACTEES (VENTES) ===")
    lignes_csv.append("Date;Action;Quantite Vendue;PRU;Prix de Vente;Devise;Cash Net Encaisse EUR;Plus ou Moins-Value Actee EUR;Performance %")

    for v_item in hist_ventes_pack:
        lignes_csv.append(
            f"{v_item.get('date','')};{v_item.get('action','')};{v_item.get('qte',0)};"
            f"{float(v_item.get('pru',0)):.2f};{float(v_item.get('prix_vente',0)):.2f};{v_item.get('devise','€')};"
            f"{float(v_item.get('montant_eur',0)):.2f};{float(v_item.get('plus_value_eur',0)):+.2f};{float(v_item.get('perf_pct',0)):+.2f}%"
        )

    contenu_csv_bytes = "\n".join(lignes_csv).encode("utf-8")
    if est_premium_ou_pro:
        st.sidebar.download_button(
            label="📥 Sauvegarde Locale (Excel / CSV)",
            data=contenu_csv_bytes,
            file_name=f"Boursy_Bilan_Complet_{datetime.now().strftime('%Y-%m-%d')}.csv",
            mime="text/csv",
            width="stretch",
        )
    else:
        st.sidebar.button("🔒 Sauvegarde CSV (Offre Premium/Pro)", disabled=True, width="stretch")

    alertes_surpond = []
    if total_val_actions_pack > 0:
        for nom_sp, val_sp in sorted(poids_actions_pack.items(), key=lambda x: x[1], reverse=True):
            pct_sp = (val_sp / total_val_actions_pack) * 100.0
            if pct_sp >= 20.0:
                alertes_surpond.append((nom_sp, pct_sp, val_sp))

    # --------------------------------------------------------------------------
    # 2. ONGLET 2 : SÉPARATION PEA/CTO, YIELD ON COST & DUEL ETF
    # --------------------------------------------------------------------------
    if _tab_portefeuille is not None and (cap_inv_pea > 0 or cap_inv_cto > 0):
        with _tab_portefeuille:
            st.markdown("---")
            st.subheader("🏛️ Architecture Patrimoniale : Séparation PEA (€) vs CTO ($), Yield on Cost & Duel ETF")

            plafond_pea_legal = 150000.0
            pv_actees_tot_pea = sum(float(v.get("plus_value_eur", 0.0)) for v in hist_ventes_pack if v.get("devise", "€") != "$")
            div_enc_pea = float(st.session_state.get("dividendes_encaisses_cumul", 0.0))
            # Même valeur que la « Jauge Officielle Plafond PEA » de l'onglet (calcul local seulement en repli)
            versements_nets_pea_unifie = float(
                versements_nets_pea if versements_nets_pea is not None
                else max(0.0, cap_inv_pea - max(0.0, pv_actees_tot_pea + div_enc_pea))
            )
            marge_pea_dispo = max(0.0, plafond_pea_legal - versements_nets_pea_unifie)
            pct_plafond_pea = min(100.0, (versements_nets_pea_unifie / plafond_pea_legal) * 100.0)
            pv_pea = val_act_pea - cap_inv_pea
            pv_cto = val_act_cto - cap_inv_cto
            c_pv_pea = "#2ecc71" if pv_pea >= 0 else "#e74c3c"
            c_pv_cto = "#2ecc71" if pv_cto >= 0 else "#e74c3c"

            yoc_global = (total_rente_actions_pack / total_cout_actions_pack * 100.0) if total_cout_actions_pack > 0 else 0.0
            rdt_marche_global = (total_rente_actions_pack / total_val_actions_pack * 100.0) if total_val_actions_pack > 0 else 0.0
            bonus_yoc_global = yoc_global - rdt_marche_global

            afficher_html(f"""
            <div class="argon-grid" style="margin-bottom: 14px;">
                <div class="argon-card" style="border-top: 3px solid #3498db;">
                    <div class="argon-title">🇫🇷 Poche PEA Éligible (Hors US)</div>
                    <div class="argon-val">{val_act_pea:,.2f} €</div>
                    <div class="argon-sub">Investi PRU : <b>{cap_inv_pea:,.0f} €</b> | PV : <span style="color:{c_pv_pea}; font-weight:700;">{pv_pea:+,.0f} €</span></div>
                </div>
                <div class="argon-card" style="border-top: 3px solid #9b59b6;">
                    <div class="argon-title">🇺🇸 Poche CTO Actions US ($)</div>
                    <div class="argon-val">{val_act_cto:,.2f} €</div>
                    <div class="argon-sub">Investi PRU : <b>{cap_inv_cto:,.0f} €</b> | PV : <span style="color:{c_pv_cto}; font-weight:700;">{pv_cto:+,.0f} €</span></div>
                </div>
                <div class="argon-card" style="border-top: 3px solid #2ecc71;">
                    <div class="argon-title">🛡️ Plafond Légal PEA (150 000 €)</div>
                    <div class="argon-val" style="color:#2ecc71;">{pct_plafond_pea:.1f}% utilisé</div>
                    <div class="argon-sub">Reste à verser sur PEA : <b>{marge_pea_dispo:,.0f} €</b></div>
                </div>
                <div class="argon-card" style="border-top: 3px solid #f39c12;">
                    <div class="argon-title">💎 Rendement sur PRU (Yield on Cost)</div>
                    <div class="argon-val" style="color:#f39c12;">{yoc_global:.2f}%</div>
                    <div class="argon-sub">Rendement marché : <b>{rdt_marche_global:.2f}%</b> ({bonus_yoc_global:+.2f}% grâce à vos PRU)</div>
                </div>
            </div>
            """)

            if alertes_surpond:
                badges_sp_html = " ".join(
                    f"<span class='b-orange' style='margin-right:6px; padding:3px 8px;'><b>{n_s}</b> : {p_s:.1f}% ({v_s:,.0f} €)</span>"
                    for n_s, p_s, v_s in alertes_surpond
                )
                afficher_html(f"""
                <div style="background:rgba(243,156,18,0.08); border-left:4px solid #f39c12; padding:10px 14px; border-radius:8px; margin-bottom:14px; font-size:0.88em;">
                    ⚖️ <b>Règle Prudentielle de Concentration (Seuil 20%) :</b> {len(alertes_surpond)} ligne(s) dépasse(nt) 20% de votre portefeuille actions :
                    <div style="margin-top:6px;">{badges_sp_html}</div>
                </div>
                """)

            with st.expander("💎 Ouvrir la Matrice du Rendement sur PRU (Yield on Cost & Années d'Amortissement)", expanded=True):
                if mode_gratuit:
                    afficher_verrou_saas(
                        "Matrice Yield on Cost & Années d'Amortissement",
                        "⚡ Offre Premium (4,90 €/mois) ou 👑 Pro (8,90 €/mois)",
                        "Visualisez votre rendement réel par rapport à votre prix d'achat initial (Yield on Cost)."
                    )
                else:
                    st.caption("Le **Yield on Cost (Rendement sur PRU)** mesure le rendement réel que vous procure chaque action par rapport au prix auquel VOUS l'avez achetée.")
                    html_yoc = "<table class='r-table'><thead><tr><th style='text-align:left;'>Action</th><th>Enveloppe</th><th>Votre PRU</th><th>Cours Actuel</th><th>Dividende / An</th><th>Rdt Marché</th><th>💎 Rdt sur PRU (YoC)</th><th>Bonus PRU</th><th>Rente Annuelle</th><th>Remboursé en</th></tr></thead><tbody>"

                    for item_y in sorted(lignes_yoc_details, key=lambda x: x["yoc"], reverse=True):
                        c_bonus = "#2ecc71" if item_y["bonus_yoc"] >= 0 else "#f39c12"
                        b_yoc = "b-green" if item_y["yoc"] >= 4.5 else ("b-blue" if item_y["yoc"] >= 2.5 else "b-orange")
                        txt_payback = f"{item_y['payback']:.1f} ans" if item_y["payback"] > 0 else "—"
                        badge_env = "<span class='b-blue'>PEA (€)</span>" if "PEA" in item_y["enveloppe"] else "<span class='b-orange'>CTO ($)</span>"

                        html_yoc += f"""
                        <tr>
                            <td class='r-name'>{item_y['nom']} <span style='font-size:0.78em; opacity:0.65;'>(x{item_y['qte']})</span></td>
                            <td>{badge_env}</td>
                            <td><b>{item_y['pru']:.2f} {item_y['dev_sym']}</b></td>
                            <td>{item_y['cours']:.2f} {item_y['dev_sym']}</td>
                            <td>{item_y['div_unitaire']:.2f} {item_y['dev_sym']}</td>
                            <td>{item_y['rdt_marche']:.2f}%</td>
                            <td><span class='{b_yoc}' style='font-weight:900;'>💎 {item_y['yoc']:.2f}%</span></td>
                            <td style='color:{c_bonus}; font-weight:800;'>{item_y['bonus_yoc']:+.2f}%</td>
                            <td style='color:#2ecc71; font-weight:800;'>{item_y['rente_eur']:,.2f} €</td>
                            <td style='font-size:0.85em; opacity:0.85;'>⏳ {txt_payback}</td>
                        </tr>
                        """
                    html_yoc += "</tbody></table>"
                    afficher_html(html_yoc)

            with st.expander("⚔️ Duel de Performance : Mon Stock-Picking (Total Return) vs ETF MSCI World (CW8) & CAC 40", expanded=True):
                if not est_pro_max:
                    afficher_verrou_saas(
                        "Duel de Performance : Stock-Picking vs ETF MSCI World (CW8) & CAC 40",
                        "👑 Offre Pro (8,90 €/mois)",
                        "Comparez votre performance globale réelle (Total Return : PV + Rente) face aux grands indices passifs."
                    )
                else:
                    st.caption(
                        "Comparaison sur la MÊME période d'1 an glissant : évolution du cours de vos lignes actuelles sur 1 an "
                        "+ leurs dividendes annuels, face aux indices sur 1 an. Le CW8 capitalise ses dividendes ; "
                        "le CAC 40 et le S&P 500 sont affichés hors dividendes."
                    )

                    # Performance 1 an des lignes ACTUELLES (mêmes quantités qu'aujourd'hui, hors espèces et hors ventes passées),
                    # calculée comme celle des indices : cours d'il y a 252 séances -> cours actuel.
                    val_actuelle_duel = 0.0
                    val_il_y_a_1an_duel = 0.0
                    rente_duel = 0.0
                    lignes_hors_duel = []
                    for l_duel in lignes_yoc_details:
                        cl_duel = hist_prix_pack.get(l_duel["nom"]) or []
                        if len(cl_duel) >= 30 and float(cl_duel[-1]) > 0:
                            idx_deb_duel = max(0, len(cl_duel) - min(252, len(cl_duel)))
                            ratio_duel = float(cl_duel[idx_deb_duel]) / float(cl_duel[-1])
                            val_actuelle_duel += l_duel["val_eur"]
                            val_il_y_a_1an_duel += l_duel["val_eur"] * ratio_duel
                            rente_duel += l_duel["rente_eur"]
                        else:
                            lignes_hors_duel.append(l_duel["nom"])

                    gain_total_return_eur = (val_actuelle_duel - val_il_y_a_1an_duel) + rente_duel
                    cap_base_total = max(1.0, val_il_y_a_1an_duel)
                    perf_user_tot_pct = (gain_total_return_eur / cap_base_total) * 100.0 if val_il_y_a_1an_duel > 0 else 0.0
                    if lignes_hors_duel:
                        st.caption("ℹ️ Lignes exclues du duel (historique de cours indisponible) : " + ", ".join(lignes_hors_duel) + ".")

                    def _perf_1an_indice(sym_idx):
                        """Performance 1 an de l'indice, ou None si son historique est indisponible (aucun chiffre inventé)."""
                        try:
                            _, cl_i, _, _ = recuperer_donnees(sym_idx)
                            if cl_i and len(cl_i) >= 30:
                                idx_deb = max(0, len(cl_i) - min(252, len(cl_i)))
                                p_deb = float(cl_i[idx_deb])
                                p_fin = float(cl_i[-1])
                                if p_deb > 0:
                                    return ((p_fin - p_deb) / p_deb) * 100.0
                        except Exception:
                            pass
                        return None

                    perf_cw8_1a = _perf_1an_indice("CW8.PA")
                    perf_cac_1a = _perf_1an_indice("^FCHI")
                    perf_sp500_1a = _perf_1an_indice("^GSPC")

                    def _txt_pct(val, nb_dec=2):
                        return f"{val:+.{nb_dec}f}%" if val is not None else "Indisponible"

                    def _txt_gain_simule(val):
                        return f"Simulé sur votre capital : <b>{cap_base_total * val / 100.0:+,.0f} €</b>" if val is not None else "Historique de l'indice indisponible"

                    alpha_vs_cw8 = (perf_user_tot_pct - perf_cw8_1a) if perf_cw8_1a is not None else None
                    alpha_vs_cac = (perf_user_tot_pct - perf_cac_1a) if perf_cac_1a is not None else None

                    c_user_duel = "#2ecc71" if perf_user_tot_pct >= 0 else "#e74c3c"
                    c_alpha_cw8 = "#95a5a6" if alpha_vs_cw8 is None else ("#2ecc71" if alpha_vs_cw8 >= 0 else "#f39c12")
                    c_alpha_cac = "#95a5a6" if alpha_vs_cac is None else ("#2ecc71" if alpha_vs_cac >= 0 else "#f39c12")
                    txt_alpha_cw8 = f"{alpha_vs_cw8:+.2f}% vs CW8" if alpha_vs_cw8 is not None else "Indisponible"
                    txt_alpha_cac = f"{alpha_vs_cac:+.2f}% vs CAC 40" if alpha_vs_cac is not None else "CAC 40 indisponible"

                    afficher_html(f"""
                    <div class="argon-grid" style="margin-top:6px;">
                        <div class="argon-card" style="border-top: 3px solid {c_user_duel};">
                            <div class="argon-title">🏆 Vos Lignes Actuelles (1 An, dividendes inclus)</div>
                            <div class="argon-val" style="color:{c_user_duel};">{perf_user_tot_pct:+.2f}%</div>
                            <div class="argon-sub">Gain 1 an (cours + rente) : <b>{gain_total_return_eur:+,.0f} €</b></div>
                        </div>
                        <div class="argon-card" style="border-top: 3px solid #3498db;">
                            <div class="argon-title">🌍 ETF MSCI World (CW8.PA - 1 An)</div>
                            <div class="argon-val" style="color:#3498db;">{_txt_pct(perf_cw8_1a)}</div>
                            <div class="argon-sub">{_txt_gain_simule(perf_cw8_1a)}</div>
                        </div>
                        <div class="argon-card" style="border-top: 3px solid #9b59b6;">
                            <div class="argon-title">🇫🇷 Indice CAC 40 (1 An, hors dividendes)</div>
                            <div class="argon-val" style="color:#9b59b6;">{_txt_pct(perf_cac_1a)}</div>
                            <div class="argon-sub">{_txt_gain_simule(perf_cac_1a)}</div>
                        </div>
                        <div class="argon-card" style="border-top: 3px solid {c_alpha_cw8};">
                            <div class="argon-title">⚡ Votre Alpha (Surperformance)</div>
                            <div class="argon-val" style="color:{c_alpha_cw8}; font-size:1.18em;">{txt_alpha_cw8}</div>
                            <div class="argon-sub">Et <b style="color:{c_alpha_cac};">{txt_alpha_cac}</b> (S&P 500 : {_txt_pct(perf_sp500_1a, 1)})</div>
                        </div>
                    </div>
                    """)

    # --------------------------------------------------------------------------
    # 3. ONGLET 3 : RADAR DES PROCHAINS DÉTACHEMENTS EN TIROIR (EXCLUSIF PRO 8,90 €)
    # --------------------------------------------------------------------------
    if _tab_dividendes is not None:
        with _tab_dividendes:
            st.markdown("---")
            with st.expander("⏳ Ouvrir le Radar des Prochains Détachements (90 jours) & Simulateur « Boost de Coupon DCA »", expanded=False):
                if not est_pro_max:
                    afficher_verrou_saas(
                        "Radar des Prochains Détachements (90J) & Simulateur Boost de Coupon DCA",
                        "👑 Offre Pro (8,90 €/mois)",
                        "Repérez les dividendes imminents à 90 jours sur vos lignes et calculez le gain immédiat de coupon si vous y allouez votre DCA."
                    )
                else:
                    st.caption("Repérez les dividendes imminents à 90 jours et calculez le gain immédiat de coupon si vous y allouez votre enveloppe DCA avant le détachement.")

                    mois_actuel_num = datetime.now().month
                    noms_mois_fr = {
                        1: "Janvier", 2: "Février", 3: "Mars", 4: "Avril",
                        5: "Mai", 6: "Juin", 7: "Juillet", 8: "Août",
                        9: "Septembre", 10: "Octobre", 11: "Novembre", 12: "Décembre",
                    }
                    fenetre_90j = [
                        mois_actuel_num,
                        (mois_actuel_num % 12) + 1,
                        ((mois_actuel_num + 1) % 12) + 1,
                        ((mois_actuel_num + 2) % 12) + 1,
                    ]
                    noms_fenetre = [noms_mois_fr[m] for m in fenetre_90j[:3]]

                    toutes_actions_div = sorted(list(set(list(WATCHLIST_DEFAUT.keys()) + list(wl_complet_pack.keys()))))
                    detachements_proches = []

                    for nom_d in toutes_actions_div:
                        if nom_d in CLES_TECHNIQUES_PF:
                            continue

                        inf_base_d = wl_complet_pack.get(nom_d, WATCHLIST_DEFAUT.get(nom_d, {}))
                        cours_def_d = float(inf_base_d.get("prix_cible", 50.0)) if isinstance(inf_base_d, dict) else 50.0
                        cours_d = float(prix_tr_pack.get(nom_d, cours_def_d))

                        inf_d, div_tot_d, mois_list_d = _extraire_infos_div_et_mois(nom_d, cours_d)
                        if div_tot_d <= 0:
                            continue

                        mois_imminents = [m for m in mois_list_d if m in fenetre_90j]
                        if mois_imminents:
                            nb_v_d = max(1, len(mois_list_d))
                            coupon_unitaire_d = div_tot_d / nb_v_d
                            dev_d = "$" if inf_d.get("devise") == "USD" else "€"
                            fact_d = (1.0 / TAUX_USD_EUR) if dev_d == "$" else 1.0
                            cours_eur_d = max(0.01, cours_d * fact_d)

                            qte_det_d = int(pf_pack.get(nom_d, {}).get("qte", 0)) if isinstance(pf_pack.get(nom_d), dict) else 0
                            coupon_deja_acquis = qte_det_d * coupon_unitaire_d * len(mois_imminents) * fact_d
                            nb_titres_dca = max(1, int(budget_dca_pack // cours_eur_d)) if budget_dca_pack >= cours_eur_d else 0
                            boost_coupon_imm = nb_titres_dca * coupon_unitaire_d * fact_d
                            boost_rente_annuelle = nb_titres_dca * div_tot_d * fact_d
                            rdt_coupon_seul = (coupon_unitaire_d / cours_d * 100.0) if cours_d > 0 else 0.0

                            dist_mois = min((m - mois_actuel_num) % 12 for m in mois_imminents)

                            detachements_proches.append({
                                "nom": nom_d,
                                "dist": dist_mois,
                                "mois_txt": ", ".join(noms_mois_fr[m] for m in sorted(mois_imminents, key=lambda x: (x - mois_actuel_num) % 12)),
                                "en_pf": qte_det_d > 0,
                                "qte_pf": qte_det_d,
                                "cours": cours_d,
                                "dev": dev_d,
                                "coupon_unit": coupon_unitaire_d,
                                "rdt_coupon": rdt_coupon_seul,
                                "acquis_eur": coupon_deja_acquis,
                                "nb_dca": nb_titres_dca,
                                "boost_imm_eur": boost_coupon_imm,
                                "boost_an_eur": boost_rente_annuelle,
                            })

                    detachements_proches.sort(key=lambda x: (not x["en_pf"], x["dist"], -x["boost_imm_eur"]))

                    if not detachements_proches:
                        st.info(f"Aucun détachement détecté sur la période {', '.join(noms_fenetre)}.")
                    else:
                        total_acquis_fenetre = sum(d["acquis_eur"] for d in detachements_proches)
                        meilleur_boost = max(detachements_proches, key=lambda x: x["boost_imm_eur"])

                        afficher_html(f"""
                        <div class="meteo-bar" style="margin-bottom: 14px;">
                            <div class="meteo-item" style="border-left-color:#2ecc71;">
                               <div>
                                    <div style="font-size:0.74em; font-weight:800; opacity:0.75;">🗓️ RADAR DE DÉTACHEMENTS (90 JOURS GLISSANTS)</div>
                                    <div style="font-size:0.98em; font-weight:900;">{' • '.join(noms_fenetre)} ({len(detachements_proches)} valeur(s) détectée(s))</div>
                                </div>
                            </div>
                            <div class="meteo-item" style="border-left-color:#3498db;">
                                <div>
                                    <div style="font-size:0.74em; font-weight:800; opacity:0.75;">💶 COUPONS DÉJÀ ACQUIS (MON PORTEFEUILLE)</div>
                                    <div style="font-size:1.02em; font-weight:900; color:#2ecc71;">+{total_acquis_fenetre:,.2f} € attendus</div>
                                </div>
                            </div>
                            <div class="meteo-item" style="border-left-color:#f39c12;">
                                <div>
                                    <div style="font-size:0.74em; font-weight:800; opacity:0.75;">🚀 MEILLEUR BOOST DCA ({budget_dca_pack:,.0f} €)</div>
                                    <div style="font-size:0.95em; font-weight:900; color:#f39c12;">{meilleur_boost['nom']} : +{meilleur_boost['boost_imm_eur']:,.2f} € dès ce détachement</div>
                                </div>
                            </div>
                        </div>
                        """)

                        html_boost = f"<table class='r-table'><thead><tr><th style='text-align:left;'>Action</th><th>Mois Détachement</th><th>Statut</th><th>Coupon Unitaire</th><th>Coupon Déjà Acquis</th><th>Renfort DCA ({budget_dca_pack:,.0f} €)</th><th>⚡ Boost Coupon Immédiat</th><th>Boost Rente / An</th></tr></thead><tbody>"
                        for d_b in detachements_proches:
                            badge_pf_b = f"<span class='b-green'>💼 {d_b['qte_pf']} titre(s)</span>" if d_b["en_pf"] else "<span class='b-blue'>🔍 Radar</span>"
                            html_boost += f"""
                            <tr>
                                <td class='r-name'>{d_b['nom']} <span style='font-size:0.78em; opacity:0.65;'>({d_b['cours']:.2f} {d_b['dev']})</span></td>
                                <td>📅 <b>{d_b['mois_txt']}</b></td>
                                <td>{badge_pf_b}</td>
                                <td><b>{d_b['coupon_unit']:.2f} {d_b['dev']}</b> <span style='font-size:0.8em; opacity:0.7;'>({d_b['rdt_coupon']:.2f}%)</span></td>
                                <td style='color:#2ecc71; font-weight:800;'>+{d_b['acquis_eur']:,.2f} €</td>
                                <td><b>+{d_b['nb_dca']} action(s)</b></td>
                                <td><span class='b-orange' style='font-weight:900;'>⚡ +{d_b['boost_imm_eur']:,.2f} €</span></td>
                                <td style='color:#3498db; font-weight:800;'>+{d_b['boost_an_eur']:,.2f} € / an</td>
                            </tr>
                            """
                        html_boost += "</tbody></table>"
                        afficher_html(html_boost)

    # --------------------------------------------------------------------------
    # 4. ONGLET 1 : BANDEAU D'OPPORTUNITÉS IMMÉDIATES & STATION GRAPHIQUE 360° (EXCLUSIF PRO 8,90 €)
    # --------------------------------------------------------------------------
    with onglet_radar:
        map_t1_sg = {d["NomBrut"]: d for d in liste_t1_pack if isinstance(d, dict) and "NomBrut" in d}
        opportunites_cibles = []

        for nom_op, inf_op in wl_pack.items():
            if nom_op in CLES_TECHNIQUES_PF or not isinstance(inf_op, dict):
                continue
            cible_op = float(inf_op.get("prix_cible", 0.0))
            dev_op = "$" if inf_op.get("devise") == "USD" else "€"
            cours_op = float(prix_tr_pack.get(nom_op, 0.0))
            sc_op = int(map_t1_sg.get(nom_op, {}).get("Score", 50))

            if cours_op > 0 and cible_op > 0:
                ecart_cible_pct = ((cours_op - cible_op) / cible_op) * 100.0
                if ecart_cible_pct <= 0:
                    opportunites_cibles.append(
                        f"<span class='cal-pill' style='border-left:3px solid #2ecc71;'>"
                        f"🎯 <b>{nom_op}</b> ({cours_op:.2f} {dev_op}) : <b style='color:#2ecc71;'>{ecart_cible_pct:+.1f}% sous cible ({cible_op:.0f} {dev_op})</b> • Score {sc_op}/100</span>"
                    )
                elif ecart_cible_pct <= 2.5:
                    opportunites_cibles.append(
                        f"<span class='cal-pill' style='border-left:3px solid #3498db;'>"
                        f"⏳ <b>{nom_op}</b> ({cours_op:.2f} {dev_op}) : <b style='color:#3498db;'>à {ecart_cible_pct:+.1f}% de la cible ({cible_op:.0f} {dev_op})</b></span>"
                    )

        html_pills_opp = (
            "".join(opportunites_cibles[:8])
            if opportunites_cibles
            else "<span style='font-size:0.85em; opacity:0.7;'>Aucune valeur sous son prix cible aujourd'hui — discipline & patience !</span>"
        )

        html_alerte_20_radar = ""
        if alertes_surpond:
            txt_sp_court = ", ".join(f"<b>{n_s} ({p_s:.0f}%)</b>" for n_s, p_s, _ in alertes_surpond[:3])
            html_alerte_20_radar = (
                f"<div style='margin-top:6px; font-size:0.82em; color:#f39c12;'>"
                f"⚖️ <b>Vigilance Concentration (>20%) :</b> {txt_sp_court} — ces lignes pèsent déjà lourd dans le portefeuille."
                f"</div>"
            )

        afficher_html(f"""
        <div class="argon-card" style="border-left: 4px solid #2ecc71; margin-top: 14px; margin-bottom: 10px; padding: 12px 16px;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
                <span style="font-size:0.82em; font-weight:800; text-transform:uppercase; color:#2ecc71;">
                    🔔 RADAR DES PRIX CIBLES (ATTEINTS & PROCHES)
                </span>
                <span class="b-green" style="font-size:0.75em;">{len(opportunites_cibles)} signal(aux) actif(s)</span>
            </div>
            <div>{html_pills_opp}</div>
            {html_alerte_20_radar}
        </div>
        """)

        with st.expander("📈 Ouvrir la Station Graphique Interactive 360° (Canal 3A, EMA 2/12, Supports & TradingView)", expanded=False):
            if not est_pro_max:
                afficher_verrou_saas(
                    "Station Graphique Interactive 360° & Terminal TradingView",
                    "👑 Offre Pro (8,90 €/mois)",
                    "Visualisez les canaux de régression 3 ans, les croisements EMA 2/12 et le terminal technique avancé."
                )
            else:
                st.caption("Sélectionnez n'importe quelle valeur de votre radar pour visualiser ses courbes EMA 2/12, son couloir de régression linéaire à 3 ans, ses supports/résistances 30J et votre PRU.")

                col_sg_filtre, col_sg_act, col_sg_hor, col_sg_mode = st.columns([1.3, 2.0, 1.3, 1.6])

                with col_sg_filtre:
                    filtre_station = st.selectbox(
                        "Filtrer la liste :",
                        ["🌐 Tout le Radar", "💼 Mon Portefeuille", "🔥 Top Scores (≥ 60)", "🎯 Prix Cibles Atteints"],
                        key="sg360_filtre_liste",
                    )

                toutes_actions_sg = sorted([k for k in wl_complet_pack.keys() if k not in CLES_TECHNIQUES_PF])
                if not toutes_actions_sg:
                    toutes_actions_sg = sorted(list(WATCHLIST_DEFAUT.keys()))

                if filtre_station == "💼 Mon Portefeuille":
                    actions_dispo_sg = [
                        k for k in toutes_actions_sg
                        if k in pf_pack and isinstance(pf_pack.get(k), dict) and float(pf_pack[k].get("qte", 0)) > 0
                    ]
                elif filtre_station == "🔥 Top Scores (≥ 60)":
                    actions_dispo_sg = [k for k in toutes_actions_sg if int(map_t1_sg.get(k, {}).get("Score", 0)) >= 60]
                elif filtre_station == "🎯 Prix Cibles Atteints":
                    actions_dispo_sg = [
                        k for k in toutes_actions_sg
                        if float(prix_tr_pack.get(k, 999999)) <= float(wl_complet_pack.get(k, {}).get("prix_cible", 0)) * 1.02
                    ]
                else:
                    actions_dispo_sg = toutes_actions_sg

                if not actions_dispo_sg:
                    actions_dispo_sg = toutes_actions_sg

                labels_actions_sg = []
                map_label_vers_nom = {}
                for nom_a_sg in actions_dispo_sg:
                    sc_sg = map_t1_sg.get(nom_a_sg, {}).get("Score", 50)
                    pr_sg = map_t1_sg.get(nom_a_sg, {}).get("Prix", "")
                    lbl_sg = f"{nom_a_sg} — {pr_sg} (Score {sc_sg}/100)" if pr_sg else f"{nom_a_sg} (Score {sc_sg}/100)"
                    labels_actions_sg.append(lbl_sg)
                    map_label_vers_nom[lbl_sg] = nom_a_sg

                with col_sg_act:
                    choix_label_sg = st.selectbox("🎯 Action à analyser :", labels_actions_sg, key="sg360_choix_action")
                    action_sg = map_label_vers_nom.get(choix_label_sg, actions_dispo_sg[0])

                with col_sg_hor:
                    horizon_sg = st.selectbox(
                        "🕒 Horizon :",
                        ["3 Mois (65 séances)", "6 Mois (130 séances)", "1 An (252 séances)", "3 Ans (Canal complet)"],
                        index=1,
                        key="sg360_choix_horizon",
                    )

                with col_sg_mode:
                    moteur_sg = st.radio(
                        "Moteur d'affichage :",
                        ["📊 Boursy Quant", "🕯️ TradingView"],
                        horizontal=True,
                        key="sg360_choix_moteur",
                    )

                info_sg = wl_complet_pack.get(action_sg, WATCHLIST_DEFAUT.get(action_sg, {}))
                sym_sg = info_sg.get("symbole", "MC.PA")
                dev_sg = "$" if info_sg.get("devise") == "USD" else "€"
                cible_sg = float(info_sg.get("prix_cible", 100.0))

                pos_pf_sg = pf_pack.get(action_sg, {})
                en_pf_sg = isinstance(pos_pf_sg, dict) and float(pos_pf_sg.get("qte", 0)) > 0
                pru_sg = float(pos_pf_sg.get("pru", 0.0)) if en_pf_sg else 0.0
                qte_sg = int(pos_pf_sg.get("qte", 0)) if en_pf_sg else 0

                _, closes_sg_full, highs_sg_full, lows_sg_full = recuperer_donnees(sym_sg)
                if not closes_sg_full or len(closes_sg_full) < 20:
                    closes_sg_full = hist_prix_pack.get(action_sg, [cible_sg] * 60)
                    highs_sg_full = [c * 1.01 for c in closes_sg_full]
                    lows_sg_full = [c * 0.99 for c in closes_sg_full]

                arr_c_full = [float(x) for x in closes_sg_full]
                n_full = len(arr_c_full)

                if n_full >= 2:
                    moy_x = (n_full - 1) / 2.0
                    moy_y = sum(arr_c_full) / n_full
                    num_reg = sum((i - moy_x) * (arr_c_full[i] - moy_y) for i in range(n_full))
                    den_reg = sum((i - moy_x) ** 2 for i in range(n_full))
                    pente_3a = (num_reg / den_reg) if den_reg > 0 else 0.0
                    intercept_3a = moy_y - pente_3a * moy_x
                    droite_reg_full = [pente_3a * i + intercept_3a for i in range(n_full)]
                    variance_3a = sum((arr_c_full[i] - droite_reg_full[i]) ** 2 for i in range(n_full)) / n_full
                    ecart_type_3a = math.sqrt(max(0.0, variance_3a))
                else:
                    droite_reg_full = list(arr_c_full)
                    ecart_type_3a = float(arr_c_full[-1] * 0.05)

                canal_haut_full = [droite_reg_full[i] + ecart_type_3a for i in range(n_full)]
                canal_bas_full = [max(0.01, droite_reg_full[i] - ecart_type_3a) for i in range(n_full)]

                s_c_full = pd.Series(arr_c_full)
                ema_rapide_full = s_c_full.ewm(span=2, adjust=False).mean().tolist()
                ema_lente_full = s_c_full.ewm(span=12, adjust=False).mean().tolist()

                fenetre_sr = min(30, n_full)
                sup_30j_sg = float(min(lows_sg_full[-fenetre_sr:])) if lows_sg_full else float(min(arr_c_full[-fenetre_sr:]))
                res_30j_sg = float(max(highs_sg_full[-fenetre_sr:])) if highs_sg_full else float(max(arr_c_full[-fenetre_sr:]))
                cours_act_sg = float(arr_c_full[-1])
                fair_val_act = float(droite_reg_full[-1])
                ecart_fv_pct = ((cours_act_sg - fair_val_act) / fair_val_act * 100.0) if fair_val_act > 0 else 0.0

                amp_sr_sg = max(0.01, res_30j_sg - sup_30j_sg)
                pos_canal_30j = max(0.0, min(100.0, ((cours_act_sg - sup_30j_sg) / amp_sr_sg) * 100.0))
                signal_ema_sg = "🟢 Haussier (EMA 2 > 12)" if ema_rapide_full[-1] >= ema_lente_full[-1] else "🔴 Baissier (EMA 2 < 12)"
                c_ema_sg = "#2ecc71" if ema_rapide_full[-1] >= ema_lente_full[-1] else "#e74c3c"
                c_fv_sg = "#2ecc71" if ecart_fv_pct <= 0 else "#f39c12"

                txt_pru_card = (
                    f"<div class='argon-val' style='color:{'#2ecc71' if cours_act_sg >= pru_sg else '#3498db'};'>{pru_sg:.2f} {dev_sg}</div>"
                    f"<div class='argon-sub'>{qte_sg} titre(s) | Écart : {((cours_act_sg - pru_sg)/pru_sg*100):+.1f}%</div>"
                    if en_pf_sg and pru_sg > 0
                    else f"<div class='argon-val' style='color:#9b59b6;'>Hors PF</div><div class='argon-sub'>Cible : <b>{cible_sg:.2f} {dev_sg}</b></div>"
                )

                html_kpi_station = f"""
                <div class="argon-grid" style="margin-top: 6px; margin-bottom: 14px;">
                    <div class="argon-card" style="border-top: 3px solid #3498db;">
                        <div class="argon-title">🏷️ Cours Live ({sym_sg})</div>
                        <div class="argon-val">{cours_act_sg:.2f} {dev_sg}</div>
                        <div class="argon-sub">Objectif Cible : <b>{cible_sg:.2f} {dev_sg}</b></div>
                    </div>
                    <div class="argon-card" style="border-top: 3px solid {c_ema_sg};">
                        <div class="argon-title">⚡ Croisement EMA 2 / 12</div>
                        <div class="argon-val" style="color:{c_ema_sg}; font-size:1.15em;">{ema_rapide_full[-1]:.2f} / {ema_lente_full[-1]:.2f}</div>
                        <div class="argon-sub"><b>{signal_ema_sg}</b></div>
                    </div>
                    <div class="argon-card" style="border-top: 3px solid #2ecc71;">
                        <div class="argon-title">🟢 Support / 🔴 Résistance 30J</div>
                        <div class="argon-val" style="font-size:1.15em;"><span style="color:#2ecc71;">{sup_30j_sg:.2f}</span> — <span style="color:#e74c3c;">{res_30j_sg:.2f} {dev_sg}</span></div>
                        <div class="argon-sub">Position dans le couloir 30J : <b>{pos_canal_30j:.0f}%</b></div>
                    </div>
                    <div class="argon-card" style="border-top: 3px solid {c_fv_sg};">
                        <div class="argon-title">📐 Canal Régression 3 Ans</div>
                        <div class="argon-val" style="color:{c_fv_sg}; font-size:1.15em;">{ecart_fv_pct:+.1f}% vs Fair Value</div>
                        <div class="argon-sub">Tunnel : <b>{canal_bas_full[-1]:.1f}</b> ➔ <b>{canal_haut_full[-1]:.1f} {dev_sg}</b></div>
                    </div>
                    <div class="argon-card" style="border-top: 3px solid #9b59b6;">
                        <div class="argon-title">💼 Votre PRU / Cible</div>
                        {txt_pru_card}
                    </div>
                </div>
                """
                afficher_html(html_kpi_station)

                if "Boursy Quant" in moteur_sg:
                    col_chk1, col_chk2, col_chk3, col_chk4, col_chk5 = st.columns(5)
                    aff_canal_3a = col_chk1.checkbox("📐 Canal 3 Ans (±1σ)", value=True, key="chk_sg360_c3a")
                    aff_ema = col_chk2.checkbox("⚡ Courbes EMA 2 & 12", value=True, key="chk_sg360_ema")
                    aff_sr30 = col_chk3.checkbox("🟢/🔴 Support & Résist. 30J", value=True, key="chk_sg360_sr")
                    aff_cible = col_chk4.checkbox("🎯 Prix Cible", value=True, key="chk_sg360_cib")
                    aff_pru = col_chk5.checkbox("💼 Mon PRU", value=en_pf_sg, disabled=not en_pf_sg, key="chk_sg360_pru")

                    map_nb_j_sg = {
                        "3 Mois (65 séances)": 65,
                        "6 Mois (130 séances)": 130,
                        "1 An (252 séances)": 252,
                        "3 Ans (Canal complet)": n_full,
                    }
                    nb_j_sg = min(n_full, map_nb_j_sg.get(horizon_sg, 130))
                    pas_sg = 2 if nb_j_sg > 350 else 1

                    dates_sg = pd.bdate_range(end=datetime.now(), periods=nb_j_sg)
                    lignes_vega_sg = []

                    for i_s in range(0, nb_j_sg, pas_sg):
                        idx_f = n_full - nb_j_sg + i_s
                        d_iso = dates_sg[i_s].strftime("%Y-%m-%d")
                        d_fr = dates_sg[i_s].strftime("%d/%m/%Y")

                        row_sg = {
                            "Date": d_iso,
                            "DateFR": d_fr,
                            "Cours": round(float(arr_c_full[idx_f]), 2),
                            "EMA_2": round(float(ema_rapide_full[idx_f]), 2),
                            "EMA_12": round(float(ema_lente_full[idx_f]), 2),
                            "FairValue_3A": round(float(droite_reg_full[idx_f]), 2),
                            "Canal_Haut": round(float(canal_haut_full[idx_f]), 2),
                            "Canal_Bas": round(float(canal_bas_full[idx_f]), 2),
                            "Support_30J": round(sup_30j_sg, 2),
                            "Resistance_30J": round(res_30j_sg, 2),
                            "Prix_Cible": round(cible_sg, 2),
                        }
                        if en_pf_sg and pru_sg > 0:
                            row_sg["Mon_PRU"] = round(pru_sg, 2)
                        lignes_vega_sg.append(row_sg)

                    df_sg = pd.DataFrame(lignes_vega_sg)
                    layers_sg = []

                    if aff_canal_3a:
                        layers_sg.append({
                            "mark": {"type": "area", "opacity": 0.13, "color": "#3498db"},
                            "encoding": {
                                "x": {"field": "Date", "type": "temporal"},
                                "y": {"field": "Canal_Bas", "type": "quantitative"},
                                "y2": {"field": "Canal_Haut"},
                            },
                        })
                        layers_sg.append({
                            "mark": {"type": "line", "strokeDash": [6, 4], "strokeWidth": 1.6, "color": "#3498db", "opacity": 0.8},
                            "encoding": {
                                "x": {"field": "Date", "type": "temporal"},
                                "y": {"field": "FairValue_3A", "type": "quantitative"},
                            },
                        })

                    if aff_sr30:
                        layers_sg.append({
                            "mark": {"type": "rule", "strokeDash": [4, 4], "strokeWidth": 1.8, "color": "#2ecc71"},
                            "encoding": {"y": {"field": "Support_30J", "type": "quantitative"}},
                        })
                        layers_sg.append({
                            "mark": {"type": "rule", "strokeDash": [4, 4], "strokeWidth": 1.8, "color": "#e74c3c"},
                            "encoding": {"y": {"field": "Resistance_30J", "type": "quantitative"}},
                        })

                    if aff_cible:
                        layers_sg.append({
                            "mark": {"type": "rule", "strokeDash": [2, 3], "strokeWidth": 1.8, "color": "#f39c12"},
                            "encoding": {"y": {"field": "Prix_Cible", "type": "quantitative"}},
                        })

                    if aff_pru and en_pf_sg and pru_sg > 0:
                        layers_sg.append({
                            "mark": {"type": "rule", "strokeWidth": 2.2, "color": "#9b59b6"},
                            "encoding": {"y": {"field": "Mon_PRU", "type": "quantitative"}},
                        })

                    if aff_ema:
                        layers_sg.append({
                            "mark": {"type": "line", "strokeWidth": 2.0, "color": "#f39c12", "opacity": 0.95},
                            "encoding": {
                                "x": {"field": "Date", "type": "temporal"},
                                "y": {"field": "EMA_2", "type": "quantitative"},
                            },
                        })
                        layers_sg.append({
                            "mark": {"type": "line", "strokeWidth": 2.2, "color": "#e67e22", "strokeDash": [3, 2], "opacity": 0.95},
                            "encoding": {
                                "x": {"field": "Date", "type": "temporal"},
                                "y": {"field": "EMA_12", "type": "quantitative"},
                            },
                        })

                    layers_sg.append({
                        "mark": {"type": "line", "strokeWidth": 2.8, "color": "#10b981"},
                        "encoding": {
                            "x": {"field": "Date", "type": "temporal", "axis": {"title": None, "format": "%b %Y", "grid": False}},
                            "y": {
                                "field": "Cours",
                                "type": "quantitative",
                                "scale": {"zero": False, "padding": 25},
                                "axis": {"title": f"Cours ({dev_sg})", "format": ",.1f"},
                            },
                            "tooltip": [
                                {"field": "DateFR", "type": "nominal", "title": "📅 Séance"},
                                {"field": "Cours", "type": "quantitative", "title": f"🏷️ Cours ({dev_sg})", "format": ",.2f"},
                                {"field": "EMA_2", "type": "quantitative", "title": "⚡ EMA Rapide (2)", "format": ",.2f"},
                                {"field": "EMA_12", "type": "quantitative", "title": "📈 EMA Lente (12)", "format": ",.2f"},
                                {"field": "FairValue_3A", "type": "quantitative", "title": "📐 Fair Value 3A", "format": ",.2f"},
                                {"field": "Support_30J", "type": "quantitative", "title": "🟢 Support 30J", "format": ",.2f"},
                                {"field": "Resistance_30J", "type": "quantitative", "title": "🔴 Résistance 30J", "format": ",.2f"},
                                {"field": "Prix_Cible", "type": "quantitative", "title": "🎯 Prix Cible", "format": ",.2f"},
                            ],
                        },
                    })

                    spec_station_vega = {
                        "height": 500,
                        "layer": layers_sg,
                        "view": {"stroke": None},
                    }
                    st.vega_lite_chart(df_sg, spec_station_vega, width="stretch")

                    afficher_html(f"""
                    <div style="display:flex; flex-wrap:wrap; gap:14px; justify-content:center; font-size:0.80em; padding:8px 12px; background:rgba(128,128,128,0.04); border-radius:8px; margin-top:-6px;">
                        <span><b style="color:#10b981;">━━</b> Cours ({cours_act_sg:.2f} {dev_sg})</span>
                        <span><b style="color:#f39c12;">━━</b> EMA Rapide 2J ({ema_rapide_full[-1]:.2f})</span>
                        <span><b style="color:#e67e22;">╍╍</b> EMA Lente 12J ({ema_lente_full[-1]:.2f})</span>
                        <span><b style="color:#3498db;">▒▒</b> Canal Régression 3A ({canal_bas_full[-1]:.1f} - {canal_haut_full[-1]:.1f})</span>
                        <span><b style="color:#2ecc71;">┈┈</b> Support 30J ({sup_30j_sg:.2f})</span>
                        <span><b style="color:#e74c3c;">┈┈</b> Résistance 30J ({res_30j_sg:.2f})</span>
                        <span><b style="color:#f39c12;">┈┈</b> Cible ({cible_sg:.2f})</span>
                        {f'<span><b style="color:#9b59b6;">━━</b> Mon PRU ({pru_sg:.2f} {dev_sg})</span>' if (en_pf_sg and pru_sg > 0) else ''}
                    </div>
                    """)

                else:
                    import streamlit.components.v1 as components

                    sym_up = sym_sg.upper().strip()
                    if sym_up.endswith(".PA") or sym_up.endswith(".AS") or sym_up.endswith(".BR") or sym_up.endswith(".LS"):
                        tv_symbol = "EURONEXT:" + sym_up.split(".")[0]
                    elif sym_up.endswith(".DE"):
                        tv_symbol = "XETR:" + sym_up.split(".")[0]
                    elif sym_up.endswith(".MI"):
                        tv_symbol = "MIL:" + sym_up.split(".")[0]
                    elif sym_up.endswith(".MC"):
                        tv_symbol = "BME:" + sym_up.split(".")[0]
                    elif sym_up.endswith(".L"):
                        tv_symbol = "LSE:" + sym_up.split(".")[0]
                    else:
                        tv_symbol = sym_up.split(".")[0]

                    tv_html = f"""
                    <div class="tradingview-widget-container" style="border-radius:12px; overflow:hidden; border:1px solid rgba(128,128,128,0.2);">
                      <div id="tv_chart_boursy" style="height:520px;"></div>
                      <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
                      <script type="text/javascript">
                      new TradingView.widget({{
                        "autosize": true,
                        "symbol": "{tv_symbol}",
                        "interval": "D",
                        "timezone": "Europe/Paris",
                        "theme": "dark",
                        "style": "1",
                        "locale": "fr",
                        "toolbar_bg": "#0f172a",
                        "enable_publishing": false,
                        "withdateranges": true,
                        "hide_side_toolbar": false,
                        "allow_symbol_change": true,
                        "studies": [
                          "Moving Average@tv-basicstudies",
                          "Moving Average@tv-basicstudies",
                          "RSI@tv-basicstudies",
                          "MACD@tv-basicstudies"
                        ],
                        "container_id": "tv_chart_boursy"
                      }});
                      </script>
                    </div>
                    """
                    components.html(tv_html, height=535)
                    st.caption(nombres_fr(f"💡 Terminal TradingView synchronisé sur **{tv_symbol}** avec indicateurs pré-chargés. Repères Boursy : Support 30J = **{sup_30j_sg:.2f} {dev_sg}** | Résistance 30J = **{res_30j_sg:.2f} {dev_sg}** | Cible = **{cible_sg:.2f} {dev_sg}**."))

