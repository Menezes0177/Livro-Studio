-- LivroStudio Online / Supabase
-- Rode este arquivo no SQL Editor do seu projeto Supabase.
-- Depois crie o bucket público "book-covers" em Storage.

create extension if not exists pgcrypto;

create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  username text not null unique,
  created_at timestamptz not null default now()
);

create table if not exists public.books (
  id uuid primary key default gen_random_uuid(),
  author_id uuid not null references auth.users(id) on delete cascade,
  author text not null default 'Autor',
  title text not null,
  synopsis text not null default '',
  text text not null,
  cover_path text not null,
  cover_url text not null,
  visibility text not null default 'private' check (visibility in ('private','public','unlisted')),
  created_at timestamptz not null default now()
);

create table if not exists public.library (
  user_id uuid not null references auth.users(id) on delete cascade,
  book_id uuid not null references public.books(id) on delete cascade,
  added_at timestamptz not null default now(),
  primary key (user_id, book_id)
);

alter table public.profiles enable row level security;
alter table public.books enable row level security;
alter table public.library enable row level security;

-- Profiles
create policy "profiles readable by authenticated users"
on public.profiles for select to authenticated
using (true);

create policy "users can create own profile"
on public.profiles for insert to authenticated
with check (id = auth.uid());

create policy "users can update own profile"
on public.profiles for update to authenticated
using (id = auth.uid())
with check (id = auth.uid());

-- Books: public Explorer can read public books; owners can manage own books.
create policy "public books readable"
on public.books for select to anon, authenticated
using (visibility = 'public' or author_id = auth.uid());

create policy "users can publish own books"
on public.books for insert to authenticated
with check (author_id = auth.uid());

create policy "owners can update books"
on public.books for update to authenticated
using (author_id = auth.uid())
with check (author_id = auth.uid());

create policy "owners can delete books"
on public.books for delete to authenticated
using (author_id = auth.uid());

-- Library: each user sees and manages only their own saved books.
create policy "users can read own library"
on public.library for select to authenticated
using (user_id = auth.uid());

create policy "users can add to own library"
on public.library for insert to authenticated
with check (user_id = auth.uid());

create policy "users can remove from own library"
on public.library for delete to authenticated
using (user_id = auth.uid());

-- Grants for the Data API roles.
grant select on public.books to anon;
grant select, insert, update, delete on public.books to authenticated;
grant select, insert, update on public.profiles to authenticated;
grant select, insert, delete on public.library to authenticated;

-- Storage bucket: create it in Dashboard as PUBLIC with name: book-covers
-- Storage policies restrict uploads/deletes to the folder named with the user's UUID.
create policy "authenticated users upload own book covers"
on storage.objects for insert to authenticated
with check (
  bucket_id = 'book-covers'
  and (storage.foldername(name))[1] = (auth.uid())::text
);

create policy "users can update own book covers"
on storage.objects for update to authenticated
using (
  bucket_id = 'book-covers'
  and (storage.foldername(name))[1] = (auth.uid())::text
)
with check (
  bucket_id = 'book-covers'
  and (storage.foldername(name))[1] = (auth.uid())::text
);

create policy "users can delete own book covers"
on storage.objects for delete to authenticated
using (
  bucket_id = 'book-covers'
  and (storage.foldername(name))[1] = (auth.uid())::text
);
