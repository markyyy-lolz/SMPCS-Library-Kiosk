-- ================================================================
-- SMPCS LIBRARY MANAGEMENT SYSTEM — COMPLETE DATABASE
-- PostgreSQL / Supabase
-- Fresh-install script
-- ================================================================

create extension if not exists pgcrypto;

create table if not exists library_settings (
  key text primary key,
  value text not null,
  updated_at timestamptz not null default now()
);

insert into library_settings(key,value)
values ('setup_complete','false')
on conflict (key) do nothing;

create table if not exists library_users (
  id uuid primary key default gen_random_uuid(),
  username text not null unique,
  full_name text not null,
  password_hash text not null,
  role text not null default 'librarian' check (role in ('admin','librarian')),
  active boolean not null default true,
  created_at timestamptz not null default now()
);

create table if not exists library_members (
  id uuid primary key default gen_random_uuid(),
  member_no text not null unique,
  rfid_uid text unique,
  full_name text not null,
  member_type text not null default 'student' check (member_type in ('student','employee','guest')),
  grade_level text,
  section text,
  gender text,
  photo_url text,
  active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists library_books (
  id uuid primary key default gen_random_uuid(),
  book_rfid text unique,
  accession_no text unique,
  isbn text,
  title text not null,
  author text,
  category text,
  publisher text,
  publication_year int,
  shelf text,
  total_copies int not null default 1 check (total_copies >= 0),
  available_copies int not null default 1 check (available_copies >= 0),
  active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists library_loans (
  id uuid primary key default gen_random_uuid(),
  member_id uuid not null references library_members(id) on delete restrict,
  book_id uuid not null references library_books(id) on delete restrict,
  borrowed_at timestamptz not null default now(),
  due_at timestamptz not null default (now() + interval '7 days'),
  returned_at timestamptz,
  borrowed_by text,
  returned_by text,
  status text not null default 'borrowed' check (status in ('borrowed','returned','lost','cancelled')),
  notes text
);

create table if not exists library_attendance (
  id uuid primary key default gen_random_uuid(),
  member_id uuid not null references library_members(id) on delete restrict,
  action text not null check (action in ('IN','OUT')),
  scanned_at timestamptz not null default now(),
  station_code text,
  notes text
);

create table if not exists library_kiosk_stations (
  id uuid primary key default gen_random_uuid(),
  station_code text not null unique,
  station_name text not null,
  station_token text not null unique default encode(gen_random_bytes(18),'hex'),
  active boolean not null default true,
  last_seen_at timestamptz,
  created_at timestamptz not null default now()
);

create table if not exists library_audit_log (
  id bigint generated always as identity primary key,
  actor_username text,
  action text not null,
  entity_type text,
  entity_id text,
  details jsonb,
  created_at timestamptz not null default now()
);

create index if not exists idx_members_rfid on library_members(rfid_uid);
create index if not exists idx_members_name on library_members(full_name);
create index if not exists idx_books_rfid on library_books(book_rfid);
create index if not exists idx_loans_member_status on library_loans(member_id,status);
create index if not exists idx_attendance_member_time on library_attendance(member_id,scanned_at desc);
create index if not exists idx_audit_created on library_audit_log(created_at desc);

-- RLS is enabled. Public clients should use RPCs instead of direct table writes.
alter table library_settings enable row level security;
alter table library_users enable row level security;
alter table library_members enable row level security;
alter table library_books enable row level security;
alter table library_loans enable row level security;
alter table library_attendance enable row level security;
alter table library_kiosk_stations enable row level security;
alter table library_audit_log enable row level security;

drop policy if exists settings_read on library_settings;
create policy settings_read on library_settings for select to anon, authenticated using (true);

drop policy if exists members_read on library_members;
create policy members_read on library_members for select to anon, authenticated using (true);

drop policy if exists books_read on library_books;
create policy books_read on library_books for select to anon, authenticated using (true);

drop policy if exists loans_read on library_loans;
create policy loans_read on library_loans for select to anon, authenticated using (true);

drop policy if exists attendance_read on library_attendance;
create policy attendance_read on library_attendance for select to anon, authenticated using (true);

drop policy if exists stations_read on library_kiosk_stations;
create policy stations_read on library_kiosk_stations for select to anon, authenticated using (true);

drop policy if exists audit_read on library_audit_log;
create policy audit_read on library_audit_log for select to anon, authenticated using (true);

-- No direct anonymous inserts/updates/deletes.
revoke insert, update, delete on library_users from anon, authenticated;
revoke insert, update, delete on library_members from anon, authenticated;
revoke insert, update, delete on library_books from anon, authenticated;
revoke insert, update, delete on library_loans from anon, authenticated;
revoke insert, update, delete on library_attendance from anon, authenticated;
revoke insert, update, delete on library_kiosk_stations from anon, authenticated;
revoke insert, update, delete on library_audit_log from anon, authenticated;

-- Password hashes are bcrypt hashes produced by the Python client.
create or replace function library_setup_admin(
  p_username text,
  p_full_name text,
  p_password_hash text
) returns jsonb
language plpgsql security definer set search_path=public
as $$
declare
  cnt int;
  uid uuid;
begin
  select count(*) into cnt from library_users;
  if cnt > 0 then
    raise exception 'SETUP_ALREADY_COMPLETE';
  end if;
  if length(trim(p_username)) < 3 then raise exception 'INVALID_USERNAME'; end if;
  if length(p_password_hash) < 20 then raise exception 'INVALID_PASSWORD_HASH'; end if;
  insert into library_users(username,full_name,password_hash,role)
  values(lower(trim(p_username)),trim(p_full_name),p_password_hash,'admin')
  returning id into uid;
  update library_settings set value='true',updated_at=now() where key='setup_complete';
  return jsonb_build_object('id',uid,'username',lower(trim(p_username)));
end $$;

create or replace function library_setup_status()
returns jsonb
language sql security definer set search_path=public
as $$
select jsonb_build_object(
  'complete', exists(select 1 from library_users where active=true),
  'users', (select count(*) from library_users)
)
$$;

grant execute on function library_setup_status() to anon,authenticated;

create or replace function library_login(
  p_username text
) returns jsonb
language plpgsql security definer set search_path=public
as $$
declare u library_users;
begin
  select * into u from library_users where username=lower(trim(p_username)) and active=true limit 1;
  if not found then raise exception 'INVALID_LOGIN'; end if;
  return jsonb_build_object(
    'id',u.id,'username',u.username,'full_name',u.full_name,'role',u.role,
    'password_hash',u.password_hash
  );
end $$;

create or replace function library_save_member(
  p_member_no text, p_rfid_uid text, p_full_name text, p_member_type text,
  p_grade_level text default null, p_section text default null, p_gender text default null
) returns jsonb
language plpgsql security definer set search_path=public
as $$
declare mid uuid;
begin
  insert into library_members(member_no,rfid_uid,full_name,member_type,grade_level,section,gender)
  values(trim(p_member_no),nullif(trim(p_rfid_uid),''),trim(p_full_name),p_member_type,
         nullif(trim(p_grade_level),''),nullif(trim(p_section),''),nullif(trim(p_gender),''))
  on conflict (member_no) do update set
    rfid_uid=excluded.rfid_uid, full_name=excluded.full_name,
    member_type=excluded.member_type, grade_level=excluded.grade_level,
    section=excluded.section, gender=excluded.gender, updated_at=now()
  returning id into mid;
  return jsonb_build_object('id',mid);
end $$;

create or replace function library_save_book(
  p_book_rfid text, p_accession_no text, p_title text, p_author text,
  p_category text, p_shelf text, p_total_copies int
) returns jsonb
language plpgsql security definer set search_path=public
as $$
declare bid uuid;
begin
  insert into library_books(book_rfid,accession_no,title,author,category,shelf,total_copies,available_copies)
  values(nullif(trim(p_book_rfid),''),nullif(trim(p_accession_no),''),trim(p_title),
         nullif(trim(p_author),''),nullif(trim(p_category),''),nullif(trim(p_shelf),''),
         greatest(p_total_copies,1),greatest(p_total_copies,1))
  on conflict (accession_no) do update set
    book_rfid=excluded.book_rfid,title=excluded.title,author=excluded.author,
    category=excluded.category,shelf=excluded.shelf,total_copies=excluded.total_copies,
    available_copies=least(library_books.available_copies + greatest(excluded.total_copies-library_books.total_copies,0),
                           excluded.total_copies),updated_at=now()
  returning id into bid;
  return jsonb_build_object('id',bid);
end $$;

create or replace function library_find_member(p_rfid text)
returns setof library_members
language sql security definer set search_path=public
as $$ select * from library_members where active=true and rfid_uid=trim(p_rfid) limit 1 $$;

create or replace function library_find_book(p_rfid text)
returns setof library_books
language sql security definer set search_path=public
as $$ select * from library_books where active=true and book_rfid=trim(p_rfid) limit 1 $$;

create or replace function library_attendance_scan(p_member_id uuid,p_action text,p_station text)
returns jsonb
language plpgsql security definer set search_path=public
as $$
declare last_action text;
begin
  select action into last_action from library_attendance
  where member_id=p_member_id and scanned_at::date=current_date
  order by scanned_at desc limit 1;

  if p_action='IN' and last_action='IN' then raise exception 'ALREADY_IN'; end if;
  if p_action='OUT' and last_action is distinct from 'IN' then raise exception 'MUST_TIME_IN_FIRST'; end if;

  insert into library_attendance(member_id,action,station_code) values(p_member_id,p_action,p_station);
  return jsonb_build_object('ok',true,'action',p_action);
end $$;

create or replace function library_borrow(
  p_member_id uuid,p_book_id uuid,p_actor text,p_due_days int default 7
) returns jsonb
language plpgsql security definer set search_path=public
as $$
declare bid uuid; mid uuid;
begin
  if exists(select 1 from library_loans where member_id=p_member_id and book_id=p_book_id and status='borrowed') then
    raise exception 'ALREADY_BORROWED';
  end if;
  update library_books set available_copies=available_copies-1,updated_at=now()
    where id=p_book_id and available_copies>0 returning id into bid;
  if bid is null then raise exception 'BOOK_UNAVAILABLE'; end if;
  insert into library_loans(member_id,book_id,due_at,borrowed_by)
    values(p_member_id,p_book_id,now()+(greatest(p_due_days,1)||' days')::interval,p_actor)
    returning id into mid;
  return jsonb_build_object('ok',true,'loan_id',mid);
end $$;

create or replace function library_return(
  p_loan_id uuid,p_actor text
) returns jsonb
language plpgsql security definer set search_path=public
as $$
declare bid uuid;
begin
  update library_loans set returned_at=now(),returned_by=p_actor,status='returned'
    where id=p_loan_id and status='borrowed' returning book_id into bid;
  if bid is null then raise exception 'LOAN_NOT_ACTIVE'; end if;
  update library_books set available_copies=least(total_copies,available_copies+1),updated_at=now()
    where id=bid;
  return jsonb_build_object('ok',true);
end $$;

create or replace function library_register_station(
  p_station_code text,p_station_name text
) returns jsonb
language plpgsql security definer set search_path=public
as $$
declare tok text;
begin
  tok=encode(gen_random_bytes(18),'hex');
  insert into library_kiosk_stations(station_code,station_name,station_token)
  values(upper(trim(p_station_code)),trim(p_station_name),tok)
  on conflict (station_code) do update set station_name=excluded.station_name,active=true
  returning station_token into tok;
  return jsonb_build_object('station_code',upper(trim(p_station_code)),'station_token',tok);
end $$;

create or replace function library_kiosk_auth(p_station_code text,p_token text)
returns jsonb
language plpgsql security definer set search_path=public
as $$
declare s library_kiosk_stations;
begin
  select * into s from library_kiosk_stations
    where station_code=upper(trim(p_station_code)) and station_token=trim(p_token) and active=true;
  if not found then raise exception 'INVALID_STATION'; end if;
  update library_kiosk_stations set last_seen_at=now() where id=s.id;
  return jsonb_build_object('station_code',s.station_code,'station_name',s.station_name);
end $$;

create or replace function library_dashboard()
returns jsonb
language sql security definer set search_path=public
as $$
select jsonb_build_object(
  'members',(select count(*) from library_members where active),
  'books',(select count(*) from library_books where active),
  'borrowed',(select count(*) from library_loans where status='borrowed'),
  'overdue',(select count(*) from library_loans where status='borrowed' and due_at<now()),
  'stations',(select count(*) from library_kiosk_stations where active)
)
$$;

grant execute on function library_setup_admin(text,text,text) to anon,authenticated;
grant execute on function library_login(text) to anon,authenticated;
grant execute on function library_save_member(text,text,text,text,text,text,text) to anon,authenticated;
grant execute on function library_save_book(text,text,text,text,text,text,int) to anon,authenticated;
grant execute on function library_find_member(text) to anon,authenticated;
grant execute on function library_find_book(text) to anon,authenticated;
grant execute on function library_attendance_scan(uuid,text,text) to anon,authenticated;
grant execute on function library_borrow(uuid,uuid,text,int) to anon,authenticated;
grant execute on function library_return(uuid,text) to anon,authenticated;
grant execute on function library_register_station(text,text) to anon,authenticated;
grant execute on function library_kiosk_auth(text,text) to anon,authenticated;
grant execute on function library_dashboard() to anon,authenticated;

-- Seed data is intentionally omitted.
