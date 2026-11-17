"""
Catalogue des valeurs suivies par Boursy (PEA, Europe, ETF, États-Unis).

Pour chaque valeur : (symbole Yahoo, devise, secteur, prix cible par défaut, dividende annuel, payout ratio,
croissance du dividende sur 5 ans, mois de versement). Utilisé par l'application et par la tâche planifiée.
"""

ENRICHISSEMENT_CATALOGUE = {
    # Actions Françaises (CAC 40 & SBF 120 - PEA)
    "Air Liquide": ("AI.PA", "EUR", "Chimie/Industrie", 165.0, 3.20, 0.55, "+8.5%", ["Mai"]),
    "Airbus": ("AIR.PA", "EUR", "Aéronautique/Défense", 145.0, 2.00, 0.35, "+6.5%", ["Avr"]),
    "Alstom": ("ALO.PA", "EUR", "Ferroviaire", 18.0, 0.25, 0.30, "+2.0%", ["Juil"]),
    "Alten": ("ATE.PA", "EUR", "Ingénierie/Tech", 95.0, 1.50, 0.25, "+8.0%", ["Juin"]),
    "Amundi": ("AMUN.PA", "EUR", "Finance/Gestion", 62.0, 4.10, 0.70, "+5.5%", ["Mai"]),
    "Arkema": ("AKE.PA", "EUR", "Chimie", 82.0, 3.50, 0.45, "+6.5%", ["Mai"]),
    "AXA": ("CS.PA", "EUR", "Assurance", 35.0, 1.98, 0.55, "+9.2%", ["Mai"]),
    "Bic": ("BB.PA", "EUR", "Consommation", 58.0, 2.85, 0.50, "+5.0%", ["Mai"]),
    "BioMérieux": ("BIM.PA", "EUR", "Santé/Diagnostic", 98.0, 0.85, 0.28, "+6.0%", ["Mai"]),
    "BNP Paribas": ("BNP.PA", "EUR", "Banque", 65.0, 4.60, 0.50, "+7.0%", ["Mai"]),
    "Bolloré": ("BOL.PA", "EUR", "Holding/Logistique", 5.6, 0.07, 0.25, "+3.0%", ["Juin"]),
    "Bouygues": ("EN.PA", "EUR", "BTP/Télécoms", 32.0, 1.90, 0.65, "+3.5%", ["Mai"]),
    "Bureau Veritas": ("BVI.PA", "EUR", "Certification", 27.0, 0.83, 0.55, "+6.0%", ["Mai"]),
    "Capgemini": ("CAP.PA", "EUR", "Services IT", 165.0, 3.40, 0.35, "+10.0%", ["Mai"]),
    "Carrefour": ("CA.PA", "EUR", "Distribution", 14.0, 0.87, 0.52, "+8.0%", ["Juin"]),
    "Coface": ("COFA.PA", "EUR", "Assurance Crédit", 13.5, 1.30, 0.80, "+7.5%", ["Mai"]),
    "Covivio": ("COV.PA", "EUR", "Immobilier", 48.0, 3.30, 0.78, "+2.0%", ["Mai"]),
    "Crédit Agricole": ("ACA.PA", "EUR", "Banque", 14.0, 1.05, 0.55, "+6.5%", ["Mai"]),
    "Danone": ("BN.PA", "EUR", "Agroalimentaire", 60.0, 2.10, 0.60, "+3.5%", ["Mai"]),
    "Dassault Aviation": ("AM.PA", "EUR", "Aéronautique/Défense", 195.0, 3.37, 0.32, "+9.0%", ["Mai"]),
    "Dassault Systèmes": ("DSY.PA", "EUR", "Logiciels/Tech", 33.0, 0.23, 0.22, "+7.0%", ["Mai"]),
    "Edenred": ("EDEN.PA", "EUR", "Paiements/Services", 34.0, 1.10, 0.48, "+9.5%", ["Mai"]),
    "Eiffage": ("FGR.PA", "EUR", "BTP/Concessions", 88.0, 4.10, 0.42, "+8.5%", ["Mai"]),
    "Elis": ("ELIS.PA", "EUR", "Services Industriels", 20.0, 0.43, 0.30, "+6.0%", ["Mai"]),
    "Engie": ("ENGI.PA", "EUR", "Énergie/Utilities", 16.0, 1.43, 0.65, "+5.0%", ["Mai"]),
    "EssilorLuxottica": ("EL.PA", "EUR", "Santé/Optique", 205.0, 3.95, 0.55, "+7.5%", ["Mai"]),
    "Eurazeo": ("RF.PA", "EUR", "Private Equity", 72.0, 2.42, 0.45, "+8.0%", ["Mai"]),
    "Euronext": ("ENX.PA", "EUR", "Bourse/Finance", 92.0, 2.48, 0.50, "+6.5%", ["Mai"]),
    "FDJ United": ("FDJU.PA", "EUR", "Loisirs/Loterie", 34.0, 1.78, 0.75, "+7.0%", ["Mai"]),  # ex-Française des Jeux
    "GTT - Gaztransport": ("GTT.PA", "EUR", "Ingénierie/GNL", 125.0, 7.30, 0.80, "+11.0%", ["Juin", "Déc"]),
    "Gecina": ("GFC.PA", "EUR", "Immobilier", 92.0, 5.30, 0.75, "+2.0%", ["Mar", "Juil"]),
    "Getlink": ("GET.PA", "EUR", "Infrastructures", 15.5, 0.55, 0.55, "+6.0%", ["Juin"]),
    "Hermès": ("RMS.PA", "EUR", "Luxe", 2050.0, 15.00, 0.35, "+14.0%", ["Fév", "Mai"]),
    "Ipsen": ("IPN.PA", "EUR", "Santé/Pharma", 108.0, 1.20, 0.25, "+4.0%", ["Mai"]),
    "Icade": ("ICAD.PA", "EUR", "Immobilier", 24.0, 4.30, 0.82, "+1.5%", ["Mar", "Juil"]),
    "Interparfums": ("ITP.PA", "EUR", "Cosmétiques/Luxe", 42.0, 1.15, 0.55, "+10.0%", ["Mai"]),
    "Kering": ("KER.PA", "EUR", "Luxe", 230.0, 6.00, 0.58, "+3.0%", ["Jan", "Mai"]),
    "Klépierre": ("LI.PA", "EUR", "Immobilier Commercial", 26.0, 1.80, 0.72, "+4.5%", ["Mar", "Juil"]),
    "L'Oréal": ("OR.PA", "EUR", "Cosmétiques", 360.0, 6.60, 0.52, "+8.5%", ["Avr"]),
    "Legrand": ("LR.PA", "EUR", "Équipement Élec.", 95.0, 2.09, 0.48, "+7.5%", ["Mai"]),
    "LVMH": ("MC.PA", "EUR", "Luxe", 620.0, 13.00, 0.45, "+12.0%", ["Avr", "Déc"]),
    "M6 - Métropole TV": ("MMT.PA", "EUR", "Médias", 12.0, 1.25, 0.68, "+4.0%", ["Mai"]),
    "Michelin": ("ML.PA", "EUR", "Automobile/Pneus", 32.0, 1.35, 0.48, "+6.5%", ["Mai"]),
    "Nexans": ("NEX.PA", "EUR", "Câbles/Énergie", 105.0, 2.30, 0.35, "+10.0%", ["Mai"]),
    "Orange": ("ORA.PA", "EUR", "Télécoms", 10.5, 0.72, 0.68, "+2.0%", ["Juin", "Déc"]),
    "Pernod Ricard": ("RI.PA", "EUR", "Spiritueux", 70.0, 4.70, 0.55, "+6.0%", ["Juil", "Nov"]),
    "Publicis": ("PUB.PA", "EUR", "Communication", 92.0, 3.40, 0.48, "+8.5%", ["Juil"]),
    "Rémy Cointreau": ("RCO.PA", "EUR", "Spiritueux", 62.0, 2.00, 0.52, "+4.0%", ["Oct"]),
    "Renault": ("RNO.PA", "EUR", "Automobile", 42.0, 1.85, 0.30, "+8.0%", ["Mai"]),
    "Rexel": ("RXL.PA", "EUR", "Distribution Élec.", 24.0, 1.20, 0.45, "+7.0%", ["Mai"]),
    "Rubis": ("RUI.PA", "EUR", "Énergie/Stockage", 25.0, 1.98, 0.62, "+3.5%", ["Juin"]),
    "Safran": ("SAF.PA", "EUR", "Aéronautique/Défense", 195.0, 2.20, 0.38, "+9.5%", ["Mai"]),
    "Saint-Gobain": ("SGO.PA", "EUR", "Matériaux", 78.0, 2.10, 0.38, "+7.5%", ["Juin"]),
    "Sanofi": ("SAN.PA", "EUR", "Santé", 90.0, 3.76, 0.58, "+4.8%", ["Mai"]),
    "Schneider Electric": ("SU.PA", "EUR", "Industrie/Tech", 210.0, 3.50, 0.48, "+8.8%", ["Mai"]),
    "Scor": ("SCR.PA", "EUR", "Réassurance", 20.0, 1.80, 0.55, "+4.0%", ["Mai"]),
    "Seb": ("SK.PA", "EUR", "Électroménager", 92.0, 2.62, 0.42, "+5.5%", ["Mai"]),
    "Société Générale": ("GLE.PA", "EUR", "Banque", 25.0, 0.90, 0.40, "+3.0%", ["Mai"]),
    "Sodexo": ("SW.PA", "EUR", "Restauration/Services", 75.0, 3.10, 0.50, "+6.0%", ["Déc"]),
    "Sopra Steria": ("SOP.PA", "EUR", "Services IT", 175.0, 4.65, 0.38, "+9.0%", ["Mai"]),
    "Spie": ("SPIE.PA", "EUR", "Services Énergie", 34.0, 0.83, 0.42, "+7.5%", ["Mai", "Sep"]),
    "Stellantis": ("STLAP.PA", "EUR", "Automobile", 13.0, 1.55, 0.35, "+6.0%", ["Mai"]),
    "STMicroelectronics": ("STMPA.PA", "EUR", "Semi-conducteurs", 26.0, 0.36, 0.18, "+5.0%", ["Mar", "Juin", "Sep", "Déc"]),
    "Téléperformance": ("TEP.PA", "EUR", "Relation Client", 88.0, 3.85, 0.45, "+7.0%", ["Mai"]),
    "TF1": ("TFI.PA", "EUR", "Médias", 8.0, 0.55, 0.62, "+5.0%", ["Avr"]),
    "Thales": ("HO.PA", "EUR", "Défense/Aérospatial", 148.0, 3.40, 0.40, "+8.5%", ["Mai", "Déc"]),
    "TotalEnergies": ("TTE.PA", "EUR", "Énergie", 58.0, 3.22, 0.42, "+6.1%", ["Jan", "Avr", "Juil", "Oct"]),
    "Trigano": ("TRI.PA", "EUR", "Loisirs/Camping-cars", 118.0, 3.50, 0.25, "+9.0%", ["Mai", "Déc"]),
    "Vallourec": ("VK.PA", "EUR", "Énergie/Tubes", 15.0, 1.50, 0.45, "+5.0%", ["Mai"]),
    "Veolia": ("VIE.PA", "EUR", "Environnement", 28.0, 1.25, 0.65, "+6.5%", ["Mai"]),
    "Verallia": ("VRLA.PA", "EUR", "Emballage Verre", 27.0, 2.15, 0.50, "+8.0%", ["Mai"]),
    "Vicat": ("VCT.PA", "EUR", "Matériaux/Ciment", 35.0, 2.00, 0.42, "+4.5%", ["Mai"]),
    "Vinci": ("DG.PA", "EUR", "Concessions/BTP", 105.0, 4.50, 0.52, "+7.5%", ["Avr", "Nov"]),
    "Vivendi": ("VIV.PA", "EUR", "Médias/Divertissement", 9.5, 0.25, 0.45, "+3.0%", ["Avr"]),
    "Wendel": ("MF.PA", "EUR", "Holding/Investissement", 88.0, 4.00, 0.45, "+6.5%", ["Mai"]),

    # Grandes Actions Européennes éligibles PEA
    "Allianz (Allemagne)": ("ALV.DE", "EUR", "Assurance EUR", 265.0, 13.80, 0.60, "+8.0%", ["Mai"]),
    "ASML Holding (Pays-Bas)": ("ASML.AS", "EUR", "Semi-conducteurs EUR", 680.0, 6.10, 0.32, "+14.0%", ["Fév", "Mai", "Août", "Nov"]),
    "BMW (Allemagne)": ("BMW.DE", "EUR", "Automobile EUR", 78.0, 6.00, 0.38, "+5.0%", ["Mai"]),
    "Deutsche Telekom (All.)": ("DTE.DE", "EUR", "Télécoms EUR", 25.0, 0.77, 0.48, "+6.0%", ["Avr"]),
    "Enel (Italie)": ("ENEL.MI", "EUR", "Énergie EUR", 6.8, 0.43, 0.65, "+5.5%", ["Jan", "Juil"]),
    "Ferrari (Italie)": ("RACE.MI", "EUR", "Luxe/Auto EUR", 385.0, 2.44, 0.30, "+12.0%", ["Mai"]),
    "Iberdrola (Espagne)": ("IBE.MC", "EUR", "Énergie Verte EUR", 12.5, 0.55, 0.65, "+6.5%", ["Jan", "Juil"]),
    "Inditex - Zara (Espagne)": ("ITX.MC", "EUR", "Mode/Retail EUR", 46.0, 1.54, 0.60, "+9.0%", ["Mai", "Nov"]),
    "ING Groep (Pays-Bas)": ("INGA.AS", "EUR", "Banque EUR", 15.0, 1.10, 0.50, "+7.0%", ["Mai", "Août"]),
    "Intesa Sanpaolo (Italie)": ("ISP.MI", "EUR", "Banque EUR", 3.6, 0.30, 0.70, "+8.0%", ["Mai", "Nov"]),
    "Mercedes-Benz (Allemagne)": ("MBG.DE", "EUR", "Automobile EUR", 58.0, 5.30, 0.42, "+6.0%", ["Mai"]),
    "SAP (Allemagne)": ("SAP.DE", "EUR", "Logiciels/Cloud EUR", 190.0, 2.20, 0.40, "+7.5%", ["Mai"]),
    "Shell (Pays-Bas)": ("SHELL.AS", "EUR", "Énergie EUR", 31.0, 1.28, 0.38, "+5.0%", ["Mar", "Juin", "Sep", "Déc"]),
    "Siemens (Allemagne)": ("SIE.DE", "EUR", "Industrie/Tech EUR", 170.0, 4.70, 0.48, "+6.5%", ["Fév"]),
    "Unilever (Pays-Bas)": ("UNA.AS", "EUR", "Consommation EUR", 52.0, 1.73, 0.62, "+3.5%", ["Mar", "Juin", "Sep", "Déc"]),

    # ETFs éligibles PEA (Capitalisants / Distribuants)
    "ETF Amundi MSCI World PEA (CW8)": ("CW8.PA", "EUR", "ETF Monde PEA", 510.0, 0.0, 0.0, "+9.5%", ["Mai"]),
    "ETF BNP S&P 500 PEA (ESE)": ("ESE.PA", "EUR", "ETF USA PEA", 25.0, 0.0, 0.0, "+10.5%", ["Mai"]),
    "ETF Amundi Nasdaq-100 PEA (PUST)": ("PUST.PA", "EUR", "ETF Tech US PEA", 72.0, 0.0, 0.0, "+12.0%", ["Mai"]),
    "ETF Amundi Euro Stoxx 50 PEA": ("MSE.PA", "EUR", "ETF Europe PEA", 48.0, 1.45, 0.40, "+6.5%", ["Juil", "Déc"]),

    # Actions Américaines (CTO en USD - Dividend Aristocrats & Tech)
    "AbbVie": ("ABBV", "USD", "Santé US", 175.0, 6.20, 0.58, "+7.5%", ["Fév", "Mai", "Août", "Nov"]),
    "Alphabet - Google": ("GOOGL", "USD", "Tech US", 170.0, 0.80, 0.12, "+10.0%", ["Mar", "Juin", "Sep", "Déc"]),
    "Amazon": ("AMZN", "USD", "Tech/E-Commerce US", 185.0, 0.0, 0.0, "+12.0%", ["Mai"]),
    "Apple": ("AAPL", "USD", "Tech US", 200.0, 1.00, 0.16, "+5.5%", ["Fév", "Mai", "Août", "Nov"]),
    "Broadcom": ("AVGO", "USD", "Semi-conducteurs US", 160.0, 2.12, 0.42, "+14.0%", ["Mar", "Juin", "Sep", "Déc"]),
    "Caterpillar": ("CAT", "USD", "Industrie US", 330.0, 5.64, 0.28, "+8.0%", ["Fév", "Mai", "Août", "Nov"]),
    "Chevron": ("CVX", "USD", "Énergie US", 148.0, 6.52, 0.55, "+6.0%", ["Mar", "Juin", "Sep", "Déc"]),
    "Coca-Cola": ("KO", "USD", "Consommation US", 62.0, 1.94, 0.70, "+4.5%", ["Avr", "Juil", "Oct", "Déc"]),
    "Costco": ("COST", "USD", "Distribution US", 820.0, 4.64, 0.28, "+11.0%", ["Fév", "Mai", "Août", "Nov"]),
    "Eli Lilly": ("LLY", "USD", "Santé/Pharma US", 800.0, 5.20, 0.35, "+15.0%", ["Mar", "Juin", "Sep", "Déc"]),
    "ExxonMobil": ("XOM", "USD", "Énergie US", 112.0, 3.80, 0.44, "+4.5%", ["Mar", "Juin", "Sep", "Déc"]),
    "Home Depot": ("HD", "USD", "Distribution US", 365.0, 9.00, 0.58, "+8.5%", ["Mar", "Juin", "Sep", "Déc"]),
    "Johnson & Johnson": ("JNJ", "USD", "Santé US", 155.0, 4.96, 0.52, "+5.5%", ["Mar", "Juin", "Sep", "Déc"]),
    "JPMorgan Chase": ("JPM", "USD", "Banque US", 205.0, 5.00, 0.28, "+7.0%", ["Jan", "Avr", "Juil", "Oct"]),
    "Main Street Capital (Mensuel)": ("MAIN", "USD", "Finance/BDC US", 48.0, 3.00, 0.72, "+4.5%", ["Jan", "Fév", "Mar", "Avr", "Mai", "Juin", "Juil", "Août", "Sep", "Oct", "Nov", "Déc"]),
    "Mastercard": ("MA", "USD", "Paiements US", 460.0, 2.64, 0.20, "+13.0%", ["Fév", "Mai", "Août", "Nov"]),
    "McDonald's": ("MCD", "USD", "Restauration US", 275.0, 7.08, 0.58, "+7.5%", ["Mar", "Juin", "Sep", "Déc"]),
    "Merck & Co": ("MRK", "USD", "Santé/Pharma US", 112.0, 3.08, 0.48, "+6.5%", ["Jan", "Avr", "Juil", "Oct"]),
    "Meta Platforms": ("META", "USD", "Tech US", 520.0, 2.00, 0.12, "+10.0%", ["Mar", "Juin", "Sep", "Déc"]),
    "Microsoft": ("MSFT", "USD", "Tech US", 400.0, 3.32, 0.25, "+10.2%", ["Mar", "Juin", "Sep", "Déc"]),
    "NVIDIA": ("NVDA", "USD", "IA & Semi-conducteurs US", 120.0, 0.04, 0.02, "+15.0%", ["Mar", "Juin", "Sep", "Déc"]),
    "PepsiCo": ("PEP", "USD", "Consommation US", 168.0, 5.42, 0.66, "+7.0%", ["Jan", "Mar", "Juin", "Sep"]),
    "Pfizer": ("PFE", "USD", "Santé/Pharma US", 28.0, 1.68, 0.68, "+3.0%", ["Mar", "Juin", "Sep", "Déc"]),
    "Procter & Gamble": ("PG", "USD", "Consommation US", 162.0, 4.03, 0.62, "+6.0%", ["Fév", "Mai", "Août", "Nov"]),
    "Realty Income": ("O", "USD", "Immobilier US (REIT)", 55.0, 3.16, 0.74, "+3.8%", ["Jan", "Fév", "Mar", "Avr", "Mai", "Juin", "Juil", "Août", "Sep", "Oct", "Nov", "Déc"]),
    "Texas Instruments": ("TXN", "USD", "Semi-conducteurs US", 185.0, 5.44, 0.65, "+7.5%", ["Fév", "Mai", "Août", "Nov"]),
    "UnitedHealth": ("UNH", "USD", "Santé/Assurance US", 520.0, 8.40, 0.32, "+12.0%", ["Mar", "Juin", "Sep", "Déc"]),
    "Verizon": ("VZ", "USD", "Télécoms US", 40.0, 2.71, 0.60, "+2.0%", ["Fév", "Mai", "Août", "Nov"]),
    "Visa": ("V", "USD", "Paiements US", 275.0, 2.36, 0.22, "+14.0%", ["Mar", "Juin", "Sep", "Déc"]),
    "Walmart": ("WMT", "USD", "Distribution US", 72.0, 0.83, 0.35, "+4.0%", ["Jan", "Avr", "Mai", "Sep"]),
}


# Valeurs renommées ou dont le symbole Yahoo a changé. Les radars et portefeuilles enregistrés avant le changement
# gardent l'ancien nom et l'ancien symbole : l'application et la tâche des alertes les traduisent avec ces tables.
SYMBOLES_RENOMMES = {
    "FDJ.PA": "FDJU.PA",  # La Française des Jeux est devenue FDJ United (symbole FDJU)
}
NOMS_RENOMMES = {
    "FDJ - Française des Jeux": "FDJ United",
}


def symbole_a_jour(symbole):
    """Symbole Yahoo actuel d'une valeur (traduit s'il a changé depuis son ajout au radar)."""
    texte = str(symbole or "").strip()
    return SYMBOLES_RENOMMES.get(texte.upper(), texte)
