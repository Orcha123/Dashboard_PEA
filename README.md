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

## DCA guidé par l'allocation cible

Dans l'onglet Radar, chacun fixe la part que chaque ligne devrait représenter dans son portefeuille (« Définir mon
allocation cible » ; par défaut, parts égales entre les lignes détenues). Chaque mois, l'enveloppe DCA va d'abord aux
lignes les plus en retard sur leur cible, en actions entières, sans jamais rien vendre ; ce qui ne peut pas être
investi reste en liquidités pour le mois suivant. Les poids sont enregistrés dans le portefeuille (clé technique
`_allocation_cible`). Le calcul (`allocation_dca.py`) n'utilise aucune prévision : le radar est affiché à titre
d'information, puisque le bilan des signaux n'a pas montré d'avantage démontré.

## Carnet de décisions

Dans l'onglet Portefeuille, « 📓 Carnet de décisions » : à chaque achat, vente ou décision d'attendre, l'utilisateur
note une raison (liste courte) et une phrase. Les achats du journal et les ventes enregistrées avec une raison y
arrivent automatiquement. Boursy montre ensuite ce qu'est devenue la valeur, dividendes compris et convertie en euros,
face à l'ETF MSCI World (CW8) sur la même période, à 1, 3, 6 et 12 mois : pour un achat, l'écart avec l'ETF ; pour une
vente ou une attente, la hausse manquée ou la baisse évitée. À 6 mois, la décision est proposée à la relecture
(« Ce que j'en retiens ») et rappelée dans le résumé mensuel par e-mail ; un bilan par raison montre quels
raisonnements ont tenu. Les décisions sont enregistrées dans le portefeuille (clé technique `_carnet_decisions`) ;
les calculs sont dans `carnet_decisions.py`.

## Fraîcheur des cours

Les cours viennent de Yahoo Finance et sont relus toutes les 5 minutes pendant les heures de bourse (du lundi au
vendredi, de 9h00 à 22h05, heure de Paris), toutes les heures le reste du temps. La page se rafraîchit seule en
séance ; chaque visiteur peut couper ce rafraîchissement dans la barre latérale. Les cours d'Euronext restent
différés d'environ 15 minutes par Yahoo : ce n'est pas du temps réel. Le rythme se règle avec la constante
`RAFRAICHISSEMENT_SEANCE_SECONDES` de `donnees_marche.py`.

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

### Résumé mensuel du DCA

`resume_mensuel.py` tourne dans la même tâche du soir, avec les mêmes secrets. Pour chaque abonné Pro qui l'a activé
dans le Centre d'Alertes (avec son jour d'achat, du 1 au 28), il envoie un e-mail par mois, le premier soir de bourse
situé dans les 3 jours qui précèdent l'achat : l'achat proposé selon l'allocation cible (même calcul que
l'application), la valeur du portefeuille et la rente estimée, les dividendes attendus ce mois-là et les valeurs du
radar sous leur prix cible, et les décisions du carnet arrivées à 6 mois. Si trop de cours manquent, l'envoi est reporté au soir suivant. Le mois envoyé est noté
dans le portefeuille (`_resume_envoye`) pour ne jamais l'envoyer deux fois. Un bouton du Centre d'Alertes envoie un
aperçu immédiat. Test sans envoi : `ALERTES_DRY_RUN=1 python resume_mensuel.py`.

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
| `catalogue_valeurs.py` | Catalogue des valeurs suivies, et symboles renommés (ex. FDJ.PA devenu FDJU.PA) |
| `allocation_dca.py` | Achat du mois selon l'allocation cible (sans Streamlit) |
| `carnet_decisions.py` | Carnet de décisions : enregistrement, résultats face à l'ETF Monde, relecture (sans Streamlit) |
| `paiements_stripe.py` | Abonnements Stripe : qui a droit à Premium ou Pro (sans Streamlit, sans lecture de secret) |
| `comptes.py` | Compte administrateur, table protégée `abonnements`, niveau retenu, suppression du compte (sans Streamlit) |
| `courriels.py` | Composition et envoi des e-mails (SMTP), partagé par l'application et les tâches du soir |
| `habillage.css`, `habillage.py` | Feuille de style ; nombres au format français et affichage du HTML |
| `pages_legales.py` | Avertissement AMF, CGV, rétractation, mentions légales (LCEN), confidentialité (RGPD) |
| `onglets/radar.py` | Onglet 1 : radar, achat du mois, centre d'alertes, résumé mensuel, bilan des signaux |
| `onglets/coach_ia.py` | Onglet 4 : coach et audits IA (Gemini ou moteur local) |
| `onglets/calendrier.py` | Onglet 3 : objectif de rente, calendrier des dividendes, détachements, boule de neige |
| `onglets/ventes.py` | Onglet 5 : arbitrages, ventes et plus-values actées (Pro) |
| `donnees_marche.py` | Lecture de Yahoo Finance (cours, historiques, change, indices, dividendes, recherche), heures de marché, rendement annualisé (sans Streamlit) |
| `alertes_quotidiennes.py` | Tâche du soir : e-mails d'alerte |
| `journal_signaux.py` | Tâche du soir : enregistrement mensuel des signaux |
| `resume_mensuel.py` | Tâche du soir : résumé mensuel du DCA par e-mail (aussi utilisé pour l'aperçu dans l'application) |
| `tests/` | Tests automatiques (voir ci-dessous) |

## Tests et vérification automatique

```bash
pip install pytest pyflakes
python -m pyflakes $(git ls-files '*.py')
python -m pytest tests
```

- `tests/test_application.py` lance l'application complète en mode test de Streamlit, sans réseau
  (`tests/banc_application.py` remplace Yahoo Finance, Supabase et Stripe par des versions factices). Pour chaque
  profil (visiteur, gratuit, Pro), il vérifie que les 5 onglets et les principaux volets s'affichent sans erreur, puis
  rejoue les actions clés : noter une décision, enregistrer une allocation cible, enregistrer un achat, et ouvrir
  les fonctions Pro à un abonné vérifié sur Stripe.
  Il vérifie aussi qu'un compte ne peut pas être supprimé tant qu'un abonnement est actif, et l'envoi du rapport
  d'alertes par e-mail.
- Les autres fichiers testent les modules un par un (allocation, résumé mensuel, carnet, paiements Stripe, comptes,
  e-mails, données de marché, habillage, pages légales).

À chaque pull request, GitHub lance ces vérifications (`.github/workflows/tests.yml`) et affiche un voyant vert ou
rouge avant la fusion. Pour rendre ce voyant obligatoire : *Settings > Branches > Add branch ruleset* sur `main`,
avec « Require status checks to pass » et la vérification `tests`.

### Découpage d'`app.py`

`app.py` est découpé étape par étape, chaque étape vérifiée par ces tests :

1. ✅ Paiements Stripe (`paiements_stripe.py`), avec le filet de tests.
2. ✅ Comptes et abonnement protégé (`comptes.py`), e-mails (`courriels.py`).
3. ✅ Données de marché (`donnees_marche.py`) : un seul lecteur Yahoo pour l'application et les tâches du soir.
4. ✅ Habillage (`habillage.css`, `habillage.py`) et pages légales (`pages_legales.py`).
5. Les onglets, un par un, dans `onglets/` : chaque onglet devient une fonction `afficher(...)` dont les paramètres
   nommés sont la liste exacte de ses dépendances. ✅ Onglets 1 (radar), 3 (calendrier), 4 (coach IA) et 5 (ventes) ;
   restent l'onglet 2 (portefeuille) et le Super-Pack Pro.

## Apparence

Le thème (sombre par défaut) est défini dans `.streamlit/config.toml` ; le reste de l'habillage est dans la feuille
de style `habillage.css` (CSS pur, modifiable sans toucher au code), injectée au début de chaque page par
`habillage.py`. Ce module met aussi les nombres au format français (`nombres_fr`). Les textes légaux (AMF, CGV,
rétractation, mentions légales, confidentialité) sont dans `pages_legales.py`.

## Avertissement

Outil d'analyse statistique à vocation pédagogique. Ce n'est pas un conseil en investissement.
