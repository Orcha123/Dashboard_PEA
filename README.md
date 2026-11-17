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
| `SUPABASE_SERVICE_KEY` | Clé `service_role` : seule autorisée à écrire la table protégée `abonnements` (voir plus bas) |
| `ADMIN_USER_ID` | UUID Supabase du compte administrateur (recommandé) |
| `ADMIN_EMAIL` | E-mail du compte administrateur, utilisé si `ADMIN_USER_ID` est absent |
| `CONTACT_EMAIL` | Adresse de contact des mentions légales (par défaut : `ADMIN_EMAIL`) |
| `EDITEUR_NOM`, `EDITEUR_SIRET`, `EDITEUR_ADRESSE` | Identité de l'éditeur affichée dans les mentions légales et la politique de confidentialité (obligatoire, loi LCEN) |
| `STRIPE_SECRET_KEY` | Vérification des abonnements |
| `STRIPE_PRICE_PREMIUM`, `STRIPE_PRICE_PRO` | Identifiants de prix Stripe (`price_...`), séparés par des virgules |
| `STRIPE_PREMIUM_URL`, `STRIPE_PRO_URL`, `STRIPE_PORTAL_URL` | Liens de paiement et portail client |
| `GEMINI_API_KEY` | Coach IA et import de portefeuille par capture d'écran |
| `SMTP_EMAIL`, `SMTP_PASSWORD` | Envoi des alertes par e-mail (Gmail) |

Aucune adresse e-mail ni clé n'est écrite dans le code : tout passe par ces secrets.

## Base Supabase

Trois tables, toutes avec la sécurité par ligne (RLS) activée :

- `user_data` : une ligne par compte (watchlist, portefeuille, budget). Chaque utilisateur lit et modifie sa ligne.
- `portfolio_history` : un snapshot par jour et par compte. Chaque utilisateur lit et modifie les siens.
- `abonnements` : le niveau d'abonnement vérifié sur Stripe. Chaque utilisateur peut **lire** sa ligne, mais
  **personne ne peut l'écrire depuis l'application** : seule la clé `service_role` le peut, après vérification
  Stripe. Un utilisateur ne peut donc plus se déclarer Premium ou Pro lui-même. Script de création :
  `supabase/abonnements.sql`.

Ne créez jamais de règle RLS avec la condition `true` : elle ouvrirait la table à tout le monde.

### Mot de passe oublié

Deux réglages dans Supabase, *Authentication* :

1. *URL Configuration* > **Site URL** : l'adresse exacte de l'application (par exemple `https://boursy.streamlit.app`).
2. *Emails* > *Templates* > **Reset Password** : remplacez le lien du modèle par
   `<a href="{{ .SiteURL }}?type=recovery&token_hash={{ .TokenHash }}">Choisir un nouveau mot de passe</a>`.

L'application lit alors le jeton dans l'adresse et affiche le formulaire de nouveau mot de passe. Le lien par défaut
de Supabase place le jeton après un `#`, que le serveur Streamlit ne peut pas lire.

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
| `SUPABASE_SERVICE_KEY` | Clé `service_role` de Supabase (*Project Settings > API*). Elle donne accès à tous les comptes : uniquement dans les secrets (GitHub et Streamlit), jamais dans le code ni dans un fichier du dépôt |
| `SMTP_EMAIL`, `SMTP_PASSWORD` | Compte Gmail d'envoi et son mot de passe d'application |

Variable facultative `APP_URL` (onglet *Variables*) : adresse de l'application, ajoutée en bouton dans l'e-mail.

Pour tester sans rien envoyer : onglet *Actions* > *Alertes prix cibles Boursy* > *Run workflow*, ou en local
`ALERTES_DRY_RUN=1 python alertes_quotidiennes.py`. GitHub suspend les tâches planifiées d'un dépôt resté
60 jours sans activité ; il suffit alors de les réactiver dans l'onglet *Actions*.

## Bilan des signaux et journal en direct

L'onglet Radar contient un bilan qui rejoue les algorithmes sur jusqu'à 7 ans d'historique (votre radar ou tout le
catalogue) et compare trois algorithmes : le score actuel du radar, le même score avec un filtre de tendance
(pas de signal fort sous la moyenne mobile à 200 jours) et un nouveau score « Tendance & Dividende » (tendance,
momentum 12-1 mois, faible volatilité, rendement et régularité du dividende).

Chaque signal y est comparé aux autres actions étudiées le même mois, avec une fourchette à 95 % qui regroupe les
observations par mois et par action. Une première version comparait chaque action à sa propre moyenne : sur des cours
simulés sans aucune prévisibilité, cette mesure donnait environ +1,3 point à 6 mois aux signaux forts du score actuel
et -2,7 points à ceux du score Tendance & Dividende, un biais purement mécanique. La comparaison au même mois n'a pas
ce défaut (détails et calibration dans `ecart_vs_autres_actions_du_mois`, `moteur_signaux.py`).

Pour un test sans retouche possible, la tâche planifiée enregistre aussi, une fois par mois, les signaux des trois
algorithmes sur tout le catalogue (`journal_signaux.py`), dans la table `signaux_mensuels`. À créer une fois dans
*SQL Editor* avec `supabase/signaux_mensuels.sql`. Seule la clé `service_role` peut lire et écrire cette table.

## Organisation du code

| Fichier | Rôle |
| --- | --- |
| `app.py` | Application Streamlit |
| `moteur_signaux.py` | Indicateurs, score du radar et algorithmes du bilan (sans Streamlit) |
| `catalogue_valeurs.py` | Catalogue des valeurs suivies |
| `alertes_quotidiennes.py` | Tâche du soir : e-mails d'alerte |
| `journal_signaux.py` | Tâche du soir : enregistrement mensuel des signaux |

## Apparence

Le thème (sombre par défaut) est défini dans `.streamlit/config.toml` ; le reste de l'habillage est dans le bloc
`STYLE_ARGON` en tête de `app.py`.

## Avertissement

Outil d'analyse statistique à vocation pédagogique. Ce n'est pas un conseil en investissement.
