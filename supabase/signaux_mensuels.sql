-- =============================================================================
-- Boursy : journal des signaux enregistrés en direct, chaque mois, sur tout le catalogue
-- À exécuter UNE fois dans Supabase > SQL Editor.
-- =============================================================================
create table if not exists public.signaux_mensuels (
  mois text not null,                 -- 'AAAA-MM'
  symbole text not null,
  nom text,
  date_cours text not null,           -- date de la clôture utilisée (AAAA-MM-JJ)
  prix double precision not null,
  score_actuel integer,
  decision_actuelle text,
  decision_tendance text,
  score_nouveau integer,
  decision_nouveau text,
  enregistre_le timestamptz not null default now(),
  primary key (mois, symbole)
);

-- Sécurité par ligne activée, sans aucune règle : seule la clé service_role (tâche planifiée et serveur de
-- l'application) peut lire et écrire. Ces données ne sont pas personnelles, mais personne ne doit pouvoir
-- les modifier après coup : c'est ce qui garantit l'honnêteté du test.
alter table public.signaux_mensuels enable row level security;
