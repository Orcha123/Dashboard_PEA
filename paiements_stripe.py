"""
Abonnements Boursy sur Stripe (module sans Streamlit).

Ce module décide qui a droit à Premium ou à Pro : il est isolé de l'application et couvert par des tests
(tests/test_paiements_stripe.py). Il ne lit aucun secret lui-même : la clé Stripe et les identifiants de prix lui
sont passés par l'application (app.py), qui les lit dans les secrets Streamlit.

Règles :
- seuls les abonnements « active » ou « trialing » comptent ;
- le palier vient de l'identifiant de prix (STRIPE_PRICE_PREMIUM / STRIPE_PRICE_PRO) ; à défaut, du montant ramené
  au mois (au-delà de 6,00 €/mois = Pro), et jamais Pro par défaut ;
- en cas d'erreur réseau ou de clé absente, rien n'est conclu (None) : l'application garde alors le niveau connu.
"""
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

API_STRIPE = "https://api.stripe.com/v1"
SEUIL_PRO_CENTIMES_PAR_MOIS = 600


def stripe_get(chemin, cle_stripe):
    """Appel GET authentifié à l'API Stripe (lève une exception en cas d'erreur HTTP ou réseau)."""
    requete = urllib.request.Request(f"{API_STRIPE}/{chemin}", headers={"Authorization": f"Bearer {cle_stripe}"})
    with urllib.request.urlopen(requete, timeout=8) as reponse:
        return json.loads(reponse.read().decode("utf-8"))


def creer_session_portail(id_client, cle_stripe, adresse_retour=""):
    """
    Ouvre une session du portail client Stripe et renvoie son adresse (valable quelques minutes) : l'abonné arrive
    directement sur sa page de gestion (résiliation, factures, moyen de paiement), sans e-mail. None si impossible.
    """
    if not cle_stripe or not (isinstance(id_client, str) and id_client.startswith("cus_")):
        return None
    champs = {"customer": id_client}
    if str(adresse_retour or "").startswith("http"):
        champs["return_url"] = adresse_retour
    requete = urllib.request.Request(
        f"{API_STRIPE}/billing_portal/sessions",
        data=urllib.parse.urlencode(champs).encode("utf-8"),
        headers={"Authorization": f"Bearer {cle_stripe}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(requete, timeout=8) as reponse:
            return json.loads(reponse.read().decode("utf-8")).get("url")
    except Exception:
        return None


def ids_prix(texte):
    """Identifiants de prix Stripe (price_...) écrits dans un secret, séparés par des virgules."""
    return {p.strip() for p in str(texte or "").split(",") if p.strip()}


def palier_depuis_abonnement(abonnement, prix_premium=frozenset(), prix_pro=frozenset()):
    """
    Palier ('premium' ou 'pro') d'un abonnement Stripe.
    - Fiable : par identifiant de prix (prix_premium, prix_pro).
    - Repli (identifiant inconnu) : par montant RAMENÉ AU MOIS (un abonnement annuel est divisé par 12),
      <= 6,00 €/mois = Premium, au-delà = Pro. Un montant inconnu ou nul donne Premium (jamais Pro par défaut).
    """
    palier = None
    for ligne in ((abonnement.get("items") or {}).get("data") or []):
        prix = ligne.get("price") or {}
        id_prix = str(prix.get("id") or "")
        if id_prix and id_prix in prix_pro:
            palier_ligne = "pro"
        elif id_prix and id_prix in prix_premium:
            palier_ligne = "premium"
        else:
            try:
                montant_centimes = float(prix.get("unit_amount") or prix.get("unit_amount_decimal") or 0)
            except Exception:
                montant_centimes = 0.0
            recurrence = prix.get("recurring") or {}
            try:
                nombre_periodes = max(1, int(recurrence.get("interval_count") or 1))
            except Exception:
                nombre_periodes = 1
            mois_par_periode = {"day": 1.0 / 30.0, "week": 12.0 / 52.0, "month": 1.0, "year": 12.0}.get(
                str(recurrence.get("interval") or "month"), 1.0
            )
            montant_mensuel = montant_centimes / (mois_par_periode * nombre_periodes)
            palier_ligne = "pro" if montant_mensuel > SEUIL_PRO_CENTIMES_PAR_MOIS else "premium"
        if palier_ligne == "pro":
            return "pro"
        palier = palier_ligne
    return palier or "premium"


def fin_programmee(abonnement):
    """Date (JJ/MM/AAAA) de fin d'accès si une résiliation est programmée, sinon None."""
    if not (abonnement.get("cancel_at_period_end") or abonnement.get("cancel_at")):
        return None
    horodatage_fin = abonnement.get("cancel_at") or abonnement.get("current_period_end")
    if not horodatage_fin:
        # Versions récentes de l'API Stripe : la fin de période est portée par les lignes de l'abonnement
        lignes = (abonnement.get("items") or {}).get("data") or []
        if lignes:
            horodatage_fin = lignes[0].get("current_period_end")
    try:
        return datetime.fromtimestamp(int(horodatage_fin)).strftime("%d/%m/%Y") if horodatage_fin else None
    except Exception:
        return None


def etat_abonnements_client(id_client, cle_stripe, prix_premium=frozenset(), prix_pro=frozenset()):
    """(palier, date de fin programmée) du meilleur abonnement actif d'un client Stripe ; (None, None) si aucun."""
    try:
        donnees = stripe_get(f"subscriptions?customer={urllib.parse.quote(str(id_client))}&status=all&limit=10", cle_stripe)
    except urllib.error.HTTPError as erreur_http:
        if erreur_http.code in (400, 404):  # client Stripe supprimé ou inconnu : aucun abonnement
            return None, None
        raise
    palier, date_fin = None, None
    for abonnement in donnees.get("data", []):
        if abonnement.get("status") not in ("active", "trialing"):
            continue
        if palier != "pro":
            palier = palier_depuis_abonnement(abonnement, prix_premium, prix_pro)
            date_fin = fin_programmee(abonnement)
    return palier, date_fin


def clients_par_reference(user_id, cle_stripe):
    """
    Clients Stripe ayant finalisé un paiement lancé depuis CE compte Boursy. Les liens de paiement transportent
    client_reference_id = identifiant du compte : l'abonné est retrouvé même s'il a payé avec une autre adresse.
    """
    try:
        try:
            donnees = stripe_get("checkout/sessions?limit=100&status=complete", cle_stripe)
        except urllib.error.HTTPError:
            donnees = stripe_get("checkout/sessions?limit=100", cle_stripe)
    except Exception:
        return []
    trouves = []
    for session in donnees.get("data", []):
        if session.get("status") == "complete" and str(session.get("client_reference_id") or "") == str(user_id):
            id_client = session.get("customer")
            if isinstance(id_client, dict):
                id_client = id_client.get("id")
            if id_client and id_client not in trouves:
                trouves.append(id_client)
    return trouves


def verifier_abonnement(email_client, cle_stripe, prix_premium=frozenset(), prix_pro=frozenset(), user_id=None,
                        id_client_memorise=None):
    """
    Vérifie en direct sur Stripe l'état de l'abonnement. Renvoie :
    - {"niveau": "premium" | "pro" | "gratuit", "fin": date de fin programmée ou None, "client_id": "cus_..." ou None} ;
    - None si la clé Stripe manque ou en cas d'erreur (rien n'est alors conclu).

    Le client Stripe est recherché dans cet ordre :
    1. identifiant client mémorisé dans la table protégée « abonnements » ;
    2. adresse e-mail du compte ;
    3. paiements portant le client_reference_id du compte (paiement fait avec une autre adresse).
    """
    if not email_client or not cle_stripe:
        return None
    identifiant = str(user_id) if user_id else ""
    try:
        ids_clients = []
        # 1. Identifiant mémorisé dans la table protégée (jamais dans le portefeuille, que l'utilisateur peut modifier)
        if isinstance(id_client_memorise, str) and id_client_memorise.startswith("cus_"):
            ids_clients.append(id_client_memorise)
        # 2. Recherche par adresse e-mail
        clients = stripe_get(f"customers?email={urllib.parse.quote(str(email_client).strip())}&limit=5", cle_stripe)
        for client in clients.get("data", []):
            id_client = client.get("id")
            if id_client and id_client not in ids_clients:
                ids_clients.append(id_client)

        meilleur = {"palier": None, "fin": None, "client": None}

        def _evaluer(id_client):
            palier, fin = etat_abonnements_client(id_client, cle_stripe, prix_premium, prix_pro)
            if palier and meilleur["palier"] != "pro":
                meilleur.update(palier=palier, fin=fin, client=id_client)

        for id_client in ids_clients:
            _evaluer(id_client)
        # 3. Aucun abonnement trouvé : recherche par référence de compte
        if meilleur["palier"] is None and identifiant:
            for id_client in clients_par_reference(identifiant, cle_stripe):
                if id_client not in ids_clients:
                    ids_clients.append(id_client)
                    _evaluer(id_client)

        if meilleur["palier"] in ("premium", "pro"):
            return {"niveau": meilleur["palier"], "fin": meilleur["fin"], "client_id": meilleur["client"]}
        return {"niveau": "gratuit", "fin": None, "client_id": None}
    except Exception:
        return None
