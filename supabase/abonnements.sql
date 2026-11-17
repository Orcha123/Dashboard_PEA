-- =============================================================================
-- Boursy : table protégée des abonnements
-- À exécuter UNE fois dans Supabase > SQL Editor, AVANT de déployer la version de l'application qui l'utilise.
-- =============================================================================

-- 1. La table : une ligne par compte, avec le niveau vérifié sur Stripe
create table if not exists public.abonnements (
  user_id uuid primary key references auth.users(id) on delete cascade,
  niveau text not null default 'gratuit' check (niveau in ('gratuit', 'premium', 'pro')),
  stripe_customer_id text,
  fin_programmee text,
  verifie_le timestamptz not null default now()
);

-- 2. Sécurité : chaque utilisateur peut LIRE sa ligne, personne ne peut l'écrire depuis l'application.
--    Seule la clé service_role (secret SUPABASE_SERVICE_KEY, côté serveur) peut créer ou modifier une ligne.
alter table public.abonnements enable row level security;

create policy "Lecture de son abonnement" on public.abonnements
  for select to authenticated
  using ((select auth.uid()) = user_id);

-- Lecture de toutes les lignes pour le compte administrateur (décompte des abonnés dans la console).
-- Remplacez VOTRE-UID-ADMIN par votre UID (Authentication > Users), le même que dans la règle « Lecture administrateur ».
create policy "Lecture administrateur des abonnements" on public.abonnements
  for select to authenticated
  using ((select auth.uid())::text = 'VOTRE-UID-ADMIN');

-- 3. Reprise des abonnés actuels, pour qu'aucun client payant ne perde son accès pendant la transition.
--    Ces valeurs viennent de l'ancien système : elles seront revérifiées sur Stripe à la prochaine connexion
--    de chaque abonné, et corrigées si besoin.
insert into public.abonnements (user_id, niveau)
select d.user_id::uuid,
       case when d.portefeuille ->> '_niveau_abo' in ('premium', 'pro') then d.portefeuille ->> '_niveau_abo' else 'pro' end
from public.user_data d
where d.est_abonne_pro = true
  and exists (select 1 from auth.users u where u.id = d.user_id::uuid)
on conflict (user_id) do nothing;

-- 4. Votre compte administrateur en Pro (utile pour les alertes e-mail automatiques).
insert into public.abonnements (user_id, niveau)
values ('VOTRE-UID-ADMIN', 'pro')
on conflict (user_id) do update set niveau = 'pro';
