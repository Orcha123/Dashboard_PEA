"""
Comptes Boursy et abonnement protégé (module sans Streamlit).

Règles de sécurité, couvertes par tests/test_comptes.py :
- le niveau d'abonnement ne vient jamais de user_data, que chaque utilisateur peut modifier sur sa ligne : il est lu
  dans la table protégée « abonnements » (lecture de sa propre ligne seulement) ou vérifié en direct sur Stripe ;
- la table « abonnements » n'est écrite qu'avec le client serveur (clé service_role), après vérification Stripe ;
- le compte administrateur est reconnu sur un utilisateur authentifié, par son identifiant (recommandé) ou à défaut
  par son adresse e-mail, jamais par une simple saisie ;
- un niveau inconnu ou illisible vaut « gratuit ».

Les clients Supabase et les secrets sont passés par l'application (app.py).
"""
from datetime import datetime

NIVEAUX = ("gratuit", "premium", "pro")
TABLES_DU_COMPTE = ("portfolio_history", "user_data", "abonnements")
MESSAGE_SUPPRESSION_INDISPONIBLE = (
    "La suppression automatique n'est pas disponible pour le moment. Écrivez-nous à l'adresse de contact des mentions "
    "légales."
)


def est_compte_admin(user, admin_user_id="", admin_email=""):
    """Vrai si l'utilisateur authentifié est l'administrateur (identifiant prioritaire, sinon adresse e-mail)."""
    if user is None:
        return False
    if admin_user_id:
        return str(getattr(user, "id", "")) == str(admin_user_id)
    if not admin_email:
        return False
    return str(getattr(user, "email", "") or "").strip().lower() == str(admin_email).strip().lower()


def lire_abonnement_protege(client, user_id):
    """Ligne de l'utilisateur dans la table abonnements (dict), {} s'il n'en a pas, None si la lecture échoue."""
    if client is None or not user_id:
        return None
    try:
        reponse = client.table("abonnements").select("niveau, stripe_customer_id, fin_programmee").eq("user_id", str(user_id)).execute()
        return dict(reponse.data[0]) if reponse.data else {}
    except Exception:
        return None


def enregistrer_abonnement_protege(client_serveur, user_id, niveau, client_id, fin, maintenant=None):
    """Écrit le niveau vérifié sur Stripe dans la table abonnements. False si la clé de service manque ou si l'écriture échoue."""
    if client_serveur is None or niveau not in NIVEAUX:
        return False
    try:
        client_serveur.table("abonnements").upsert({
            "user_id": str(user_id),
            "niveau": niveau,
            "stripe_customer_id": client_id,
            "fin_programmee": fin,
            "verifie_le": (maintenant or datetime.now().astimezone()).isoformat(),
        }).execute()
        return True
    except Exception:
        return False


def supprimer_compte(client_serveur, user_id):
    """
    Efface définitivement un compte : snapshots, données de portefeuille, abonnement, puis le compte de connexion.
    Nécessite le client serveur. Renvoie (succès, message d'erreur éventuel).
    """
    if client_serveur is None or not user_id:
        return False, MESSAGE_SUPPRESSION_INDISPONIBLE
    identifiant = str(user_id)
    try:
        for table in TABLES_DU_COMPTE:
            client_serveur.table(table).delete().eq("user_id", identifiant).execute()
        client_serveur.auth.admin.delete_user(identifiant)
        return True, ""
    except Exception as erreur:
        return False, (f"La suppression n'a pas pu aboutir ({erreur}). Réessayez ou écrivez-nous à l'adresse de contact "
                       "des mentions légales.")


def decider_niveau(ligne, verdict_stripe):
    """
    Niveau retenu à partir de la ligne protégée (dict, éventuellement vide) et du verdict Stripe (dict ou None).
    - Sans verdict (Stripe non configuré ou injoignable) : la ligne protégée fait foi.
    - Avec un verdict : il fait foi, et la ligne protégée est à réécrire s'il diffère d'elle.
    Renvoie {"niveau", "fin", "client_id", "a_enregistrer"}.
    """
    ligne = ligne if isinstance(ligne, dict) else {}
    niveau = ligne.get("niveau") if ligne.get("niveau") in NIVEAUX else "gratuit"
    fin, client_enregistre = ligne.get("fin_programmee"), ligne.get("stripe_customer_id")
    if not isinstance(verdict_stripe, dict) or verdict_stripe.get("niveau") not in NIVEAUX:
        return {"niveau": niveau, "fin": fin, "client_id": client_enregistre, "a_enregistrer": False}
    client_id = verdict_stripe.get("client_id") or client_enregistre
    nouveau = (verdict_stripe["niveau"], verdict_stripe.get("fin"), client_id)
    return {"niveau": nouveau[0], "fin": nouveau[1], "client_id": client_id,
            "a_enregistrer": nouveau != (niveau, fin, client_enregistre)}
