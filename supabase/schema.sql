-- 進捗を保存するテーブル（1ユーザー1行）
create table if not exists public.progress (
  user_id uuid primary key references auth.users(id) on delete cascade,
  data jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);
alter table public.progress enable row level security;
-- ログインした本人の行だけ読み書きできる
create policy "own progress select" on public.progress for select to authenticated using ((select auth.uid()) = user_id);
create policy "own progress insert" on public.progress for insert to authenticated with check ((select auth.uid()) = user_id);
create policy "own progress update" on public.progress for update to authenticated using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
