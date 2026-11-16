# Boursy — Dashboard PEA

Application Streamlit d'aide à la décision d'achat en DCA sur PEA et compte-titres : radar technique noté sur 100,
suivi de portefeuille en euros et en dollars, calendrier de dividendes, coach IA et journal des ventes.

## Lancer l'application

```bash
pip install -r requirements.txt
streamlit run app.py
```

Sans secrets, l'application démarre en « mode local » : pas de compte, pas de sauvegarde, forfait gratuit.

## Secrets Streamlit

À renseigner dans `.streamlit/secrets.toml` en local (fichier ignoré par git) ou dans les réglages de l'application
sur Streamlit Cloud. Aucun n'est obligatoire pour démarrer.

| Secret | Rôle |
| --- | --- |
| `SUPABASE_URL`, `SUPABASE_KEY` | Comptes utilisateurs et sauvegarde cloud |
| `ADMIN_USER_ID` | UUID Supabase du compte administrateur (recommandé) |
| `ADMIN_EMAIL` | E-mail du compte administrateur, utilisé si `ADMIN_USER_ID` est absent |
| `CONTACT_EMAIL` | Adresse de contact des mentions légales (par défaut : `ADMIN_EMAIL`) |
| `STRIPE_SECRET_KEY` | Vérification des abonnements |
| `STRIPE_PRICE_PREMIUM`, `STRIPE_PRICE_PRO` | Identifiants de prix Stripe (`price_...`), séparés par des virgules |
| `STRIPE_PREMIUM_URL`, `STRIPE_PRO_URL`, `STRIPE_PORTAL_URL` | Liens de paiement et portail client |
| `GEMINI_API_KEY` | Coach IA et import de portefeuille par capture d'écran |
| `SMTP_EMAIL`, `SMTP_PASSWORD` | Envoi des alertes par e-mail (Gmail) |

Aucune adresse e-mail ni clé n'est écrite dans le code : tout passe par ces secrets.

## Base Supabase

Deux tables : `user_data` (une ligne par compte : watchlist, portefeuille, budget, abonnement) et
`portfolio_history` (un snapshot par jour). Activez la sécurité par ligne (RLS) sur les deux, avec une règle
limitant chaque utilisateur à ses propres lignes.

## Apparence

Le thème (sombre par défaut) est défini dans `.streamlit/config.toml` ; le reste de l'habillage est dans le bloc
`STYLE_ARGON` en tête de `app.py`.

## Avertissement

Outil d'analyse statistique à vocation pédagogique. Ce n'est pas un conseil en investissement.
