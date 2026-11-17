"""
Moteur de signaux de Boursy : indicateurs techniques, score du radar et algorithmes comparés dans le bilan.

Module sans Streamlit, partagé par l'application (radar et bilan des signaux) et par la tâche planifiée qui
enregistre les signaux chaque mois (journal_signaux.py).
"""
import math
from datetime import datetime, timedelta


# ==============================================================================
# INDICATEURS TECHNIQUES ET SCORE DU RADAR (repris tels quels de app.py)
# ==============================================================================
def calculer_rsi(clotures, periode=14):
    if len(clotures) < periode + 1:
        return 50.0
    variations = [clotures[i] - clotures[i - 1] for i in range(1, len(clotures))]
    gains = [v if v > 0 else 0 for v in variations[-periode:]]
    pertes = [-v if v < 0 else 0 for v in variations[-periode:]]
    moy_gain = sum(gains) / periode
    moy_perte = sum(pertes) / periode
    if moy_perte == 0:
        return 100.0
    rs = moy_gain / moy_perte
    return 100.0 - (100.0 / (1.0 + rs))

def calculer_stochastique(clotures, hauts, bas, periode=14):
    if len(clotures) < periode or len(hauts) < periode or len(bas) < periode:
        return 50.0
    plus_bas = min(bas[-periode:])
    plus_haut = max(hauts[-periode:])
    if plus_haut == plus_bas:
        return 50.0
    k = ((clotures[-1] - plus_bas) / (plus_haut - plus_bas)) * 100.0
    return max(0.0, min(100.0, k))

def calculer_atr_pct(clotures, hauts, bas, periode=14):
    n = min(len(clotures), len(hauts), len(bas))
    if n < periode + 1 or clotures[-1] <= 0:
        return 1.5
    trs = []
    for i in range(n - periode, n):
        tr = max(
            hauts[i] - bas[i],
            abs(hauts[i] - clotures[i - 1]),
            abs(bas[i] - clotures[i - 1])
        )
        trs.append(tr)
    atr = sum(trs) / len(trs)
    return (atr / clotures[-1]) * 100.0

def calculer_bollinger(clotures, periode=20):
    if len(clotures) < periode:
        return clotures[-1] * 0.95, clotures[-1] * 1.05
    fenetre = clotures[-periode:]
    moyenne = sum(fenetre) / periode
    variance = sum((x - moyenne) ** 2 for x in fenetre) / periode
    ecart_type = math.sqrt(variance)
    return moyenne - (2 * ecart_type), moyenne + (2 * ecart_type)

def calculer_macd(clotures):
    if len(clotures) < 35:
        return 0.0, 0.0
    k12, k26, k9 = 2 / 13, 2 / 27, 2 / 10
    e12, e26 = sum(clotures[:12]) / 12, sum(clotures[:26]) / 26
    macds = []
    for i, prix in enumerate(clotures):
        if i >= 12:
            e12 = (prix * k12) + (e12 * (1 - k12))
        if i >= 26:
            e26 = (prix * k26) + (e26 * (1 - k26))
            macds.append(e12 - e26)
    if len(macds) < 9:
        return macds[-1], 0.0
    sig = sum(macds[:9]) / 9
    for m in macds[9:]:
        sig = (m * k9) + (sig * (1 - k9))
    return macds[-1], sig

def calculer_ema_serie(clotures, periode):
    if not clotures:
        return []
    k = 2 / (periode + 1)
    emas = []
    if len(clotures) >= periode:
        sma = sum(clotures[:periode]) / periode
        ema = sma
        for i, prix in enumerate(clotures):
            if i < periode - 1:
                emas.append(None)
            elif i == periode - 1:
                emas.append(sma)
            else:
                ema = (prix * k) + (ema * (1 - k))
                emas.append(ema)
    else:
        ema = clotures[0]
        for prix in clotures:
            ema = (prix * k) + (ema * (1 - k))
            emas.append(ema)
    return emas

def analyser_signal_ema_2_12(clotures):
    if len(clotures) < 15:
        return "⚪ Neutre", 0
    ema2_serie = calculer_ema_serie(clotures, 2)
    ema12_serie = calculer_ema_serie(clotures, 12)
    valides = [(e2, e12) for e2, e12 in zip(ema2_serie, ema12_serie) if e2 is not None and e12 is not None]
    if len(valides) < 2:
        return "⚪ Neutre", 0
    veille_e2, veille_e12 = valides[-2]
    jour_e2, jour_e12 = valides[-1]
    ecart_pct = ((jour_e2 - jour_e12) / jour_e12 * 100) if jour_e12 > 0 else 0.0

    if veille_e2 <= veille_e12 and jour_e2 > jour_e12:
        return "🟢 Croisement haussier", 15
    elif jour_e2 > jour_e12 and ecart_pct >= 0.20:
        return "🟢 Tendance haussière", 12
    elif veille_e2 >= veille_e12 and jour_e2 < jour_e12:
        return "🔴 Croisement baissier", -10
    else:
        return "⚪ Neutre", 5

def calculer_score_radar(prix_actuel, prix_cible, payout_r, rendement_actuel, ecart_reg_pct, pts_ema, rsi, stoch_k,
                         borne_inf, borne_sup, macd_val, macd_sig, statut_ema_2_12):
    """Score /100 et décision du radar. Renvoie (score, est_surevalue, decision). Utilisée aussi par le bilan des signaux."""
    score = 0
    if payout_r <= 0.55:
        score += 18
    elif payout_r <= 0.72:
        score += 13
    else:
        score += 6

    if rendement_actuel >= 0.05:
        score += 15
    elif rendement_actuel >= 0.03:
        score += 11
    else:
        score += 6

    if prix_cible > 0 and prix_actuel <= prix_cible:
        score += 15
    elif prix_cible > 0 and prix_actuel <= prix_cible * 1.05:
        score += 8

    if ecart_reg_pct <= -10:
        score += 15
    elif ecart_reg_pct < 0:
        score += 10
    elif ecart_reg_pct <= 5:
        score += 4

    score += pts_ema

    if rsi <= 32 or stoch_k <= 20:
        score += 14
    elif rsi <= 46 or stoch_k <= 35:
        score += 9
    elif rsi >= 72 and stoch_k >= 80:
        score -= 10

    if prix_actuel <= borne_inf * 1.02:
        score += 6
    if macd_val > macd_sig:
        score += 7
    else:
        score -= 2

    score = int(min(100, max(0, score)))
    est_surevalue = (prix_cible > 0 and prix_actuel >= prix_cible * 1.22 and (rsi >= 70 or prix_actuel >= borne_sup))

    if est_surevalue:
        decision = "🟠 ZONE HAUTE"
    elif score >= 65 and "🔴" not in statut_ema_2_12:
        decision = "🟢 SIGNAL FORT"
    elif score >= 45 and "🔴" not in statut_ema_2_12:
        decision = "🔵 SIGNAL FAVORABLE"
    else:
        decision = "⚪ SIGNAL NEUTRE"
    return score, est_surevalue, decision


def calculer_regression_lineaire(clotures):
    n = len(clotures)
    if n < 2:
        return clotures[-1], 0.0, [], 0.0
    x = list(range(n))
    moy_x, moy_y = sum(x) / n, sum(clotures) / n
    numerateur = sum((x[i] - moy_x) * (clotures[i] - moy_y) for i in range(n))
    denominateur = sum((x[i] - moy_x) ** 2 for i in range(n))
    pente = numerateur / denominateur if denominateur != 0 else 0
    ordonnee = moy_y - (pente * moy_x)
    droite_regression = [(pente * i) + ordonnee for i in range(n)]
    residus = [clotures[i] - droite_regression[i] for i in range(n)]
    std_res = math.sqrt(sum(r ** 2 for r in residus) / n)
    val_reg = max(0.01, float(droite_regression[-1]))
    ecart_pct = ((clotures[-1] - val_reg) / val_reg) * 100.0
    return val_reg, ecart_pct, droite_regression, std_res


# ==============================================================================
# ALGORITHMES COMPARÉS DANS LE BILAN DES SIGNAUX
# ==============================================================================
SIGNAL_FORT, SIGNAL_FAVORABLE, SIGNAL_NEUTRE = "🟢 SIGNAL FORT", "🔵 SIGNAL FAVORABLE", "⚪ SIGNAL NEUTRE"

# Clé de décision dans les observations -> libellé affiché
ALGORITHMES_SIGNAUX = {
    "decision_actuelle": "Score actuel du radar",
    "decision_tendance": "Score actuel + filtre de tendance",
    "decision_nouveau": "Nouveau score Tendance & Dividende",
}


def moyenne_mobile(clotures, periode):
    fenetre = clotures[-periode:]
    return sum(fenetre) / len(fenetre) if fenetre else 0.0


def decision_avec_filtre_tendance(decision, prix, moyenne_200):
    """Variante décidée à l'avance : pas de signal fort quand le cours est sous sa moyenne mobile à 200 jours."""
    if decision == SIGNAL_FORT and prix < moyenne_200:
        return SIGNAL_FAVORABLE
    return decision


def sommes_dividendes_annuelles(dividendes, date_t, nombre_annees=5):
    """Sommes des dividendes détachés sur chacune des N dernières périodes de 365 jours (la plus récente d'abord)."""
    fin = datetime.fromisoformat(str(date_t)[:10])
    sommes = []
    for k in range(nombre_annees):
        borne_haute = (fin - timedelta(days=365 * k)).date().isoformat()
        borne_basse = (fin - timedelta(days=365 * (k + 1))).date().isoformat()
        sommes.append(sum(m for d, m in dividendes if borne_basse < d <= borne_haute))
    return sommes


def calculer_score_tendance_dividende(clotures, dividendes, date_t, date_debut_historique):
    """
    Nouveau score « Tendance & Dividende » sur 100, construit sur des facteurs parmi les plus documentés par la
    recherche, avec des paramètres standards fixés à l'avance (pas ajustés sur vos données) :
    - tendance de fond (25 pts) : cours au-dessus de sa moyenne mobile à 200 jours ;
    - momentum 12-1 mois (25 pts) : performance entre il y a 12 mois et il y a 1 mois ;
    - faible volatilité (20 pts) : volatilité annualisée des 12 derniers mois ;
    - rendement du dividende (15 pts) : dividendes des 12 derniers mois / cours ;
    - régularité du dividende (15 pts) : versé chaque année depuis 5 ans, sans baisse sur 2 ans.
    Philosophie opposée au score actuel : il privilégie ce qui monte calmement et paie régulièrement,
    plutôt que ce qui a baissé. Renvoie (score, décision).
    """
    prix = clotures[-1]
    score = 0
    if len(clotures) >= 200 and prix > moyenne_mobile(clotures, 200):
        score += 25
    if len(clotures) >= 253 and clotures[-253] > 0:
        momentum = clotures[-22] / clotures[-253] - 1.0
        score += 25 if momentum > 0.10 else (15 if momentum > 0 else (5 if momentum > -0.10 else 0))
    if len(clotures) >= 253:
        rendements = [clotures[i] / clotures[i - 1] - 1.0 for i in range(len(clotures) - 252, len(clotures)) if clotures[i - 1] > 0]
        if len(rendements) > 2:
            moyenne_r = sum(rendements) / len(rendements)
            volatilite = math.sqrt(sum((r - moyenne_r) ** 2 for r in rendements) / (len(rendements) - 1)) * math.sqrt(252)
            score += 20 if volatilite < 0.20 else (12 if volatilite < 0.30 else (5 if volatilite < 0.40 else 0))
    sommes = sommes_dividendes_annuelles(dividendes, date_t, 5)
    rendement = sommes[0] / prix if prix > 0 else 0.0
    score += 15 if rendement >= 0.04 else (10 if rendement >= 0.025 else (5 if rendement > 0 else 0))
    cinq_ans_connus = str(date_debut_historique) <= (datetime.fromisoformat(str(date_t)[:10]) - timedelta(days=365 * 5)).date().isoformat()
    if not cinq_ans_connus:
        score += 5
    elif all(s > 0 for s in sommes):
        score += 15 if (sommes[0] + sommes[1]) >= 0.9 * (sommes[2] + sommes[3]) else 7
    decision = SIGNAL_FORT if score >= 70 else (SIGNAL_FAVORABLE if score >= 50 else SIGNAL_NEUTRE)
    return score, decision


def evaluer_signaux_a_la_date(dates, clotures, plus_hauts, plus_bas, dividendes, rang, payout_r, fenetre=756):
    """
    Les trois algorithmes à la date dates[rang], avec uniquement les données connues à cette date
    (3 ans de cours, dividendes passés). Le prix cible, inconnu dans le passé, n'est pas compté.
    """
    debut = rang - fenetre + 1
    c, h, b = clotures[debut:rang + 1], plus_hauts[debut:rang + 1], plus_bas[debut:rang + 1]
    prix, date_t = c[-1], dates[rang]
    dividendes_connus = [(d, m) for d, m in dividendes if d <= date_t]
    il_y_a_un_an = (datetime.fromisoformat(date_t) - timedelta(days=365)).date().isoformat()
    dividende_12_mois = sum(m for d, m in dividendes_connus if d > il_y_a_un_an)
    statut_ema, pts_ema = analyser_signal_ema_2_12(c)
    borne_inf, borne_sup = calculer_bollinger(c, 20)
    macd_val, macd_sig = calculer_macd(c)
    _, ecart_reg_pct, _, _ = calculer_regression_lineaire(c)
    score_actuel, _, decision_actuelle = calculer_score_radar(
        prix, 0.0, payout_r, (dividende_12_mois / prix) if prix > 0 else 0.0, ecart_reg_pct, pts_ema,
        calculer_rsi(c, 14), calculer_stochastique(c, h, b, 14), borne_inf, borne_sup, macd_val, macd_sig, statut_ema,
    )
    score_nouveau, decision_nouveau = calculer_score_tendance_dividende(c, dividendes_connus, date_t, dates[0])
    return {
        "date": date_t, "prix": prix,
        "score": score_actuel, "decision_actuelle": decision_actuelle,
        "decision_tendance": decision_avec_filtre_tendance(decision_actuelle, prix, moyenne_mobile(c, 200)),
        "score_nouveau": score_nouveau, "decision_nouveau": decision_nouveau,
    }


def performance_apres(dates, clotures, dividendes, rang, horizon):
    """Performance entre dates[rang] et dates[rang + horizon], dividendes détachés entre-temps inclus ; None si trop tôt."""
    if rang + horizon >= len(clotures):
        return None
    date_t, date_fin = dates[rang], dates[rang + horizon]
    dividendes_periode = sum(m for d, m in dividendes if date_t < d <= date_fin)
    return (clotures[rang + horizon] + dividendes_periode) / clotures[rang] - 1.0


def rejouer_signaux(historique, payout_r, fenetre=756, pas=21):
    """
    Rejoue les trois algorithmes une fois par mois sur un historique (dates, clôtures, dividendes, plus hauts, plus bas)
    et mesure la performance des 1, 3 et 6 mois suivants. La clé « decision » vaut la décision du score actuel.
    """
    dates, clotures, dividendes, plus_hauts, plus_bas = historique
    observations = []
    for rang in range(fenetre - 1, len(clotures) - 21, pas):
        signaux = evaluer_signaux_a_la_date(dates, clotures, plus_hauts, plus_bas, dividendes, rang, payout_r, fenetre)
        signaux["decision"] = signaux["decision_actuelle"]
        signaux.update({
            "r1": performance_apres(dates, clotures, dividendes, rang, 21),
            "r3": performance_apres(dates, clotures, dividendes, rang, 63),
            "r6": performance_apres(dates, clotures, dividendes, rang, 126),
        })
        observations.append(signaux)
    return observations
