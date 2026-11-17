"""
Alertes automatiques Boursy : e-mail quand une valeur du radar passe sous son prix cible.

Ce script ne fait pas partie de l'application Streamlit. Il est lancé chaque soir de bourse par la tâche planifiée
GitHub Actions (.github/workflows/alertes.yml), même si personne n'ouvre Boursy.

Pour chaque compte Pro ayant activé « Recevoir automatiquement un e-mail » dans le Centre d'Alertes :
- lit les cours de son radar sur Yahoo Finance ;
- envoie UN e-mail listant les valeurs passées sous leur prix cible ;
- ne relance la même valeur qu'après DELAI_RELANCE_JOURS jours, et la réarme dès qu'elle repasse au-dessus.

Variables d'environnement (secrets GitHub du dépôt) :
  SUPABASE_URL, SUPABASE_SERVICE_KEY  clé « service_role » : lit tous les comptes malgré la sécurité par ligne
  SMTP_EMAIL, SMTP_PASSWORD           compte Gmail d'envoi (mot de passe d'application)
  APP_URL                             facultatif, lien vers l'application dans l'e-mail
  ALERTES_DRY_RUN=1                   facultatif, n'envoie rien et n'écrit rien : affiche seulement ce qui serait fait
"""
import html
import json
import os
import smtplib
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

DELAI_RELANCE_JOURS = 7
CLES_TECHNIQUES = (
    "Espèces", "_historique_ventes", "_quota_ia", "_niveau_abo", "_div_encaisses_cumul",
    "_stripe_customer_id", "_alertes_auto", "_alertes_envoyees",
)
ENTETES_YAHOO = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
}


def _env(nom, defaut=""):
    return str(os.environ.get(nom, defaut)).strip()


def requete_supabase(methode, chemin, corps=None):
    """Appel REST à Supabase avec la clé de service. Renvoie le JSON décodé (ou None si la réponse est vide)."""
    url = f"{_env('SUPABASE_URL').rstrip('/')}/rest/v1/{chemin}"
    cle = _env("SUPABASE_SERVICE_KEY")
    donnees = json.dumps(corps).encode("utf-8") if corps is not None else None
    req = urllib.request.Request(url, data=donnees, method=methode, headers={
        "apikey": cle,
        "Authorization": f"Bearer {cle}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    })
    with urllib.request.urlopen(req, timeout=20) as rep:
        brut = rep.read().decode("utf-8")
    return json.loads(brut) if brut.strip() else None


_cache_cours = {}


def cours_actuel(symbole):
    """Dernier cours Yahoo d'un symbole, ou None s'il est indisponible (jamais de valeur inventée)."""
    if symbole in _cache_cours:
        return _cache_cours[symbole]
    prix = None
    sym_enc = urllib.parse.quote(str(symbole).strip())
    for serveur in ("query1", "query2"):
        try:
            req = urllib.request.Request(
                f"https://{serveur}.finance.yahoo.com/v8/finance/chart/{sym_enc}?range=5d&interval=1d",
                headers=ENTETES_YAHOO,
            )
            with urllib.request.urlopen(req, timeout=8) as rep:
                meta = json.loads(rep.read().decode("utf-8"))["chart"]["result"][0]["meta"]
            valeur = float(meta.get("regularMarketPrice") or 0.0)
            if valeur > 0:
                prix = valeur
                break
        except Exception:
            continue
    _cache_cours[symbole] = prix
    return prix


def lire_suivi(liste_brute):
    """Suivi des alertes déjà envoyées : liste de "Nom|AAAA-MM-JJ" -> dictionnaire {nom: date}."""
    suivi = {}
    for entree in liste_brute if isinstance(liste_brute, list) else []:
        nom, _, jour = str(entree).rpartition("|")
        try:
            suivi[nom] = date.fromisoformat(jour)
        except ValueError:
            continue
    return suivi


def valeurs_sous_cible(watchlist):
    """Valeurs du radar dont le cours est connu et inférieur ou égal au prix cible."""
    trouvees = []
    for nom, info in (watchlist or {}).items():
        if nom in CLES_TECHNIQUES or not isinstance(info, dict) or not info.get("symbole"):
            continue
        try:
            cible = float(info.get("prix_cible") or 0.0)
        except (TypeError, ValueError):
            continue
        if cible <= 0:
            continue
        prix = cours_actuel(info["symbole"])
        if prix is not None and prix <= cible:
            trouvees.append({
                "nom": nom,
                "prix": prix,
                "cible": cible,
                "devise": "$" if info.get("devise") == "USD" else "€",
                "ecart_pct": (prix - cible) / cible * 100.0,
            })
    return sorted(trouvees, key=lambda v: v["ecart_pct"])


def decider_envois(sous_cible, suivi, aujourd_hui):
    """
    Renvoie (valeurs à signaler aujourd'hui, nouveau suivi).
    Une valeur est signalée si elle ne l'a jamais été, ou pas depuis DELAI_RELANCE_JOURS jours.
    Une valeur repassée au-dessus de sa cible sort du suivi : elle sera de nouveau signalée à sa prochaine baisse.
    """
    a_signaler, nouveau_suivi = [], {}
    for valeur in sous_cible:
        dernier_envoi = suivi.get(valeur["nom"])
        if dernier_envoi is None or (aujourd_hui - dernier_envoi).days >= DELAI_RELANCE_JOURS:
            a_signaler.append(valeur)
            nouveau_suivi[valeur["nom"]] = aujourd_hui
        else:
            nouveau_suivi[valeur["nom"]] = dernier_envoi
    return a_signaler, nouveau_suivi


def _fr(nombre, decimales=2):
    return f"{nombre:,.{decimales}f}".replace(",", " ").replace(".", ",")


def composer_email(expediteur, destinataire, valeurs):
    message = MIMEMultipart("alternative")
    message["Subject"] = f"🔔 Boursy — {len(valeurs)} valeur(s) sous votre prix cible"
    message["From"] = expediteur
    message["To"] = destinataire
    lignes = "".join(
        f"<li style='margin-bottom:8px;'><b>{html.escape(v['nom'])}</b> : cours <b>{_fr(v['prix'])} {v['devise']}</b> "
        f"pour une cible à {_fr(v['cible'])} {v['devise']} (<b>{_fr(v['ecart_pct'], 1)} %</b>)</li>"
        for v in valeurs
    )
    lien = _env("APP_URL")
    bouton = (
        f"<p><a href='{html.escape(lien)}' style='background:#10b981; color:white; padding:10px 16px; "
        "text-decoration:none; border-radius:6px; font-weight:bold;'>Ouvrir Boursy</a></p>"
        if lien else ""
    )
    corps = f"""
    <html><body style="font-family: Arial, sans-serif; color: #2c3e50;">
        <h2>📈 Alertes prix cibles du {datetime.now().strftime('%d/%m/%Y')}</h2>
        <p>Les valeurs suivantes de votre radar sont passées sous le prix cible que vous avez fixé :</p>
        <ul>{lignes}</ul>
        {bouton}
        <p style="font-size:12px; color:#7f8c8d;">Vous recevez cet e-mail car les alertes automatiques sont activées dans
        votre Centre d'Alertes Boursy ; vous pouvez les désactiver au même endroit. Information statistique à but
        pédagogique, qui ne constitue pas un conseil en investissement.</p>
    </body></html>
    """
    message.attach(MIMEText(corps, "html", "utf-8"))
    return message


def envoyer(message):
    expediteur, mot_de_passe = _env("SMTP_EMAIL"), _env("SMTP_PASSWORD")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=20) as serveur:
        serveur.login(expediteur, mot_de_passe)
        serveur.sendmail(expediteur, message["To"], message.as_string())


def main():
    essai = _env("ALERTES_DRY_RUN") == "1"
    manquantes = [n for n in ("SUPABASE_URL", "SUPABASE_SERVICE_KEY", "SMTP_EMAIL", "SMTP_PASSWORD") if not _env(n)]
    if manquantes:
        print("Configuration incomplète, secrets manquants : " + ", ".join(manquantes))
        return 1

    comptes = requete_supabase("GET", "user_data?select=user_id,email,watchlist,portefeuille") or []
    # Niveau d'abonnement lu dans la table protégée « abonnements » (jamais dans user_data, modifiable par l'utilisateur)
    abonnements = requete_supabase("GET", "abonnements?select=user_id,niveau") or []
    comptes_pro = {str(a.get("user_id")) for a in abonnements if a.get("niveau") == "pro"}
    aujourd_hui = date.today()
    nb_inscrits = nb_emails = nb_erreurs = 0

    for compte in comptes:
        portefeuille = compte.get("portefeuille")
        if not isinstance(portefeuille, dict) or not portefeuille.get("_alertes_auto"):
            continue
        # Les alertes e-mail font partie de l'offre Pro
        if str(compte.get("user_id")) not in comptes_pro or not compte.get("email"):
            continue
        nb_inscrits += 1

        suivi = lire_suivi(portefeuille.get("_alertes_envoyees"))
        a_signaler, nouveau_suivi = decider_envois(valeurs_sous_cible(compte.get("watchlist")), suivi, aujourd_hui)

        try:
            if a_signaler:
                if essai:
                    print(f"[essai] e-mail pour un compte : {[v['nom'] for v in a_signaler]}")
                else:
                    envoyer(composer_email(_env("SMTP_EMAIL"), compte["email"], a_signaler))
                nb_emails += 1
            if nouveau_suivi != suivi and not essai:
                # Relecture juste avant l'écriture : limite le risque d'écraser une modification faite entre-temps
                frais = requete_supabase("GET", f"user_data?select=portefeuille&user_id=eq.{urllib.parse.quote(str(compte['user_id']))}") or []
                pf_frais = frais[0].get("portefeuille") if frais else None
                if isinstance(pf_frais, dict):
                    pf_frais["_alertes_envoyees"] = [f"{nom}|{jour.isoformat()}" for nom, jour in sorted(nouveau_suivi.items())]
                    requete_supabase(
                        "PATCH",
                        f"user_data?user_id=eq.{urllib.parse.quote(str(compte['user_id']))}",
                        {"portefeuille": pf_frais},
                    )
        except Exception as erreur:
            nb_erreurs += 1
            print(f"Erreur sur un compte ({type(erreur).__name__}) : alerte non envoyée ou suivi non enregistré.")

    print(f"{nb_inscrits} compte(s) avec alertes automatiques, {nb_emails} e-mail(s) envoyé(s), {nb_erreurs} erreur(s).")
    return 1 if nb_erreurs else 0


if __name__ == "__main__":
    sys.exit(main())
