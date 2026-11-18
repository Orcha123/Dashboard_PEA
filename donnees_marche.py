"""
Données de marché de Boursy (module sans Streamlit) : lecture de Yahoo Finance, heures de marché et calculs sur les
historiques. Partagé par l'application (qui met les résultats en cache) et par les tâches du soir.

Règles communes, couvertes par tests/test_donnees_marche.py :
- chaque lecture essaie les serveurs query1 puis query2 de Yahoo ;
- une lecture qui échoue lève une erreur (RuntimeError) au lieu de renvoyer une valeur inventée : l'application ne
  met ainsi jamais un échec en cache, et réessaie au prochain affichage ;
- les séries de cours restent alignées séance par séance : une séance sans clôture est écartée de toutes les séries,
  un plus haut ou un plus bas manquant est remplacé par la clôture du jour.
"""
import bisect
import calendar
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

ENTETES_YAHOO = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
}
SERVEURS_YAHOO = ("query1", "query2")
RAFRAICHISSEMENT_SEANCE_SECONDES = 300
MOIS_ABREGES = ["Jan", "Fév", "Mar", "Avr", "Mai", "Juin", "Juil", "Août", "Sep", "Oct", "Nov", "Déc"]
SUFFIXES_EURO = (".PA", ".AS", ".DE", ".MI", ".MC", ".BR", ".HE", ".LS", ".VI")


# ==============================================================================
# HEURES DE MARCHÉ ET FRAÎCHEUR DES COURS
# ==============================================================================
def heure_paris():
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Europe/Paris"))
    except Exception:
        return datetime.now()


def marches_ouverts(maintenant=None):
    """Vrai du lundi au vendredi entre l'ouverture de Paris (9h00) et la clôture de New York (22h05), heure de Paris."""
    maintenant = maintenant or heure_paris()
    minutes = maintenant.hour * 60 + maintenant.minute
    return maintenant.weekday() < 5 and 9 * 60 <= minutes < 22 * 60 + 5


def creneau_cours(maintenant=None, instant=None):
    """
    Étiquette du créneau de cours en vigueur. Les lectures sont mises en cache PAR créneau : un nouveau créneau toutes
    les 5 minutes en séance (cours rafraîchis), toutes les heures sinon.
    """
    instant = int(time.time() if instant is None else instant)
    if marches_ouverts(maintenant):
        return f"S{instant // RAFRAICHISSEMENT_SEANCE_SECONDES}"
    return f"F{instant // 3600}"


# ==============================================================================
# LECTURE DE YAHOO FINANCE
# ==============================================================================
def lire_chart(serveur, symbole, plage, evenements_dividendes=False, timeout=6, intervalle="1d", periode=None):
    """
    Réponse « chart » de Yahoo (premier élément de result) depuis un serveur donné ; lève une exception en cas
    d'échec. Les fonctions ci-dessous essaient chaque serveur de SERVEURS_YAHOO tour à tour.
    periode : (début, fin) en secondes Unix, à la place de la plage (avec range=max, Yahoo peut espacer les points).
    """
    suffixe = "&events=div" if evenements_dividendes else ""
    fenetre = f"period1={int(periode[0])}&period2={int(periode[1])}" if periode else f"range={plage}"
    requete = urllib.request.Request(
        f"https://{serveur}.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(str(symbole).strip())}"
        f"?{fenetre}&interval={intervalle}{suffixe}",
        headers=ENTETES_YAHOO,
    )
    with urllib.request.urlopen(requete, timeout=timeout) as reponse:
        return json.loads(reponse.read().decode("utf-8"))["chart"]["result"][0]


def _series(resultat):
    quote = ((resultat.get("indicators") or {}).get("quote") or [{}])[0]
    return quote.get("close") or [], quote.get("high") or [], quote.get("low") or []


def _haut_bas(bruts, rang, cloture):
    return float(bruts[rang]) if rang < len(bruts) and bruts[rang] is not None else float(cloture)


def dividendes_du_resultat(resultat):
    """Dividendes détachés [(date ISO, montant)], du plus ancien au plus récent."""
    return sorted(
        (datetime.fromtimestamp(int(d["date"])).date().isoformat(), float(d["amount"]))
        for d in ((resultat.get("events") or {}).get("dividends") or {}).values()
        if d.get("date") and float(d.get("amount") or 0) > 0
    )


def cours_et_historique(symbole, plage="3y", timeout=6):
    """(dernier cours, clôtures, plus hauts, plus bas) sur la plage donnée. Lève RuntimeError si indisponible."""
    for serveur in SERVEURS_YAHOO:
        try:
            resultat = lire_chart(serveur, symbole, plage, timeout=timeout)
            clotures_brutes, hauts_bruts, bas_bruts = _series(resultat)
            clotures, hauts, bas = [], [], []
            for rang, cloture in enumerate(clotures_brutes):
                if cloture is None:
                    continue
                clotures.append(float(cloture))
                hauts.append(_haut_bas(hauts_bruts, rang, cloture))
                bas.append(_haut_bas(bas_bruts, rang, cloture))
            prix = float((resultat.get("meta") or {}).get("regularMarketPrice") or (clotures[-1] if clotures else 0.0))
            if prix > 0 and clotures:
                return prix, clotures, hauts, bas
        except Exception:
            continue
    raise RuntimeError(f"Cours indisponible pour {symbole}")


def historique_dix_ans(symbole, seances_closes_seulement=False, aujourd_hui=None, timeout=10):
    """
    (dates ISO, clôtures, dividendes [(date ISO, montant)], plus hauts, plus bas) sur 10 ans. Lève RuntimeError si
    indisponible. seances_closes_seulement : écarte la séance du jour, pas encore close (tâches du soir).
    """
    limite = (aujourd_hui or datetime.now().date()).isoformat() if seances_closes_seulement else None
    for serveur in SERVEURS_YAHOO:
        try:
            resultat = lire_chart(serveur, symbole, "10y", evenements_dividendes=True, timeout=timeout)
            clotures_brutes, hauts_bruts, bas_bruts = _series(resultat)
            dates, clotures, hauts, bas = [], [], [], []
            for rang, (horodatage, cloture) in enumerate(zip(resultat.get("timestamp") or [], clotures_brutes)):
                if cloture is None or float(cloture) <= 0:
                    continue
                jour = datetime.fromtimestamp(int(horodatage)).date().isoformat()
                if limite and jour >= limite:
                    continue
                dates.append(jour)
                clotures.append(float(cloture))
                hauts.append(_haut_bas(hauts_bruts, rang, cloture))
                bas.append(_haut_bas(bas_bruts, rang, cloture))
            if dates:
                return dates, clotures, dividendes_du_resultat(resultat), hauts, bas
        except Exception:
            continue
    raise RuntimeError(f"Historique indisponible : {symbole}")


def clotures_par_mois(resultat, mois_en_cours):
    """
    {« AAAA-MM » : dernière clôture du mois} d'une réponse Yahoo (points mensuels ou quotidiens), mois en cours exclu.
    Horodatages ramenés à l'heure de la place (+6 heures de marge : un point mensuel daté du 1er à minuit, heure
    d'hiver ou d'été, reste dans son mois ; un point quotidien reste dans sa journée).
    """
    decalage = int((resultat.get("meta") or {}).get("gmtoffset") or 0) + 6 * 3600
    clotures = ((resultat.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
    par_mois = {}
    for horodatage, cloture in sorted(zip(resultat.get("timestamp") or [], clotures)):
        if cloture is None or float(cloture) <= 0:
            continue
        mois = datetime.fromtimestamp(int(horodatage) + decalage, tz=timezone.utc).strftime("%Y-%m")
        if mois < mois_en_cours:
            par_mois[mois] = float(cloture)
    return par_mois


def historique_mensuel_dividendes(symbole, annees=11, aujourd_hui=None, timeout=10):
    """
    (dates, clôtures, dividendes [(date ISO, montant)], clôtures, clôtures) au format de historique_dix_ans, mais avec
    une seule clôture par mois (la dernière, mois en cours exclu) sur `annees` ans : environ 20 fois plus léger que
    l'historique quotidien, et tout ce qu'il faut pour la solidité des dividendes. Lève RuntimeError si indisponible.
    """
    maintenant = int(time.time())
    periode = (maintenant - int(annees * 365.25 * 86400), maintenant)
    mois_en_cours = (aujourd_hui or datetime.now().date()).strftime("%Y-%m")
    for serveur in SERVEURS_YAHOO:
        try:
            resultat = lire_chart(serveur, symbole, None, evenements_dividendes=True, timeout=timeout, intervalle="1mo",
                                  periode=periode)
            par_mois = clotures_par_mois(resultat, mois_en_cours)
            if par_mois:
                mois = sorted(par_mois)
                dates = [f"{m}-{calendar.monthrange(int(m[:4]), int(m[5:7]))[1]:02d}" for m in mois]
                clotures = [par_mois[m] for m in mois]
                return dates, clotures, dividendes_du_resultat(resultat), clotures, clotures
        except Exception:
            continue
    raise RuntimeError(f"Historique mensuel indisponible : {symbole}")


def dernier_cours(symbole, timeout=8):
    """Dernier cours (regularMarketPrice), ou None s'il est indisponible : jamais de valeur inventée."""
    for serveur in SERVEURS_YAHOO:
        try:
            meta = lire_chart(serveur, symbole, "5d", timeout=timeout).get("meta") or {}
            valeur = float(meta.get("regularMarketPrice") or 0.0)
            if valeur > 0:
                return valeur
        except Exception:
            continue
    return None


def taux_eur_usd(timeout=5):
    """Dollars pour 1 euro. Lève RuntimeError si indisponible."""
    for serveur in SERVEURS_YAHOO:
        try:
            taux = float(lire_chart(serveur, "EURUSD=X", "1d", timeout=timeout)["meta"]["regularMarketPrice"])
            if taux > 0:
                return taux
        except Exception:
            continue
    raise RuntimeError("Taux EUR/USD indisponible")


def niveau_et_variation(symbole, timeout=5):
    """(niveau, variation du jour en %) d'un indice. Lève RuntimeError si indisponible."""
    for serveur in SERVEURS_YAHOO:
        try:
            resultat = lire_chart(serveur, symbole, "5d", timeout=timeout)
            prix = float(resultat["meta"]["regularMarketPrice"])
            clotures = [float(c) for c in _series(resultat)[0] if c is not None]
            veille = clotures[-2] if len(clotures) >= 2 else float(resultat["meta"].get("chartPreviousClose", prix))
            return prix, ((prix - veille) / veille * 100.0) if veille > 0 else 0.0
        except Exception:
            continue
    raise RuntimeError(f"Indice indisponible : {symbole}")


def tendance_ema_2_12(clotures):
    """Lecture de la tendance d'un indice par croisement des moyennes exponentielles 2 et 12 jours : (libellé, couleur)."""
    if len(clotures) < 15:
        return "⚪ Neutre", "#95a5a6"

    def _ema(valeurs, periode):
        k = 2.0 / (periode + 1.0)
        serie = [valeurs[0]]
        for valeur in valeurs[1:]:
            serie.append(valeur * k + serie[-1] * (1.0 - k))
        return serie

    ema2, ema12 = _ema(clotures, 2), _ema(clotures, 12)
    if ema2[-2] <= ema12[-2] and ema2[-1] > ema12[-1]:
        return "🚀 Croisement haussier", "#2ecc71"
    if ema2[-1] > ema12[-1] and clotures[-1] >= ema2[-1]:
        return "🟢 Tendance haussière", "#2ecc71"
    if ema2[-1] > ema12[-1]:
        return "🟡 Neutre (Pause)", "#f39c12"
    return "🔴 Tendance baissière", "#e74c3c"


def clotures_trois_mois(symbole, timeout=5):
    """Clôtures des 3 derniers mois. Lève RuntimeError si indisponible."""
    for serveur in SERVEURS_YAHOO:
        try:
            return [float(c) for c in _series(lire_chart(serveur, symbole, "3mo", timeout=timeout))[0] if c is not None]
        except Exception:
            continue
    raise RuntimeError(f"Indice indisponible : {symbole}")


def inspecter_dividende(symbole, maintenant=None, timeout=6):
    """
    (cours, devise réelle de cotation, dividende des 12 derniers mois, mois de versement) lus sur Yahoo.
    (None, "EUR", 0.0, ["Mai"]) si la valeur est introuvable.
    """
    maintenant = maintenant or datetime.now()
    for serveur in SERVEURS_YAHOO:
        try:
            resultat = lire_chart(serveur, symbole, "1y", evenements_dividendes=True, timeout=timeout)
            meta = resultat.get("meta") or {}
            clotures = [float(x) for x in _series(resultat)[0] if x is not None]
            cours = float(meta.get("regularMarketPrice") or (clotures[-1] if clotures else 50.0))
            # Devise RÉELLE de cotation (EUR, USD, mais aussi GBP, CHF, DKK...) : l'appelant refuse celles non gérées
            devise = str(meta.get("currency") or "EUR").upper()
            dividende_annuel, mois = 0.0, set()
            seuil = maintenant.timestamp() - 375 * 86400
            for detachement in ((resultat.get("events") or {}).get("dividends") or {}).values():
                horodatage, montant = float(detachement.get("date", 0)), float(detachement.get("amount", 0.0))
                if horodatage >= seuil and montant > 0:
                    dividende_annuel += montant
                    mois.add(datetime.fromtimestamp(horodatage).month)
            noms_mois = [MOIS_ABREGES[m - 1] for m in sorted(mois)] if mois else (["Mar", "Juin", "Sep", "Déc"] if devise == "USD" else ["Mai"])
            return round(cours, 2), devise, round(dividende_annuel, 2), noms_mois
        except Exception:
            continue
    return None, "EUR", 0.0, ["Mai"]


def prochain_detachement(symbole, aujourd_hui=None, jours=90, timeout=5):
    """
    Prochain détachement attendu dans les `jours` jours, projeté à partir des dates des 2 dernières années :
    (jours restants, date, montant), ou (None, None, None).
    """
    aujourd_hui = aujourd_hui or datetime.now().date()
    for serveur in SERVEURS_YAHOO:
        try:
            dividendes = ((lire_chart(serveur, symbole, "2y", evenements_dividendes=True, timeout=timeout)
                           .get("events") or {}).get("dividends") or {})
            candidats = []
            for cle, detachement in dividendes.items():
                jour_passe = datetime.fromtimestamp(int(detachement.get("date", cle))).date()
                montant = float(detachement.get("amount", 0.0))
                for annee in (aujourd_hui.year, aujourd_hui.year + 1):
                    try:
                        jour_projete = jour_passe.replace(year=annee)
                    except ValueError:  # 29 février
                        jour_projete = jour_passe.replace(year=annee, day=28)
                    ecart = (jour_projete - aujourd_hui).days
                    if 0 <= ecart <= jours:
                        candidats.append((ecart, jour_projete, montant))
            return min(candidats, key=lambda c: c[0]) if candidats else (None, None, None)
        except Exception:
            continue
    return None, None, None


def rechercher_yahoo(requete, deja_vus=(), timeout=6):
    """
    Actions et ETF trouvés par la recherche Yahoo : [{"label", "nom", "symbole", "devise", "secteur"}].
    Les symboles de deja_vus (en majuscules) sont ignorés. Liste vide si Yahoo ne répond pas.
    """
    deja_vus, resultats = {str(s).upper() for s in deja_vus}, []
    requete_url = urllib.parse.quote(str(requete).strip())
    for hote in ("query2.finance.yahoo.com", "query1.finance.yahoo.com"):
        try:
            requete_http = urllib.request.Request(
                f"https://{hote}/v1/finance/search?q={requete_url}&quotesCount=10&newsCount=0", headers=ENTETES_YAHOO)
            with urllib.request.urlopen(requete_http, timeout=timeout) as reponse:
                donnees = json.loads(reponse.read().decode("utf-8"))
            for element in donnees.get("quotes", []):
                type_cotation = element.get("quoteType", "")
                symbole = str(element.get("symbol", "")).strip().upper()
                if type_cotation not in ("EQUITY", "ETF") or not symbole or symbole in deja_vus:
                    continue
                nom = element.get("shortname") or element.get("longname") or symbole
                bourse = element.get("exchDisp") or element.get("exchange") or ""
                secteur = element.get("sectorDisp") or element.get("industryDisp") or ("ETF" if type_cotation == "ETF" else "Action Internationale")
                en_euros = any(symbole.endswith(s) for s in SUFFIXES_EURO)
                # Suffixe de place inconnu (.L, .SW, .CO...) : la devise réelle est vérifiée sur Yahoo à la sélection
                libelle_devise = ("EUR" if en_euros else "USD") if (en_euros or "." not in symbole) else "devise à vérifier"
                resultats.append({"label": f"{nom} ({symbole} — {bourse} | {libelle_devise})", "nom": nom, "symbole": symbole,
                                  "devise": "EUR" if en_euros else "USD", "secteur": secteur})
                deja_vus.add(symbole)
            if resultats:
                break
        except Exception:
            continue
    return resultats


# ==============================================================================
# CALCULS SUR LES HISTORIQUES
# ==============================================================================
def cours_a_la_date(historique, date_iso):
    """Dernière clôture connue à la date donnée (ou juste avant) ; None si la date précède l'historique."""
    if not historique:
        return None
    dates, valeurs = historique[0], historique[1]
    indice = bisect.bisect_right(dates, str(date_iso)[:10]) - 1
    return valeurs[indice] if indice >= 0 else None


def taux_rendement_interne(flux):
    """
    Rendement annualisé (TRI, équivalent du XIRR d'Excel) d'une suite de flux [(date ISO, montant)] :
    versements négatifs, retraits et valeur finale positifs. None s'il n'est pas calculable.
    """
    flux = [(datetime.fromisoformat(str(d)[:10]), float(m)) for d, m in flux if m]
    if not flux or all(m >= 0 for _, m in flux) or all(m <= 0 for _, m in flux):
        return None
    origine = min(d for d, _ in flux)

    def valeur_actuelle_nette(taux):
        return sum(m / (1.0 + taux) ** ((d - origine).days / 365.25) for d, m in flux)

    bas, haut = -0.9999, 10.0
    valeur_bas, valeur_haut = valeur_actuelle_nette(bas), valeur_actuelle_nette(haut)
    if valeur_bas * valeur_haut > 0:
        return None
    for _ in range(200):
        milieu = (bas + haut) / 2.0
        valeur_milieu = valeur_actuelle_nette(milieu)
        if valeur_bas * valeur_milieu <= 0:
            haut = milieu
        else:
            bas, valeur_bas = milieu, valeur_milieu
        if haut - bas < 1e-7:
            break
    return (bas + haut) / 2.0
