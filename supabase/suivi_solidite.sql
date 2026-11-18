-- =============================================================================
-- Boursy : suivi de la solidité des dividendes en conditions réelles (classement enregistré chaque mois de janvier)
-- Protocole : etudes/protocole_suivi_dividendes.md. À exécuter UNE fois dans Supabase > SQL Editor.
-- =============================================================================
create table if not exists public.suivi_solidite (
  annee integer not null,             -- classement au 31 décembre de cette année
  symbole text not null,
  nom text,
  dans_catalogue boolean not null default true,
  categorie text not null,            -- 'solide', 'neutre', 'alerte' ou 'non classée'
  alertes text,
  rendement double precision,         -- dividende de l'année / cours du 31 décembre
  dividende double precision,         -- dividende par action de l'année (devise de l'action) ; null si illisible
  dividende_precedent double precision,
  seuil_rendement double precision,   -- seuil des 20 % de rendements les plus élevés du catalogue cette année-là
  enregistre_le timestamptz not null default now(),
  primary key (annee, symbole)
);

-- Sécurité par ligne activée, sans aucune règle : seule la clé service_role (tâche planifiée et serveur de
-- l'application) peut lire et écrire. Personne ne doit pouvoir modifier un classement après coup.
alter table public.suivi_solidite enable row level security;
