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

## Fraîcheur des cours

Les cours viennent de Yahoo Finance et sont relus toutes les 5 minutes pendant les heures de bourse (du lundi au
vendredi, de 9h00 à 22h05, heure de Paris), toutes les heures le reste du temps. La page se rafraîchit seule en
séance ; chaque visiteur peut couper ce rafraîchissement dans la barre latérale. Les cours d'Euronext restent
différés d'environ 15 minutes par Yahoo : ce n'est pas du temps réel. Le rythme se règle avec la constante
`RAFRAICHISSEMENT_SEANCE_SECONDES` de `app.py`.

## Alertes automatiques par e-mail

`alertes_quotidiennes.py` est lancé chaque soir de bourse par GitHub Actions (`.github/workflows/alertes.yml`),
même si personne n'ouvre l'application. Il prévient par e-mail les abonnés Pro qui ont activé l'option dans le
Centre d'Alertes dès qu'une valeur de leur radar passe sous son prix cible (une relance au plus par semaine).

À renseigner dans GitHub : *Settings > Secrets and variables > Actions*.

| Secret GitHub | Rôle |
| --- | --- |
| `SUPABASE_URL` | Même valeur que dans Streamlit |
| `SUPABASE_SERVICE_KEY` | Clé `service_role` de Supabase (*Project Settings > API*). Elle donne accès à tous les comptes : ne la mettez que dans les secrets GitHub, jamais dans le code ni dans Streamlit |
| `SMTP_EMAIL`, `SMTP_PASSWORD` | Compte Gmail d'envoi et son mot de passe d'application |

Variable facultative `APP_URL` (onglet *Variables*) : adresse de l'application, ajoutée en bouton dans l'e-mail.

Pour tester sans rien envoyer : onglet *Actions* > *Alertes prix cibles Boursy* > *Run workflow*, ou en local
`ALERTES_DRY_RUN=1 python alertes_quotidiennes.py`. GitHub suspend les tâches planifiées d'un dépôt resté
60 jours sans activité ; il suffit alors de les réactiver dans l'onglet *Actions*.

## Apparence

Le thème (sombre par défaut) est défini dans `.streamlit/config.toml` ; le reste de l'habillage est dans le bloc
`STYLE_ARGON` en tête de `app.py`.

## Avertissement

Outil d'analyse statistique à vocation pédagogique. Ce n'est pas un conseil en investissement.
