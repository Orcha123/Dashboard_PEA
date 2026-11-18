"""
Échéances fiscales du PEA : date des 5 ans, plafond des versements et ordre de grandeur de l'impôt d'un retrait.
Sans Streamlit.

Règles en vigueur en 2026 (Code monétaire et financier, article D. 221-113-3 ; BOFiP BOI-RPPM-RCM-40-50 ;
service-public.fr, fiche F2385 ; loi de financement de la sécurité sociale pour 2026) :
- l'ancienneté fiscale court à partir du PREMIER VERSEMENT sur le plan, pas de la signature du contrat ;
- avant 5 ans, tout retrait clôture le plan (sauf licenciement, invalidité ou mise à la retraite anticipée du titulaire
  ou de son conjoint, ou création ou reprise d'entreprise dans les 3 mois) ; le gain est imposé au prélèvement
  forfaitaire unique : 12,8 % d'impôt sur le revenu et 18,6 % de prélèvements sociaux (option possible pour le barème) ;
- après 5 ans, les retraits partiels ne clôturent plus le plan et les versements restent possibles ; le gain est
  exonéré d'impôt sur le revenu, seuls les prélèvements sociaux (18,6 % depuis 2026) restent dus sur la part de gain
  retirée ; une sortie en rente viagère est exonérée d'impôt sur le revenu ;
- plafond : 150 000 € de versements (225 000 € pour le PEA et le PEA-PME réunis) ; les gains n'y comptent pas.
"""
from datetime import date

PLAFOND_PEA = 150000.0
PLAFOND_PEA_ET_PEA_PME = 225000.0
ANNEES_AVANTAGE = 5
TAUX_IMPOT_REVENU = 0.128
TAUX_PRELEVEMENTS_SOCIAUX = 0.186  # depuis le 1er janvier 2026 (17,2 % auparavant)
SEUIL_PLAFOND_PROCHE = 0.80
JOURS_AVANT_RAPPEL = 92  # le résumé mensuel prévient environ 3 mois avant les 5 ans
JOURS_APRES_RAPPEL = 31  # ... et le mois où ils sont atteints
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre",
        "décembre"]


def lire_date(valeur):
    """date à partir d'un texte AAAA-MM-JJ (ou d'une date) ; None si illisible."""
    if isinstance(valeur, date):
        return valeur
    try:
        return date.fromisoformat(str(valeur or "")[:10])
    except ValueError:
        return None


def date_fr(jour):
    return f"{jour.day}{'er' if jour.day == 1 else ''} {MOIS[jour.month - 1]} {jour.year}"


def date_des_5_ans(premier_versement):
    """Jour où le plan a 5 ans. Premier versement un 29 février : le 1er mars (jamais un jour trop tôt)."""
    try:
        return premier_versement.replace(year=premier_versement.year + ANNEES_AVANTAGE)
    except ValueError:
        return date(premier_versement.year + ANNEES_AVANTAGE, 3, 1)


def anciennete(premier_versement, aujourd_hui):
    """(années, mois) révolus depuis le premier versement."""
    mois = (aujourd_hui.year - premier_versement.year) * 12 + aujourd_hui.month - premier_versement.month
    if aujourd_hui.day < premier_versement.day:
        mois -= 1
    mois = max(0, mois)
    return mois // 12, mois % 12


def texte_anciennete(ans, mois):
    morceaux = []
    if ans:
        morceaux.append(f"{ans} an{'s' if ans > 1 else ''}")
    if mois or not ans:
        morceaux.append(f"{mois} mois")
    return " et ".join(morceaux)


def premier_achat_pea_du_journal(portefeuille):
    """Date du plus ancien achat en euros du journal (suggestion pour le premier versement) ; None si aucun."""
    dates = []
    for e in (portefeuille or {}).get("_journal_achats") or []:
        if isinstance(e, dict) and e.get("devise", "EUR") != "USD" and e.get("sens", "achat") == "achat":
            jour = lire_date(e.get("date"))
            if jour:
                dates.append(jour)
    return min(dates) if dates else None


def versements_nets_estimes(cout_lignes_pea, ventes, dividendes_encaisses):
    """
    Versements nets estimés du PEA : coût des lignes en euros (espèces comprises), moins les plus-values actées dans le
    PEA (ventes en euros) et les dividendes encaissés, qui ont financé une partie de ces lignes sans nouveau versement.
    """
    pv_pea = sum(float(v.get("plus_value_eur", 0.0) or 0.0) for v in (ventes or [])
                 if isinstance(v, dict) and v.get("devise", "€") != "$")
    return max(0.0, float(cout_lignes_pea or 0.0) - max(0.0, pv_pea + float(dividendes_encaisses or 0.0)))


def etat_pea(portefeuille, aujourd_hui, versements=None, valeur=None):
    """
    Échéances du PEA. portefeuille["_pea"]["premier_versement"] : date saisie par l'utilisateur (AAAA-MM-JJ).
    versements : versements nets estimés ; valeur : valeur des lignes du PEA. Montants d'impôt : ordres de grandeur
    pour une clôture aujourd'hui (gain = valeur - versements), avant et après les 5 ans.
    """
    reglages = (portefeuille or {}).get("_pea")
    premier = lire_date(reglages.get("premier_versement")) if isinstance(reglages, dict) else None
    if premier and premier > aujourd_hui:
        premier = None
    etat = {
        "premier_versement": premier,
        "suggestion": None if premier else premier_achat_pea_du_journal(portefeuille),
        "date_5_ans": None, "plus_de_5_ans": None, "jours_restants": None, "anciennete": None,
        "versements": None, "part_plafond": None, "reste_versable": None, "plafond_proche": False,
        "valeur": None, "gain": None, "impot_avant_5_ans": None, "impot_apres_5_ans": None, "ecart_impot": None,
    }
    if premier:
        echeance = date_des_5_ans(premier)
        etat.update(date_5_ans=echeance, plus_de_5_ans=aujourd_hui >= echeance,
                    jours_restants=max(0, (echeance - aujourd_hui).days), anciennete=anciennete(premier, aujourd_hui))
    if versements is not None:
        versements = max(0.0, float(versements))
        etat.update(versements=versements, part_plafond=versements / PLAFOND_PEA,
                    reste_versable=max(0.0, PLAFOND_PEA - versements),
                    plafond_proche=versements / PLAFOND_PEA >= SEUIL_PLAFOND_PROCHE)
        if valeur is not None:
            gain = max(0.0, float(valeur) - versements)
            etat.update(valeur=float(valeur), gain=gain,
                        impot_avant_5_ans=gain * (TAUX_IMPOT_REVENU + TAUX_PRELEVEMENTS_SOCIAUX),
                        impot_apres_5_ans=gain * TAUX_PRELEVEMENTS_SOCIAUX,
                        ecart_impot=gain * TAUX_IMPOT_REVENU)
    return etat


def rappel_du_mois(etat, aujourd_hui):
    """
    Échéance à signaler dans le résumé mensuel : {"type": "bientot" | "atteint", "date_5_ans", "jours"} quand les 5 ans
    tombent dans les 3 prochains mois ou ont été atteints il y a moins d'un mois ; None sinon.
    """
    echeance = (etat or {}).get("date_5_ans")
    if not echeance:
        return None
    ecart = (echeance - aujourd_hui).days
    if 0 < ecart <= JOURS_AVANT_RAPPEL:
        return {"type": "bientot", "date_5_ans": echeance, "jours": ecart}
    if -JOURS_APRES_RAPPEL <= ecart <= 0:
        return {"type": "atteint", "date_5_ans": echeance, "jours": -ecart}
    return None
