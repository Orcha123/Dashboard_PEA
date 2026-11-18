"""
Onglet 2 de Boursy : saisie des lignes, journal des achats (saisie, import CSV, import IA), carnet de décisions,
valorisation du portefeuille, répartition, trajectoire et performance comparée à l'ETF Monde.

afficher() renvoie les valeurs calculées ici et utilisées par les onglets suivants (valeur du portefeuille, lignes,
dividendes, expositions...).

Toutes les informations venues du reste de l'application sont des paramètres nommés d'afficher() :
leur liste est la liste exacte des dépendances de l'onglet (vérifiée par tests/test_application.py).
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import html as html_lib
import io
import json
import math
import re
import time
import urllib.parse

import pandas as pd
import streamlit as st

from carnet_decisions import HORIZONS_MOIS, HORIZON_RELECTURE_MOIS, LONGUEUR_NOTE_MAX, NOM_REFERENCE, RAISONS, SYMBOLE_REFERENCE, TYPES_DECISION, ajouter_decision, ajouter_mois, bilan_par_raison, decisions_a_relire, enregistrer_lecon, evaluer_decision, lire_carnet, nouvelle_decision, phrase_resultat, supprimer_decision
from catalogue_valeurs import symbole_a_jour
from donnees_marche import cours_a_la_date, taux_rendement_interne
from habillage import afficher_html, markdown_fr, nombres_fr


def afficher(
    *,
    BUDGET_MENSUEL,
    CATALOGUE_ACTIONS,
    CLES_TECHNIQUES_PF,
    TAUX_USD_EUR,
    WATCHLIST_DEFAUT,
    _lire_secret,
    afficher_verrou_saas,
    construire_position,
    est_premium_ou_pro,
    est_pro_max,
    facteur_cout_usd,
    historique_long,
    historiques_prix,
    mode_gratuit,
    prix_temps_reel,
    recuperer_donnees,
    sauvegarder_dans_cloud,
    supabase,
    variations_jour,
):
    # Versements nets estimés du PEA (jauge du plafond), repris par le Super-Pack ; None si le portefeuille est vide
    versements_nets_pea = None
    performance_vs_etf = None  # rendement annualisé comparé à un ETF Monde (calculé plus bas si possible), pour le coach
    st.subheader("💼 Gestionnaire de Portefeuille Multidevises & Fiscalité")

    # Intègre toutes les actions du catalogue pour pouvoir les sélectionner librement
    for lib_cat, (sym_c, dev_c, sec_c) in CATALOGUE_ACTIONS.items():
        nom_c = lib_cat.rsplit(" (", 1)[0]
        if nom_c not in WATCHLIST_DEFAUT:
            WATCHLIST_DEFAUT[nom_c] = {
                "symbole": sym_c,
                "prix_cible": 100.0,
                "secteur": sec_c,
                "div_eur": 2.0,
                "payout_ratio": 0.50,
                "croissance_5a": "+5.0%",
                "mois_div": ["Mar", "Juin", "Sep", "Déc"] if dev_c == "USD" else ["Mai"],
                "devise": dev_c,
            }

    with st.expander("✏️ Saisir ou modifier mes actions détenues (Quantité & PRU)", expanded=False):
        st.markdown("#### 💶 Poche Liquidités (Espèces disponibles)")
        esp_dict_actuel = st.session_state["portefeuille"].get("Espèces", {})
        pru_esp_defaut = float(esp_dict_actuel.get("pru", 0.0)) if isinstance(esp_dict_actuel, dict) else 0.0
        montant_especes = st.number_input("Montant Espèces (€)", min_value=0.0, value=float(st.session_state.get("pru_Espèces", pru_esp_defaut)), step=50.0, key="pru_Espèces")

        nouveau_portefeuille_temp = {}
        for cle_t in ("_historique_ventes", "_quota_ia", "_niveau_abo", "_div_encaisses_cumul", "_stripe_customer_id", "_alertes_auto", "_alertes_envoyees", "_journal_achats", "_allocation_cible", "_resume_mensuel", "_jour_dca", "_resume_envoye", "_carnet_decisions"):
            if cle_t in st.session_state["portefeuille"]:
                nouveau_portefeuille_temp[cle_t] = st.session_state["portefeuille"][cle_t]
        if st.session_state.get("historique_ventes"):
            nouveau_portefeuille_temp["_historique_ventes"] = list(st.session_state["historique_ventes"])
        if montant_especes > 0:
            nouveau_portefeuille_temp["Espèces"] = {"qte": 1, "pru": montant_especes}
            st.session_state["qte_Espèces"] = 1

        st.markdown("---")
        st.markdown("#### 🎯 Choisir les actions à afficher dans mon portefeuille")

        actions_deja_detenues = [k for k in st.session_state["portefeuille"].keys() if k not in CLES_TECHNIQUES_PF]
        for k_det in actions_deja_detenues:
            if k_det not in WATCHLIST_DEFAUT:
                WATCHLIST_DEFAUT[k_det] = {
                    "symbole": k_det.upper(), "prix_cible": float(st.session_state["portefeuille"][k_det].get("pru", 50.0)),
                    "secteur": "Action Portefeuille", "div_eur": 0.0, "payout_ratio": 0.50,
                    "croissance_5a": "+5.0%", "mois_div": ["Mai"], "devise": "EUR",
                }
        actions_radar = [k for k in st.session_state["watchlist"].keys() if k not in CLES_TECHNIQUES_PF]
        selection_par_defaut = sorted(list(set(actions_deja_detenues + actions_radar)))

        actions_choisies_pf = st.multiselect(
            "Sélectionnez ou recherchez vos actions (ex: Engie, TotalEnergies, Air Liquide, Rubis, AXA...) :",
            options=sorted([k for k in WATCHLIST_DEFAUT.keys() if k not in CLES_TECHNIQUES_PF]),
            default=[a for a in selection_par_defaut if a in WATCHLIST_DEFAUT],
        )

        st.markdown("#### 📈 Mes Positions Actions (Saisissez le PRU dans la devise de l'action : € ou $)")
        cols_saisie = st.columns(3)

        for idx, nom_act in enumerate(actions_choisies_pf):
            info_act = WATCHLIST_DEFAUT[nom_act]
            col_active = cols_saisie[idx % 3]
            devise_a = info_act.get("devise", "EUR")
            with col_active:
                st.markdown(f"**{nom_act}** *({devise_a})*")
                pos_existante = st.session_state["portefeuille"].get(nom_act, {})
                qte_defaut = int(pos_existante.get("qte", 0)) if isinstance(pos_existante, dict) else 0
                pru_defaut = float(pos_existante.get("pru", float(info_act["prix_cible"]))) if isinstance(pos_existante, dict) else float(info_act["prix_cible"])

                qte_saisie = st.number_input(f"Quantité ({nom_act})", min_value=0, value=int(st.session_state.get(f"qte_{nom_act}", qte_defaut)), key=f"qte_{nom_act}")
                pru_saisi = st.number_input(f"PRU Unitaire ({devise_a})", min_value=0.0, value=float(st.session_state.get(f"pru_{nom_act}", pru_defaut)), step=0.5, key=f"pru_{nom_act}")

                taux_achat_saisi = 0.0
                if devise_a == "USD":
                    try:
                        taux_achat_defaut = float(pos_existante.get("taux_achat") or 0.0) if isinstance(pos_existante, dict) else 0.0
                    except Exception:
                        taux_achat_defaut = 0.0
                    taux_achat_saisi = st.number_input(
                        "Taux €/$ à l'achat (1 € = ? $)",
                        min_value=0.0,
                        max_value=5.0,
                        value=min(5.0, max(0.0, float(st.session_state.get(f"txa_{nom_act}", taux_achat_defaut)))),
                        step=0.01,
                        format="%.4f",
                        key=f"txa_{nom_act}",
                        help="Taux de change moyen de vos achats (ex. 1,0850). Il sert à convertir votre PRU en euros, pour que "
                             "la plus-value tienne compte de l'effet de change. Laissez 0 pour utiliser le taux du jour.",
                    )

                if qte_saisie > 0:
                    nouveau_portefeuille_temp[nom_act] = {"qte": qte_saisie, "pru": pru_saisi}
                    if taux_achat_saisi > 0:
                        nouveau_portefeuille_temp[nom_act]["taux_achat"] = round(float(taux_achat_saisi), 4)
                    if nom_act not in st.session_state["watchlist"]:
                        st.session_state["watchlist"][nom_act] = info_act.copy()
                st.markdown("---")

        st.session_state["portefeuille"] = nouveau_portefeuille_temp
        if st.button("💾 Enregistrer mon portefeuille & créer un Snapshot Cloud", type="primary", width="stretch"):
            sauvegarder_dans_cloud()
            st.rerun()

    # ======================================================================
    # JOURNAL DES ACHATS : CHAQUE ACHAT MET À JOUR LA QUANTITÉ ET LE PRU (FRAIS INCLUS)
    # ======================================================================
    def _nombre_lu(valeur):
        """Lit un nombre écrit à la française ou à l'anglaise ('1 234,56 €', '1,234.56') ; None si illisible."""
        if valeur is None:
            return None
        if isinstance(valeur, (int, float)):
            return None if (isinstance(valeur, float) and math.isnan(valeur)) else float(valeur)
        texte = str(valeur)
        for parasite in (" ", " ", " ", "€", "$", "EUR", "USD"):
            texte = texte.replace(parasite, "")
        texte = texte.strip()
        if not texte:
            return None
        if "," in texte and "." in texte:
            # Le séparateur le plus à droite est celui des décimales
            texte = texte.replace(".", "").replace(",", ".") if texte.rfind(",") > texte.rfind(".") else texte.replace(",", "")
        else:
            texte = texte.replace(",", ".")
        try:
            return float(texte)
        except ValueError:
            return None

    def _calculer_position_apres_achat(position, est_usd, qte, prix, frais_eur, taux_operation):
        """Nouvelle position après un achat : PRU moyen pondéré frais inclus, et taux €/$ moyen pour les lignes en dollars."""
        position = position if isinstance(position, dict) else {}
        qte_avant = float(position.get("qte", 0) or 0)
        pru_avant = float(position.get("pru", 0) or 0)
        frais_devise = frais_eur * taux_operation if est_usd else frais_eur
        cout_devise = qte_avant * pru_avant + qte * prix + frais_devise
        qte_apres = qte_avant + qte
        nouvelle = {"qte": int(round(qte_apres)), "pru": round(cout_devise / qte_apres, 4) if qte_apres > 0 else 0.0}
        if est_usd:
            taux_avant = float(position.get("taux_achat") or 0) or float(TAUX_USD_EUR)
            cout_eur = (qte_avant * pru_avant) / taux_avant + (qte * prix) / taux_operation + frais_eur
            nouvelle["taux_achat"] = round(cout_devise / cout_eur, 4) if cout_eur > 0 else round(taux_operation, 4)
        return nouvelle

    def _synchroniser_saisie_position(nom_action, position):
        """Aligne les champs « Quantité / PRU / Taux » du volet de saisie sur la position (ou les vide si elle disparaît)."""
        st.session_state[f"qte_{nom_action}"] = int(position.get("qte", 0)) if position else 0
        if position:
            st.session_state[f"pru_{nom_action}"] = float(position.get("pru", 0.0))
        st.session_state[f"txa_{nom_action}"] = float((position or {}).get("taux_achat") or 0.0)

    def noter_dans_carnet(type_decision, nom_action, jour, raison, note, source, qte=None, prix=None):
        """Ajoute une décision au carnet si l'utilisateur a indiqué une raison ou une note (sinon ne fait rien)."""
        note = str(note or "").strip()
        if (not raison or raison == "—") and not note:
            return None
        info_carnet = WATCHLIST_DEFAUT.get(nom_action, {})
        return ajouter_decision(st.session_state["portefeuille"], nouvelle_decision(
            jour, nom_action, symbole_a_jour(info_carnet.get("symbole", "")), type_decision,
            raison if raison and raison != "—" else "Autre", note, info_carnet.get("devise", "EUR"), source, qte, prix,
        ))

    def appliquer_achat(nom_action, date_achat, qte, prix, frais_eur, taux_operation=0.0, source="saisie"):
        """Ajoute un achat au journal et met à jour la ligne du portefeuille. Renvoie la nouvelle position."""
        est_usd = WATCHLIST_DEFAUT.get(nom_action, {}).get("devise") == "USD"
        taux_operation = float(taux_operation) if (est_usd and taux_operation and float(taux_operation) > 0) else (float(TAUX_USD_EUR) if est_usd else 1.0)
        pf = st.session_state["portefeuille"]
        position_avant = pf.get(nom_action) if isinstance(pf.get(nom_action), dict) else {}
        nouvelle = _calculer_position_apres_achat(position_avant, est_usd, qte, prix, frais_eur, taux_operation)
        pf[nom_action] = nouvelle
        journal = pf.get("_journal_achats") if isinstance(pf.get("_journal_achats"), list) else []
        journal.append({
            "id": f"{time.time():.6f}",
            "date": str(date_achat)[:10],
            "action": nom_action,
            "qte": int(qte),
            "prix": float(prix),
            "frais_eur": float(frais_eur),
            "devise": "USD" if est_usd else "EUR",
            "taux_change": round(taux_operation, 4) if est_usd else None,
            "source": source,
            "avant": {k: position_avant.get(k) for k in ("qte", "pru", "taux_achat") if position_avant.get(k) is not None},
            "apres": dict(nouvelle),
        })
        pf["_journal_achats"] = journal
        _synchroniser_saisie_position(nom_action, nouvelle)
        if nom_action not in st.session_state["watchlist"] and nom_action in WATCHLIST_DEFAUT:
            st.session_state["watchlist"][nom_action] = WATCHLIST_DEFAUT[nom_action].copy()
        return nouvelle

    def _achat_annulable(entree):
        """Un achat n'est annulable que si la ligne n'a pas changé depuis (ni achat, ni vente, ni modification manuelle)."""
        position = st.session_state["portefeuille"].get(entree.get("action"))
        apres = entree.get("apres") or {}
        return (
            isinstance(position, dict)
            and int(position.get("qte", 0)) == int(apres.get("qte", -1))
            and abs(float(position.get("pru", 0)) - float(apres.get("pru", -1))) < 0.005
        )

    def _enregistrer_achat_saisi():
        nom_action = st.session_state.get("ja_action")
        qte = int(st.session_state.get("ja_qte", 0) or 0)
        prix = float(st.session_state.get(f"ja_prix_{nom_action}", 0.0) or 0.0)
        frais = float(st.session_state.get("ja_frais", 0.0) or 0.0)
        if not nom_action or qte <= 0 or prix <= 0:
            st.session_state["_notif_journal"] = ("erreur", "Indiquez une action, une quantité et un prix supérieurs à zéro.")
            return
        position = appliquer_achat(nom_action, st.session_state.get("ja_date", datetime.now().date()), qte, prix, frais,
                                   st.session_state.get(f"ja_taux_{nom_action}", 0.0))
        decision_notee = noter_dans_carnet("achat", nom_action, st.session_state.get("ja_date", datetime.now().date()),
                                           st.session_state.get("ja_raison"), st.session_state.get("ja_note"), "journal", qte, prix)
        st.session_state["ja_note"] = ""
        st.session_state["ja_raison"] = "—"
        sauvegarder_dans_cloud()
        st.session_state["_notif_journal"] = ("ok", f"✅ Achat enregistré : +{qte} {nom_action}. Nouvelle ligne : {position['qte']} titre(s), PRU {position['pru']:.2f}."
                                              + (" Raison notée dans le carnet de décisions." if decision_notee else ""))

    def _annuler_achat(id_achat):
        pf = st.session_state["portefeuille"]
        journal = list(pf.get("_journal_achats") or [])
        entree = next((e for e in journal if e.get("id") == id_achat), None)
        if entree is None or not _achat_annulable(entree):
            st.session_state["_notif_journal"] = ("erreur", "Cet achat ne peut plus être annulé : la ligne a changé depuis.")
            return
        nom_action = entree["action"]
        avant = entree.get("avant") or {}
        if int(avant.get("qte", 0) or 0) > 0:
            pf[nom_action] = {k: avant[k] for k in ("qte", "pru", "taux_achat") if avant.get(k) is not None}
            _synchroniser_saisie_position(nom_action, pf[nom_action])
        else:
            pf.pop(nom_action, None)
            _synchroniser_saisie_position(nom_action, None)
        pf["_journal_achats"] = [e for e in journal if e.get("id") != id_achat]
        sauvegarder_dans_cloud()
        st.session_state["_notif_journal"] = ("ok", f"🔄 Achat annulé : la ligne {nom_action} est revenue à son état précédent.")

    def _lire_date(valeur):
        texte_date = str(valeur or "").strip()
        if re.match(r"^\d{4}-\d{2}-\d{2}", texte_date):
            return pd.to_datetime(texte_date[:10], format="%Y-%m-%d", errors="coerce")
        return pd.to_datetime(texte_date, dayfirst=True, errors="coerce")

    def _analyser_operations(operations, taux_dollar):
        """
        Contrôle des opérations lues dans un fichier CSV ou par l'IA. Chaque opération est un dict
        {date, libelle, qte, prix, frais, sens}. Renvoie (achats importables, aperçu ligne par ligne).
        """
        journal_actuel = st.session_state["portefeuille"].get("_journal_achats")
        journal_actuel = journal_actuel if isinstance(journal_actuel, list) else []
        signatures = {f"{e.get('date')}|{e.get('action')}|{int(e.get('qte', 0))}|{float(e.get('prix', 0)):.4f}" for e in journal_actuel}
        lignes_valides, apercu = [], []
        for operation in operations:
            libelle = str(operation.get("libelle", "") or "")
            date_lue = _lire_date(operation.get("date"))
            qte_lue = _nombre_lu(operation.get("qte"))
            prix_lu = _nombre_lu(operation.get("prix"))
            frais_lus = _nombre_lu(operation.get("frais")) or 0.0
            sens_lu = _normaliser(operation.get("sens", "") or "")
            action_lue = _reconnaitre_action(libelle)
            if any(m in sens_lu for m in ("vente", "sell", "cession")):
                statut = "Ignorée : vente (à saisir dans l'onglet Arbitrages)"
            elif pd.isna(date_lue) or not qte_lue or not prix_lu or prix_lu <= 0:
                statut = "Ignorée : date, quantité ou prix illisible"
            elif action_lue is None:
                statut = "Ignorée : action non reconnue (ajoutez-la d'abord à votre radar)"
            elif date_lue.date() > datetime.now().date():
                statut = "Ignorée : date dans le futur"
            else:
                ligne = {
                    "date": date_lue.date().isoformat(), "action": action_lue, "qte": int(round(abs(qte_lue))),
                    "prix": float(prix_lu), "frais": abs(float(frais_lus)), "taux": float(taux_dollar),
                }
                signature = f"{ligne['date']}|{ligne['action']}|{ligne['qte']}|{ligne['prix']:.4f}"
                if ligne["qte"] <= 0:
                    statut = "Ignorée : quantité nulle"
                elif signature in signatures:
                    statut = "Ignorée : déjà dans le journal"
                else:
                    signatures.add(signature)
                    lignes_valides.append(ligne)
                    statut = "✅ À importer"
            apercu.append({
                "Date": date_lue.strftime("%d/%m/%Y") if not pd.isna(date_lue) else "?",
                "Valeur lue": libelle,
                "Action reconnue": action_lue or "—",
                "Quantité": qte_lue,
                "Prix": prix_lu,
                "Statut": statut,
            })
        return lignes_valides, apercu

    def _extraire_json_gemini(parties):
        """Envoie un texte ou une image à Gemini et renvoie (liste JSON extraite, message d'erreur éventuel)."""
        cle_gemini_journal = next((v for v in (_lire_secret(n) for n in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GEMINI_KEY")) if v), "")
        if not cle_gemini_journal:
            return None, "⚠️ Clé `GEMINI_API_KEY` absente de vos Secrets Streamlit."
        corps_requete = json.dumps({"contents": [{"parts": parties}]}).encode("utf-8")
        for modele in ("gemini-2.5-flash", "gemini-2.0-flash", "gemini-flash-latest"):
            try:
                requete = urllib.request.Request(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{modele}:generateContent?key={urllib.parse.quote(cle_gemini_journal)}",
                    data=corps_requete, headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(requete, timeout=40) as reponse:
                    texte_ia = json.loads(reponse.read().decode("utf-8"))["candidates"][0]["content"]["parts"][0]["text"]
                debut, fin = texte_ia.find("["), texte_ia.rfind("]")
                if debut != -1 and fin > debut:
                    donnees = json.loads(texte_ia[debut:fin + 1])
                    if isinstance(donnees, list):
                        return donnees, None
            except Exception:
                continue
        return None, "L'IA n'a pas pu lire cet historique. Réessayez avec une capture plus nette, ou copiez-collez le texte."

    CONSIGNE_HISTORIQUE_IA = (
        "Extrais chaque opération d'achat ou de vente d'actions ou d'ETF de cet historique de PEA ou de compte-titres. "
        "Réponds UNIQUEMENT avec un tableau JSON valide de la forme : "
        '[{"date": "2025-03-15", "nom": "Air Liquide", "sens": "achat", "qte": 5, "prix": 160.50, "frais": 1.95}]. '
        "date = date d'exécution au format AAAA-MM-JJ ; sens = achat ou vente ; qte = nombre de titres ; "
        "prix = prix unitaire d'exécution ; frais = frais de courtage en euros (0 s'ils ne sont pas indiqués). "
        "Ignore les dividendes, versements, virements, taxes et droits de garde. "
        "Utilise les noms standards si tu reconnais l'entreprise (ex : TotalEnergies, Air Liquide, AXA, LVMH, Sanofi, "
        "Engie, Vinci, BNP Paribas, Schneider Electric, Microsoft, Apple, Realty Income)."
    )

    def _importer_achats(lignes_a_importer):
        for ligne in sorted(lignes_a_importer, key=lambda l: l["date"]):
            appliquer_achat(ligne["action"], ligne["date"], ligne["qte"], ligne["prix"], ligne["frais"], ligne["taux"], source="import")
        sauvegarder_dans_cloud()
        # Nouveaux champs de dépôt (clés différentes) : le fichier ou le texte importé disparaît de l'écran
        st.session_state["_compteur_import_achats"] = int(st.session_state.get("_compteur_import_achats", 0)) + 1
        st.session_state.pop("_operations_ia", None)
        st.session_state["_notif_journal"] = ("ok", f"✅ {len(lignes_a_importer)} achat(s) importé(s). Quantités et PRU mis à jour.")

    def _sans_accents(texte):
        import unicodedata
        return "".join(c for c in unicodedata.normalize("NFD", str(texte)) if unicodedata.category(c) != "Mn")

    def _normaliser(texte):
        return re.sub(r"[^a-z0-9]+", " ", _sans_accents(texte).lower()).strip()

    def _reconnaitre_action(texte):
        """Retrouve une action connue à partir d'un libellé ou d'un symbole de courtier ; None si aucune ne correspond."""
        cherche = _normaliser(texte)
        if not cherche:
            return None
        meilleure, longueur = None, 0
        for nom_c, info_c in WATCHLIST_DEFAUT.items():
            if nom_c in CLES_TECHNIQUES_PF or not isinstance(info_c, dict):
                continue
            nom_n = _normaliser(nom_c)
            symbole = str(info_c.get("symbole", ""))
            if cherche in (nom_n, _normaliser(symbole)) or (len(symbole.split(".")[0]) >= 2 and cherche == _normaliser(symbole.split(".")[0])):
                return nom_c
            nom_court = _normaliser(re.sub(r"\(.*?\)", "", nom_c))
            for candidat in {nom_n, nom_court}:
                if len(candidat) >= 4 and (candidat in cherche or (len(cherche) >= 4 and cherche in candidat)) and len(candidat) > longueur:
                    meilleure, longueur = nom_c, len(candidat)
        return meilleure

    with st.expander("🧾 Journal des achats : enregistrer un achat (PRU recalculé automatiquement)", expanded=False):
        notif_journal = st.session_state.pop("_notif_journal", None)
        if notif_journal:
            (st.success if notif_journal[0] == "ok" else st.error)(nombres_fr(notif_journal[1]))
        st.caption(
            "Chaque achat enregistré met à jour la quantité et le PRU de la ligne, frais de courtage inclus. "
            "Vos lignes déjà saisies servent de point de départ."
        )

        options_achat = sorted([k for k in WATCHLIST_DEFAUT.keys() if k not in CLES_TECHNIQUES_PF])
        lignes_detenues = [k for k, v in st.session_state["portefeuille"].items() if k not in CLES_TECHNIQUES_PF and isinstance(v, dict)]
        index_defaut = options_achat.index(lignes_detenues[0]) if lignes_detenues and lignes_detenues[0] in options_achat else 0
        col_ja1, col_ja2 = st.columns([2, 1])
        with col_ja1:
            action_achat = st.selectbox("Action achetée :", options_achat, index=index_defaut, key="ja_action")
        with col_ja2:
            st.date_input("Date de l'achat :", value=datetime.now().date(), max_value=datetime.now().date(), key="ja_date", format="DD/MM/YYYY")

        est_usd_achat = WATCHLIST_DEFAUT.get(action_achat, {}).get("devise") == "USD"
        symbole_achat = "$" if est_usd_achat else "€"
        cours_reference = float(prix_temps_reel.get(action_achat, WATCHLIST_DEFAUT.get(action_achat, {}).get("prix_cible", 0.0)) or 0.0)
        col_ja3, col_ja4, col_ja5 = st.columns(3)
        with col_ja3:
            st.number_input("Quantité achetée :", min_value=0, value=0, step=1, key="ja_qte")
        with col_ja4:
            st.number_input(f"Prix unitaire ({symbole_achat}) :", min_value=0.0, value=round(cours_reference, 2), step=0.5, key=f"ja_prix_{action_achat}")
        with col_ja5:
            st.number_input("Frais de courtage (€) :", min_value=0.0, value=0.0, step=0.5, key="ja_frais")
        if est_usd_achat:
            st.number_input("Taux €/$ de l'achat (1 € = ? $) :", min_value=0.0, max_value=5.0, value=round(float(TAUX_USD_EUR), 4),
                            step=0.01, format="%.4f", key=f"ja_taux_{action_achat}")

        qte_apercu = int(st.session_state.get("ja_qte", 0) or 0)
        prix_apercu = float(st.session_state.get(f"ja_prix_{action_achat}", 0.0) or 0.0)
        if qte_apercu > 0 and prix_apercu > 0:
            taux_apercu = float(st.session_state.get(f"ja_taux_{action_achat}", TAUX_USD_EUR) or TAUX_USD_EUR) if est_usd_achat else 1.0
            position_actuelle = st.session_state["portefeuille"].get(action_achat)
            position_apercu = _calculer_position_apres_achat(position_actuelle, est_usd_achat, qte_apercu, prix_apercu,
                                                             float(st.session_state.get("ja_frais", 0.0) or 0.0), taux_apercu)
            qte_actuelle_ap = int(position_actuelle.get("qte", 0)) if isinstance(position_actuelle, dict) else 0
            pru_actuel_ap = float(position_actuelle.get("pru", 0.0)) if isinstance(position_actuelle, dict) else 0.0
            afficher_html(f"""
            <div style="background:rgba(128,128,128,0.05); border:1px dashed #3498db; padding:10px 14px; border-radius:8px; margin:6px 0 10px 0; font-size:0.88em;">
                🔎 <b>Aperçu :</b> {qte_actuelle_ap} ➔ <b>{position_apercu['qte']} titre(s)</b> |
                PRU {pru_actuel_ap:.2f} ➔ <b>{position_apercu['pru']:.2f} {symbole_achat}</b> (frais inclus) |
                Montant de l'achat : <b>{qte_apercu * prix_apercu:,.2f} {symbole_achat}</b>
            </div>
            """)
        col_ja6, col_ja7 = st.columns([1, 2])
        with col_ja6:
            st.selectbox("📓 Pourquoi cet achat ? (facultatif)", ["—"] + RAISONS["achat"], key="ja_raison",
                         help="Noté dans le carnet de décisions : six mois plus tard, Boursy vous montrera ce qu'est devenue la valeur.")
        with col_ja7:
            st.text_input("En une phrase (facultatif) :", max_chars=LONGUEUR_NOTE_MAX, key="ja_note",
                          placeholder="Ex. : sous mon prix cible depuis 3 semaines, dividende confirmé.")
        st.button("➕ Enregistrer cet achat", type="primary", width="stretch", on_click=_enregistrer_achat_saisi, key="btn_enregistrer_achat")

        journal_achats = st.session_state["portefeuille"].get("_journal_achats") if isinstance(st.session_state["portefeuille"].get("_journal_achats"), list) else []
        if journal_achats:
            st.markdown("#### 📜 Historique des achats")
            montant_total_achats = sum(
                (e["qte"] * e["prix"]) / (e.get("taux_change") or TAUX_USD_EUR) + e.get("frais_eur", 0.0) if e.get("devise") == "USD"
                else e["qte"] * e["prix"] + e.get("frais_eur", 0.0)
                for e in journal_achats
            )
            st.caption(nombres_fr(f"{len(journal_achats)} achat(s) enregistré(s), pour un total de {montant_total_achats:,.2f} € frais inclus."))
            entrees_triees = sorted(journal_achats, key=lambda e: (e.get("date", ""), e.get("id", "")), reverse=True)
            for entree in entrees_triees[:30]:
                sym_e = "$" if entree.get("devise") == "USD" else "€"
                date_e = str(entree.get("date", ""))
                date_fr_e = f"{date_e[8:10]}/{date_e[5:7]}/{date_e[0:4]}" if len(date_e) == 10 else date_e
                col_h1, col_h2 = st.columns([5, 1])
                with col_h1:
                    markdown_fr(
                        f"**{date_fr_e}** — **{entree['action']}** : +{entree['qte']} à {entree['prix']:.2f} {sym_e}"
                        + (f" (frais {entree.get('frais_eur', 0.0):.2f} €)" if entree.get("frais_eur") else "")
                        + (" · *importé*" if entree.get("source") == "import" else "")
                    )
                with col_h2:
                    annulable = _achat_annulable(entree)
                    st.button("↩️ Annuler", key=f"annuler_achat_{entree['id']}", on_click=_annuler_achat, args=(entree["id"],),
                              disabled=not annulable, width="stretch",
                              help=None if annulable else "La ligne a changé depuis cet achat (autre achat, vente ou modification) : il ne peut plus être annulé.")
            if len(entrees_triees) > 30:
                st.caption(f"… et {len(entrees_triees) - 30} achat(s) plus ancien(s).")

        # --- IMPORT D'UN HISTORIQUE D'ACHATS (CSV EXPORTÉ DEPUIS LE COURTIER) ---
        st.markdown("#### 📥 Importer un historique d'achats (fichier CSV de votre courtier)")
        if not est_premium_ou_pro:
            afficher_verrou_saas(
                "Import d'un historique d'achats depuis votre courtier (CSV)",
                "⚡ Offre Premium (4,90 €/mois) ou 👑 Pro (8,90 €/mois)",
                "Importez en une fois tous vos achats passés : quantités et PRU sont recalculés automatiquement."
            )
        else:
            st.caption(
                "Exportez l'historique de vos opérations depuis votre courtier au format CSV, puis déposez-le ici. "
                "Indiquez quelle colonne contient quoi : seuls les achats d'actions reconnues sont importés. "
                "Pas d'export CSV ? Utilisez l'import par l'IA juste en dessous (offre Pro)."
            )
            fichier_achats = st.file_uploader("Fichier CSV des opérations", type=["csv", "txt"], key=f"up_csv_achats_{st.session_state.get('_compteur_import_achats', 0)}")
            if fichier_achats is not None:
                tableau_csv = None
                for encodage in ("utf-8-sig", "latin-1"):
                    try:
                        tableau_csv = pd.read_csv(io.BytesIO(fichier_achats.getvalue()), sep=None, engine="python", encoding=encodage, dtype=str)
                        break
                    except Exception:
                        continue
                if tableau_csv is None or tableau_csv.empty:
                    st.error("Ce fichier n'a pas pu être lu. Vérifiez qu'il s'agit bien d'un export CSV (texte séparé par des points-virgules ou des virgules).")
                else:
                    colonnes_csv = [str(c) for c in tableau_csv.columns]
                    tableau_csv.columns = colonnes_csv

                    def _colonne_probable(mots):
                        for c in colonnes_csv:
                            if any(m in _normaliser(c) for m in mots):
                                return colonnes_csv.index(c) + 1
                        return 0

                    choix_aucune = ["(aucune)"] + colonnes_csv
                    col_m1, col_m2, col_m3 = st.columns(3)
                    with col_m1:
                        col_date = st.selectbox("Colonne Date :", choix_aucune, index=_colonne_probable(["date"]), key="map_date")
                        col_valeur = st.selectbox("Colonne Valeur (nom ou symbole) :", choix_aucune,
                                                  index=_colonne_probable(["libelle", "valeur", "titre", "instrument", "produit", "nom", "symbole", "ticker", "action"]), key="map_valeur")
                    with col_m2:
                        col_qte = st.selectbox("Colonne Quantité :", choix_aucune, index=_colonne_probable(["quantite", "qte", "nombre", "quantity"]), key="map_qte")
                        col_prix = st.selectbox("Colonne Prix unitaire :", choix_aucune, index=_colonne_probable(["cours", "prix", "price"]), key="map_prix")
                    with col_m3:
                        col_frais = st.selectbox("Colonne Frais (facultatif, en €) :", choix_aucune, index=_colonne_probable(["frais", "commission", "courtage"]), key="map_frais")
                        col_sens = st.selectbox("Colonne Sens (facultatif : achat / vente) :", choix_aucune,
                                                index=_colonne_probable(["sens", "operation", "nature", "type"]), key="map_sens")
                    taux_import = st.number_input("Taux €/$ appliqué aux achats en dollars de ce fichier (1 € = ? $) :", min_value=0.0, max_value=5.0,
                                                  value=round(float(TAUX_USD_EUR), 4), step=0.01, format="%.4f", key="map_taux")

                    if "(aucune)" in (col_date, col_valeur, col_qte, col_prix):
                        st.info("Indiquez au minimum les colonnes Date, Valeur, Quantité et Prix unitaire.")
                    else:
                        lignes_valides, apercu_import = _analyser_operations([
                            {
                                "date": rangee.get(col_date),
                                "libelle": rangee.get(col_valeur),
                                "qte": rangee.get(col_qte),
                                "prix": rangee.get(col_prix),
                                "frais": rangee.get(col_frais) if col_frais != "(aucune)" else 0.0,
                                "sens": rangee.get(col_sens) if col_sens != "(aucune)" else "",
                            }
                            for _, rangee in tableau_csv.iterrows()
                        ], taux_import)
                        st.dataframe(pd.DataFrame(apercu_import), width="stretch", hide_index=True)
                        if lignes_valides:
                            st.button(f"📥 Importer {len(lignes_valides)} achat(s)", type="primary", width="stretch",
                                      on_click=_importer_achats, args=(lignes_valides,), key="btn_importer_achats")
                        else:
                            st.warning("Aucun achat importable dans ce fichier.")

        # --- IMPORT D'UN HISTORIQUE D'OPÉRATIONS PAR L'IA (CAPTURE D'ÉCRAN OU COPIER-COLLER) ---
        st.markdown("#### 🤖 Importer un historique par capture d'écran ou copier-coller (IA Gemini)")
        if not est_pro_max:
            afficher_verrou_saas(
                "Import d'un historique d'opérations par l'IA (capture d'écran ou copier-coller)",
                "👑 Offre Pro (8,90 €/mois)",
                "Pas d'export CSV ? L'IA lit une capture d'écran de votre historique d'opérations et remplit le journal, dates comprises."
            )
        else:
            st.caption(
                "Faites une capture d'écran de la page « Historique des opérations » ou « Mouvements » de votre courtier, "
                "ou copiez-collez son texte. L'IA en extrait les achats datés ; vous vérifiez l'aperçu avant d'importer."
            )
            compteur_import = st.session_state.get("_compteur_import_achats", 0)
            mode_historique_ia = st.radio("Source :", ["📋 Copier-coller le texte", "📸 Capture d'écran (PNG / JPG)"],
                                          horizontal=True, key="rad_historique_ia")
            parties_ia = None
            if mode_historique_ia.startswith("📋"):
                texte_historique = st.text_area(
                    "Collez ici l'historique de vos opérations :", height=120, key=f"txt_historique_ia_{compteur_import}",
                    placeholder="Ex. : 15/03/2025  Achat  5 AIR LIQUIDE  160,50 €  frais 1,95 €",
                )
                if st.button("🤖 Extraire les opérations de ce texte", key="btn_historique_ia_texte"):
                    if texte_historique.strip():
                        parties_ia = [{"text": f"{CONSIGNE_HISTORIQUE_IA}\n\nHistorique :\n{texte_historique}"}]
                    else:
                        st.warning("Collez d'abord le texte de votre historique.")
            else:
                image_historique = st.file_uploader("Capture d'écran de l'historique", type=["png", "jpg", "jpeg", "webp"],
                                                    key=f"up_historique_ia_{compteur_import}")
                if image_historique is not None and st.button("🤖 Analyser cette capture", key="btn_historique_ia_image"):
                    import base64
                    parties_ia = [
                        {"text": CONSIGNE_HISTORIQUE_IA},
                        {"inline_data": {"mime_type": image_historique.type or "image/jpeg",
                                         "data": base64.b64encode(image_historique.getvalue()).decode("utf-8")}},
                    ]
            if parties_ia is not None:
                with st.spinner("🧠 Lecture de votre historique d'opérations..."):
                    operations_lues, erreur_lecture = _extraire_json_gemini(parties_ia)
                if erreur_lecture:
                    st.error(erreur_lecture)
                else:
                    st.session_state["_operations_ia"] = operations_lues

            if st.session_state.get("_operations_ia"):
                taux_historique_ia = st.number_input(
                    "Taux €/$ appliqué aux achats en dollars de cet historique (1 € = ? $) :", min_value=0.0, max_value=5.0,
                    value=round(float(TAUX_USD_EUR), 4), step=0.01, format="%.4f", key="taux_historique_ia",
                )
                lignes_ia, apercu_ia = _analyser_operations([
                    {"date": o.get("date"), "libelle": o.get("nom"), "qte": o.get("qte"), "prix": o.get("prix"),
                     "frais": o.get("frais", 0.0), "sens": o.get("sens", "")}
                    for o in st.session_state["_operations_ia"] if isinstance(o, dict)
                ], taux_historique_ia)
                st.success(f"✅ {len(apercu_ia)} opération(s) lue(s), dont {len(lignes_ia)} achat(s) importable(s). Vérifiez l'aperçu avant d'importer.")
                st.dataframe(pd.DataFrame(apercu_ia), width="stretch", hide_index=True)
                if lignes_ia:
                    st.button(f"📥 Importer {len(lignes_ia)} achat(s)", type="primary", width="stretch",
                              on_click=_importer_achats, args=(lignes_ia,), key="btn_importer_historique_ia")
                else:
                    st.warning("Aucun achat importable dans cet historique.")

    # ======================================================================
    # CARNET DE DÉCISIONS : POURQUOI J'ACHÈTE, POURQUOI JE VENDS, ET CE QUE C'EST DEVENU (carnet_decisions.py)
    # ======================================================================
    def _noter_decision_carnet():
        type_d = st.session_state.get("cd_type", "achat")
        nom_d = st.session_state.get("cd_action")
        note_d = str(st.session_state.get("cd_note") or "").strip()
        if not nom_d:
            st.session_state["_notif_carnet"] = ("erreur", "Choisissez une valeur.")
            return
        info_d = WATCHLIST_DEFAUT.get(nom_d, {})
        ajouter_decision(st.session_state["portefeuille"], nouvelle_decision(
            st.session_state.get("cd_date", datetime.now().date()), nom_d, symbole_a_jour(info_d.get("symbole", "")), type_d,
            st.session_state.get(f"cd_raison_{type_d}", "Autre"), note_d, info_d.get("devise", "EUR"), "carnet",
        ))
        st.session_state["cd_note"] = ""
        sauvegarder_dans_cloud()
        st.session_state["_notif_carnet"] = ("ok", f"📓 Décision notée : {TYPES_DECISION[type_d].lower()} — {nom_d}.")

    def _enregistrer_lecon_carnet(id_decision):
        if enregistrer_lecon(st.session_state["portefeuille"], id_decision, st.session_state.get(f"cd_lecon_{id_decision}", "")):
            sauvegarder_dans_cloud()
            st.session_state["_notif_carnet"] = ("ok", "💡 Leçon enregistrée.")

    def _supprimer_decision_carnet(id_decision):
        if supprimer_decision(st.session_state["portefeuille"], id_decision):
            sauvegarder_dans_cloud()
            st.session_state["_notif_carnet"] = ("ok", "🗑️ Décision supprimée du carnet.")

    def _date_fr(jour_iso):
        jour_iso = str(jour_iso)[:10]
        return f"{jour_iso[8:10]}/{jour_iso[5:7]}/{jour_iso[0:4]}" if len(jour_iso) == 10 else jour_iso

    def _pct_carnet(valeur):
        return "—" if valeur is None else f"{valeur * 100:+.1f} %"

    carnet_actuel = lire_carnet(st.session_state["portefeuille"])
    # Titre fixe : un titre qui change (nombre de décisions) refermerait le volet après chaque enregistrement
    with st.expander("📓 Carnet de décisions : pourquoi j'achète, pourquoi je vends", expanded=False):
        notif_carnet = st.session_state.pop("_notif_carnet", None)
        if notif_carnet:
            (st.success if notif_carnet[0] == "ok" else st.error)(notif_carnet[1])
        st.caption(
            "Notez en une phrase pourquoi vous achetez, vendez ou préférez attendre. Plus tard, Boursy vous montre ce qu'est "
            f"devenue la valeur, dividendes compris, face à l'{NOM_REFERENCE} sur la même période : de quoi voir quels "
            "raisonnements ont tenu. Les achats et les ventes enregistrés avec une raison y arrivent automatiquement."
        )

        st.markdown("#### ✍️ Noter une décision")
        aujourd_hui_carnet = datetime.now().date()
        options_carnet = sorted([k for k in WATCHLIST_DEFAUT.keys() if k not in CLES_TECHNIQUES_PF])
        col_cd1, col_cd2, col_cd3 = st.columns([1.3, 2, 1])
        with col_cd1:
            type_carnet = st.selectbox("Décision :", list(TYPES_DECISION), format_func=TYPES_DECISION.get, key="cd_type")
        with col_cd2:
            st.selectbox("Valeur :", options_carnet, key="cd_action")
        with col_cd3:
            st.date_input("Date :", value=aujourd_hui_carnet, max_value=aujourd_hui_carnet, key="cd_date", format="DD/MM/YYYY")
        st.selectbox("Raison principale :", RAISONS[type_carnet], key=f"cd_raison_{type_carnet}")
        st.text_area("Pourquoi, en une ou deux phrases :", max_chars=LONGUEUR_NOTE_MAX, key="cd_note", height=80,
                     placeholder="Ex. : je n'achète pas ce mois-ci, le cours a pris 25 % en deux mois ; j'attends un repli.")
        st.button("📓 Noter dans le carnet", type="primary", width="stretch", on_click=_noter_decision_carnet, key="btn_noter_decision")

        if carnet_actuel:
            # Historiques (mis en cache 6 heures) : valeurs du carnet, ETF de référence et change €/$ pour les valeurs en dollars
            symboles_carnet = sorted({symbole_a_jour(d.get("symbole")) for d in carnet_actuel if d.get("symbole")})
            symboles_a_charger = symboles_carnet + [SYMBOLE_REFERENCE] + (["EURUSD=X"] if any(d.get("devise") == "USD" for d in carnet_actuel) else [])
            with ThreadPoolExecutor(max_workers=6) as executeur_carnet:
                historiques_carnet = dict(zip(symboles_a_charger, executeur_carnet.map(historique_long, symboles_a_charger)))
            evaluations_carnet = {
                d["id"]: evaluer_decision(d, historiques_carnet.get(symbole_a_jour(d.get("symbole"))),
                                          historiques_carnet.get(SYMBOLE_REFERENCE), aujourd_hui_carnet, historiques_carnet.get("EURUSD=X"))
                for d in carnet_actuel
            }

            a_relire_carnet = decisions_a_relire(carnet_actuel, aujourd_hui_carnet)
            if a_relire_carnet:
                st.info(
                    f"🔔 {len(a_relire_carnet)} décision(s) ont plus de {HORIZON_RELECTURE_MOIS} mois et attendent votre relecture : "
                    + ", ".join(f"{d['action']} ({_date_fr(d['date'])})" for d in a_relire_carnet[:5])
                    + (" …" if len(a_relire_carnet) > 5 else "") + ". Choisissez-les plus bas, dans « Relire une décision »."
                )

            st.markdown(f"#### 🔎 Ce que sont devenues mes décisions ({len(carnet_actuel)})")
            html_carnet = (
                "<table class='r-table'><thead><tr><th>Date</th><th style='text-align:left;'>Valeur et décision</th>"
                "<th style='text-align:left;'>Pourquoi</th><th>Depuis : valeur · ETF Monde</th>"
                f"<th>Résultat à {HORIZON_RELECTURE_MOIS} mois</th></tr></thead><tbody>"
            )
            for d in carnet_actuel[:40]:
                ev_d = evaluations_carnet[d["id"]]
                depuis_d = ev_d["depuis"]
                mesure_6 = ev_d["horizons"].get(HORIZON_RELECTURE_MOIS)
                if mesure_6:
                    resultat_6 = phrase_resultat(d["type"], mesure_6["action"], mesure_6["reference"])
                    couleur_6 = "#2ecc71" if (mesure_6["en_faveur"] or 0) >= 0 else "#e74c3c"
                    cellule_6 = f"<span style='color:{couleur_6}; font-weight:700;'>{html_lib.escape(resultat_6)}</span>"
                else:
                    cellule_6 = (f"<span style='opacity:0.7;'>le {_date_fr(ajouter_mois(d['date'], HORIZON_RELECTURE_MOIS).isoformat())}</span>")
                pourquoi_d = html_lib.escape(d.get("note") or "—")
                if d.get("lecon"):
                    pourquoi_d += f"<br><span style='font-size:0.85em; opacity:0.8;'>💡 {html_lib.escape(d['lecon'])}</span>"
                html_carnet += (
                    f"<tr><td style='white-space:nowrap;'>{_date_fr(d['date'])}</td>"
                    f"<td class='r-name' style='text-align:left;'><b>{html_lib.escape(d['action'])}</b><br>"
                    f"<span style='font-size:0.85em; opacity:0.8;'>{TYPES_DECISION.get(d['type'], d['type'])} · {html_lib.escape(d.get('raison', ''))}</span></td>"
                    f"<td style='text-align:left; max-width:320px;'>{pourquoi_d}</td>"
                    f"<td style='white-space:nowrap;'>{_pct_carnet(depuis_d['action'] if depuis_d else None)} · {_pct_carnet(depuis_d['reference'] if depuis_d else None)}</td>"
                    f"<td>{cellule_6}</td></tr>"
                )
            html_carnet += "</tbody></table>"
            afficher_html(html_carnet)
            st.caption(
                "Achat : écart avec l'ETF Monde, qu'on aurait pu acheter à la place. Vente ou attente : hausse manquée ou baisse "
                "évitée en ne détenant pas la valeur. Performances de clôture à clôture, dividendes compris, converties en "
                "euros pour les valeurs en dollars."
                + (f" Seules les 40 décisions les plus récentes sont affichées ({len(carnet_actuel)} au total)." if len(carnet_actuel) > 40 else "")
            )

            st.markdown("#### 💡 Relire une décision")
            ordre_relecture = a_relire_carnet + [d for d in carnet_actuel if d not in a_relire_carnet]
            decisions_par_id = {d["id"]: d for d in ordre_relecture}
            ids_a_relire = {d["id"] for d in a_relire_carnet}
            id_relu = st.selectbox(
                "Décision :", list(decisions_par_id), key="cd_relue",
                format_func=lambda i: f"{_date_fr(decisions_par_id[i]['date'])} · {TYPES_DECISION.get(decisions_par_id[i]['type'], '')} · "
                                      f"{decisions_par_id[i]['action']}" + (" 🔔" if i in ids_a_relire else ""),
            )
            decision_relue = decisions_par_id.get(id_relu)
            if decision_relue:
                ev_relue = evaluations_carnet[decision_relue["id"]]
                markdown_fr(
                    f"**{TYPES_DECISION.get(decision_relue['type'])} — {decision_relue['action']}** le {_date_fr(decision_relue['date'])} · "
                    f"*{decision_relue.get('raison', '')}*" + (f" : « {decision_relue['note']} »" if decision_relue.get("note") else "")
                )
                lignes_relue = []
                for mois_r in HORIZONS_MOIS:
                    mesure_r = ev_relue["horizons"].get(mois_r)
                    lignes_relue.append({
                        "Horizon": f"{mois_r} mois",
                        "Valeur": _pct_carnet(mesure_r["action"]) if mesure_r else f"le {_date_fr(ajouter_mois(decision_relue['date'], mois_r).isoformat())}",
                        NOM_REFERENCE: _pct_carnet(mesure_r["reference"]) if mesure_r else "—",
                        "Résultat": phrase_resultat(decision_relue["type"], mesure_r["action"], mesure_r["reference"]) if mesure_r else "pas encore",
                    })
                st.dataframe(pd.DataFrame(lignes_relue).map(nombres_fr), width="stretch", hide_index=True)
                st.text_area("Ce que j'en retiens :", value=decision_relue.get("lecon", ""), max_chars=LONGUEUR_NOTE_MAX, height=80,
                             key=f"cd_lecon_{decision_relue['id']}",
                             placeholder="Ex. : acheter sous mon prix cible a bien marché ; je garde cette règle.")
                col_cl1, col_cl2 = st.columns(2)
                with col_cl1:
                    st.button("💾 Enregistrer ma leçon", width="stretch", key=f"cd_btn_lecon_{decision_relue['id']}",
                              on_click=_enregistrer_lecon_carnet, args=(decision_relue["id"],))
                with col_cl2:
                    with st.popover("🗑️ Supprimer cette décision", width="stretch"):
                        st.caption("La décision et la leçon notée seront effacées du carnet.")
                        st.button("Confirmer la suppression", type="primary", width="stretch", key=f"cd_btn_suppr_{decision_relue['id']}",
                                  on_click=_supprimer_decision_carnet, args=(decision_relue["id"],))

            bilan_carnet = bilan_par_raison(carnet_actuel, evaluations_carnet)
            st.markdown(f"#### 📊 Quels raisonnements ont tenu ? (à {HORIZON_RELECTURE_MOIS} mois)")
            if not bilan_carnet:
                st.caption(f"Le bilan apparaîtra quand vos premières décisions auront {HORIZON_RELECTURE_MOIS} mois.")
            else:
                html_bilan_carnet = (
                    "<table class='r-table'><thead><tr><th style='text-align:left;'>Décision et raison</th><th>Décisions</th>"
                    "<th>Résultat moyen</th><th>Part favorable</th></tr></thead><tbody>"
                )
                for g in bilan_carnet:
                    couleur_g = "#2ecc71" if g["moyenne"] >= 0 else "#e74c3c"
                    html_bilan_carnet += (
                        f"<tr><td class='r-name' style='text-align:left;'>{TYPES_DECISION.get(g['type'])} · {html_lib.escape(g['raison'])}</td>"
                        f"<td>{g['nombre']}</td><td style='color:{couleur_g}; font-weight:800;'>{g['moyenne'] * 100:+.1f} pt</td>"
                        f"<td>{g['part_favorable'] * 100:.0f} %</td></tr>"
                    )
                html_bilan_carnet += "</tbody></table>"
                afficher_html(html_bilan_carnet)
                st.caption(
                    "Résultat moyen : pour un achat, l'écart avec l'ETF Monde ; pour une vente ou une attente, la baisse évitée "
                    "(positive) ou la hausse manquée (négative). Avec moins d'une dizaine de décisions par raison, ces chiffres "
                    "tiennent de l'anecdote : ils servent à se poser des questions, pas à conclure."
                )

    portefeuille_utilisateur = st.session_state["portefeuille"]
    valeur_totale_portefeuille = 0.0
    cout_total_achat = 0.0
    plus_value_globale = 0.0
    plus_value_pct = 0.0
    dividendes_bruts_totaux_eur = 0.0
    dividendes_nets_totaux_eur = 0.0
    repartition_secteurs = {}
    exposition_eur = 0.0
    exposition_usd = 0.0
    lignes_triees = []

    actions_actives_pf = [
        k for k, v in portefeuille_utilisateur.items()
        if k not in ("_historique_ventes", "_quota_ia", "_niveau_abo", "_div_encaisses_cumul") and isinstance(v, dict) and float(v.get("qte", 0)) > 0
    ]

    if not actions_actives_pf:
        st.warning("Votre portefeuille est vide. Ouvrez le volet ci-dessus pour renseigner vos lignes.")
    else:
        if mode_gratuit:
            st.info("🌱 **Forfait Gratuit (0 €)** : Suivi limité à 2 lignes d'actions. Passez à **Premium (4,90 €/mois)** ou **Pro (8,90 €/mois)** pour débloquer un nombre illimité de lignes et l'export CSV !")

        # Fiscalité automatique selon l'enveloppe : PEA (EUR) = 100% en réinvestissement interne, CTO (USD) = 70% net (-30% Flat Tax)
        taux_net_eur = 1.0
        taux_net_usd = 0.70

        lignes_detaillees = []
        variation_jour_totale_eur = 0.0
        lignes_sans_cours = []
        nb_actions_comptees_gratuit = 0

        for nom_act, data_pos in portefeuille_utilisateur.items():
            if nom_act in ("_historique_ventes", "_quota_ia", "_niveau_abo", "_div_encaisses_cumul") or not isinstance(data_pos, dict):
                continue

            if nom_act == "Espèces":
                val_especes = float(data_pos.get("pru", 0.0))
                if val_especes <= 0:
                    continue
                valeur_totale_portefeuille += val_especes
                cout_total_achat += val_especes
                exposition_eur += val_especes
                repartition_secteurs["Liquidités (€)"] = val_especes
                lignes_detaillees.append({
                    "est_especes": True,
                    "nom_act": "Espèces",
                    "env_label": "Liquidités",
                    "devise": "EUR",
                    "sym": "€",
                    "qte": 1,
                    "pru": val_especes,
                    "prix_jour": val_especes,
                    "val_eur": val_especes,
                    "cout_eur": val_especes,
                    "pv_eur": 0.0,
                    "pv_pct": 0.0,
                    "div_brut_l": 0.0,
                    "div_net_l": 0.0,
                })
                continue

            if nom_act not in WATCHLIST_DEFAUT:
                continue

            qte = float(data_pos.get("qte", 0.0))
            if qte <= 0:
                continue

            if mode_gratuit and nb_actions_comptees_gratuit >= 2:
                continue
            nb_actions_comptees_gratuit += 1

            pru = float(data_pos.get("pru", 0.0))
            info_act = WATCHLIST_DEFAUT[nom_act]
            devise = info_act.get("devise", "EUR")
            sym = "$" if devise == "USD" else "€"
            env_label = "CTO US" if devise == "USD" else "PEA"
            facteur = (1.0 / TAUX_USD_EUR) if devise == "USD" else 1.0
            if nom_act in prix_temps_reel:
                prix_jour = float(prix_temps_reel[nom_act])
            else:
                # Cours indisponible : la ligne est valorisée à son PRU (plus-value nulle) et signalée, jamais au prix cible
                prix_jour = pru if pru > 0 else float(info_act.get("prix_cible", 0.0))
                lignes_sans_cours.append(nom_act)

            val_ligne_eur = qte * prix_jour * facteur
            # Coût d'achat converti au taux €/$ du jour de l'achat s'il est renseigné (sinon taux du jour)
            facteur_cout = facteur_cout_usd(data_pos) if devise == "USD" else 1.0
            cout_ligne_eur = qte * pru * facteur_cout
            pv_eur = val_ligne_eur - cout_ligne_eur
            pv_pct = (pv_eur / cout_ligne_eur * 100) if cout_ligne_eur > 0 else 0.0
            div_brut_eur = qte * float(info_act["div_eur"]) * facteur
            div_net_eur = div_brut_eur * (taux_net_usd if devise == "USD" else taux_net_eur)

            # Variation du jour de la ligne (en € et en %), si le cours et la clôture précédente sont connus
            var_jour_pct_l = variations_jour.get(nom_act) if nom_act in prix_temps_reel else None
            var_jour_eur_l = (val_ligne_eur * var_jour_pct_l / (1.0 + var_jour_pct_l)) if (var_jour_pct_l is not None and var_jour_pct_l > -1.0) else 0.0
            variation_jour_totale_eur += var_jour_eur_l

            valeur_totale_portefeuille += val_ligne_eur
            cout_total_achat += cout_ligne_eur
            dividendes_bruts_totaux_eur += div_brut_eur
            dividendes_nets_totaux_eur += div_net_eur

            if devise == "USD":
                exposition_usd += val_ligne_eur
            else:
                exposition_eur += val_ligne_eur

            secteur = info_act["secteur"]
            repartition_secteurs[secteur] = repartition_secteurs.get(secteur, 0.0) + val_ligne_eur

            lignes_detaillees.append({
                "est_especes": False,
                "nom_act": nom_act,
                "env_label": env_label,
                "devise": devise,
                "sym": sym,
                "qte": int(qte),
                "pru": pru,
                "prix_jour": prix_jour,
                "val_eur": val_ligne_eur,
                "cout_eur": cout_ligne_eur,
                "pv_eur": pv_eur,
                "pv_pct": pv_pct,
                "div_brut_l": div_brut_eur,
                "div_net_l": div_net_eur,
                "var_jour_pct": (var_jour_pct_l * 100.0) if var_jour_pct_l is not None else None,
                "var_jour_eur": var_jour_eur_l,
            })

        lignes_triees = sorted(lignes_detaillees, key=lambda x: x["val_eur"], reverse=True)

        if lignes_sans_cours:
            st.warning(
                "⚠️ Cours indisponible pour : **" + ", ".join(lignes_sans_cours) + "**. "
                "Ces lignes sont valorisées à leur PRU (plus-value affichée à 0) en attendant le retour des cours. "
                "Cliquez sur « 🔄 Actualiser les cours Bourse » pour réessayer."
            )

        lignes_export_csv = []
        for l_item in lignes_triees:
            poids_item = (l_item["val_eur"] / valeur_totale_portefeuille * 100) if valeur_totale_portefeuille > 0 else 0.0
            lignes_export_csv.append({
                "Actif": l_item["nom_act"],
                "Enveloppe": l_item["env_label"],
                "Devise": l_item["devise"],
                "Quantite": l_item["qte"],
                "PRU_Devise": round(l_item["pru"], 2),
                "Cours_Actuel_Devise": round(l_item["prix_jour"], 2),
                "Valorisation_EUR": round(l_item["val_eur"], 2),
                "Poids_Portefeuille_Pct": round(poids_item, 2),
                "Plus_Value_EUR": round(l_item["pv_eur"], 2),
                "Dividende_Brut_EUR": round(l_item["div_brut_l"], 2),
                "Dividende_Net_EUR": round(l_item["div_net_l"], 2),
            })

        plus_value_globale = valeur_totale_portefeuille - cout_total_achat
        plus_value_pct = (plus_value_globale / cout_total_achat * 100) if cout_total_achat > 0 else 0.0
        yoc_global = (dividendes_bruts_totaux_eur / cout_total_achat * 100) if cout_total_achat > 0 else 0.0
        part_usd_pct = (exposition_usd / valeur_totale_portefeuille * 100) if valeur_totale_portefeuille > 0 else 0.0
        part_eur_pct = 100.0 - part_usd_pct
        c_pv = "#2ecc71" if plus_value_globale >= 0 else "#e74c3c"
        valeur_veille_pf = valeur_totale_portefeuille - variation_jour_totale_eur
        variation_jour_totale_pct = (variation_jour_totale_eur / valeur_veille_pf * 100.0) if valeur_veille_pf > 0 else 0.0
        c_jour = "#2ecc71" if variation_jour_totale_eur >= 0 else "#e74c3c"

        html_kpi_port = f"""
        <div class="argon-grid bz-5">
            <div class="argon-card">
                <div class="argon-title">💼 Valorisation Totale (€)</div>
                <div class="argon-val">{valeur_totale_portefeuille:,.2f} €</div>
                <div class="argon-sub">Capital investi : <b>{cout_total_achat:,.2f} €</b></div>
            </div>
            <div class="argon-card">
                <div class="argon-title">⚡ Variation du Jour</div>
                <div class="argon-val" style="color:{c_jour};">{variation_jour_totale_eur:+,.2f} €</div>
                <div class="argon-sub" style="color:{c_jour};">Depuis la clôture précédente : <b>{variation_jour_totale_pct:+.2f}%</b></div>
            </div>
            <div class="argon-card">
                <div class="argon-title">📈 Plus/Moins-Value Latente</div>
                <div class="argon-val" style="color:{c_pv};">{plus_value_globale:+,.2f} €</div>
                <div class="argon-sub" style="color:{c_pv};">Performance : <b>{plus_value_pct:+.2f}%</b></div>
            </div>
            <div class="argon-card">
                <div class="argon-title">💰 Rente Brute vs Nette</div>
                <div class="argon-val" style="color:#2ecc71;">{dividendes_nets_totaux_eur:,.2f} € net/an</div>
                <div class="argon-sub">Brut : <b>{dividendes_bruts_totaux_eur:,.2f} €</b> (YoC : {yoc_global:.2f}%)</div>
            </div>
            <div class="argon-card">
                <div class="argon-title">🌍 Exposition Devises</div>
                <div class="argon-val">{part_eur_pct:.0f}% € / {part_usd_pct:.0f}% $</div>
                <div class="argon-sub">PEA : {exposition_eur:,.0f} € | US : {exposition_usd:,.0f} €</div>
            </div>
        </div>
        """
        afficher_html(html_kpi_port)

        col_titre_p, col_btn_csv = st.columns([3, 1])
        with col_titre_p:
            st.subheader("💼 Portefeuille et Performance")
        with col_btn_csv:
            if est_premium_ou_pro:
                df_export = pd.DataFrame(lignes_export_csv)
                csv_bytes = df_export.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig")
                st.download_button(
                    label="📥 Exporter Bilan CSV (Excel)",
                    data=csv_bytes,
                    file_name=f"Boursy_Portefeuille_{datetime.now().strftime('%Y-%m-%d')}.csv",
                    mime="text/csv",
                    width="stretch",
                )
            else:
                st.button("🔒 Export CSV (Offre Premium/Pro)", disabled=True, width="stretch")

        html_port = "<table class='r-table'><thead><tr><th style='text-align: left;'>Actif (Enveloppe)</th><th>Qté</th><th>PRU ➔ Cours</th><th>Valorisation (€)</th><th>+/- Value (€ & %)</th><th>Div. Brut / Net (€)</th><th style='width:140px;'>Poids (%)</th></tr></thead><tbody>"

        for l_item in lignes_triees:
            poids = (l_item["val_eur"] / valeur_totale_portefeuille * 100) if valeur_totale_portefeuille > 0 else 0.0
            if l_item["est_especes"]:
                html_port += f"""
                <tr>
                    <td class='r-name'>💶 Espèces (Liquidités)</td>
                    <td>-</td>
                    <td>-</td>
                    <td><b>{l_item['val_eur']:,.2f} €</b></td>
                    <td><span class='b-neutral'>0.00 €</span></td>
                    <td>-</td>
                    <td>
                        <div style="font-weight:800;">{poids:.1f}%</div>
                        <div class="score-bg"><div style="width:{min(100, poids)}%; background:#95a5a6; height:100%;"></div></div>
                    </td>
                </tr>
                """
            else:
                b_pv = "b-green" if l_item["pv_eur"] >= 0 else "b-red"
                vj_l = l_item.get("var_jour_pct")
                badge_jour_l = (
                    f"<br><span style='font-size:0.80em; font-weight:700; color:{'#2ecc71' if vj_l >= 0 else '#e74c3c'};'>"
                    f"{'▲' if vj_l >= 0 else '▼'} {vj_l:+.2f}% aujourd'hui</span>"
                    if vj_l is not None else ""
                )
                html_port += f"""
                <tr>
                    <td class="r-name">{l_item['nom_act']} <span class="b-neutral" style="font-size:0.75em;">{l_item['env_label']}</span></td>
                    <td><b>{l_item['qte']}</b></td>
                    <td style="white-space:nowrap;">{l_item['pru']:.2f} {l_item['sym']} ➔ <b>{l_item['prix_jour']:.2f} {l_item['sym']}</b>{badge_jour_l}</td>
                    <td><b>{l_item['val_eur']:,.2f} €</b></td>
                    <td><span class="{b_pv}">{l_item['pv_eur']:+,.2f} € ({l_item['pv_pct']:+.1f}%)</span></td>
                    <td><span style="opacity:0.75;">{l_item['div_brut_l']:.1f} €</span> ➔ <b style="color:#2ecc71;">{l_item['div_net_l']:.2f} € net</b></td>
                    <td>
                        <div style="font-weight:800;">{poids:.1f}%</div>
                        <div class="score-bg"><div style="width:{min(100, poids)}%; background:#3498db; height:100%;"></div></div>
                    </td>
                </tr>
                """
        html_port += "</tbody></table>"
        afficher_html(html_port)

        col_sec, col_hist = st.columns(2)

        with col_sec:
            st.subheader("🍩 Répartition sectorielle du portefeuille")
            secteurs_tries = sorted(repartition_secteurs.items(), key=lambda x: x[1], reverse=True)
            df_camembert = pd.DataFrame([
                {
                    "Secteur": sec,
                    "Montant (€)": round(montant_s, 2),
                    "Poids (%)": round((montant_s / valeur_totale_portefeuille * 100) if valeur_totale_portefeuille > 0 else 0.0, 1),
                }
                for sec, montant_s in secteurs_tries
            ])

            spec_camembert = {
                "height": 310,
                "mark": {"type": "arc", "innerRadius": 55, "outerRadius": 125, "stroke": "#ffffff", "strokeWidth": 2},
                "encoding": {
                    "theta": {"field": "Montant (€)", "type": "quantitative", "stack": True},
                    "color": {
                        "field": "Secteur",
                        "type": "nominal",
                        "scale": {"range": ["#2ecc71", "#3498db", "#9b59b6", "#f1c40f", "#e67e22", "#e74c3c", "#1abc9c", "#34495e", "#fd79a8"]},
                        "legend": {"title": "Secteurs", "orient": "right"},
                    },
                    "tooltip": [
                        {"field": "Secteur", "type": "nominal"},
                        {"field": "Montant (€)", "type": "quantitative", "format": ",.2f"},
                        {"field": "Poids (%)", "type": "quantitative", "format": ".1f"},
                    ],
                },
                "view": {"stroke": None},
            }
            st.vega_lite_chart(df_camembert, spec_camembert, width="stretch")

            html_sec = "<div style='background:rgba(128,128,128,0.04); padding:14px; border-radius:12px; border:1px solid rgba(128,128,128,0.18);'>"
            for row_s in df_camembert.to_dict("records"):
                pct_s = row_s["Poids (%)"]
                c_sec = "#e74c3c" if pct_s > 35 else ("#f39c12" if pct_s > 25 else "#2ecc71")
                html_sec += f"""
                <div style="margin-bottom: 9px;">
                    <div style="display:flex; justify-content:space-between; font-size:0.88em; font-weight:700; margin-bottom:3px;">
                        <span>{row_s['Secteur']}</span>
                        <span>{row_s['Montant (€)']:,.0f} € ({pct_s:.1f}%)</span>
                    </div>
                    <div class="score-bg"><div style="width:{min(100, pct_s)}%; background:{c_sec}; height:100%;"></div></div>
                </div>
                """
            html_sec += "</div>"
            afficher_html(html_sec)

        with col_hist:
            st.subheader("🚀 Trajectoire & Benchmark vs ETF MSCI World (CW8)")
            col_h_rad, col_h_chk = st.columns([2.2, 1.8])
            with col_h_rad:
                choix_horizon_courbe = st.radio(
                    "Horizon boursier :",
                    ["1 Mois", "6 Mois", "1 An", "3 Ans"],
                    index=2,
                    horizontal=True,
                    label_visibility="collapsed",
                )
            with col_h_chk:
                afficher_bench_cw8 = st.checkbox("🌍 Comparer à l'ETF MSCI World (CW8)", value=True)

            map_jours = {"1 Mois": 22, "6 Mois": 126, "1 An": 252, "3 Ans": 750}
            nb_j_cible = map_jours[choix_horizon_courbe]

            longueurs_dispo = [
                len(historiques_prix[nom_a])
                for nom_a in portefeuille_utilisateur
                if nom_a not in CLES_TECHNIQUES_PF and nom_a in historiques_prix and len(historiques_prix[nom_a]) > 1
            ]
            nb_jours_reels = min(nb_j_cible, min(longueurs_dispo)) if longueurs_dispo else 30
            dates_bourse = pd.bdate_range(end=datetime.now(), periods=nb_jours_reels)
            pas_echantillon = 3 if nb_jours_reels > 300 else 1

            _, closes_cw8_brut, _, _ = recuperer_donnees("CW8.PA") if afficher_bench_cw8 else (None, None, None, None)
            serie_cw8 = closes_cw8_brut if closes_cw8_brut else []

            val_esp_fixe = float(portefeuille_utilisateur.get("Espèces", {}).get("pru", 0.0)) if isinstance(portefeuille_utilisateur.get("Espèces"), dict) else 0.0
            donnees_courbe_reelle = []
            valeurs_quotidiennes = []
            valeurs_cw8_rebased = []
            val_depart_pf = None
            cw8_depart = None

            noms_retenus_courbe = [l["nom_act"] for l in lignes_triees if not l["est_especes"]]

            for idx_j in range(0, nb_jours_reels, pas_echantillon):
                offset_fin = idx_j - nb_jours_reels
                val_jour_eur = val_esp_fixe

                for nom_a in noms_retenus_courbe:
                    d_pos = portefeuille_utilisateur.get(nom_a, {})
                    if not isinstance(d_pos, dict) or nom_a not in WATCHLIST_DEFAUT:
                        continue
                    q_a = float(d_pos.get("qte", 0.0))
                    dev_a = WATCHLIST_DEFAUT[nom_a].get("devise", "EUR")
                    fact_a = (1.0 / TAUX_USD_EUR) if dev_a == "USD" else 1.0
                    serie_c = historiques_prix.get(nom_a, [])
                    if serie_c:
                        p_hist = serie_c[offset_fin] if abs(offset_fin) <= len(serie_c) else serie_c[0]
                    else:
                        p_hist = float(prix_temps_reel.get(nom_a, d_pos.get("pru", 0.0)))
                    val_jour_eur += q_a * p_hist * fact_a

                if idx_j >= nb_jours_reels - pas_echantillon:
                    val_jour_eur = valeur_totale_portefeuille

                if val_depart_pf is None:
                    val_depart_pf = max(1.0, val_jour_eur)
                    if serie_cw8:
                        cw8_depart = serie_cw8[offset_fin] if abs(offset_fin) <= len(serie_cw8) else serie_cw8[0]

                date_iso = dates_bourse[idx_j].strftime("%Y-%m-%d")
                date_fr = dates_bourse[idx_j].strftime("%d/%m/%Y")
                ecart_pru_jour = round(val_jour_eur - cout_total_achat, 2)
                valeurs_quotidiennes.append((date_fr, round(val_jour_eur, 2)))

                donnees_courbe_reelle.append({
                    "Date": date_iso,
                    "DateFR": date_fr,
                    "Série": "Valorisation Portefeuille (€)",
                    "Montant (€)": round(val_jour_eur, 2),
                    "Écart vs PRU (€)": ecart_pru_jour,
                })
                donnees_courbe_reelle.append({
                    "Date": date_iso,
                    "DateFR": date_fr,
                    "Série": "Capital Investi / PRU (€)",
                    "Montant (€)": round(cout_total_achat, 2),
                    "Écart vs PRU (€)": ecart_pru_jour,
                })

                if afficher_bench_cw8 and serie_cw8 and cw8_depart and cw8_depart > 0:
                    p_cw8_j = serie_cw8[offset_fin] if abs(offset_fin) <= len(serie_cw8) else serie_cw8[0]
                    val_cw8_eq = val_depart_pf * (p_cw8_j / cw8_depart)
                    valeurs_cw8_rebased.append(val_cw8_eq)
                    donnees_courbe_reelle.append({
                        "Date": date_iso,
                        "DateFR": date_fr,
                        "Série": "Benchmark ETF MSCI World CW8 (€)",
                        "Montant (€)": round(val_cw8_eq, 2),
                        "Écart vs PRU (€)": round(val_cw8_eq - cout_total_achat, 2),
                    })

            df_courbe_reelle = pd.DataFrame(donnees_courbe_reelle)
            domain_series = ["Valorisation Portefeuille (€)", "Capital Investi / PRU (€)"]
            range_colors = ["#2ecc71", "#3498db"]
            range_dash = [[1, 0], [6, 4]]
            range_width = [2.8, 2.0]
            if afficher_bench_cw8 and valeurs_cw8_rebased:
                domain_series.append("Benchmark ETF MSCI World CW8 (€)")
                range_colors.append("#9b59b6")
                range_dash.append([3, 3])
                range_width.append(2.2)

            spec_courbe_bourse = {
                "height": 275,
                "layer": [
                    {
                        "mark": {"type": "line", "interpolate": "monotone"},
                        "encoding": {
                            "x": {"field": "Date", "type": "temporal", "axis": {"title": None, "format": "%b %Y", "grid": False}},
                            "y": {"field": "Montant (€)", "type": "quantitative", "scale": {"zero": False, "padding": 18}, "axis": {"title": "Valeur (€)", "format": ",.0f"}},
                            "color": {
                                "field": "Série",
                                "type": "nominal",
                                "scale": {"domain": domain_series, "range": range_colors},
                                "legend": {"orient": "top", "title": None},
                            },
                            "strokeDash": {
                                "field": "Série",
                                "type": "nominal",
                                "scale": {"domain": domain_series, "range": range_dash},
                                "legend": None,
                            },
                            "strokeWidth": {
                                "field": "Série",
                                "type": "nominal",
                                "scale": {"domain": domain_series, "range": range_width},
                                "legend": None,
                            },
                            "tooltip": [
                                {"field": "DateFR", "type": "nominal", "title": "Séance du"},
                                {"field": "Série", "type": "nominal", "title": "Courbe"},
                                {"field": "Montant (€)", "type": "quantitative", "format": ",.2f", "title": "Montant (€)"},
                                {"field": "Écart vs PRU (€)", "type": "quantitative", "format": "+,.2f", "title": "+/- Value vs PRU (€)"},
                            ],
                        },
                    },
                ],
                "view": {"stroke": None},
            }
            st.vega_lite_chart(df_courbe_reelle, spec_courbe_bourse, width="stretch")

            if valeurs_quotidiennes:
                pt_debut = valeurs_quotidiennes[0]
                pt_fin = valeurs_quotidiennes[-1]
                var_periode_eur = pt_fin[1] - pt_debut[1]
                var_periode_pct = (var_periode_eur / pt_debut[1] * 100.0) if pt_debut[1] > 0 else 0.0
                c_var_p = "#2ecc71" if var_periode_eur >= 0 else "#e74c3c"

                pic_courant = valeurs_quotidiennes[0][1]
                max_dd_pct = 0.0
                for _, v_j in valeurs_quotidiennes:
                    if v_j > pic_courant:
                        pic_courant = v_j
                    dd_j = ((v_j - pic_courant) / pic_courant * 100.0) if pic_courant > 0 else 0.0
                    if dd_j < max_dd_pct:
                        max_dd_pct = dd_j

                if valeurs_cw8_rebased and len(valeurs_cw8_rebased) >= 2:
                    perf_cw8_pct = ((valeurs_cw8_rebased[-1] - valeurs_cw8_rebased[0]) / valeurs_cw8_rebased[0] * 100.0) if valeurs_cw8_rebased[0] > 0 else 0.0
                    alpha_pct = var_periode_pct - perf_cw8_pct
                    c_alpha = "#2ecc71" if alpha_pct >= 0 else "#f39c12"
                    ligne_bench_html = (
                        f"<div style='display:flex; justify-content:space-between; padding:5px 0; border-bottom:1px solid rgba(128,128,128,0.12); font-size:0.88em;'>"
                        f"<span>🌍 <b>ETF MSCI World (CW8)</b> sur {choix_horizon_courbe}</span>"
                        f"<span style='font-weight:800; color:{c_alpha};'>CW8 : {perf_cw8_pct:+.1f}% (Alpha : {alpha_pct:+.1f}%)</span>"
                        f"</div>"
                    )
                else:
                    ligne_bench_html = ""

                html_bilan_traj = f"""
                <div style="background:rgba(128,128,128,0.04); padding:14px; border-radius:12px; border:1px solid rgba(128,128,128,0.18);">
                    <div style="font-size:0.82em; font-weight:800; text-transform:uppercase; opacity:0.75; margin-bottom:9px;">⚡ Indicateurs Quantitatifs sur {choix_horizon_courbe}</div>
                    <div style="display:flex; justify-content:space-between; padding:5px 0; border-bottom:1px solid rgba(128,128,128,0.12); font-size:0.88em;">
                        <span>📈 <b>Performance Portefeuille ({choix_horizon_courbe})</b></span>
                        <span style="color:{c_var_p}; font-weight:800;">{var_periode_eur:+,.0f} € ({var_periode_pct:+.1f}%)</span>
                    </div>
                    {ligne_bench_html}
                    <div style="display:flex; justify-content:space-between; padding:5px 0; border-bottom:1px solid rgba(128,128,128,0.12); font-size:0.88em;">
                        <span>🛡️ <b>Max Drawdown</b> (Repli max sur la période)</span>
                        <span style="color:#3498db; font-weight:800;">{max_dd_pct:.1f}%</span>
                    </div>
                    <div style="display:flex; justify-content:space-between; padding:5px 0; font-size:0.88em;">
                        <span>🎯 <b>Écart actuel vs PRU ({cout_total_achat:,.0f} €)</b></span>
                        <span style="color:{c_pv}; font-weight:800;">{plus_value_globale:+,.0f} € ({plus_value_pct:+.1f}%)</span>
                    </div>
                </div>
                """
                afficher_html(html_bilan_traj)

        # ======================================================================
        # ÉVOLUTION RÉELLE DU PORTEFEUILLE (SNAPSHOTS ENREGISTRÉS À CHAQUE SAUVEGARDE)
        # ======================================================================
        if supabase and st.session_state.get("user") is not None:
            with st.expander("📈 Évolution réelle de mon portefeuille (historique de mes sauvegardes)", expanded=True):
                if mode_gratuit:
                    afficher_verrou_saas(
                        "Évolution réelle du portefeuille (historique jour par jour)",
                        "⚡ Offre Premium (4,90 €/mois) ou 👑 Pro (8,90 €/mois)",
                        "Suivez la vraie trajectoire de votre patrimoine, versements et plus-values séparés."
                    )
                else:
                    uid_hist = str(st.session_state["user"].id)
                    cache_hist = st.session_state.get("_historique_snapshots")
                    if not isinstance(cache_hist, dict) or cache_hist.get("uid") != uid_hist:
                        try:
                            rep_hist = (
                                supabase.table("portfolio_history")
                                .select("date, capital_investi, valorisation_pea, rente_annuelle")
                                .eq("user_id", uid_hist)
                                .order("date")
                                .execute()
                            )
                            cache_hist = {"uid": uid_hist, "lignes": list(rep_hist.data or []), "erreur": False}
                        except Exception:
                            cache_hist = {"uid": uid_hist, "lignes": [], "erreur": True}
                        st.session_state["_historique_snapshots"] = cache_hist

                    points_hist = []
                    for ligne_h in cache_hist.get("lignes", []):
                        try:
                            points_hist.append({
                                "date": str(ligne_h.get("date", ""))[:10],
                                "valo": float(ligne_h.get("valorisation_pea") or 0.0),
                                "capital": float(ligne_h.get("capital_investi") or 0.0),
                                "rente": float(ligne_h.get("rente_annuelle") or 0.0),
                            })
                        except Exception:
                            continue
                    points_hist = sorted((pt for pt in points_hist if len(pt["date"]) == 10 and pt["valo"] > 0), key=lambda pt: pt["date"])

                    if cache_hist.get("erreur"):
                        st.info("L'historique n'a pas pu être lu pour le moment.")
                        if st.button("🔄 Réessayer", key="btn_relire_historique"):
                            st.session_state.pop("_historique_snapshots", None)
                            st.rerun()
                    elif len(points_hist) < 2:
                        st.info(
                            "Votre historique se construit tout seul : un point est enregistré chaque jour où vous sauvegardez "
                            "votre portefeuille. La courbe apparaîtra dès le deuxième jour enregistré."
                        )
                    else:
                        choix_periode_hist = st.radio(
                            "Période affichée :",
                            ["3 mois", "1 an", "Tout l'historique"],
                            index=2,
                            horizontal=True,
                            key="rad_periode_historique",
                        )
                        if choix_periode_hist != "Tout l'historique":
                            nb_jours_hist = 92 if choix_periode_hist == "3 mois" else 366
                            date_min_hist = (pd.Timestamp(points_hist[-1]["date"]) - pd.Timedelta(days=nb_jours_hist)).strftime("%Y-%m-%d")
                            points_periode = [pt for pt in points_hist if pt["date"] >= date_min_hist]
                            if len(points_periode) < 2:
                                points_periode = points_hist[-2:]
                        else:
                            points_periode = points_hist

                        pt_deb, pt_fin = points_periode[0], points_periode[-1]
                        delta_valo_h = pt_fin["valo"] - pt_deb["valo"]
                        delta_capital_h = pt_fin["capital"] - pt_deb["capital"]
                        gain_marche_h = delta_valo_h - delta_capital_h
                        gain_marche_pct_h = (gain_marche_h / pt_deb["valo"] * 100.0) if pt_deb["valo"] > 0 else 0.0
                        delta_rente_h = pt_fin["rente"] - pt_deb["rente"]
                        c_gain_h = "#2ecc71" if gain_marche_h >= 0 else "#e74c3c"
                        date_deb_fr = f"{pt_deb['date'][8:10]}/{pt_deb['date'][5:7]}/{pt_deb['date'][0:4]}"

                        afficher_html(f"""
                        <div class="argon-grid">
                            <div class="argon-card">
                                <div class="argon-title">💼 Valorisation enregistrée</div>
                                <div class="argon-val">{pt_fin['valo']:,.2f} €</div>
                                <div class="argon-sub">Depuis le {date_deb_fr} : <b>{delta_valo_h:+,.0f} €</b></div>
                            </div>
                            <div class="argon-card">
                                <div class="argon-title">💶 Versements sur la période</div>
                                <div class="argon-val" style="color:#3498db;">{delta_capital_h:+,.0f} €</div>
                                <div class="argon-sub">Capital investi : <b>{pt_fin['capital']:,.0f} €</b></div>
                            </div>
                            <div class="argon-card">
                                <div class="argon-title">📈 Gain dû aux marchés</div>
                                <div class="argon-val" style="color:{c_gain_h};">{gain_marche_h:+,.0f} €</div>
                                <div class="argon-sub" style="color:{c_gain_h};">Hors versements : <b>{gain_marche_pct_h:+.1f}%</b></div>
                            </div>
                            <div class="argon-card">
                                <div class="argon-title">💰 Rente annuelle</div>
                                <div class="argon-val" style="color:#2ecc71;">{pt_fin['rente']:,.0f} € / an</div>
                                <div class="argon-sub">Évolution : <b>{delta_rente_h:+,.0f} € / an</b></div>
                            </div>
                        </div>
                        """)

                        donnees_hist_graph = []
                        for pt in points_periode:
                            date_fr_h = f"{pt['date'][8:10]}/{pt['date'][5:7]}/{pt['date'][0:4]}"
                            donnees_hist_graph.append({"Date": pt["date"], "DateFR": date_fr_h, "Série": "Valorisation réelle (€)", "Montant (€)": round(pt["valo"], 2)})
                            donnees_hist_graph.append({"Date": pt["date"], "DateFR": date_fr_h, "Série": "Capital investi (€)", "Montant (€)": round(pt["capital"], 2)})
                        series_hist = ["Valorisation réelle (€)", "Capital investi (€)"]
                        st.vega_lite_chart(
                            pd.DataFrame(donnees_hist_graph),
                            {
                                "height": 300,
                                "mark": {"type": "line", "interpolate": "monotone", "point": len(points_periode) <= 40},
                                "encoding": {
                                    "x": {"field": "Date", "type": "temporal", "axis": {"title": None, "format": "%d/%m/%y", "grid": False}},
                                    "y": {"field": "Montant (€)", "type": "quantitative", "scale": {"zero": False, "padding": 18}, "axis": {"title": "Valeur (€)", "format": ",.0f"}},
                                    "color": {"field": "Série", "type": "nominal", "scale": {"domain": series_hist, "range": ["#2ecc71", "#3498db"]}, "legend": {"orient": "top", "title": None}},
                                    "strokeDash": {"field": "Série", "type": "nominal", "scale": {"domain": series_hist, "range": [[1, 0], [6, 4]]}, "legend": None},
                                    "tooltip": [
                                        {"field": "DateFR", "type": "nominal", "title": "Sauvegarde du"},
                                        {"field": "Série", "type": "nominal", "title": "Courbe"},
                                        {"field": "Montant (€)", "type": "quantitative", "format": ",.2f"},
                                    ],
                                },
                                "view": {"stroke": None},
                            },
                            width="stretch",
                        )
                        st.caption(
                            f"{len(points_hist)} jour(s) enregistré(s). Contrairement à la trajectoire simulée ci-dessus, cette courbe "
                            "reflète vos vraies valorisations, versements et ventes inclus, telles qu'enregistrées à chaque sauvegarde."
                        )

        # ======================================================================
        # PERFORMANCE RÉELLE (TRI) COMPARÉE À UN ETF MSCI WORLD AVEC LES MÊMES VERSEMENTS
        # ======================================================================
        with st.expander("🏁 Ma performance réelle comparée à un ETF MSCI World (mêmes versements, mêmes dates)", expanded=False):
            if not est_premium_ou_pro:
                afficher_verrou_saas(
                    "Performance réelle annualisée comparée à un ETF MSCI World",
                    "⚡ Offre Premium (4,90 €/mois) ou 👑 Pro (8,90 €/mois)",
                    "Votre vrai rendement annualisé, comparé à ce qu'auraient donné les mêmes sommes, aux mêmes dates, dans un ETF Monde."
                )
            else:
                pf_perf = st.session_state["portefeuille"]
                journal_perf = pf_perf.get("_journal_achats") if isinstance(pf_perf.get("_journal_achats"), list) else []
                ventes_perf = [v for v in st.session_state.get("historique_ventes", []) if isinstance(v, dict)]
                aujourd_hui_iso = datetime.now().date().isoformat()

                achats_par_action = {}
                for entree_p in journal_perf:
                    achats_par_action.setdefault(entree_p.get("action"), []).append(entree_p)

                flux_perf, lignes_perf, exclusions_perf = [], [], []
                for action_p, entrees_p in sorted(achats_par_action.items()):
                    entrees_p = sorted(entrees_p, key=lambda e: (str(e.get("date", "")), str(e.get("id", ""))))
                    info_p = WATCHLIST_DEFAUT.get(action_p, {})
                    est_usd_p = info_p.get("devise") == "USD"
                    if int((entrees_p[0].get("avant") or {}).get("qte", 0) or 0) > 0:
                        exclusions_perf.append((action_p, "détenue avant votre premier achat enregistré dans le journal"))
                        continue
                    date_debut_p = str(entrees_p[0].get("date", ""))
                    ventes_p = [v for v in ventes_perf if v.get("action") == action_p and str(v.get("date", "")) >= date_debut_p]
                    qte_attendue_p = sum(int(e.get("qte", 0)) for e in entrees_p) - sum(int(v.get("qte", 0)) for v in ventes_p)
                    position_p = pf_perf.get(action_p)
                    qte_actuelle_p = int(position_p.get("qte", 0)) if isinstance(position_p, dict) else 0
                    if qte_actuelle_p != qte_attendue_p:
                        exclusions_perf.append((action_p, "quantité modifiée en dehors du journal et des ventes"))
                        continue
                    if qte_actuelle_p > 0 and action_p not in prix_temps_reel:
                        exclusions_perf.append((action_p, "cours du jour indisponible"))
                        continue
                    historique_p = historique_long(info_p.get("symbole", "")) if info_p.get("symbole") else None
                    if historique_p is None:
                        exclusions_perf.append((action_p, "historique de cours indisponible"))
                        continue

                    mouvements_p = []
                    for e in entrees_p:
                        taux_e = float(e.get("taux_change") or TAUX_USD_EUR) if est_usd_p else 1.0
                        montant_e = float(e.get("qte", 0)) * float(e.get("prix", 0)) / taux_e + float(e.get("frais_eur", 0) or 0)
                        flux_perf.append((str(e["date"]), -montant_e, "Achat"))
                        mouvements_p.append((str(e["date"]), int(e.get("qte", 0))))
                    for v in ventes_p:
                        flux_perf.append((str(v["date"]), float(v.get("montant_eur", 0) or 0), "Vente"))
                        mouvements_p.append((str(v["date"]), -int(v.get("qte", 0))))
                    facteur_dividende_p = (0.70 / TAUX_USD_EUR) if est_usd_p else 1.0
                    for date_div, montant_div in historique_p[2]:
                        if date_debut_p < date_div <= aujourd_hui_iso:
                            qte_au_detachement = sum(q for d, q in mouvements_p if d < date_div)
                            if qte_au_detachement > 0:
                                flux_perf.append((date_div, qte_au_detachement * montant_div * facteur_dividende_p, "Dividende"))
                    facteur_valeur_p = (1.0 / TAUX_USD_EUR) if est_usd_p else 1.0
                    lignes_perf.append({
                        "action": action_p, "mouvements": mouvements_p, "historique": historique_p, "facteur": facteur_valeur_p,
                        "valeur_finale": qte_actuelle_p * float(prix_temps_reel.get(action_p, 0.0)) * facteur_valeur_p,
                    })

                historique_etf = historique_long("CW8.PA")
                if not lignes_perf:
                    st.info(
                        "Pour calculer votre performance réelle, Boursy a besoin de l'historique complet d'au moins une ligne : "
                        "tous ses achats enregistrés dans le 🧾 Journal des achats (saisie, import CSV ou import par l'IA), depuis le premier."
                    )
                elif historique_etf is None:
                    st.warning("L'historique de l'ETF MSCI World (CW8) est indisponible pour le moment. Réessayez dans quelques minutes.")
                else:
                    flux_perf.sort(key=lambda f: f[0])
                    date_premier_flux = flux_perf[0][0]
                    # L'ETF reçoit exactement les mêmes versements et retraits, aux mêmes dates (méthode PME de Long et Nickels)
                    parts_etf, flux_etf_dates = 0.0, []
                    for date_f, montant_f, _ in flux_perf:
                        cours_etf = cours_a_la_date(historique_etf, date_f) or historique_etf[1][0]
                        parts_etf -= montant_f / cours_etf
                        flux_etf_dates.append((date_f, parts_etf))
                    valeur_portefeuille_perf = sum(l["valeur_finale"] for l in lignes_perf)
                    valeur_etf_perf = parts_etf * historique_etf[1][-1]
                    tri_portefeuille = taux_rendement_interne([(d, m) for d, m, _ in flux_perf] + [(aujourd_hui_iso, valeur_portefeuille_perf)])
                    tri_etf = taux_rendement_interne([(d, m) for d, m, _ in flux_perf] + [(aujourd_hui_iso, valeur_etf_perf)])
                    total_verse = -sum(m for _, m, n in flux_perf if n == "Achat")
                    total_ventes = sum(m for _, m, n in flux_perf if n == "Vente")
                    total_dividendes = sum(m for _, m, n in flux_perf if n == "Dividende")
                    gain_portefeuille = valeur_portefeuille_perf + total_ventes + total_dividendes - total_verse
                    ecart_valeur = valeur_portefeuille_perf - valeur_etf_perf
                    duree_jours = (datetime.now().date() - datetime.fromisoformat(date_premier_flux).date()).days
                    c_tri = "#2ecc71" if (tri_portefeuille or 0) >= 0 else "#e74c3c"
                    c_ecart = "#2ecc71" if ecart_valeur >= 0 else "#f39c12"
                    texte_tri = f"{tri_portefeuille * 100:+.2f} % / an" if tri_portefeuille is not None else "Non calculable"
                    texte_tri_etf = f"{tri_etf * 100:+.2f} % / an" if tri_etf is not None else "Non calculable"
                    texte_ecart_tri = (f"{(tri_portefeuille - tri_etf) * 100:+.2f} point(s) par an"
                                       if (tri_portefeuille is not None and tri_etf is not None) else "—")
                    date_premier_fr = f"{date_premier_flux[8:10]}/{date_premier_flux[5:7]}/{date_premier_flux[0:4]}"
                    performance_vs_etf = {
                        "tri": tri_portefeuille, "tri_etf": tri_etf, "depuis": date_premier_flux, "jours": duree_jours,
                        "valeur": valeur_portefeuille_perf, "valeur_etf": valeur_etf_perf,
                        "lignes": len(lignes_perf), "exclues": len(exclusions_perf),
                    }

                    afficher_html(f"""
                    <div class="argon-grid">
                        <div class="argon-card" style="border-top: 3px solid {c_tri};">
                            <div class="argon-title">🏁 Votre rendement annualisé</div>
                            <div class="argon-val" style="color:{c_tri};">{texte_tri}</div>
                            <div class="argon-sub">Gain total : <b>{gain_portefeuille:+,.0f} €</b> depuis le {date_premier_fr}</div>
                        </div>
                        <div class="argon-card" style="border-top: 3px solid #3498db;">
                            <div class="argon-title">🌍 Mêmes versements dans le CW8</div>
                            <div class="argon-val" style="color:#3498db;">{texte_tri_etf}</div>
                            <div class="argon-sub">Valeur aujourd'hui : <b>{valeur_etf_perf:,.0f} €</b></div>
                        </div>
                        <div class="argon-card" style="border-top: 3px solid {c_ecart};">
                            <div class="argon-title">⚖️ Écart avec l'ETF</div>
                            <div class="argon-val" style="color:{c_ecart};">{ecart_valeur:+,.0f} €</div>
                            <div class="argon-sub">Soit <b>{texte_ecart_tri}</b></div>
                        </div>
                        <div class="argon-card" style="border-top: 3px solid #9b59b6;">
                            <div class="argon-title">💶 Vos flux</div>
                            <div class="argon-val" style="font-size:1.2em;">{total_verse:,.0f} € versés</div>
                            <div class="argon-sub">Ventes : <b>{total_ventes:,.0f} €</b> · Dividendes estimés : <b>{total_dividendes:,.0f} €</b></div>
                        </div>
                    </div>
                    """)
                    if duree_jours < 365:
                        st.caption("⚠️ Sur moins d'un an, le rendement annualisé est très sensible aux variations récentes : regardez surtout l'écart en euros.")

                    # Courbe mensuelle : valeur des lignes retenues, valeur de l'ETF avec les mêmes flux, argent investi net
                    points_courbe = sorted(set(
                        [d.date().isoformat() for d in pd.date_range(date_premier_flux, aujourd_hui_iso, freq="MS")]
                        + [date_premier_flux, aujourd_hui_iso]
                    ))
                    donnees_courbe_perf = []
                    for date_c in points_courbe:
                        investi_net = -sum(m for d, m, n in flux_perf if d <= date_c and n in ("Achat", "Vente"))
                        if date_c == aujourd_hui_iso:
                            valeur_pf_c = valeur_portefeuille_perf
                        else:
                            valeur_pf_c = sum(
                                sum(q for d, q in l["mouvements"] if d <= date_c) * (cours_a_la_date(l["historique"], date_c) or 0.0) * l["facteur"]
                                for l in lignes_perf
                            )
                        parts_c = next((p for d, p in reversed(flux_etf_dates) if d <= date_c), 0.0)
                        valeur_etf_c = parts_c * (cours_a_la_date(historique_etf, date_c) or 0.0)
                        date_fr_c = f"{date_c[8:10]}/{date_c[5:7]}/{date_c[0:4]}"
                        for serie_c, valeur_c in (("Vos lignes (€)", valeur_pf_c), ("Mêmes versements dans le CW8 (€)", valeur_etf_c), ("Argent investi net (€)", investi_net)):
                            donnees_courbe_perf.append({"Date": date_c, "DateFR": date_fr_c, "Série": serie_c, "Montant (€)": round(valeur_c, 2)})
                    series_perf = ["Vos lignes (€)", "Mêmes versements dans le CW8 (€)", "Argent investi net (€)"]
                    st.vega_lite_chart(
                        pd.DataFrame(donnees_courbe_perf),
                        {
                            "height": 300,
                            "mark": {"type": "line", "interpolate": "monotone"},
                            "encoding": {
                                "x": {"field": "Date", "type": "temporal", "axis": {"title": None, "format": "%m/%y", "grid": False}},
                                "y": {"field": "Montant (€)", "type": "quantitative", "scale": {"zero": False, "padding": 18}, "axis": {"title": "Valeur (€)", "format": ",.0f"}},
                                "color": {"field": "Série", "type": "nominal", "scale": {"domain": series_perf, "range": ["#2ecc71", "#3498db", "#95a5a6"]}, "legend": {"orient": "top", "title": None, "labelLimit": 320}},
                                "strokeDash": {"field": "Série", "type": "nominal", "scale": {"domain": series_perf, "range": [[1, 0], [6, 3], [2, 3]]}, "legend": None},
                                "tooltip": [
                                    {"field": "DateFR", "type": "nominal", "title": "Date"},
                                    {"field": "Série", "type": "nominal", "title": "Courbe"},
                                    {"field": "Montant (€)", "type": "quantitative", "format": ",.2f"},
                                ],
                            },
                            "view": {"stroke": None},
                        },
                        width="stretch",
                    )

                    texte_lignes = ", ".join(l["action"] for l in lignes_perf)
                    st.caption(nombres_fr(
                        f"Calcul sur {len(lignes_perf)} ligne(s) dont tout l'historique est dans le journal : {texte_lignes} "
                        f"({valeur_portefeuille_perf:,.0f} € aujourd'hui)."
                    ))
                    if exclusions_perf:
                        st.caption(
                            "Lignes non prises en compte : "
                            + " ; ".join(f"{a} ({motif})" for a, motif in exclusions_perf)
                            + ". Pour inclure une ligne détenue avant le journal, enregistrez tous ses achats depuis le premier "
                              "(par exemple en remettant sa quantité à 0, puis en important l'historique de votre courtier)."
                        )
                    st.caption(
                        "Méthode : rendement annualisé (taux de rendement interne) calculé sur vos flux réels. L'ETF Amundi MSCI World (CW8) "
                        "reçoit exactement les mêmes versements et retraits, aux mêmes dates. Dividendes estimés d'après l'historique Yahoo "
                        "(nets de 30 % pour les actions américaines), comptés à leur date de détachement ; lignes en dollars valorisées au taux "
                        "du jour. Les performances passées ne préjugent pas des performances futures."
                    )

        # ======================================================================
        # COMPTEUR OFFICIEL PLAFOND PEA (150 000 €) & RICHESSE TOTALE CRÉÉE
        # ======================================================================
        st.markdown("<div style='margin-top:18px;'></div>", unsafe_allow_html=True)
        total_pv_actees_pf = sum(float(v.get("plus_value_eur", 0.0)) for v in st.session_state.get("historique_ventes", []))
        div_encaisses_cumul = float(st.session_state.get("dividendes_encaisses_cumul", 0.0))
        # Plafond PEA : seules les plus-values actées DANS le PEA (ventes en €) réduisent les versements estimés.
        # Cette valeur est réutilisée telle quelle par la carte « Plafond Légal PEA » plus bas dans l'onglet.
        pv_actees_pea_pf = sum(
            float(v.get("plus_value_eur", 0.0))
            for v in st.session_state.get("historique_ventes", [])
            if v.get("devise", "€") != "$"
        )
        capital_autofinance = max(0.0, pv_actees_pea_pf + div_encaisses_cumul)
        cout_pru_pea_seul = sum(l["cout_eur"] for l in lignes_triees if l["devise"] == "EUR")
        versements_nets_pea = max(0.0, cout_pru_pea_seul - capital_autofinance)
        plafond_legal_pea = 150000.0
        pct_plafond_pea = min(100.0, (versements_nets_pea / plafond_legal_pea) * 100.0)
        marge_restante_pea = max(0.0, plafond_legal_pea - versements_nets_pea)

        # Richesse réellement créée : plus-values latentes + plus-values actées + dividendes DÉJÀ encaissés
        # (et non la rente annuelle prévue, qui n'a pas encore été perçue)
        richesse_totale_creee = plus_value_globale + total_pv_actees_pf + div_encaisses_cumul
        tri_global_pct = (richesse_totale_creee / cout_total_achat * 100.0) if cout_total_achat > 0 else 0.0
        c_rich = "#2ecc71" if richesse_totale_creee >= 0 else "#e74c3c"

        html_pea_tri = f"""
        <div class="argon-grid" style="margin-bottom: 18px;">
            <div class="argon-card" style="text-align:left; border-left: 4px solid #3498db;">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <span class="argon-title" style="color:#3498db; margin:0;">🏛️ Jauge Officielle Plafond PEA (150 000 €)</span>
                    <span class="b-blue">{pct_plafond_pea:.1f}% utilisé</span>
                </div>
                <div class="score-bg" style="height:10px; margin:8px 0;">
                    <div style="width:{max(2.0, pct_plafond_pea)}%; background:linear-gradient(90deg, #3498db, #2ecc71); height:100%;"></div>
                </div>
                <div style="display:flex; justify-content:space-between; font-size:0.82em; opacity:0.9;">
                    <span>Versements nets estimés : <b>{versements_nets_pea:,.0f} €</b></span>
                    <span>Marge de versement restante : <b>{marge_restante_pea:,.0f} €</b></span>
                </div>
            </div>
            <div class="argon-card" style="text-align:left; border-left: 4px solid {c_rich};">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <span class="argon-title" style="color:{c_rich}; margin:0;">🏆 Richesse Totale Créée (Latent + Acté + Dividendes encaissés)</span>
                    <span class="{'b-green' if richesse_totale_creee >= 0 else 'b-red'}">Rendement Global : {tri_global_pct:+.1f}%</span>
                </div>
                <div style="font-size:1.35em; font-weight:900; color:{c_rich}; margin:4px 0;">{richesse_totale_creee:+,.2f} €</div>
                <div style="font-size:0.80em; opacity:0.85;">
                    PV Latente : <b>{plus_value_globale:+,.0f} €</b> | PV Actées : <b>{total_pv_actees_pf:+,.0f} €</b> | Dividendes encaissés : <b style="color:#2ecc71;">+{div_encaisses_cumul:,.0f} €</b> <span style="opacity:0.75;">(rente prévue : {dividendes_nets_totaux_eur:,.0f} €/an, non comptée)</span>
                </div>
            </div>
        </div>
        """
        afficher_html(html_pea_tri)

        # ======================================================================
        # MODULE PRIME DE FIDÉLITÉ NOMINATIF ADMINISTRÉ (+10% & ACTIONS GRATUITES)
        # ======================================================================
        bonus_annuel_nom = 0.0
        texte_al = ""
        eligibles_nom_pf = [
            k for k in portefeuille_utilisateur.keys()
            if k in ("Air Liquide", "L'Oréal", "Engie", "Seb", "Crédit Agricole")
            and isinstance(portefeuille_utilisateur.get(k), dict)
            and float(portefeuille_utilisateur[k].get("qte", 0)) > 0
        ]
        if eligibles_nom_pf:
            with st.expander("🏅 Prime de Fidélité Nominatif Administré (+10% Dividende & Actions Gratuites Air Liquide)", expanded=False):
                if mode_gratuit:
                    afficher_verrou_saas(
                        "Calculateur Prime de Fidélité Nominatif Administré (+10%) & Actions Gratuites",
                        "⚡ Offre Premium (4,90 €/mois) ou 👑 Pro (8,90 €/mois)",
                        "Simulez vos primes de fidélité +10% et vos paliers d'attribution d'actions gratuites Air Liquide."
                    )
                else:
                    if "actions_nominatif" not in st.session_state:
                        st.session_state["actions_nominatif"] = eligibles_nom_pf.copy()
                    selection_nom = st.multiselect(
                        "Sélectionnez vos lignes passées au Nominatif Administré (+10% de bonus dividende après 2 années civiles) :",
                        options=eligibles_nom_pf,
                        default=[a for a in st.session_state["actions_nominatif"] if a in eligibles_nom_pf],
                        key="ms_actions_nominatif",
                    )
                    st.session_state["actions_nominatif"] = selection_nom

                    for act_n in selection_nom:
                        q_n = float(portefeuille_utilisateur[act_n].get("qte", 0))
                        div_n = float(WATCHLIST_DEFAUT.get(act_n, {}).get("div_eur", 0.0))
                        bonus_annuel_nom += q_n * div_n * 0.10

                    if "Air Liquide" in portefeuille_utilisateur and isinstance(portefeuille_utilisateur.get("Air Liquide"), dict) and float(portefeuille_utilisateur["Air Liquide"].get("qte", 0)) > 0:
                        q_al = int(portefeuille_utilisateur["Air Liquide"]["qte"])
                        act_gratuites = q_al // 10
                        manque_al = 10 - (q_al % 10) if (q_al % 10) != 0 else 0
                        cours_al = float(prix_temps_reel.get("Air Liquide", 165.0))
                        val_cadeau_al = act_gratuites * cours_al
                        texte_al = (
                            f" | 🎁 <b>Air Liquide ({q_al} titres)</b> : Droit à <b>{act_gratuites} action(s) gratuite(s)</b> (~{val_cadeau_al:,.0f} €)"
                            + (f" — <i>Plus que {manque_al} action(s) pour débloquer la suivante !</i>" if manque_al > 0 else " — <i>Palier exact de 10 atteint !</i>")
                        )

                    afficher_html(f"""
                    <div style="background:rgba(46,204,113,0.08); border:1px solid rgba(46,204,113,0.35); border-radius:10px; padding:12px 16px; font-size:0.90em;">
                        🏅 <b>Gain de Rente Nominatif (+10%) :</b> <b style="color:#2ecc71;">+{bonus_annuel_nom:.2f} € / an</b> (soit <b>+{bonus_annuel_nom*10:.0f} €</b> sur 10 ans sans apport){texte_al}
                    </div>
                    """)

        # ======================================================================
        # MINI-SIMULATEUR D'IMPACT PRU & RENFORCEMENT DCA (100% ARGON DARK/LIGHT)
        # ======================================================================
        actions_Simu_pru = [
            k for k, v in portefeuille_utilisateur.items()
            if k not in CLES_TECHNIQUES_PF and isinstance(v, dict) and float(v.get("qte", 0)) > 0
        ]
        if actions_Simu_pru:
            st.markdown("#### 🧮 Simulateur Express d'Impact PRU & DCA")
            if mode_gratuit:
                afficher_verrou_saas(
                    "Simulateur Express d'Impact PRU & Renforcement DCA",
                    "⚡ Offre Premium (4,90 €/mois) ou 👑 Pro (8,90 €/mois)",
                    "Calculez instantanément votre nouveau PRU et le gain de dividende annuel avant de passer votre ordre."
                )
            else:
                col_sim1, col_sim2 = st.columns([2, 1])
                with col_sim1:
                    act_choisie = st.selectbox(
                        "Action du portefeuille à renforcer :",
                        actions_Simu_pru,
                        key="simu_pru_action"
                    )
                with col_sim2:
                    budget_simu = st.number_input(
                        "Montant DCA à investir (€) :",
                        min_value=50.0,
                        max_value=50000.0,
                        value=float(BUDGET_MENSUEL),
                        step=50.0,
                        key="simu_pru_budget"
                    )

                pos_act = portefeuille_utilisateur.get(act_choisie, {})
                qte_act = float(pos_act.get("qte", 0.0))
                pru_act = float(pos_act.get("pru", 0.0))
                info_w = st.session_state.get("watchlist", WATCHLIST_DEFAUT).get(act_choisie, WATCHLIST_DEFAUT.get(act_choisie, {}))
                dev_sim = "$" if info_w.get("devise") == "USD" else "€"
                div_unit = float(info_w.get("div_eur", 0.0))
                cours_live = float(st.session_state.get("prix_temps_reel", {}).get(act_choisie, pru_act))

                if cours_live > 0 and qte_act > 0:
                    budget_devise = (budget_simu * TAUX_USD_EUR) if dev_sim == "$" else budget_simu
                    nb_ach = int(budget_devise // cours_live)
                    mode_1_titre = False
                    if nb_ach == 0:
                        nb_ach = 1
                        mode_1_titre = True
                    cout_ordre = nb_ach * cours_live
                    nouv_qte = qte_act + nb_ach
                    nouv_pru = ((qte_act * pru_act) + cout_ordre) / nouv_qte
                    ecart_pru = nouv_pru - pru_act
                    ecart_pru_pct = (ecart_pru / pru_act * 100) if pru_act > 0 else 0.0
                    gain_div_an = nb_ach * div_unit

                    classe_b_pru = "b-green" if ecart_pru <= 0 else "b-blue"
                    col_p = "#2ecc71" if ecart_pru <= 0 else "#3498db"
                    txt_badge = f"📉 PRU abaissé de {ecart_pru:.2f} {dev_sim} ({ecart_pru_pct:+.1f}%)" if ecart_pru <= 0 else f"📈 PRU moyenné à +{ecart_pru:.2f} {dev_sim} ({ecart_pru_pct:+.1f}%)"
                    note_1t = f"(Ajusté à 1 titre = {cout_ordre:.2f} {dev_sim})" if mode_1_titre else f"(Investi : {cout_ordre:.2f} {dev_sim})"

                    html_simu_pru = f"""
                    <div class="argon-card" style="text-align:left; margin-bottom:18px;">
                        <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px;">
                            <div>
                                <div class="argon-title">Ordre simulé au cours actuel ({cours_live:.2f} {dev_sim})</div>
                                <div style="font-size:1.08em; font-weight:900;">+{nb_ach} action(s) {act_choisie} <span style="font-size:0.84em; opacity:0.75; font-weight:600;">{note_1t}</span></div>
                            </div>
                            <div>
                                <div class="argon-title">Trajectoire du PRU</div>
                                <div style="font-size:1.08em; font-weight:900;">{pru_act:.2f} {dev_sim} ➔ <span style="color:{col_p};">{nouv_pru:.2f} {dev_sim}</span></div>
                            </div>
                            <div><span class="{classe_b_pru}">{txt_badge}</span></div>
                            <div><span class="b-green">+{gain_div_an:.2f} {dev_sim} / an de dividendes</span></div>
                        </div>
                    </div>
                    """
                    afficher_html(html_simu_pru)

        # ======================================================================
        # IMPORT MAGIQUE DU PORTEFEUILLE (EXCLUSIF OFFRE PRO 8,90 €)
        # ======================================================================
        def _analyser_ligne_import_ia(item_ext):
            """(action reconnue, quantité, PRU, statut) pour une ligne lue par Gemini."""
            if not isinstance(item_ext, dict):
                return None, 0, 0.0, "Ignorée : ligne illisible"
            nom_lu = re.sub(r"[<>]", "", str(item_ext.get("nom", ""))).strip()
            qte_lue = _nombre_lu(item_ext.get("qte"))
            pru_lu = _nombre_lu(item_ext.get("pru"))
            action_lue = _reconnaitre_action(nom_lu)
            if action_lue is None:
                return None, 0, 0.0, "Ignorée : action non reconnue (ajoutez-la d'abord à votre radar)"
            if not qte_lue or qte_lue <= 0 or pru_lu is None or pru_lu < 0:
                return action_lue, 0, 0.0, "Ignorée : quantité ou PRU illisible"
            return action_lue, int(round(qte_lue)), round(float(pru_lu), 4), "✅ À appliquer"

        def appliquer_import_ia_portefeuille():
            lignes_ext = st.session_state.get("_lignes_extraites_vision", [])
            nb_maj = 0
            for item_ext in lignes_ext:
                nom_e, qte_e, pru_e, _ = _analyser_ligne_import_ia(item_ext)
                if nom_e and qte_e > 0:
                    st.session_state["portefeuille"][nom_e] = construire_position(nom_e, qte_e, pru_e)
                    st.session_state[f"qte_{nom_e}"] = qte_e
                    st.session_state[f"pru_{nom_e}"] = pru_e
                    if nom_e not in st.session_state["watchlist"] and nom_e in WATCHLIST_DEFAUT:
                        st.session_state["watchlist"][nom_e] = WATCHLIST_DEFAUT[nom_e].copy()
                    nb_maj += 1
            st.session_state.pop("_lignes_extraites_vision", None)
            sauvegarder_dans_cloud()
            st.session_state["_notif_import_ia"] = f"✅ {nb_maj} ligne(s) importée(s) et synchronisée(s) dans votre portefeuille !"

        if st.session_state.get("_notif_import_ia"):
            st.success(st.session_state.pop("_notif_import_ia"))

        with st.expander("📸 Import Magique : mettre à jour mes positions actuelles par capture d'écran ou copier-coller (IA Gemini)", expanded=False):
            if not est_pro_max:
                afficher_verrou_saas(
                    "Import Magique IA (Lecture optique de Capture d'Écran & Copier-Coller Courtier)",
                    "👑 Offre Pro (8,90 €/mois)",
                    "Importez ou mettez à jour toutes les lignes et PRU de votre portefeuille en 1 clic grâce à Gemini Vision."
                )
            else:
                st.caption(
                    "Met à jour d'un coup vos positions actuelles (quantité et PRU tels qu'affichés par votre courtier) : "
                    "les lignes lues remplacent celles du portefeuille. Pour garder l'historique de chaque achat avec sa date, "
                    "utilisez plutôt le 🧾 Journal des achats, plus haut."
                )
                mode_imp_ia = st.radio(
                    "Méthode d'importation :",
                    ["📋 Copier-Coller le texte de mon courtier (Ultra-rapide)", "📸 Déposer une Capture d'Écran (PNG / JPG)"],
                    horizontal=True,
                    key="rad_mode_imp_ia",
                )

                cle_gem_vis = ""
                for k_s in ["GEMINI_API_KEY", "GOOGLE_API_KEY", "GEMINI_KEY"]:
                    v_s = _lire_secret(k_s)
                    if v_s:
                        cle_gem_vis = v_s
                        break

                prompt_base_json = (
                    "Extrais chaque ligne d'action détenue dans ce portefeuille boursier. "
                    "Réponds UNIQUEMENT avec un tableau JSON valide de la forme : "
                    '[{"nom": "TotalEnergies", "qte": 25, "pru": 54.20}]. '
                    "Utilise exactement les noms standards du catalogue si tu reconnais l'entreprise "
                    "(ex: TotalEnergies, Air Liquide, AXA, Rubis, LVMH, Sanofi, Engie, Vinci, BNP Paribas, "
                    "Pernod Ricard, Schneider Electric, Veolia, Alphabet - Google, Microsoft, Apple, Realty Income)."
                )

                if "Copier-Coller" in mode_imp_ia:
                    texte_courtier = st.text_area(
                        "Collez ici en vrac les lignes copiées depuis votre courtier (BoursoBank, Crédit Agricole, Fortuneo, Bourse Direct, Excel...) :",
                        placeholder="Exemple : TotalEnergies 25 titres PRU 54,20 € | Engie 40 actions à 15,10 € | Rubis 30 x 24,50 €...",
                        height=100,
                        key="txt_imp_courtier",
                    )
                    if st.button("🤖 Extraire mes positions depuis ce texte", type="primary", key="btn_ext_txt"):
                        if not cle_gem_vis:
                            st.error("⚠️ Clé `GEMINI_API_KEY` absente de vos Secrets Streamlit.")
                        elif not texte_courtier.strip():
                            st.warning("⚠️ Collez d'abord le texte de vos positions ci-dessus.")
                        else:
                            with st.spinner("🧠 Analyse de vos lignes et PRU en cours..."):
                                payload_t = json.dumps({
                                    "contents": [{"parts": [{"text": f"{prompt_base_json}\n\nTexte du portefeuille :\n{texte_courtier}"}]}]
                                }).encode("utf-8")
                                for mod_v in ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-flash-latest"]:
                                    try:
                                        url_v = f"https://generativelanguage.googleapis.com/v1beta/models/{mod_v}:generateContent?key={urllib.parse.quote(cle_gem_vis)}"
                                        req_v = urllib.request.Request(url_v, data=payload_t, headers={"Content-Type": "application/json"})
                                        with urllib.request.urlopen(req_v, timeout=25) as resp_v:
                                            res_v = json.loads(resp_v.read().decode("utf-8"))
                                            txt_v = res_v["candidates"][0]["content"]["parts"][0]["text"]
                                            deb_j, fin_j = txt_v.find("["), txt_v.rfind("]")
                                            if deb_j != -1 and fin_j != -1:
                                                st.session_state["_lignes_extraites_vision"] = json.loads(txt_v[deb_j:fin_j+1])
                                                break
                                    except Exception:
                                        continue
                else:
                    fichier_img = st.file_uploader("Choisir une capture d'écran (PNG, JPG, WEBP)", type=["png", "jpg", "jpeg", "webp"], key="up_vision_pf_v2")
                    if fichier_img is not None:
                        if st.button("🤖 Analyser ma capture d'écran avec Gemini Vision", type="primary", key="btn_ext_img"):
                            if not cle_gem_vis:
                                st.error("⚠️ Clé `GEMINI_API_KEY` absente de vos Secrets Streamlit.")
                            else:
                                import base64
                                with st.spinner("🔍 Lecture optique de vos lignes et PRU en cours..."):
                                    b64_img = base64.b64encode(fichier_img.read()).decode("utf-8")
                                    mime_t = fichier_img.type or "image/jpeg"
                                    payload_v = json.dumps({
                                        "contents": [{
                                            "parts": [
                                                {"text": prompt_base_json},
                                                {"inline_data": {"mime_type": mime_t, "data": b64_img}}
                                            ]
                                        }]
                                    }).encode("utf-8")
                                    for mod_v in ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-flash-latest"]:
                                        try:
                                            url_v = f"https://generativelanguage.googleapis.com/v1beta/models/{mod_v}:generateContent?key={urllib.parse.quote(cle_gem_vis)}"
                                            req_v = urllib.request.Request(url_v, data=payload_v, headers={"Content-Type": "application/json"})
                                            with urllib.request.urlopen(req_v, timeout=25) as resp_v:
                                                res_v = json.loads(resp_v.read().decode("utf-8"))
                                                txt_v = res_v["candidates"][0]["content"]["parts"][0]["text"]
                                                deb_j, fin_j = txt_v.find("["), txt_v.rfind("]")
                                                if deb_j != -1 and fin_j != -1:
                                                    st.session_state["_lignes_extraites_vision"] = json.loads(txt_v[deb_j:fin_j+1])
                                                    break
                                        except Exception:
                                            continue

                if st.session_state.get("_lignes_extraites_vision"):
                    lignes_ext = st.session_state["_lignes_extraites_vision"]
                    apercu_ia = []
                    for item_ext in lignes_ext:
                        action_ia, qte_ia, pru_ia, statut_ia = _analyser_ligne_import_ia(item_ext)
                        apercu_ia.append({
                            "Lu par l'IA": str(item_ext.get("nom", "")) if isinstance(item_ext, dict) else "?",
                            "Action reconnue": action_ia or "—",
                            "Quantité": qte_ia or None,
                            "PRU": pru_ia or None,
                            "Statut": statut_ia,
                        })
                    nb_applicables = sum(1 for a in apercu_ia if a["Statut"].startswith("✅"))
                    st.success(f"✅ {len(lignes_ext)} position(s) détectée(s), dont {nb_applicables} applicable(s).")
                    st.dataframe(pd.DataFrame(apercu_ia), width="stretch", hide_index=True)
                    st.button(
                        "📥 Appliquer ces positions à mon Portefeuille",
                        type="primary",
                        width="stretch",
                        on_click=appliquer_import_ia_portefeuille,
                    )

    return {
        "actions_actives_pf": actions_actives_pf,
        "cout_total_achat": cout_total_achat,
        "dividendes_bruts_totaux_eur": dividendes_bruts_totaux_eur,
        "dividendes_nets_totaux_eur": dividendes_nets_totaux_eur,
        "exposition_eur": exposition_eur,
        "exposition_usd": exposition_usd,
        "lignes_triees": lignes_triees,
        "noter_dans_carnet": noter_dans_carnet,
        "performance_vs_etf": performance_vs_etf,
        "plus_value_globale": plus_value_globale,
        "plus_value_pct": plus_value_pct,
        "portefeuille_utilisateur": portefeuille_utilisateur,
        "repartition_secteurs": repartition_secteurs,
        "valeur_totale_portefeuille": valeur_totale_portefeuille,
        "versements_nets_pea": versements_nets_pea,
    }
