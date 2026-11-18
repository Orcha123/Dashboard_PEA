"""
Pages légales de Boursy : avertissement AMF (non-CIF), CGV, droit de rétractation, mentions légales (loi LCEN) et
politique de confidentialité (RGPD), affichées en bas de chaque page.

L'identité de l'éditeur vient des secrets Streamlit (EDITEUR_NOM, EDITEUR_SIRET, EDITEUR_ADRESSE, CONTACT_EMAIL),
passés par app.py ; tant qu'ils manquent, un texte « à renseigner » s'affiche à leur place. Les textes de chaque
onglet sont produits par des fonctions séparées, vérifiées par tests/test_pages_legales.py.
"""
import html

import streamlit as st

from habillage import afficher_html

NOM_APP_LEGAL = "Boursy"  # nom commercial affiché dans les textes légaux


def identite_editeur(nom="", siret="", adresse="", contact=""):
    """Identité de l'éditeur prête à afficher (échappée), avec un texte « à renseigner » pour chaque secret manquant."""
    def _texte(valeur, defaut):
        return html.escape(str(valeur or "").strip() or defaut, quote=False)

    return {
        "nom": _texte(nom, "Éditeur à renseigner (secret EDITEUR_NOM)"),
        "siret": _texte(siret, "en cours d'immatriculation"),
        "adresse": _texte(adresse, "adresse à renseigner (secret EDITEUR_ADRESSE)"),
        "contact": html.escape(str(contact or "").strip() or "adresse de contact à renseigner (secret CONTACT_EMAIL)"),
    }


def html_avertissement_amf(nom_app=NOM_APP_LEGAL):
    """Avertissement AMF : outil pédagogique, pas un conseiller en investissement (non-CIF)."""
    return f"""
    <div style="font-size:0.86em; line-height:1.6; opacity:0.92;">
        <b>1. Absence de Conseil en Investissement Financier (Statut Non-CIF)</b><br>
        La plateforme <b>{nom_app}</b> est un outil logiciel d'analyse statistique, quantitative et de suivi patrimonial à vocation strictement <b>pédagogique et informative</b>. L'éditeur n'agit en aucun cas en qualité de Conseiller en Investissements Financiers (CIF) au sens des articles L.541-1 et suivants du Code monétaire et financier, ni en tant que prestataire de services d'investissement (PSI) agréé par l'Autorité des Marchés Financiers (AMF).<br><br>
        <b>2. Nature des indicateurs algorithmiques et de l'Intelligence Artificielle</b><br>
        Les scores (/100), signaux techniques (RSI, Stochastique, Bandes de Bollinger, MACD, croisements EMA 2/12, ATR, canaux de régression linéaire à 3 ans), simulations d'allocation DCA et synthèses générées par le module <b>Coach IA (Google Gemini)</b> constituent des traitements mathématiques automatisés. Ils ne sauraient être interprétés comme une recommandation personnalisée d'achat, de vente ou de conservation d'instruments financiers.<br><br>
        <b>3. Responsabilité de l'utilisateur et exactitude des flux de marché</b><br>
        Les cotations, historiques de cours, taux de change (EUR/USD) et calendriers de dividendes proviennent de flux tiers publics (notamment Yahoo Finance) fournis « en l'état », pouvant comporter des délais ou des imprécisions. L'investissement en bourse (PEA / CTO) comporte un <b>risque de perte en capital</b>. L'utilisateur demeure seul maître et responsable de ses décisions d'investissement auprès de son établissement bancaire ou courtier. Les performances passées ne préjugent pas des performances futures.
    </div>
    """


def html_cgv(nom_app=NOM_APP_LEGAL):
    """Conditions générales de vente et formules d'abonnement."""
    return f"""
    <div style="font-size:0.86em; line-height:1.6; opacity:0.92;">
        <b>Article 1 — Objet et Architecture des Offres</b><br>
        Les présentes Conditions Générales de Vente (CGV) régissent la souscription aux services numériques de la plateforme <b>{nom_app}</b>, déclinés en trois formules :<br>
        • <b>🌱 Forfait Gratuit (0,00 € / mois) :</b> Accès découverte limité à 2 valeurs dans le radar/portefeuille et 1 crédit d'audit IA par jour.<br>
        • <b>⚡ Forfait Premium (4,90 € TTC / mois) :</b> Accès au catalogue complet (+100 valeurs PEA/US & recherche Yahoo Live), Tableaux 1 à 4 débloqués, gestion de portefeuille illimitée, export CSV, simulateur PRU, guichet d'encaissement espèces et 3 crédits d'audit IA par jour.<br>
        • <b>👑 Forfait Pro Max (8,90 € TTC / mois) :</b> Accès intégral incluant les fonctionnalités Premium ainsi que le Journal des Arbitrages & Calendrier 12 mois des Plus-Values Actées, la Station Graphique Interactive 360° (Quant & TradingView), l'Import Magique IA par capture d'écran, le Duel de performance vs ETF, le Radar de détachements à 90 jours, les alertes par email et 15 crédits d'audit IA par jour.<br><br>
        <b>Article 2 — Paiement Sécurisé et Facturation</b><br>
        Les règlements sont opérés par carte bancaire via notre prestataire certifié PCI-DSS <b>Stripe</b>. Aucune coordonnée bancaire n'est stockée sur les serveurs de {nom_app}. Le prix est exigible comptant à la souscription, puis renouvelé par tacite reconduction mensuelle à la date anniversaire.<br><br>
        <b>Article 3 — Absence d'Engagement et Résiliation en 1 Clic</b><br>
        Les abonnements <b>Premium</b> et <b>Pro Max</b> sont <b>sans aucun engagement de durée</b>. L'abonné peut résilier ou modifier sa formule à tout moment en un clic depuis le menu latéral gauche via le bouton <b>« ⚙️ Gérer mon abonnement / Factures »</b> (Portail Client officiel Stripe). Toute résiliation prend effet à l'issue de la période mensuelle en cours : l'utilisateur conserve l'intégralité de ses accès payants jusqu'au dernier jour de la période facturée, puis son compte repasse automatiquement en Forfait Gratuit sans perte de ses données enregistrées.
    </div>
    """


def html_retractation():
    """Renoncement exprès au droit de rétractation (article L221-28 13° du Code de la consommation)."""
    return """
    <div style="font-size:0.86em; line-height:1.6; opacity:0.92;">
        <b>Renoncement exprès au droit de rétractation (Article L221-28 13° du Code de la consommation)</b><br>
        Conformément aux dispositions de l'article L221-28 13° du Code de la consommation français, le droit de rétractation de quatorze (14) jours ne peut être exercé pour les contrats de fourniture d'un contenu numérique non fourni sur un support matériel dont l'exécution a commencé après accord préalable exprès du consommateur et renoncement exprès à son droit de rétractation.<br><br>
        En validant son paiement sur l'interface Stripe et en accédant instantanément aux fonctionnalités débloquées des offres <b>Premium (4,90 €/mois)</b> ou <b>Pro Max (8,90 €/mois)</b>, le Client :
        <ul style="margin:6px 0 8px 18px;">
            <li>Demande expressément l'activation immédiate de son abonnement numérique avant l'expiration du délai légal de rétractation ;</li>
            <li>Reconnaît qu'il renonce expressément à son droit de rétractation pour la période mensuelle entamée.</li>
        </ul>
        En conséquence, aucun remboursement prorata temporis ne sera effectué pour le mois en cours en cas d'annulation, l'accès aux outils Pro/Premium demeurant pleinement actif jusqu'à l'échéance mensuelle.
    </div>
    """


def html_mentions_legales(identite):
    """Mentions légales (loi LCEN) : éditeur, contact et hébergeurs."""
    return f"""
    <div style="font-size:0.86em; line-height:1.6; opacity:0.92;">
        <b>1. Éditeur et Hébergement (Loi LCEN)</b><br>
        • <b>Éditeur du service :</b> {identite['nom']} — SIRET : {identite['siret']} — {identite['adresse']}<br>
        • <b>Contact & Support Client :</b> <a href="mailto:{identite['contact']}">{identite['contact']}</a><br>
        • <b>Hébergement de l'application :</b> Streamlit Cloud / Snowflake Inc. (San Mateo, Californie, USA)<br>
        • <b>Hébergement de la base de données chiffrée :</b> Supabase Inc. (Infrastructure Cloud sécurisée avec protocole Row Level Security)<br><br>
        <b>2. Données personnelles</b><br>
        Le traitement de vos données personnelles est décrit dans l'onglet <b>🔒 5. Politique de Confidentialité</b>.
    </div>
    """


def html_confidentialite(identite):
    """Politique de confidentialité (RGPD) : données, finalités, durées, sous-traitants, droits."""
    return f"""
    <div style="font-size:0.86em; line-height:1.6; opacity:0.92;">
        <b>1. Responsable du traitement</b><br>
        {identite['nom']} — {identite['adresse']} — contact : <a href="mailto:{identite['contact']}">{identite['contact']}</a>.<br><br>
        <b>2. Données collectées</b><br>
        • Votre adresse e-mail et votre mot de passe (conservé sous forme chiffrée par Supabase, jamais lisible par l'éditeur).<br>
        • Les données que vous saisissez : actions suivies, quantités, prix de revient, prix cibles, budget, ventes, dividendes encaissés, préférences d'alertes.<br>
        • Votre niveau d'abonnement et votre identifiant client Stripe. Vos coordonnées bancaires sont traitées par Stripe uniquement et ne nous sont jamais transmises.<br>
        • Les questions posées au coach IA, transmises avec un résumé de votre portefeuille au moment de l'analyse, ainsi que les captures d'écran et textes que vous soumettez aux imports par IA.<br>
        • Des données techniques de connexion (adresse IP, navigateur), traitées par nos hébergeurs pour faire fonctionner le service.<br><br>
        <b>3. Finalités et base légale</b><br>
        Ces données servent uniquement à fournir le service que vous avez demandé (suivi de portefeuille, alertes, analyses, gestion de l'abonnement) : la base légale est l'exécution du contrat. Elles ne sont ni vendues, ni louées, ni utilisées à des fins publicitaires.<br><br>
        <b>4. Durée de conservation</b><br>
        Tant que votre compte existe. À sa suppression, vos données de portefeuille, votre historique et votre compte sont effacés immédiatement. Les justificatifs de paiement sont conservés par Stripe et par l'éditeur pendant la durée exigée par les obligations comptables.<br><br>
        <b>5. Destinataires (sous-traitants)</b><br>
        • <b>Supabase</b> : comptes utilisateurs et base de données.<br>
        • <b>Streamlit Cloud (Snowflake Inc., États-Unis)</b> : hébergement de l'application.<br>
        • <b>Stripe</b> : paiement et gestion des abonnements.<br>
        • <b>Google</b> : API Gemini (analyses du coach IA, à votre demande) et Gmail (envoi des e-mails).<br>
        • <b>GitHub (Microsoft)</b> : exécution de la tâche quotidienne d'envoi des alertes.<br>
        Les cours de bourse sont obtenus auprès de Yahoo Finance : seuls les symboles des actions lui sont transmis, jamais vos données personnelles.<br><br>
        <b>6. Transferts hors de l'Union européenne</b><br>
        Certains de ces prestataires sont situés aux États-Unis. Ces transferts s'appuient sur les garanties prévues par le RGPD (décision d'adéquation du Data Privacy Framework ou clauses contractuelles types de la Commission européenne, selon le prestataire).<br><br>
        <b>7. Vos droits</b><br>
        Vous disposez d'un droit d'accès, de rectification, d'effacement, de limitation, d'opposition et de portabilité. Vous pouvez :<br>
        • exporter vos données avec le bouton <b>📥 Export CSV</b> ;<br>
        • supprimer vous-même votre compte et toutes vos données dans <b>⚙️ Mon compte</b> (menu de gauche, une fois connecté) ;<br>
        • pour toute autre demande, écrire à <a href="mailto:{identite['contact']}">{identite['contact']}</a>.<br>
        Si vous estimez que vos droits ne sont pas respectés, vous pouvez adresser une réclamation à la <b>CNIL</b> (www.cnil.fr).<br><br>
        <b>8. Cookies</b><br>
        Boursy n'utilise aucun cookie publicitaire ni de mesure d'audience. Seuls les cookies techniques nécessaires au fonctionnement de l'application et de la connexion sont utilisés.
    </div>
    """


def html_pied_de_page(identite, nom_app=NOM_APP_LEGAL):
    """Ligne de bas de page : nature du service, paiement sécurisé et contact."""
    return (
        f"<div style='text-align: center; font-size: 0.80em; opacity: 0.72; padding: 6px 0 14px 0;'>"
        f"⚖️ <b>{nom_app} SaaS</b> — Suite Boursière PEA, US & Dividendes | "
        f"Outil d'analyse statistique et pédagogique (Non-CIF) • Paiements sécurisés par Stripe • Contact : {identite['contact']}"
        f"</div>"
    )


def afficher_pages_legales(nom_editeur="", siret="", adresse="", contact="", nom_app=NOM_APP_LEGAL):
    """Volet des pages légales (5 onglets) puis ligne de bas de page."""
    identite = identite_editeur(nom_editeur, siret, adresse, contact)
    st.markdown("---")
    with st.expander(f"⚖️ Mentions Légales, CGV, Droit de Rétractation & Avertissement AMF ({nom_app} SaaS)", expanded=False):
        onglet_amf, onglet_cgv, onglet_retractation, onglet_mentions, onglet_confidentialite = st.tabs([
            "🛡️ 1. Avertissement AMF (Non-CIF)",
            "💳 2. CGV & Abonnements (4,90 € / 8,90 €)",
            "⏳ 3. Droit de Rétractation (L221-28)",
            "🏛️ 4. Mentions Légales",
            "🔒 5. Politique de Confidentialité",
        ])
        with onglet_amf:
            afficher_html(html_avertissement_amf(nom_app))
        with onglet_cgv:
            afficher_html(html_cgv(nom_app))
        with onglet_retractation:
            afficher_html(html_retractation())
        with onglet_mentions:
            afficher_html(html_mentions_legales(identite))
        with onglet_confidentialite:
            afficher_html(html_confidentialite(identite))
    afficher_html(html_pied_de_page(identite, nom_app))
