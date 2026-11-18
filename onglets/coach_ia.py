"""
Onglet 4 de Boursy : coach et audits IA (Google Gemini, ou moteur local si Gemini n'est pas disponible), synthèse
flash du portefeuille et matrice des opportunités. Les audits de la rente reprennent la solidité des dividendes, la
diversification et la projection prudente (mêmes calculs que les onglets Radar et Calendrier, étude des dividendes).

Toutes les informations venues du reste de l'application sont des paramètres nommés d'afficher() :
leur liste est la liste exacte des dépendances de l'onglet (vérifiée par tests/test_application.py).
"""
from datetime import datetime
import json
import re
import urllib.parse

import streamlit as st

from diversification_rente import SEUIL_LIGNE, SEUIL_SECTEUR, lignes_de_rente, phrase_crise, repartition_rente
from habillage import afficher_html, markdown_fr
from solidite_dividendes import (
    EVOLUTION_REVENU, TAUX_MESURES, bilan_rente, categorie_projection, projeter_rente, rendement_median_solides,
)


def afficher(
    *,
    BUDGET_MENSUEL,
    CLES_TECHNIQUES_PF,
    TAUX_USD_EUR,
    WATCHLIST_DEFAUT,
    _lire_secret,
    achats_dca,
    afficher_verrou_saas,
    allocation_personnalisee,
    analyse_solidite_dividendes,
    budget_courant,
    cac_str,
    candidats_tries,
    cout_total_achat,
    dividendes_bruts_totaux_eur,
    dividendes_nets_totaux_eur,
    donnees_t1,
    donnees_t2,
    donnees_t3,
    donnees_t4,
    est_pro_max,
    etat_vix,
    exposition_eur,
    exposition_usd,
    libelle_allocation_dca,
    lignes_triees,
    mode_gratuit,
    montant_investi_dca,
    montant_tot_div_dca,
    niveau_acces,
    plus_value_pct,
    portefeuille_utilisateur,
    prix_temps_reel,
    quota_ia_max,
    repartition_secteurs,
    sauvegarder_dans_cloud,
    sp_str,
    valeur_totale_portefeuille,
    vix_val,
):
    st.subheader("🤖 Coach & Audit IA 2.0 (Diagnostic Instantané & Intelligence Gemini)")

    quota_utilise = int(st.session_state.get("quota_ia_utilise", 0))
    quota_restant = max(0, quota_ia_max - quota_utilise)

    nb_lignes_actions = sum(
        1 for k, v in portefeuille_utilisateur.items()
        if k not in CLES_TECHNIQUES_PF and isinstance(v, dict) and float(v.get("qte", 0)) > 0 and k in WATCHLIST_DEFAUT
    )
    poids_max_ligne = 0.0
    nom_max_ligne = "Aucune"
    if valeur_totale_portefeuille > 0 and lignes_triees:
        for l_it in lignes_triees:
            if not l_it["est_especes"]:
                p_it = (l_it["val_eur"] / valeur_totale_portefeuille) * 100.0
                if p_it > poids_max_ligne:
                    poids_max_ligne = p_it
                    nom_max_ligne = l_it["nom_act"]

    note_sante_pf = min(100, max(20, int(40 + min(30, nb_lignes_actions * 5) + (20 if poids_max_ligne <= 30 else 5) + (10 if len(repartition_secteurs) >= 3 else 0))))
    taux_couverture_dca = (dividendes_bruts_totaux_eur / (BUDGET_MENSUEL * 12) * 100.0) if BUDGET_MENSUEL > 0 else 0.0

    html_ia_header = f"""
    <div class="argon-grid">
        <div class="argon-card">
            <div class="argon-title">🩺 Score de Santé Portefeuille</div>
            <div class="argon-val" style="color:#2ecc71;">{note_sante_pf} / 100</div>
            <div class="argon-sub">{nb_lignes_actions} ligne(s) | {len(repartition_secteurs)} secteur(s)</div>
        </div>
        <div class="argon-card">
            <div class="argon-title">⚖️ Ligne Principale (Concentration)</div>
            <div class="argon-val" style="color:{'#2ecc71' if poids_max_ligne <= 30 else '#f39c12'};">{poids_max_ligne:.1f}%</div>
            <div class="argon-sub">Plus forte position : <b>{nom_max_ligne}</b></div>
        </div>
        <div class="argon-card">
            <div class="argon-title">🔄 Autonomie Financière DCA</div>
            <div class="argon-val" style="color:#3498db;">{taux_couverture_dca:.1f}%</div>
            <div class="argon-sub">Part du DCA annuel financée par vos dividendes</div>
        </div>
        <div class="argon-card">
            <div class="argon-title">⚡ Crédits d'Audit IA du Jour</div>
            <div class="argon-val" style="color:#9b59b6;">{quota_restant} / {quota_ia_max}</div>
            <div class="argon-sub">Forfait actif : <b>{niveau_acces.upper()}</b> | VIX : {vix_val:.1f}</div>
        </div>
    </div>
    """
    afficher_html(html_ia_header)

    top_opps_noms = [f"<b>{c['nom']}</b> ({c['score']}/100)" for c in candidats_tries[:2]]
    texte_opps_moment = " et ".join(top_opps_noms) if top_opps_noms else "aucune valeur en signal fort actuellement"
    etat_conc_court = "bien équilibré" if poids_max_ligne <= 30 else f"concentré sur <b>{nom_max_ligne}</b> ({poids_max_ligne:.1f}%)"

    # --- SYNTHÈSE DES PLUS-VALUES ACTÉES POUR LE COACH IA ---
    hist_ventes_ia = st.session_state.get("historique_ventes", []) if est_pro_max else []
    total_pv_actee_ia = sum(float(v.get("plus_value_eur", 0.0)) for v in hist_ventes_ia)
    total_vol_vendu_ia = sum(float(v.get("montant_eur", 0.0)) for v in hist_ventes_ia)
    total_cout_vendu_ia = total_vol_vendu_ia - total_pv_actee_ia
    perf_extraction_ia = (total_pv_actee_ia / total_cout_vendu_ia * 100.0) if total_cout_vendu_ia > 0 else 0.0
    nb_ventes_gagnantes_ia = sum(1 for v in hist_ventes_ia if float(v.get("plus_value_eur", 0.0)) >= 0)
    texte_bilan_ventes_flash = (
        f" Vos arbitrages ont permis d'acter <b>{total_pv_actee_ia:+,.2f} €</b> de plus-values réelles "
        f"(performance d'extraction de <b>{perf_extraction_ia:+.2f}%</b> sur {len(hist_ventes_ia)} vente(s))."
        if hist_ventes_ia else ""
    )

    html_phrase_flash = f"""
    <div class="ia-flash">
        💡 <b>Synthèse Flash du Coach :</b> Votre portefeuille actif de <b>{valeur_totale_portefeuille:,.0f} €</b> ({plus_value_pct:+.1f}% latent) est {etat_conc_court} et génère <b>{dividendes_nets_totaux_eur:,.0f} € net/an</b> ({dividendes_nets_totaux_eur/12.0:.1f} €/mois).{texte_bilan_ventes_flash} Les signaux techniques les plus forts du moment concernent {texte_opps_moment}.
    </div>
    """
    afficher_html(html_phrase_flash)

    # ==========================================================================
    # SYNTHÈSE CROISÉE 360° DES OPPORTUNITÉS DU MOMENT (RADAR + TECH + DIV + PF)
    # ==========================================================================
    map_t2_ia = {d["Actif"]: d for d in donnees_t2}
    map_t3_ia = {d["Actif"]: d for d in donnees_t3}
    map_t4_ia = {d["Actif"]: d for d in donnees_t4}

    synthese_opportunites = []
    for d1 in donnees_t1:
        clef_actif = d1["Actif"]
        nom_b = d1["NomBrut"]
        d2 = map_t2_ia.get(clef_actif, {})
        d3 = map_t3_ia.get(clef_actif, {})
        d4 = map_t4_ia.get(clef_actif, {})

        info_w = WATCHLIST_DEFAUT.get(nom_b, {})
        devise_a = info_w.get("devise", "EUR")
        sym_d = "$" if devise_a == "USD" else "€"
        facteur_d = (1.0 / TAUX_USD_EUR) if devise_a == "USD" else 1.0

        try:
            prix_f = float(str(d1["Prix"]).split()[0])
        except Exception:
            prix_f = float(prix_temps_reel.get(nom_b, 50.0))

        try:
            sup_f = float(str(d4.get("Support 30J", f"{prix_f*0.95}")).split()[0])
            res_f = float(str(d4.get("Résistance 30J", f"{prix_f*1.05}")).split()[0])
        except Exception:
            sup_f, res_f = prix_f * 0.95, prix_f * 1.05

        amp_30 = max(0.01, res_f - sup_f)
        pos_canal_30 = max(0.0, min(100.0, ((prix_f - sup_f) / amp_30) * 100.0))
        stoch_f = float(d1.get("Stoch", 50.0))
        score_timing_ct = int(round(100.0 - (0.55 * pos_canal_30 + 0.45 * stoch_f)))
        score_timing_ct = max(10, min(98, score_timing_ct))

        ecart_3a = float(d2.get("EcartNum", 0.0))
        try:
            rend_f = float(str(d3.get("Rendement", "3.0%")).replace("%", "").strip())
        except Exception:
            rend_f = 3.0
        try:
            payout_f = float(str(d3.get("Payout", "55%")).replace("%", "").strip())
        except Exception:
            payout_f = 55.0

        pos_pf = portefeuille_utilisateur.get(nom_b)
        bonus_pf = 0
        est_sous_pru = False
        if pos_pf and isinstance(pos_pf, dict) and float(pos_pf.get("qte", 0)) > 0:
            q_pf = int(pos_pf["qte"])
            pru_pf = float(pos_pf["pru"])
            val_l_eur = q_pf * prix_f * facteur_d
            poids_pf = (val_l_eur / valeur_totale_portefeuille * 100.0) if valeur_totale_portefeuille > 0 else 0.0
            ecart_pru_pct = ((prix_f - pru_pf) / pru_pf * 100.0) if pru_pf > 0 else 0.0

            if prix_f < pru_pf and poids_pf < 25.0:
                est_sous_pru = True
                bonus_pf = 8
                badge_pf = f"<span class='b-green'>📉 Sous votre PRU ({pru_pf:.2f} {sym_d} | {ecart_pru_pct:+.1f}%)</span>"
                conseil_pf = f"Cours sous votre PRU (poids actuel : {poids_pf:.1f}%)"
            elif poids_pf >= 28.0:
                bonus_pf = -12
                badge_pf = f"<span class='b-yellow'>⚖️ Ligne forte ({poids_pf:.1f}% du PF)</span>"
                conseil_pf = f"PRU : {pru_pf:.2f} {sym_d} — ligne déjà importante dans le portefeuille"
            else:
                bonus_pf = 4
                badge_pf = f"<span class='b-blue'>💼 En portefeuille ({q_pf} act. | {poids_pf:.1f}%)</span>"
                conseil_pf = f"PRU : {pru_pf:.2f} {sym_d} ({ecart_pru_pct:+.1f}%)"
        else:
            bonus_pf = 6
            badge_pf = "<span class='b-purple'>✨ Absente du portefeuille</span>"
            conseil_pf = "Valeur absente du portefeuille"

        pts_radar = float(d1["Score"]) * 0.40
        pts_timing = float(score_timing_ct) * 0.25
        pts_value = (20.0 if ecart_3a <= -10 else (15.0 if ecart_3a < 0 else (8.0 if ecart_3a <= 5 else 2.0)))
        pts_div = min(15.0, (rend_f * 1.8) + (5.0 if payout_f <= 65 else 1.5))
        score_conv = int(round(min(99.0, max(12.0, pts_radar + pts_timing + pts_value + pts_div + bonus_pf))))

        ordre_limite_ideal = max(sup_f, min(prix_f, sup_f + 0.25 * amp_30))

        synthese_opportunites.append({
            "Nom": nom_b,
            "Actif": clef_actif,
            "Prix": d1["Prix"],
            "Cible": d1["Prix Cible"],
            "EcartCible": d1["Écart Cible (%)"],
            "ScoreRadar": d1["Score"],
            "ScoreTiming": score_timing_ct,
            "ScoreConv": score_conv,
            "RSI": d1["RSI"],
            "Stoch": int(stoch_f),
            "Ecart3A": d2.get("Écart %", "0.0%"),
            "Ecart3ANum": ecart_3a,
            "StatutValue": d2.get("Statut Value", "Neutre"),
            "Rendement": d3.get("Rendement", "N/A"),
            "RendNum": rend_f,
            "Payout": d3.get("Payout", "N/A"),
            "PayoutNum": payout_f,
            "Support": d4.get("Support 30J", "N/A"),
            "OrdreLimite": f"{ordre_limite_ideal:.2f} {sym_d}",
            "BadgePF": badge_pf,
            "ConseilPF": conseil_pf,
            "EstSousPRU": est_sous_pru,
            "EnPortefeuille": bool(pos_pf and isinstance(pos_pf, dict) and float(pos_pf.get("qte", 0)) > 0),
        })

    synthese_opportunites.sort(key=lambda x: x["ScoreConv"], reverse=True)

    st.markdown("#### 🎯 Radar de Convergence 360° : les Signaux les Plus Convergents")
    st.caption("Croisement automatique en temps réel entre vos **4 Tableaux Techniques/Fondamentaux** et **les lignes de votre Portefeuille**.")

    if synthese_opportunites:
        top_podium = synthese_opportunites[:3]
        medailles = ["🥇 CONVERGENCE #1", "🥈 CONVERGENCE #2", "🥉 CONVERGENCE #3"]
        couleurs_bord = ["#2ecc71", "#3498db", "#9b59b6"]

        html_podium = "<div class='argon-grid'>"
        for idx_p, opp in enumerate(top_podium):
            c_b = couleurs_bord[idx_p]
            b_val_c = "b-green" if opp["Ecart3ANum"] < 0 else "b-neutral"
            b_tim_c = "b-green" if opp["ScoreTiming"] >= 65 else ("b-blue" if opp["ScoreTiming"] >= 48 else "b-yellow")

            nom_o = opp["Nom"]
            pos_p = portefeuille_utilisateur.get(nom_o)
            conseil_pru_dynamique = opp["ConseilPF"]

            if pos_p and isinstance(pos_p, dict) and float(pos_p.get("qte", 0)) > 0:
                q_actuelle = float(pos_p["qte"])
                pru_actuel = float(pos_p["pru"])
                try:
                    prix_act_f = float(str(opp["Prix"]).split()[0])
                except Exception:
                    prix_act_f = pru_actuel

                nouveau_pru_simule = ((q_actuelle * pru_actuel) + (1 * prix_act_f)) / (q_actuelle + 1)
                sym_dev_p = "$" if "$" in opp["Prix"] else "€"

                if prix_act_f < pru_actuel:
                    conseil_pru_dynamique = f"Simulation : 1 titre de plus ferait passer votre PRU de <b>{pru_actuel:.2f} ➔ {nouveau_pru_simule:.2f} {sym_dev_p}</b>"
                else:
                    conseil_pru_dynamique = f"Cours au-dessus de votre PRU ({pru_actuel:.2f} {sym_dev_p})"

            html_podium += f"""
            <div class="argon-card" style="text-align:left; border-top: 4px solid {c_b}; min-width: 260px;">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
                    <span style="font-size:0.75em; font-weight:900; color:{c_b}; letter-spacing:0.6px;">{medailles[idx_p]}</span>
                    <span class="b-green" style="font-size:0.82em;">Convergence : {opp['ScoreConv']}/100</span>
                </div>
                <div style="font-size:1.22em; font-weight:900; margin-bottom:4px;">{opp['Actif']} — <span style="color:{c_b};">{opp['Prix']}</span></div>
                <div style="font-size:0.80em; opacity:0.85; margin-bottom:10px;">🎯 Objectif Cible : <b>{opp['Cible']}</b> ({opp['EcartCible']})</div>
                <div style="display:flex; flex-wrap:wrap; gap:5px; margin-bottom:10px;">
                    <span class="b-blue" style="font-size:0.76em;">📊 Radar : {opp['ScoreRadar']}/100 (RSI {opp['RSI']})</span>
                    <span class="{b_val_c}" style="font-size:0.76em;">📐 Canal 3A : {opp['Ecart3A']}</span>
                    <span class="{b_tim_c}" style="font-size:0.76em;">⚡ Timing 30J : {opp['ScoreTiming']}/100</span>
                    <span class="b-green" style="font-size:0.76em;">💰 Div : {opp['Rendement']} (Payout {opp['Payout']})</span>
                </div>
                <div style="background:rgba(128,128,128,0.06); border-radius:8px; padding:8px 10px; font-size:0.82em; line-height:1.45;">
                    <div style="margin-bottom:4px;">{opp['BadgePF']}</div>
                    <div>💡 {conseil_pru_dynamique}</div>
                    <div style="margin-top:4px; color:#2ecc71; font-weight:700;">📏 Niveau technique de référence : {opp['OrdreLimite']} (Support : {opp['Support']})</div>
                </div>
            </div>
            """
        html_podium += "</div>"
        afficher_html(html_podium)

        opp_moyennage = next((x for x in synthese_opportunites if x["EstSousPRU"]), None)
        opp_value_timing = sorted(synthese_opportunites, key=lambda x: (x["Ecart3ANum"] - x["ScoreTiming"] * 0.3))[0]
        opp_rendement = sorted([x for x in synthese_opportunites if x["PayoutNum"] <= 75], key=lambda x: x["RendNum"], reverse=True)
        opp_rend_top = opp_rendement[0] if opp_rendement else synthese_opportunites[0]
        opp_decouverte = next((x for x in synthese_opportunites if not x["EnPortefeuille"]), synthese_opportunites[0])

        txt_moy = f"<b>{opp_moyennage['Nom']}</b> (Cours {opp_moyennage['Prix']} sous votre PRU)" if opp_moyennage else "Toutes vos lignes sont au-dessus de leur PRU 🎉"

        html_boussole = f"""
        <div class="meteo-bar" style="margin-top: -6px; margin-bottom: 18px;">
            <div class="meteo-item" style="border-left-color:#2ecc71;">
                <div><div style="font-size:0.72em; font-weight:800; opacity:0.75;">📉 COURS SOUS VOTRE PRU</div><div style="font-size:0.90em; margin-top:2px;">{txt_moy}</div></div>
            </div>
            <div class="meteo-item" style="border-left-color:#3498db;">
                <div><div style="font-size:0.72em; font-weight:800; opacity:0.75;">📐 TOP DÉCOTE + TIMING</div><div style="font-size:0.90em; margin-top:2px;"><b>{opp_value_timing['Nom']}</b> (3A : {opp_value_timing['Ecart3A']} | Timing {opp_value_timing['ScoreTiming']}/100)</div></div>
            </div>
            <div class="meteo-item" style="border-left-color:#f39c12;">
                <div><div style="font-size:0.72em; font-weight:800; opacity:0.75;">👑 RENDEMENT LE PLUS ÉLEVÉ (PAYOUT ≤ 75 %)</div><div style="font-size:0.90em; margin-top:2px;"><b>{opp_rend_top['Nom']}</b> ({opp_rend_top['Rendement']} | Payout {opp_rend_top['Payout']})</div></div>
            </div>
            <div class="meteo-item" style="border-left-color:#9b59b6;">
                <div><div style="font-size:0.72em; font-weight:800; opacity:0.75;">🌱 MEILLEURE CONVERGENCE HORS PORTEFEUILLE</div><div style="font-size:0.90em; margin-top:2px;"><b>{opp_decouverte['Nom']}</b> (Convergence {opp_decouverte['ScoreConv']}/100)</div></div>
            </div>
        </div>
        """
        afficher_html(html_boussole)

        with st.expander("📊 Voir la Matrice Complète de Convergence 360° (Toutes vos actions classées)", expanded=False):
            if mode_gratuit:
                afficher_verrou_saas(
                    "Matrice Complète de Convergence 360° (Ensemble du Catalogue)",
                    "⚡ Offre Premium (4,90 €/mois) ou 👑 Pro (8,90 €/mois)",
                    "Débloquez le classement croisé intégral sur toutes vos actions PEA et US."
                )
            else:
                html_mat = """
                <table class='r-table'>
                <thead>
                    <tr>
                        <th>Rang</th>
                        <th style='text-align:left;'>Actif</th>
                        <th>Score Convergence</th>
                        <th>Radar (/100)</th>
                        <th>Canal 3 Ans</th>
                        <th>Timing 30J</th>
                        <th>Dividende (Payout)</th>
                        <th>Statut Portefeuille</th>
                        <th>Niveau Technique</th>
                    </tr>
                </thead>
                <tbody>
                """
                for idx_m, om in enumerate(synthese_opportunites, start=1):
                    c_conv = "#2ecc71" if om["ScoreConv"] >= 70 else ("#3498db" if om["ScoreConv"] >= 55 else "#f39c12")
                    html_mat += f"""
                    <tr>
                        <td><b>#{idx_m}</b></td>
                        <td class='r-name'>{om['Actif']}<br><span style='font-size:0.80em; opacity:0.75;'>Cours : {om['Prix']}</span></td>
                        <td>
                            <div style='font-weight:900; color:{c_conv};'>{om['ScoreConv']} / 100</div>
                            <div class='score-bg'><div style='width:{om['ScoreConv']}%; background:{c_conv}; height:100%;'></div></div>
                        </td>
                        <td><b>{om['ScoreRadar']}</b> (RSI {om['RSI']})</td>
                        <td>{om['Ecart3A']}</td>
                        <td>{om['ScoreTiming']}/100 (Stoch {om['Stoch']}%)</td>
                        <td><b style='color:#2ecc71;'>{om['Rendement']}</b> ({om['Payout']})</td>
                        <td>{om['BadgePF']}</td>
                        <td><span class='b-green'>{om['OrdreLimite']}</span></td>
                    </tr>
                    """
                html_mat += "</tbody></table>"
                afficher_html(html_mat)

    @st.cache_data(ttl=3600)
    def lister_modeles_gemini_actifs(cle_api):
        modeles = []
        try:
            url_list = f"https://generativelanguage.googleapis.com/v1beta/models?key={urllib.parse.quote(cle_api)}"
            req_list = urllib.request.Request(url_list, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req_list, timeout=8) as resp_l:
                data_l = json.loads(resp_l.read().decode("utf-8"))
                for m_info in data_l.get("models", []):
                    methodes = m_info.get("supportedGenerationMethods", [])
                    nom_m = m_info.get("name", "").replace("models/", "")
                    if "generateContent" in methodes and "gemini" in nom_m:
                        modeles.append(nom_m)
        except Exception:
            pass
        return modeles

    # ==========================================================================
    # RENTE : SOLIDITÉ, DIVERSIFICATION ET PROJECTION PRUDENTE (étude des dividendes)
    # ==========================================================================
    acces_rente = niveau_acces in ("premium", "pro")
    MOTS_RENTE = ("rente", "dividende", "solid", "diversif", "projection", "crise", "secteur", "retenue")

    def audit_sur_la_rente(question_utilisateur, code_audit):
        return code_audit in ("AUDIT_1", "AUDIT_4", "AUDIT_5") or any(m in (question_utilisateur or "").lower() for m in MOTS_RENTE)

    def contexte_rente(calculer=False):
        """
        Mêmes calculs que les onglets Radar et Calendrier : lignes de rente, diversification et, si l'analyse du
        catalogue est disponible (calculer=True la lance), solidité, rente en cas de crise et projection prudente.
        """
        lignes = lignes_de_rente(portefeuille_utilisateur, WATCHLIST_DEFAUT, TAUX_USD_EUR,
                                 [l["nom_act"] for l in lignes_triees if not l["est_especes"]])
        contexte = {"lignes": lignes, "repartition": repartition_rente(lignes), "solidite": None}
        if not acces_rente:
            return contexte
        try:
            analyse = analyse_solidite_dividendes(sorted({sym for _, sym, _, _ in lignes if sym}), calculer=calculer)
        except Exception:
            analyse = None
        if analyse:
            def categorie(symbole):
                return categorie_projection((analyse["demandes"].get(symbole) or (None, None))[1])

            lignes_categories = [(nom, revenu, categorie(sym)) for nom, sym, _secteur, revenu in lignes]
            rendement = rendement_median_solides(analyse["catalogue"].values())
            contexte["solidite"] = bilan_rente(lignes_categories, rendement_achats=rendement,
                                               apport_annuel=12.0 * BUDGET_MENSUEL, horizon=10)
            contexte["rente_20_ans"] = projeter_rente([(r, c) for _, r, c in lignes_categories], 12.0 * BUDGET_MENSUEL,
                                                      rendement, reinvestir=True, annees=20)[-1][1]
            contexte["annee"] = analyse["annee"]
        return contexte

    def _eur(x):
        return f"{x:,.0f}".replace(",", " ") + " €"

    def _pc(x):
        return f"{x * 100:.0f} %"

    def bloc_rente_md(contexte):
        """Solidité, diversification et projection prudente, en Markdown (moteur local)."""
        if not acces_rente:
            return ("#### 🛡️ Solidité, diversification et projection de votre rente\n"
                    "- 🔒 Réservées aux offres **Premium (4,90 €/mois)** et **Pro (8,90 €/mois)** : part de votre rente issue "
                    "de dividendes solides, lignes à surveiller, rente en cas de crise, répartition par secteur et par pays, "
                    "et projection prudente à 10 et 20 ans.")
        repartition, solidite = contexte["repartition"], contexte["solidite"]
        morceaux = ["#### 🛡️ Solidité de votre rente (étude des dividendes de Boursy)"]
        if solidite and solidite["rente"] > 0:
            rente, parts = solidite["rente"], solidite["parts"]
            morceaux.append(
                f"- Sur **{_eur(rente)}** de dividendes attendus par an : **{_eur(parts['solide'])} solides "
                f"({_pc(parts['solide'] / rente)})**, {_eur(parts['neutre'])} neutres ou non classés, "
                f"**{_eur(parts['alerte'])} à surveiller ({_pc(parts['alerte'] / rente)})**."
            )
            if solidite["a_surveiller"]:
                morceaux.append(
                    f"- **À surveiller** (rendement élevé ou anormal) : {', '.join(solidite['a_surveiller'])}. Dans l'étude, "
                    f"{_pc(TAUX_MESURES['rendement_eleve'][0])} des rendements les plus élevés ont baissé leur dividende dans les "
                    f"3 années suivantes, contre {_pc(TAUX_MESURES['solide'][0])} des dividendes solides."
                )
            morceaux.append(
                f"- **L'année d'une crise comme 2020** (pire année mesurée) : environ **{_eur(solidite['rente_crise'])}** au "
                f"lieu de {_eur(rente)}. Les dividendes ne sont pas à l'abri des crises : en 2020, la moitié des actions du "
                "catalogue ont baissé ou suspendu le leur."
            )
        elif solidite is None:
            morceaux.append("- Solidité indisponible pour le moment (historiques Yahoo Finance) : réessayez dans quelques minutes.")
        else:
            morceaux.append("- Aucun dividende attendu sur vos lignes actuelles : la rente viendra de vos prochains achats.")

        morceaux.append("\n#### 🧩 Diversification de votre rente")
        if repartition["rente"] > 0:
            principaux = ", ".join(f"{secteur} ({_pc(part)})" for secteur, _m, part in repartition["par_secteur"][:4])
            morceaux.append(f"- **Par grand secteur** : {principaux}.")
            for secteur, _m, part in repartition["secteurs_trop_lourds"]:
                morceaux.append(f"- ⚠️ **{secteur}** : {_pc(part)} de votre rente, au-dessus du repère de "
                                f"{_pc(SEUIL_SECTEUR)} par secteur.{phrase_crise(secteur)}")
            if repartition["lignes_trop_lourdes"]:
                morceaux.append(f"- ⚠️ **Lignes au-dessus de {_pc(SEUIL_LIGNE)} de la rente** : "
                                + ", ".join(f"{nom} ({_pc(part)})" for nom, _m, part in repartition["lignes_trop_lourdes"]) + ".")
            if not repartition["secteurs_trop_lourds"] and not repartition["lignes_trop_lourdes"]:
                morceaux.append(f"- ✅ Aucun secteur au-dessus de {_pc(SEUIL_SECTEUR)} de la rente, aucune ligne au-dessus de "
                                f"{_pc(SEUIL_LIGNE)}.")
            if repartition["retenues"]:
                morceaux.append(f"- **Retenues à la source étrangères** (non récupérables dans un PEA) : environ "
                                f"{_eur(repartition['retenue_totale'])} par an ("
                                + ", ".join(f"{r['nom']}, {r['pays']}" for r in repartition["retenues"]) + ").")
            if repartition["hors_pea"]:
                morceaux.append("- **Hors PEA** (siège hors Union européenne) : "
                                + ", ".join(f"{nom} ({pays})" for nom, pays in repartition["hors_pea"]) + ".")
        else:
            morceaux.append("- Rien à répartir : aucun dividende attendu sur vos lignes.")

        if solidite:
            morceaux.append("\n#### 📈 Projection prudente (en euros d'aujourd'hui)")
            morceaux.append(
                f"- Avec votre achat mensuel de **{_eur(BUDGET_MENSUEL)}** et les dividendes réinvestis, placés en dividendes "
                f"solides au rendement médian actuel de la liste ({solidite['rendement_achats'] * 100:.1f} %) : environ "
                f"**{_eur(solidite['rente_prudente_horizon'])} par an dans 10 ans** et **{_eur(contexte['rente_20_ans'])} par an "
                "dans 20 ans**, sans aucune croissance réelle des dividendes."
            )
            morceaux.append(
                f"- Pourquoi prudente : les dividendes solides du catalogue ont progressé de "
                f"{(EVOLUTION_REVENU['solide'][10][0] ** 0.1 - 1) * 100:.1f} % par an sur 10 ans, mais ce chiffre est gonflé "
                "(catalogue d'entreprises qui existent encore, rattrapage d'après 2009). Ce sont vos apports réguliers qui font "
                "l'essentiel de la rente future."
            )
        return "\n".join(morceaux)

    def bloc_rente_prompt(contexte):
        """Les mêmes informations, en texte brut, pour Gemini."""
        if not acces_rente:
            return "Solidité, diversification et projection de la rente : réservées aux offres Premium et Pro (ne pas les inventer)."
        repartition, solidite = contexte["repartition"], contexte["solidite"]
        lignes = [
            "Répartition de la rente par grand secteur : "
            + (", ".join(f"{s} {_pc(p)}" for s, _m, p in repartition["par_secteur"]) or "aucun dividende attendu"),
            "Secteurs au-dessus du repère de 30 % de la rente : "
            + (", ".join(f"{s} ({_pc(p)})" for s, _m, p in repartition["secteurs_trop_lourds"]) or "aucun"),
            "Lignes au-dessus de 20 % de la rente : "
            + (", ".join(f"{n} ({_pc(p)})" for n, _m, p in repartition["lignes_trop_lourdes"]) or "aucune"),
            f"Retenues à la source étrangères non récupérables en PEA : environ {_eur(repartition['retenue_totale'])} par an ; "
            "hors PEA : " + (", ".join(f"{n} ({p})" for n, p in repartition["hors_pea"]) or "aucune ligne"),
        ]
        if solidite:
            parts = solidite["parts"]
            lignes += [
                f"Solidité de la rente : {_eur(parts['solide'])} solides, {_eur(parts['neutre'])} neutres ou non classés, "
                f"{_eur(parts['alerte'])} à surveiller ; lignes à surveiller : {', '.join(solidite['a_surveiller']) or 'aucune'}",
                f"Rente l'année d'une crise comme 2020 : environ {_eur(solidite['rente_crise'])} au lieu de {_eur(solidite['rente'])}",
                f"Projection prudente (euros d'aujourd'hui, achat mensuel de {_eur(BUDGET_MENSUEL)}, dividendes réinvestis au "
                f"rendement médian des solides de {solidite['rendement_achats'] * 100:.1f} %, sans croissance réelle) : "
                f"{_eur(solidite['rente_prudente_horizon'])} par an dans 10 ans, {_eur(contexte['rente_20_ans'])} dans 20 ans",
            ]
        lignes.append(
            "Résultats de l'étude des dividendes de Boursy, à respecter : les dividendes « solides » (5 ans sans baisse, plus "
            "élevés qu'il y a 5 ans, rendement non extrême) ont baissé dans 22 % des cas en 3 ans, contre 43 % pour les autres ; "
            "les 20 % de rendements les plus élevés ont baissé dans 58 % des cas ; le rendement total des solides n'est pas "
            "meilleur de façon démontrée ; en 2020, la moitié des actions ont baissé ou suspendu leur dividende (100 % dans "
            "l'automobile et l'aéronautique, 63 % dans la finance, 20 % dans la santé). Ne présente jamais un rendement élevé "
            "comme une qualité en soi, ni la rente comme insensible aux crises."
        )
        return "\n".join("- " + l for l in lignes)

    def generer_audit_expert_hybride(question_utilisateur, code_audit=""):
        if question_utilisateur:
            for s_a, a_a in [
                ("opportunite", "opportunité"), ("strategie", "stratégie"),
                ("securite", "sécurité"), ("equilibre", "équilibre"),
                ("repartition", "répartition"), ("sante", "santé"),
                ("impot", "impôt"), ("fiscalite", "fiscalité"),
            ]:
                # Mots entiers uniquement : « puissante » ou « croissante » ne doivent pas devenir « puissanté »
                question_utilisateur = re.sub(rf"\b{s_a}(s?)\b", rf"{a_a}\1", question_utilisateur)
                question_utilisateur = re.sub(rf"\b{s_a.capitalize()}(s?)\b", rf"{a_a.capitalize()}\1", question_utilisateur)

        plus_value_glob = valeur_totale_portefeuille - cout_total_achat
        pv_pct_glob = (plus_value_glob / cout_total_achat * 100) if cout_total_achat > 0 else 0.0
        rente_mens_nette = dividendes_nets_totaux_eur / 12.0
        rente_ctx = contexte_rente(calculer=audit_sur_la_rente(question_utilisateur, code_audit))

        top_3_lignes = [
            f"**{l['nom_act']}** ({l['val_eur']:,.0f} €, soit {(l['val_eur']/valeur_totale_portefeuille*100 if valeur_totale_portefeuille>0 else 0):.1f}% du portefeuille, PV : `{l['pv_eur']:+,.0f} €`)"
            for l in lignes_triees if not l["est_especes"]
        ][:3]
        top_3_radar = [
            f"**{d['Actif']}** (Score `{d['Score']}/100` — {d['Décision']}, Cours : {d['Prix']}, Cible : {d['Prix Cible']}, RSI : {d['RSI']})"
            for d in sorted(donnees_t1, key=lambda x: x["Score"], reverse=True)[:3]
        ]

        if hist_ventes_ia:
            lignes_v_recap = "\n".join(
                f"* **{v['date']} — {v['action']}** (x{v['qte']}) : Vendu à **{v['prix_vente']:.2f} {v['devise']}** vs PRU **{v['pru']:.2f} {v['devise']}** ➔ Plus/Moins-Value actée : **`{v['plus_value_eur']:+,.2f} € ({v['perf_pct']:+.2f}%)`**"
                for v in hist_ventes_ia[:10]
            )
            bloc_recap_pv_md = f"""#### 💰 Bilan de vos Arbitrages & Plus/Moins-Values Actées (Réalisées)
- **Total Plus/Moins-Values Nettes Actées :** **`{total_pv_actee_ia:+,.2f} €`** extraits sur **{len(hist_ventes_ia)} arbitrage(s)**.
- **Performance d'Extraction Réelle :** **`{perf_extraction_ia:+.2f}%`** (calculée sur **{total_cout_vendu_ia:,.2f} €** de capital initial vendu, pour **{total_vol_vendu_ia:,.2f} €** encaissés net).
- **Taux de Réussite (Win Rate) :** **{nb_ventes_gagnantes_ia} vente(s) gagnante(s) sur {len(hist_ventes_ia)}** ({(nb_ventes_gagnantes_ia/len(hist_ventes_ia)*100):.0f}% de réussite).
- **Dernières opérations actées :**
{lignes_v_recap}"""
        else:
            bloc_recap_pv_md = """#### 💰 Bilan de vos Arbitrages & Plus/Moins-Values Actées (Réalisées)
- *Aucune vente actée active (ou module Arbitrages réservé à l'offre Pro 8,90 €/mois).*"""

        if code_audit == "AUDIT_1":
            return f"""### 🔍 Audit Complet 360°, Plus-Values Actées & Optimisation Fiscale

#### 1. Bilan Patrimonial & Performance Globale
- **Valorisation Active :** Votre portefeuille s'élève à **{valeur_totale_portefeuille:,.2f} €** pour un capital investi de **{cout_total_achat:,.2f} €**, soit une performance latente de **{plus_value_glob:+,.2f} € ({pv_pct_glob:+.2f}%)**.
- **Score de Santé Global :** **{note_sante_pf}/100** avec **{nb_lignes_actions} ligne(s) active(s)** répartie(s) sur **{len(repartition_secteurs)} secteur(s)**.
- **Vos Piliers Principaux :** {', '.join(top_3_lignes) if top_3_lignes else 'Aucune ligne enregistrée'}.

{bloc_recap_pv_md}

#### 3. Analyse de Concentration & PRU
- **Concentration Maximale :** Votre première ligne (**{nom_max_ligne}**) pèse **{poids_max_ligne:.1f}%** de votre patrimoine. {'✅ Excellente maîtrise du risque (< 30%).' if poids_max_ligne <= 30 else '⚠️ Attention : cette ligne dépasse le seuil prudentiel de 30%. Une répartition plus homogène réduirait la dépendance à cette seule ligne.'}

#### 4. Bilan Fiscal PEA (EUR) vs CTO (USD)
- **Exposition Devises :** **{exposition_eur:,.0f} € en zone Euro (PEA)** contre **{exposition_usd:,.0f} € en Dollars US (CTO)**.
- **Efficience Fiscale des Dividendes :** Vos actions produisent **{dividendes_bruts_totaux_eur:,.2f} € brut/an**, soit **{dividendes_nets_totaux_eur:,.2f} € net/an ({rente_mens_nette:.2f} € net/mois)**.

{bloc_rente_md(rente_ctx)}

*⚖️ Rappel : Analyse statistique et pédagogique générée par le moteur Boursy 2.0 (Non-CIF).*"""

        elif code_audit == "AUDIT_2":
            achats_txt = "\n".join(
                f"* **{l['nom']} ({l['devise']})** : **{l['qte']} action(s)** à `{l['prix_eur']:.2f} €`, poids {l['poids_actuel']:.1f} % → cible {l['poids_cible']:.1f} % (gain de rente : **+{l['qte'] * l['div_eur']:.2f} €/an**)"
                for l in achats_dca
            )
            if not achats_txt:
                achats_txt = "* Aucune ligne n'est en retard sur sa cible, ou aucun cours n'est disponible : l'enveloppe reste en liquidités ce mois-ci."
            return f"""### 🛒 Achat DCA du Mois ({BUDGET_MENSUEL:.0f} €) : allocation cible, VIX & RSI

#### 1. Lecture de la Météo des Marchés
- **Indice de nervosité VIX :** **{vix_val:.1f}** ({etat_vix}) | **CAC 40 :** {cac_str} | **S&P 500 :** {sp_str}.
- **Contexte de marché :** {'Le VIX est élevé : la nervosité domine le marché, et ces phases s’accompagnent souvent de cours plus bas sur de nombreuses valeurs.' if vix_val >= 22 else 'Le marché est calme à normal.'}

#### 2. Top 3 des Signaux Techniques du Jour
{chr(10).join('* ' + s for s in top_3_radar)}

*Ces signaux ne servent pas au calcul de l’achat : sur environ 7 ans et 120 actions, ils n’ont pas fait mieux, de façon démontrée, que les autres actions du même mois.*

#### 3. Achat du Mois : {libelle_allocation_dca.lower()}
{achats_txt}
- **Total investi ce mois-ci :** **{montant_investi_dca:.2f} €** (Liquidités restantes : **{budget_courant:.2f} €**)
- **Nouveaux dividendes annuels acquis :** **+{montant_tot_div_dca:.2f} € / an**.

*⚖️ Rappel : Analyse statistique et pédagogique générée par le moteur Boursy 2.0 (Non-CIF).*"""

        elif code_audit == "AUDIT_3":
            return f"""### 🌍 Arbitrage Stratégique : PEA (EUR) vs Actions US ($)

#### 1. Analyse du Taux de Change EUR/USD
- **Parité actuelle :** **1 € = {TAUX_USD_EUR:.4f} $** (soit **1 $ = {1/TAUX_USD_EUR:.4f} €**).
- **Impact Devises :** {'L’euro est au-dessus de 1,08 $ : les actifs cotés en dollars coûtent moins cher en euros qu’avec un euro plus faible.' if TAUX_USD_EUR >= 1.08 else 'Le dollar est fort face à l’euro : les actifs cotés en dollars coûtent plus cher en euros.'}

#### 2. Complémentarité Rendement Européen (PEA) vs Croissance US (CTO)
- **Poche Socle PEA (valeurs européennes) :** Dividendes réinvestis **sans frottement fiscal** dans l'enveloppe, et sans retenue à la source pour les sociétés françaises. Privilégiez la solidité au rendement : dans l'étude des dividendes de Boursy, les 20 % de rendements les plus élevés ont baissé leur dividende dans **58 %** des cas en 3 ans, contre **22 %** pour les dividendes solides (volet « Solidité des dividendes » du Radar).
- **Poche Accélérateur US (Microsoft, Apple, Realty Income, Coca-Cola...) :** Apporte une **croissance séculaire** et des versements trimestriels ou mensuels qui lissent votre calendrier de rente.

*⚖️ Rappel : Analyse statistique et pédagogique générée par le moteur Boursy 2.0 (Non-CIF).*"""

        elif code_audit == "AUDIT_4":
            choc_20 = valeur_totale_portefeuille * 0.80
            return f"""### 🛡️ Stress-Test, Gestion des Risques & Diversification

#### 1. Simulation de Krach Boursier (-20 % sur les marchés)
- **Valorisation après choc de -20 % :** Votre portefeuille passerait temporairement de **{valeur_totale_portefeuille:,.0f} €** à **{choc_20:,.0f} €** (soit un repli latent de `-{valeur_totale_portefeuille * 0.20:,.0f} €`).
- **Votre rente de dividendes ({dividendes_bruts_totaux_eur:,.2f} €/an) n'est pas à l'abri :** dans l'étude des dividendes de Boursy, la moitié des actions du catalogue ont baissé ou suspendu leur dividende en 2020, et 41 % en 2009. Ce sont des secteurs entiers qui baissent ensemble : voir ci-dessous.

#### 2. Diagnostic de Concentration
- **Ligne numéro 1 :** **{nom_max_ligne}** représente **{poids_max_ligne:.1f}%** du portefeuille sur **{len(repartition_secteurs)} secteur(s)**.

{bloc_rente_md(rente_ctx)}

*⚖️ Rappel : Analyse statistique et pédagogique générée par le moteur Boursy 2.0 (Non-CIF).*"""

        elif code_audit == "AUDIT_5":
            manque_100 = max(0.0, (100.0 * 12) - dividendes_nets_totaux_eur)
            if rente_ctx["solidite"] and rente_ctx["solidite"]["rendement_achats"] > 0:
                rendement_ref = rente_ctx["solidite"]["rendement_achats"]
                libelle_rendement = "rendement médian actuel des dividendes solides du catalogue"
            else:
                rendement_ref = (dividendes_bruts_totaux_eur / valeur_totale_portefeuille) if valeur_totale_portefeuille > 0 and dividendes_bruts_totaux_eur > 0 else 0.035
                libelle_rendement = "rendement actuel de votre portefeuille" if valeur_totale_portefeuille > 0 and dividendes_bruts_totaux_eur > 0 else "rendement prudent"
            ratio_net = (dividendes_nets_totaux_eur / dividendes_bruts_totaux_eur) if dividendes_bruts_totaux_eur > 0 else 1.0
            cap_requis_100 = manque_100 / (rendement_ref * ratio_net) if rendement_ref > 0 else 0.0
            return f"""### 💵 Ma Rente : Solidité, Diversification & Projection Prudente

#### 1. Trajectoire Actuelle de vos Revenus Passifs
- **Rente Annuelle Actuelle :** **{dividendes_bruts_totaux_eur:,.2f} € brut / an** (**{dividendes_nets_totaux_eur:,.2f} € net / an**).
- **Revenu Mensuel Lissé :** **{rente_mens_nette:,.2f} € net / mois** (couvrant déjà **{taux_couverture_dca:.1f}%** de votre effort d'épargne DCA annuel).

{bloc_rente_md(rente_ctx)}

#### Feuille de Route vers le Palier des 100 € / mois (1 200 € / an)
- **Écart restant à combler :** Il vous manque **{manque_100:,.2f} € de dividendes nets annuels** pour franchir le cap des **100 € / mois**, soit environ **{cap_requis_100:,.0f} €** à investir au {libelle_rendement} (**{rendement_ref * 100:.1f} %**). Viser plus haut en rendement raccourcirait le chemin sur le papier, mais les rendements les plus élevés sont aussi ceux qui baissent le plus souvent.

*⚖️ Rappel : Analyse statistique et pédagogique générée par le moteur Boursy 2.0 (Non-CIF).*"""

        elif code_audit == "AUDIT_6":
            perf_globale_cumulee = plus_value_glob + total_pv_actee_ia
            return f"""### 💰 Audit Complet de vos Arbitrages & Plus/Moins-Values Actées

{bloc_recap_pv_md}

#### 📊 Comparaison Performance Latente vs Performance Actée
- **Plus/Moins-Value Latente (Portefeuille actif) :** **`{plus_value_glob:+,.2f} € ({pv_pct_glob:+.2f}%)`**
- **Plus/Moins-Value Réalisée (Extraite par vos ventes) :** **`{total_pv_actee_ia:+,.2f} € ({perf_extraction_ia:+.2f}%)`**
- **Création de Valeur Totale Cumulée (Latent + Acté) :** **`{perf_globale_cumulee:+,.2f} €`**

#### 🎯 Point Fiscal sur vos Arbitrages
- **Enveloppe PEA :** Les plus-values actées au sein du PEA ne subissent **aucune imposition immédiate** tant que le cash reste dans l'enveloppe, le produit de cession (`{total_vol_vendu_ia:,.2f} €`) reste donc disponible dans l'enveloppe.

*⚖️ Rappel : Analyse statistique et pédagogique générée par le moteur Boursy 2.0 (Non-CIF).*"""

        q_low = question_utilisateur.strip().lower()
        if any(m in q_low for m in ["vente", "vendu", "actée", "actee", "arbitrage", "plus-value", "moins-value", "réalisé"]):
            return f"""### 🧠 Réponse de votre Coach IA 2.0 — Bilan des Plus/Moins-Values Actées

**Votre question :** *« {question_utilisateur} »*

{bloc_recap_pv_md}

*⚖️ Rappel : Analyse statistique et pédagogique générée par le moteur Boursy 2.0 (Non-CIF).*"""

        focus_actions = []
        for d in donnees_t1:
            nom_b = d["NomBrut"]
            if nom_b.lower() in q_low:
                info_w = WATCHLIST_DEFAUT.get(nom_b, {})
                pos_pf = portefeuille_utilisateur.get(nom_b)
                txt_pf = f"Détenue en portefeuille (**{pos_pf['qte']} actions** avec un PRU de **{pos_pf['pru']}**)" if (pos_pf and isinstance(pos_pf, dict)) else "Non détenue actuellement en portefeuille"
                focus_actions.append(
                    f"* **{d['Actif']}** : Cours actuel **{d['Prix']}** | Prix Cible : **{d['Prix Cible']}** ({d['Écart Cible (%)']}) | "
                    f"RSI : **{d['RSI']}** | Stochastique : **{d['Stoch']}%** | Signal EMA 2/12 : **{d['EMA 2/12']}** | "
                    f"Rendement : **{(info_w.get('div_eur',0)/ max(0.01, prix_temps_reel.get(nom_b, 1))*100):.2f}%** | "
                    f"Score Algo : **{d['Score']}/100 ({d['Décision']})** — *{txt_pf}*."
                )

        if focus_actions:
            bloc_focus = "\n".join(focus_actions)
            return f"""### 🧠 Réponse Personnalisée de votre Coach IA 2.0

**Votre question :** *« {question_utilisateur} »*

#### 1. Analyse Technique & Fondamentale sur mesure
{bloc_focus}

#### 2. Stratégie adaptée à votre Portefeuille ({valeur_totale_portefeuille:,.0f} €)
- **Repères :** le Radar compare le cours actuel à votre **Prix Cible** et à votre **PRU** ; un **Score ≥ 55/100** signifie qu'une majorité d'indicateurs sont favorables.

*⚖️ Rappel : Analyse statistique et pédagogique générée par le moteur Boursy 2.0 (Non-CIF).*"""

        else:
            return f"""### 🧠 Synthèse Globale de votre Coach IA 2.0

**Votre question :** *« {question_utilisateur} »*

- **Portefeuille Actif :** **{valeur_totale_portefeuille:,.2f} €** (Plus-value latente : **{plus_value_glob:+,.2f} € / {pv_pct_glob:+.2f}%**).
- **Rente Annuelle :** **{dividendes_nets_totaux_eur:,.2f} € net/an** ({rente_mens_nette:.2f} € net/mois).

{bloc_recap_pv_md}

*⚖️ Rappel : Analyse statistique et pédagogique générée par le moteur Boursy 2.0 (Non-CIF).*"""

    def appeler_gemini_coach(question_utilisateur, code_audit=""):
        # Protection anti-abus API : si le visiteur n'est pas connecté à un compte, utilise le moteur local gratuit
        if st.session_state.get("user") is None:
            return generer_audit_expert_hybride(question_utilisateur, code_audit)

        cle_gemini = ""
        for nom_secret in ["GEMINI_API_KEY", "GOOGLE_API_KEY", "GEMINI_KEY"]:
            val_s = _lire_secret(nom_secret)
            if val_s:
                cle_gemini = val_s
                break
        if not cle_gemini:
            return generer_audit_expert_hybride(question_utilisateur, code_audit)

        resume_pf = []
        for l_it in lignes_triees:
            if l_it["est_especes"]:
                resume_pf.append(f"- Espèces : {l_it['val_eur']:.2f} €")
            else:
                p_l = (l_it["val_eur"] / valeur_totale_portefeuille * 100) if valeur_totale_portefeuille > 0 else 0
                resume_pf.append(
                    f"- {l_it['nom_act']} ({l_it['env_label']}) : Qté={l_it['qte']}, PRU={l_it['pru']} {l_it['sym']}, "
                    f"Cours={l_it['prix_jour']:.2f} {l_it['sym']}, Val={l_it['val_eur']:.1f} € (Poids {p_l:.1f}%), "
                    f"PV={l_it['pv_eur']:+.1f} € ({l_it['pv_pct']:+.1f}%), Div Net={l_it['div_net_l']:.2f} €/an"
                )

        resume_radar = [
            f"- {d['Actif']} : Prix={d['Prix']}, Cible={d['Prix Cible']}, RSI={d['RSI']}, Stoch={d['Stoch']}%, EMA={d['EMA 2/12']}, Score={d['Score']}/100 ({d['Décision']})"
            for d in donnees_t1[:15]
        ]

        plus_value_glob = valeur_totale_portefeuille - cout_total_achat
        resume_ventes_ia = [
            f"- {v['date']} ({v['mois_annee']}) : Vente de {v['qte']} {v['action']} à {v['prix_vente']} {v['devise']} "
            f"(PRU {v['pru']} {v['devise']}) -> Plus/Moins-value actée : {v['plus_value_eur']:+.2f} € ({v['perf_pct']:+.2f}%)"
            for v in hist_ventes_ia[:15]
        ]
        bloc_ventes_prompt = (
            f"Total Plus/Moins-Values Actées : {total_pv_actee_ia:+.2f} € (Performance d'extraction réelle : {perf_extraction_ia:+.2f}% sur {len(hist_ventes_ia)} vente(s), {nb_ventes_gagnantes_ia} gagnante(s), Cash total encaissé : {total_vol_vendu_ia:.2f} €).\n"
            + "\n".join(resume_ventes_ia)
            if hist_ventes_ia else "Aucune vente actée enregistrée pour le moment."
        )

        rente_ctx = contexte_rente(calculer=audit_sur_la_rente(question_utilisateur, code_audit))
        prompt_complet = f"""Tu es Boursy Coach IA 2.0, un expert patrimonial et boursier de haut niveau spécialisé dans les stratégies PEA, CTO US et dividendes croissants en DCA.
Voici les données exactes en temps réel du portefeuille de l'utilisateur :
- Météo des marchés : CAC 40 = {cac_str}, S&P 500 = {sp_str}, VIX = {vix_val:.1f} ({etat_vix})
- Taux de change EUR/USD : 1 € = {TAUX_USD_EUR:.4f} $
- Valorisation totale active : {valeur_totale_portefeuille:.2f} € (Capital investi : {cout_total_achat:.2f} €, Plus-value latente : {plus_value_glob:+.2f} €)
- Rente annuelle : {dividendes_bruts_totaux_eur:.2f} € brut / {dividendes_nets_totaux_eur:.2f} € net par an (soit {dividendes_nets_totaux_eur/12:.2f} € net/mois)
- Enveloppe DCA mensuelle : {BUDGET_MENSUEL:.0f} € / mois, répartie selon {'l’allocation cible de l’utilisateur' if allocation_personnalisee else 'des parts égales (allocation par défaut)'} ; achat du mois calculé : {', '.join(str(l['qte']) + ' ' + l['nom'] for l in achats_dca) or 'aucun'}
- Bilan historique du radar : sur environ 7 ans et 120 actions, ses signaux forts n’ont pas fait mieux, de façon démontrée, que les autres actions du même mois. Ne présente jamais un signal comme une prévision.
- Bilan des Plus-Values ou Moins-Values Actées (Réalisées) & Arbitrages :
{bloc_ventes_prompt}
- Détail des lignes du portefeuille (triées par poids décroissant) :
{chr(10).join(resume_pf) if resume_pf else 'Portefeuille vide'}
- Signaux techniques et fondamentaux du Radar Boursy aujourd'hui :
{chr(10).join(resume_radar)}
- Rente : solidité, diversification et projection (mêmes calculs que les onglets Radar et Calendrier de Boursy) :
{bloc_rente_prompt(rente_ctx)}

Mission demandée par l'utilisateur : {question_utilisateur}

Réponds en français avec une structure claire (titres, puces, chiffres précis tirés de son portefeuille, un récapitulatif dédié aux performances de ses plus-values ou moins-values actées, ses points forts, points de vigilance et pistes de réflexion). Ne formule jamais de recommandation personnalisée d'achat ou de vente : pas de « achetez » ni « vendez », pas de quantités ni de prix d'ordre à passer. Décris ce que montrent les indicateurs et laisse la décision à l'utilisateur. Rappelle discrètement en fin de message qu'il s'agit d'un audit pédagogique et statistique (non-CIF).
"""
        modeles_candidats = lister_modeles_gemini_actifs(cle_gemini)
        priorite_modeles = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-flash-latest", "gemini-2.5-pro"]
        modeles_propres = [
            m for m in modeles_candidats
            if not any(ex in m for ex in ["tts", "audio", "image", "vision", "embedding", "bis", "exp"])
        ]
        modeles_ordonnes = []
        # Les modèles "prioritaires" ne sont tentés que s'ils existent encore chez Google (évite des appels voués à l'échec)
        priorites_valides = [m for m in priorite_modeles if (not modeles_candidats or m in modeles_candidats)]
        for m_prio in priorites_valides + modeles_propres + modeles_candidats:
            if m_prio not in modeles_ordonnes:
                modeles_ordonnes.append(m_prio)

        for mod in modeles_ordonnes[:8]:
            try:
                url_api = f"https://generativelanguage.googleapis.com/v1beta/models/{mod}:generateContent?key={urllib.parse.quote(cle_gemini)}"
                payload_ia = json.dumps({"contents": [{"parts": [{"text": prompt_complet}]}]}).encode("utf-8")
                req_ia = urllib.request.Request(
                    url_api,
                    data=payload_ia,
                    headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
                )
                with urllib.request.urlopen(req_ia, timeout=25) as resp_ia:
                    res_json = json.loads(resp_ia.read().decode("utf-8"))
                    texte_rep = res_json["candidates"][0]["content"]["parts"][0]["text"]
                    if texte_rep:
                        return texte_rep
            except Exception:
                continue

        return generer_audit_expert_hybride(question_utilisateur, code_audit)

    st.markdown("#### 🚀 Choisissez un Audit Prédéfini en 1 Clic (ou posez votre question ci-dessous)")
    col_ia1, col_ia2, col_ia3 = st.columns(3)
    prompt_choisi = None
    code_audit_choisi = ""
    titre_audit = ""

    if col_ia1.button("🔍 1. Audit Complet 360° & Fiscalité", width="stretch"):
        titre_audit = "Audit Complet 360° & Fiscalité"
        code_audit_choisi = "AUDIT_1"
        prompt_choisi = "Réalise un audit 360° complet de mon portefeuille : équilibre sectoriel, récapitulatif de mes plus-values ou moins-values actées, analyse de mes PRU par rapport aux cours actuels, et optimisation fiscale de ma rente."
    if col_ia2.button("🛒 2. Achat DCA du Mois (allocation cible)", width="stretch"):
        titre_audit = "Achat DCA du Mois"
        code_audit_choisi = "AUDIT_2"
        prompt_choisi = f"Compte tenu du VIX actuel ({vix_val:.1f}) et des indicateurs techniques du radar (RSI, Stochastique, EMA 2/12, écart au prix cible), que montrent les indicateurs pour les valeurs de mon radar, et comment mon enveloppe de {BUDGET_MENSUEL:.0f} € se répartit-elle selon mon allocation cible ?"
    if col_ia3.button("🌍 3. Arbitrage PEA (EUR) vs Actions US ($)", width="stretch"):
        titre_audit = "Arbitrage PEA (EUR) vs Actions US ($)"
        code_audit_choisi = "AUDIT_3"
        prompt_choisi = "Analyse la pertinence d'arbitrer ou de renforcer mes valeurs européennes de rendement en PEA face aux géants américains en CTO compte tenu de la parité EUR/USD actuelle et de mes lignes."

    col_ia4, col_ia5, col_ia6 = st.columns(3)
    if col_ia4.button("🛡️ 4. Stress-Test, Risques & Diversification", width="stretch"):
        titre_audit = "Stress-Test, Risques & Diversification"
        code_audit_choisi = "AUDIT_4"
        prompt_choisi = "Analyse les risques de concentration de mon portefeuille et de ma rente (plus grosses lignes, secteurs dominants, pays), fais un stress-test en cas de baisse de marché de 20 % et d'une crise des dividendes comme 2020, en t'appuyant sur les baisses mesurées par secteur, et montre quels secteurs sont peu ou pas représentés."
    if col_ia5.button("💵 5. Ma Rente : Solidité, Diversification & Projection", width="stretch"):
        titre_audit = "Ma Rente : Solidité, Diversification & Projection"
        code_audit_choisi = "AUDIT_5"
        prompt_choisi = "Analyse la solidité de ma rente (part issue de dividendes solides, lignes à surveiller), sa diversification par secteur et par pays (retenues à la source en PEA), ce qu'une crise comme 2020 lui ferait, et sa projection prudente à 10 et 20 ans avec mon achat mensuel ; puis les leviers vers 100 €/mois puis 500 €/mois de rente, sans privilégier les rendements les plus élevés."
    if col_ia6.button("💰 6. Bilan de mes Plus/Moins-Values Actées (Pro)", width="stretch"):
        if not est_pro_max:
            st.warning("🔒 L'audit des Arbitrages & Plus-Values Actées est réservé à l'offre **Pro (8,90 €/mois)**.")
        else:
            titre_audit = "Bilan de mes Arbitrages & Plus-Values Actées"
            code_audit_choisi = "AUDIT_6"
            prompt_choisi = "Fais-moi un récapitulatif complet et détaillé des performances de mes plus-values ou moins-values actées (réalisées), analyse mon taux de réussite (win rate), ma performance d'extraction réelle et le montant de cash disponible après ces ventes."

    st.markdown("---")
    col_q_input, col_q_btn, col_q_clear = st.columns([4, 1.3, 0.8])
    with col_q_input:
        question_libre = st.text_input(
            "💬 Posez une question personnalisée à votre Coach IA 2.0 :",
            placeholder="Ex: Analyse mon PRU sur Rubis et mes opportunités DCA du mois...",
            label_visibility="collapsed",
        )
    with col_q_btn:
        if st.button("✨ Lancer l'Analyse IA", type="primary", width="stretch"):
            if question_libre.strip():
                titre_audit = f"Question libre : {question_libre.strip()}"
                code_audit_choisi = "LIBRE"
                prompt_choisi = question_libre.strip()
    with col_q_clear:
        if st.button("🗑️ Effacer", width="stretch"):
            st.session_state["reponse_ia_coach"] = ""
            st.session_state["historique_chat_ia"] = []
            st.rerun()

    if prompt_choisi:
        if quota_restant <= 0:
            st.error("🔒 Vous avez atteint votre quota journalier d'analyses IA. Passez au forfait supérieur dans le menu de gauche (3 audits/jour en Premium 4,90 € ou 15 audits/jour en Pro 8,90 €) !")
        else:
            with st.spinner("🧠 Le Coach IA 2.0 analyse votre portefeuille et les indicateurs techniques en direct..."):
                reponse_texte = appeler_gemini_coach(prompt_choisi, code_audit_choisi)
                st.session_state["quota_ia_utilise"] = quota_utilise + 1
                sauvegarder_dans_cloud()
                st.session_state["reponse_ia_coach"] = reponse_texte
                st.session_state["historique_chat_ia"].insert(0, {
                    "heure": datetime.now().strftime("%H:%M"),
                    "titre": titre_audit,
                    "reponse": reponse_texte,
                })
                st.rerun()

    if st.session_state.get("reponse_ia_coach"):
        afficher_html("<div class='ia-box'><b>📋 Dernier Rapport d'Audit de votre Coach IA 2.0 :</b></div>")
        markdown_fr(st.session_state["reponse_ia_coach"])

    if len(st.session_state.get("historique_chat_ia", [])) > 1:
        with st.expander(f"🕒 Consulter l'historique de vos {len(st.session_state['historique_chat_ia'])} analyses IA de la session", expanded=False):
            for idx_h, item_h in enumerate(st.session_state["historique_chat_ia"]):
                st.markdown(f"#### {idx_h + 1}. {item_h['titre']} *(à {item_h['heure']})*")
                markdown_fr(item_h["reponse"])
                st.markdown("---")

