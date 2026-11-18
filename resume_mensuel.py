"""
Résumé mensuel du DCA par e-mail (Boursy).

Chaque soir de bourse, la tâche planifiée (.github/workflows/alertes.yml) lance ce script. Pour chaque compte Pro qui a
activé « Recevoir chaque mois le résumé de mon DCA » dans le Centre d'Alertes, un e-mail part une fois par mois, dans
les JOURS_AVANT_ACHAT jours qui précèdent le jour d'achat choisi. Il contient :
- l'achat du mois selon l'allocation cible (même calcul que l'application : allocation_dca.py) ;
- la valeur du portefeuille et la rente annuelle estimée ;
- les dividendes attendus le mois de l'achat ;
- les valeurs du radar passées sous leur prix cible ;
- les décisions du carnet arrivées à leur échéance de relecture (6 mois) ;
- la solidité de la rente (étude des dividendes) : part solide, part à surveiller, rente l'année d'une crise comme 2020
  et rente prudente dans 10 ans.
L'application utilise les mêmes fonctions pour l'aperçu immédiat.

Variables d'environnement : celles de alertes_quotidiennes.py (SUPABASE_URL, SUPABASE_SERVICE_KEY, SMTP_EMAIL,
SMTP_PASSWORD, APP_URL facultatif, ALERTES_DRY_RUN=1 pour un essai sans envoi ni écriture).
"""
import html
import sys
import urllib.parse
from datetime import date, datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from allocation_dca import (
    STATUTS_ACHAT,
    calculer_achat_du_mois,
    est_cle_technique,
    lignes_detenues,
    lire_allocation_cible,
    preparer_lignes_dca,
    statut_achat,
)
from carnet_decisions import HORIZON_RELECTURE_MOIS, TYPES_DECISION, decisions_arrivees_a_echeance, lire_carnet
from catalogue_valeurs import ENRICHISSEMENT_CATALOGUE, NOMS_RENOMMES, symbole_a_jour
from fiscalite_pea import (
    PLAFOND_PEA, TAUX_IMPOT_REVENU, TAUX_PRELEVEMENTS_SOCIAUX, date_fr, etat_pea, rappel_du_mois, versements_nets_estimes,
)
from solidite_dividendes import (
    TAUX_MESURES, analyser_catalogue, annee_de_reference, bilan_rente, caracteristiques, categorie_projection,
    rendement_median_solides, statut,
)

JOURS_AVANT_ACHAT = 3
MOIS_ABREGES = ["Jan", "Fév", "Mar", "Avr", "Mai", "Juin", "Juil", "Août", "Sep", "Oct", "Nov", "Déc"]
MOIS_NOMS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
             "novembre", "décembre"]


# ==============================================================================
# CALENDRIER
# ==============================================================================
def jour_dca_valide(jour):
    """Jour d'achat entre 1 et 28 (présent dans tous les mois)."""
    try:
        valeur = int(jour)
    except (TypeError, ValueError):
        return 1
    return min(28, max(1, valeur))


def prochaine_date_dca(aujourd_hui, jour):
    """Prochaine date d'achat, aujourd'hui compris."""
    jour = jour_dca_valide(jour)
    candidate = date(aujourd_hui.year, aujourd_hui.month, jour)
    if candidate < aujourd_hui:
        annee, mois = (aujourd_hui.year + 1, 1) if aujourd_hui.month == 12 else (aujourd_hui.year, aujourd_hui.month + 1)
        candidate = date(annee, mois, jour)
    return candidate


def doit_envoyer_resume(aujourd_hui, jour, deja_envoye):
    """
    (envoyer ?, date du prochain achat). Un seul envoi par mois d'achat (suivi « AAAA-MM »), au premier soir de bourse
    situé dans les JOURS_AVANT_ACHAT jours qui précèdent l'achat : la tâche ne tourne pas le week-end.
    """
    date_achat = prochaine_date_dca(aujourd_hui, jour)
    dans_la_fenetre = (date_achat - aujourd_hui).days <= JOURS_AVANT_ACHAT
    return dans_la_fenetre and str(deja_envoye or "") != date_achat.strftime("%Y-%m"), date_achat


def date_en_toutes_lettres(jour):
    return f"{jour.day} {MOIS_NOMS[jour.month - 1]}"


# ==============================================================================
# CONTENU DU RÉSUMÉ
# ==============================================================================
def fiches_valeurs(watchlist):
    """Fiche de chaque valeur : catalogue, anciens noms des valeurs renommées, puis radar de l'utilisateur (prioritaire)."""
    fiches = {}
    for nom, (symbole, devise, _secteur, cible, dividende, _payout, _croissance, mois) in ENRICHISSEMENT_CATALOGUE.items():
        fiches[nom] = {"symbole": symbole, "devise": devise, "prix_cible": cible, "div_eur": dividende, "mois_div": list(mois)}
    for ancien_nom, nouveau_nom in NOMS_RENOMMES.items():
        if nouveau_nom in fiches:
            fiches.setdefault(ancien_nom, dict(fiches[nouveau_nom]))
    for nom, info in (watchlist or {}).items():
        if isinstance(info, dict) and info.get("symbole") and not est_cle_technique(nom):
            fiches[nom] = dict(info, symbole=symbole_a_jour(info["symbole"]))
    return fiches


def noms_du_radar(watchlist, fiches):
    return [n for n in (watchlist or {}) if not est_cle_technique(n) and n in fiches]


def noms_a_coter(portefeuille, watchlist, fiches):
    """Valeurs dont il faut le cours : radar, lignes détenues et lignes de l'allocation cible."""
    noms = set(noms_du_radar(watchlist, fiches)) | set(lignes_detenues(portefeuille)) | set(lire_allocation_cible(portefeuille))
    return sorted(n for n in noms if n in fiches)


def construire_resume(portefeuille, watchlist, budget, cours, taux_usd_eur, date_achat, fiches=None, aujourd_hui=None,
                      categorie_de=None, rendement_achats=0.0):
    """
    Données du résumé. cours : {nom: dernier cours dans la devise de la valeur} ; taux_usd_eur : dollars pour 1 euro.
    categorie_de(symbole) : « solide », « neutre » ou « alerte » (solidité des dividendes) ; sans elle, pas de section
    solidité. rendement_achats : rendement médian des dividendes solides, pour la projection prudente.
    """
    portefeuille = portefeuille if isinstance(portefeuille, dict) else {}
    fiches = fiches if fiches is not None else fiches_valeurs(watchlist)
    radar = noms_du_radar(watchlist, fiches)
    lignes, personnalisee, defaut_detenues = preparer_lignes_dca(portefeuille, radar, fiches, cours, taux_usd_eur)
    plan = calculer_achat_du_mois(lignes, budget)

    detenues = [l for l in plan["lignes"] if l["qte_detenue"] > 0]
    especes_brutes = portefeuille.get("Espèces")
    especes = float(especes_brutes.get("pru") or 0.0) if isinstance(especes_brutes, dict) else 0.0
    mois_achat = MOIS_ABREGES[date_achat.month - 1]
    dividendes_mois = sorted(
        ((l["nom"], l["qte_detenue"] * l["div_eur"] / len(l["mois_div"]))
         for l in detenues if l["div_eur"] > 0 and l["mois_div"] and mois_achat in l["mois_div"]),
        key=lambda d: -d[1],
    )
    sous_cible = []
    for nom in radar:
        prix, fiche = cours.get(nom), fiches[nom]
        try:
            cible = float(fiche.get("prix_cible") or 0.0)
        except (TypeError, ValueError):
            cible = 0.0
        if prix and cible > 0 and prix <= cible:
            sous_cible.append({"nom": nom, "prix": float(prix), "cible": cible,
                               "devise": "$" if fiche.get("devise") == "USD" else "€", "ecart_pct": (prix - cible) / cible * 100.0})
    solidite_rente = None
    if categorie_de is not None:
        lignes_rente = [(l["nom"], l["qte_detenue"] * l["div_eur"], categorie_de(str(fiches[l["nom"]].get("symbole", "")).strip()))
                        for l in detenues if l["div_eur"] > 0]
        solidite_rente = bilan_rente(lignes_rente, rendement_achats=rendement_achats, apport_annuel=12.0 * float(budget))
    # Échéances du PEA : 5 ans à partir du premier versement, plafond (versements nets estimés comme dans l'onglet
    # Portefeuille : coût des lignes en euros et espèces, moins plus-values actées dans le PEA et dividendes encaissés)
    cout_pea = especes + sum(
        float(position.get("qte") or 0) * float(position.get("pru") or 0)
        for nom, position in portefeuille.items()
        if not est_cle_technique(nom) and isinstance(position, dict) and nom in fiches and fiches[nom].get("devise") != "USD"
    )
    etat = etat_pea(portefeuille, aujourd_hui or date.today(),
                    versements_nets_estimes(cout_pea, portefeuille.get("_historique_ventes"), portefeuille.get("_div_encaisses_cumul")))
    return {
        "date_achat": date_achat,
        "budget": float(budget),
        "plan": plan,
        "allocation_personnalisee": personnalisee,
        "defaut_sur_lignes_detenues": defaut_detenues,
        "valeur_portefeuille": sum(l["valeur_eur"] for l in detenues) + especes,
        "especes": especes,
        "rente_annuelle": sum(l["qte_detenue"] * l["div_eur"] for l in detenues),
        "dividendes_mois": dividendes_mois,
        "sous_cible": sorted(sous_cible, key=lambda v: v["ecart_pct"]),
        # Décisions du carnet dont les 6 mois sont tombés depuis environ un mois, sans leçon écrite
        "decisions_a_relire": decisions_arrivees_a_echeance(lire_carnet(portefeuille), aujourd_hui or date.today()),
        "solidite_rente": solidite_rente,
        "echeance_pea": rappel_du_mois(etat, aujourd_hui or date.today()),
        "plafond_pea": ({"versements": etat["versements"], "part": etat["part_plafond"], "reste": etat["reste_versable"]}
                        if etat["plafond_proche"] else None),
    }


# ==============================================================================
# E-MAIL
# ==============================================================================
def _fr(nombre, decimales=2):
    return f"{nombre:,.{decimales}f}".replace(",", " ").replace(".", ",")


def composer_email_resume(resume, expediteur, destinataire, lien_app="", apercu=False):
    plan, date_achat = resume["plan"], resume["date_achat"]
    jour_achat = date_en_toutes_lettres(date_achat)
    message = MIMEMultipart("alternative")
    message["Subject"] = (("[Aperçu] " if apercu else "") + f"📅 Boursy — Votre achat DCA du {jour_achat} : "
                          f"{_fr(plan['investi'])} € proposés")
    message["From"] = expediteur
    message["To"] = destinataire

    style_td = "padding:8px 10px; border-bottom:1px solid #e5e7eb;"
    lignes_affichees = sorted(
        (l for l in plan["lignes"] if l["poids_cible"] > 0 or l["qte_detenue"] > 0),
        key=lambda l: (-l["cout_eur"], l["poids_actuel"] - l["poids_cible"]),
    )
    lignes_html = ""
    for l in lignes_affichees:
        statut = statut_achat(l)
        if statut == "achat":
            achat = f"<b style='color:#059669;'>{l['qte']} action(s)</b><br><span style='color:#6b7280;'>{_fr(l['cout_eur'])} €</span>"
        else:
            achat = f"<span style='color:#6b7280;'>{html.escape(STATUTS_ACHAT[statut].capitalize())}</span>"
        lignes_html += (
            f"<tr><td style='{style_td}'><b>{html.escape(l['nom'])}</b></td><td style='{style_td}'>{achat}</td>"
            f"<td style='{style_td} white-space:nowrap;'>{_fr(l['poids_actuel'], 1)} % → {_fr(l['poids_apres'], 1)} %"
            f"<br><span style='color:#6b7280;'>cible {_fr(l['poids_cible'], 1)} %</span></td></tr>"
        )
    tableau = (
        "<table style='border-collapse:collapse; font-size:14px; width:100%; max-width:640px;'>"
        "<tr style='background:#f3f4f6; text-align:left;'><th style='padding:8px 10px;'>Valeur</th>"
        "<th style='padding:8px 10px;'>Achat proposé</th><th style='padding:8px 10px;'>Poids actuel → après achat</th></tr>"
        + lignes_html + "</table>"
    ) if lignes_html else "<p>Aucune ligne à renforcer : ajoutez des valeurs à votre radar ou à votre portefeuille.</p>"

    origine = ("Répartition selon votre allocation cible." if resume["allocation_personnalisee"]
               else "Répartition par défaut : parts égales entre "
               + ("vos lignes" if resume["defaut_sur_lignes_detenues"] else "les valeurs de votre radar")
               + ". Réglez votre allocation cible dans Boursy, onglet Radar.")
    synthese = f"Investi : <b>{_fr(plan['investi'])} €</b> sur {_fr(resume['budget'])} €, reste {_fr(plan['reste'])} € gardé pour le mois suivant."
    if plan["ecart_avant"] is not None and plan["ecart_apres"] is not None:
        synthese += (f" Écart à la cible : {_fr(plan['ecart_avant'], 1)} % du portefeuille mal réparti avant cet achat, "
                     f"{_fr(plan['ecart_apres'], 1)} % après.")

    dividendes_html = (
        "<ul>" + "".join(f"<li>{html.escape(nom)} : environ {_fr(montant)} €</li>" for nom, montant in resume["dividendes_mois"]) + "</ul>"
        if resume["dividendes_mois"] else f"<p>Aucun dividende attendu en {MOIS_NOMS[date_achat.month - 1]} sur vos lignes.</p>"
    )
    sous_cible_html = (
        "<ul>" + "".join(
            f"<li>{html.escape(v['nom'])} : {_fr(v['prix'])} {v['devise']} pour une cible à {_fr(v['cible'])} {v['devise']} "
            f"({_fr(v['ecart_pct'], 1)} %)</li>" for v in resume["sous_cible"]) + "</ul>"
        if resume["sous_cible"] else "<p>Aucune valeur de votre radar n'est sous son prix cible.</p>"
    )
    dont_especes = f" (dont {_fr(resume['especes'])} € de liquidités)" if resume["especes"] > 0 else ""
    decisions = resume.get("decisions_a_relire") or []
    decisions_html = (
        f"<h3>📓 Décisions à relire ({HORIZON_RELECTURE_MOIS} mois plus tard)</h3><ul>" + "".join(
            f"<li>{d['date'][8:10]}/{d['date'][5:7]}/{d['date'][0:4]} · {html.escape(TYPES_DECISION.get(d.get('type'), ''))} — "
            f"<b>{html.escape(d['action'])}</b> ({html.escape(d.get('raison', ''))})"
            + (f" : « {html.escape(d['note'])} »" if d.get("note") else "") + "</li>"
            for d in decisions)
        + "</ul><p>Voyez ce qu'elles sont devenues dans Boursy (onglet Portefeuille, Carnet de décisions) et notez ce que "
          "vous en retenez.</p>"
    ) if decisions else ""
    solidite = resume.get("solidite_rente")
    solidite_html = ""
    if solidite and (solidite["rente"] > 0 or solidite["apport_annuel"] > 0):
        rente, parts = solidite["rente"], solidite["parts"]

        def part(montant):
            return f"{_fr(montant)} € ({_fr(montant / rente * 100.0, 0)} %)" if rente > 0 else f"{_fr(montant)} €"

        solidite_html = (
            "<h3>🛡️ Solidité de votre rente</h3>"
            f"<p>Sur {_fr(rente)} € de dividendes attendus par an : <b>{part(parts['solide'])} solides</b>, "
            f"{part(parts['neutre'])} neutres ou non classés, <b>{part(parts['alerte'])} à surveiller</b>.</p>"
        )
        if solidite["a_surveiller"]:
            solidite_html += (
                "<p>À surveiller (rendement élevé ou anormal) : " + ", ".join(html.escape(n) for n in solidite["a_surveiller"])
                + f". Dans l'étude de Boursy, {_fr(TAUX_MESURES['rendement_eleve'][0] * 100, 0)} % des rendements les plus "
                "élevés ont baissé leur dividende dans les 3 années suivantes.</p>"
            )
        solidite_html += (
            f"<p>L'année d'une crise comme 2020 : environ <b>{_fr(solidite['rente_crise'], 0)} €</b> au lieu de "
            f"{_fr(rente, 0)} €. Projection prudente dans {solidite['horizon']} ans, en euros d'aujourd'hui, avec votre achat "
            f"mensuel de {_fr(solidite['apport_annuel'] / 12.0, 0)} € et les dividendes réinvestis : environ "
            f"<b>{_fr(solidite['rente_prudente_horizon'], 0)} € par an</b>.</p>"
        )
    pea_html = ""
    echeance, plafond = resume.get("echeance_pea"), resume.get("plafond_pea")
    taux_avant = _fr((TAUX_IMPOT_REVENU + TAUX_PRELEVEMENTS_SOCIAUX) * 100, 1)
    taux_apres = _fr(TAUX_PRELEVEMENTS_SOCIAUX * 100, 1)
    if echeance and echeance["type"] == "bientot":
        pea_html += (f"<p>Votre PEA aura <b>5 ans le {date_fr(echeance['date_5_ans'])}</b> (dans {echeance['jours']} jours). "
                     f"Jusque-là, un retrait clôturerait le plan et le gain serait imposé à {taux_avant} % ; ensuite, les "
                     f"retraits partiels ne clôtureront plus le plan et seuls {taux_apres} % de prélèvements sociaux "
                     "resteront dus sur le gain retiré.</p>")
    elif echeance:
        pea_html += (f"<p>🎉 Votre PEA a <b>5 ans depuis le {date_fr(echeance['date_5_ans'])}</b> : les retraits partiels ne "
                     "clôturent plus le plan, les versements restent possibles, et le gain retiré est exonéré d'impôt sur "
                     f"le revenu ({taux_apres} % de prélèvements sociaux seulement).</p>")
    if plafond:
        pea_html += (f"<p>Plafond : environ <b>{_fr(plafond['versements'], 0)} €</b> versés sur {_fr(PLAFOND_PEA, 0)} € "
                     f"({_fr(plafond['part'] * 100, 0)} %), soit {_fr(plafond['reste'], 0)} € encore possibles. Prévoyez où "
                     "iront les apports suivants.</p>")
    if pea_html:
        pea_html = "<h3>📅 Votre PEA</h3>" + pea_html
    bouton = (
        f"<p><a href='{html.escape(lien_app)}' style='background:#10b981; color:white; padding:10px 16px; "
        "text-decoration:none; border-radius:6px; font-weight:bold;'>Ouvrir Boursy</a></p>"
        if lien_app else ""
    )
    corps = f"""
    <html><body style="font-family: Arial, sans-serif; color: #1f2937; line-height:1.5;">
        <h2 style="margin-bottom:4px;">📅 Votre achat DCA du {jour_achat}</h2>
        <p style="margin-top:0; color:#6b7280;">Cours du {datetime.now().strftime('%d/%m/%Y')} ; ils bougeront d'ici votre achat.</p>
        <h3>🧭 L'achat proposé ({_fr(resume['budget'], 0)} €)</h3>
        <p>{origine}</p>
        {tableau}
        <p>{synthese}</p>
        <h3>💼 Votre portefeuille</h3>
        <p>Valeur : <b>{_fr(resume['valeur_portefeuille'])} €</b>{dont_especes}.
        Rente annuelle estimée : <b>{_fr(resume['rente_annuelle'])} €</b> brut.</p>
        <h3>💶 Dividendes attendus en {MOIS_NOMS[date_achat.month - 1]}</h3>
        {dividendes_html}
        <h3>🎯 Valeurs de votre radar sous leur prix cible</h3>
        {sous_cible_html}
        {decisions_html}
        {solidite_html}
        {pea_html}
        {bouton}
        <p style="font-size:12px; color:#6b7280;">L'achat proposé est un calcul arithmétique à partir de vos poids cibles :
        l'enveloppe va d'abord aux lignes les plus en retard sur leur cible, en actions entières, sans rien vendre. Le radar
        n'entre pas dans ce calcul : sur environ 7 ans et 120 actions, ses signaux forts n'ont pas fait mieux, de façon
        démontrée, que les autres actions du même mois. Les dividendes du mois sont estimés à partir du calendrier habituel
        de chaque valeur. Solidité de la rente : étude des dividendes de Boursy (protocole écrit avant les calculs),
        hypothèses prudentes (pas de croissance réelle du dividende, achats futurs en dividendes solides au rendement médian
        de la liste, crise : baisses de 2020). PEA : règles fiscales en vigueur en 2026, versements estimés à partir de
        vos lignes. Information à but pédagogique, qui ne constitue pas un conseil en investissement.<br>
        Vous recevez cet e-mail car le résumé mensuel est activé dans le Centre d'Alertes de Boursy ; vous pouvez le
        désactiver au même endroit.</p>
    </body></html>
    """
    message.attach(MIMEText(corps, "html", "utf-8"))
    return message


# ==============================================================================
# TÂCHE DU SOIR
# ==============================================================================
def lire_historique_solidite(symbole):
    """Clôtures mensuelles et dividendes sur 11 ans pour la solidité de la rente ; None si indisponible."""
    from donnees_marche import historique_mensuel_dividendes

    try:
        return historique_mensuel_dividendes(symbole, timeout=20)
    except Exception:
        return None


def preparer_solidite(aujourd_hui, lire_historique=None):
    """
    (categorie_de, rendement des achats) pour le résumé, à partir de l'étude des dividendes appliquée au catalogue ;
    (None, 0.0) si les historiques sont indisponibles : le résumé part alors sans cette section.
    """
    lire_historique = lire_historique or lire_historique_solidite
    annee = annee_de_reference(aujourd_hui)
    try:
        valeurs_catalogue, seuils = analyser_catalogue(lire_historique, annee)
    except Exception:
        return None, 0.0
    statuts = {sym: statut(v, seuils, annee) for sym, v in valeurs_catalogue.items()}
    hors_catalogue = {}

    def categorie_de(symbole):
        if symbole not in statuts and symbole not in hors_catalogue:
            hors_catalogue[symbole] = statut(caracteristiques(lire_historique(symbole) if symbole else None, annee), seuils, annee)
        return categorie_projection(statuts.get(symbole) or hors_catalogue[symbole])

    return categorie_de, rendement_median_solides((valeurs_catalogue[s], statuts[s]) for s in statuts)


def main():
    from alertes_quotidiennes import _env, cours_actuel, envoyer, requete_supabase

    essai = _env("ALERTES_DRY_RUN") == "1"
    manquantes = [n for n in ("SUPABASE_URL", "SUPABASE_SERVICE_KEY", "SMTP_EMAIL", "SMTP_PASSWORD") if not _env(n)]
    if manquantes:
        print("Configuration incomplète, secrets manquants : " + ", ".join(manquantes))
        return 1

    comptes = requete_supabase("GET", "user_data?select=user_id,email,watchlist,portefeuille,budget_dca") or []
    # Niveau d'abonnement lu dans la table protégée « abonnements » (jamais dans user_data, modifiable par l'utilisateur)
    abonnements = requete_supabase("GET", "abonnements?select=user_id,niveau") or []
    comptes_pro = {str(a.get("user_id")) for a in abonnements if a.get("niveau") == "pro"}
    aujourd_hui = date.today()
    taux_usd_eur = None
    solidite = None  # (categorie_de, rendement des achats), calculée au premier résumé à envoyer
    nb_inscrits = nb_emails = nb_reportes = nb_erreurs = 0

    for compte in comptes:
        portefeuille = compte.get("portefeuille")
        if not isinstance(portefeuille, dict) or not portefeuille.get("_resume_mensuel"):
            continue
        # Le résumé par e-mail fait partie de l'offre Pro
        if str(compte.get("user_id")) not in comptes_pro or not compte.get("email"):
            continue
        nb_inscrits += 1
        a_envoyer, date_achat = doit_envoyer_resume(aujourd_hui, portefeuille.get("_jour_dca", 1), portefeuille.get("_resume_envoye"))
        if not a_envoyer:
            continue
        try:
            watchlist = compte.get("watchlist") if isinstance(compte.get("watchlist"), dict) else {}
            fiches = fiches_valeurs(watchlist)
            noms = noms_a_coter(portefeuille, watchlist, fiches)
            cours = {nom: cours_actuel(fiches[nom]["symbole"]) for nom in noms}
            if taux_usd_eur is None and any(fiches[n].get("devise") == "USD" for n in noms):
                taux_usd_eur = cours_actuel("EURUSD=X")
            # Jamais de résumé bâti sur des cours manquants : on réessaie le soir suivant (l'envoi reste dans la fenêtre)
            if (any(fiches[n].get("devise") == "USD" for n in noms) and not taux_usd_eur) or \
                    (noms and sum(1 for v in cours.values() if v) < len(noms) / 2):
                nb_reportes += 1
                print("Cours indisponibles pour un compte : résumé reporté au prochain soir de bourse.")
                continue
            try:
                budget = float(compte.get("budget_dca") or 450.0)
            except (TypeError, ValueError):
                budget = 450.0
            if solidite is None:
                solidite = preparer_solidite(aujourd_hui)
                if solidite[0] is None:
                    print("Historiques indisponibles : résumés envoyés sans la section « Solidité de votre rente ».")
            resume = construire_resume(portefeuille, watchlist, budget, cours, taux_usd_eur, date_achat, fiches,
                                       categorie_de=solidite[0], rendement_achats=solidite[1])
            if essai:
                achats = [f"{l['qte']} {l['nom']}" for l in resume["plan"]["lignes"] if l["qte"] > 0]
                print(f"[essai] résumé pour un compte, achat du {date_achat.isoformat()} : {achats}")
            else:
                envoyer(composer_email_resume(resume, _env("SMTP_EMAIL"), compte["email"], _env("APP_URL")))
                # Relecture juste avant l'écriture : limite le risque d'écraser une modification faite entre-temps
                identifiant = urllib.parse.quote(str(compte["user_id"]))
                frais = requete_supabase("GET", f"user_data?select=portefeuille&user_id=eq.{identifiant}") or []
                pf_frais = frais[0].get("portefeuille") if frais else None
                if isinstance(pf_frais, dict):
                    pf_frais["_resume_envoye"] = date_achat.strftime("%Y-%m")
                    requete_supabase("PATCH", f"user_data?user_id=eq.{identifiant}", {"portefeuille": pf_frais})
            nb_emails += 1
        except Exception as erreur:
            nb_erreurs += 1
            print(f"Erreur sur un compte ({type(erreur).__name__}) : résumé non envoyé ou suivi non enregistré.")

    print(f"{nb_inscrits} compte(s) avec résumé mensuel, {nb_emails} résumé(s) envoyé(s), {nb_reportes} reporté(s), "
          f"{nb_erreurs} erreur(s).")
    return 1 if nb_erreurs else 0


if __name__ == "__main__":
    sys.exit(main())
