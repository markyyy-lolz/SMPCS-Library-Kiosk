-- Apply once in Supabase SQL Editor before using v1.5.0. Existing data is retained.
begin;
create extension if not exists pgcrypto;
create table if not exists public.library_app_sessions (
 token_hash text primary key, user_id uuid references public.library_users(id), member_id uuid references public.library_members(id),
 expires_at timestamptz not null, check ((user_id is null) <> (member_id is null))
);
create table if not exists public.library_member_pins (member_id uuid primary key references public.library_members(id), pin_hash text not null);
create table if not exists public.library_login_limits (identity text primary key, failures int not null default 0, blocked_until timestamptz);
create table if not exists public.library_return_requests (
 id uuid primary key default gen_random_uuid(), loan_id uuid not null references public.library_loans(id),
 station_code text not null, created_at timestamptz not null default now(), status text not null default 'pending' check(status in ('pending','approved','rejected')),
 reviewed_by uuid references public.library_users(id), reviewed_at timestamptz
);
create unique index if not exists one_pending_return on public.library_return_requests(loan_id) where status='pending';
create table if not exists public.library_offline_events (id uuid primary key, station_code text not null, result jsonb not null);
do $$ declare t text; begin
 foreach t in array array['library_app_sessions','library_member_pins','library_login_limits','library_return_requests','library_offline_events'] loop
 execute format('alter table public.%I enable row level security',t);
 execute format('revoke all on public.%I from anon, authenticated',t);
 end loop;
end $$;

create or replace function public.library_account_login(p_kind text,p_identity text,p_secret text) returns jsonb
language plpgsql security definer set search_path=public,extensions as $$
declare uid uuid; mid uuid; ph text; tok text; ident text; lim library_login_limits; u library_users;
begin
 if p_kind not in ('staff','member') then return jsonb_build_object('error','Invalid sign-in.'); end if;
 ident=p_kind||':'||lower(trim(p_identity));
 insert into library_login_limits(identity) values(ident) on conflict do nothing;
 select * into lim from library_login_limits where identity=ident for update;
 if lim.blocked_until>now() then return jsonb_build_object('error','Too many attempts. Try again in 15 minutes.'); end if;
 if lim.blocked_until is not null then update library_login_limits set failures=0,blocked_until=null where identity=ident; end if;
 if p_kind='staff' then
 select * into u from library_users where username=lower(trim(p_identity)) and active;
 uid=u.id; ph=u.password_hash;
 else
 select m.id,p.pin_hash into mid,ph from library_members m join library_member_pins p on p.member_id=m.id where m.rfid_uid=trim(p_identity) and m.active;
 end if;
 if ph is null or p_secret is null or octet_length(p_secret)>72 or crypt(p_secret,ph)<>ph then
 update library_login_limits set failures=failures+1,blocked_until=case when failures+1>=5 then now()+interval '15 minutes' else null end where identity=ident;
 return jsonb_build_object('error','Invalid credentials, inactive account, or PIN not yet assigned. Ask the librarian.');
 end if;
 delete from library_login_limits where identity=ident;
 delete from library_app_sessions where expires_at<now();
 tok=encode(gen_random_bytes(32),'hex');
 insert into library_app_sessions values(encode(digest(tok,'sha256'),'hex'),uid,mid,now()+case when uid is null then interval '5 minutes' else interval '8 hours' end);
 return jsonb_build_object('token',tok,'id',coalesce(uid,mid),'username',u.username,'full_name',u.full_name,'role',u.role);
end $$;

create or replace function public.library_account_action(p_token text,p_action text,p_data jsonb default '{}'::jsonb) returns jsonb
language plpgsql security definer set search_path=public,extensions as $$
declare s library_app_sessions; u library_users; mid uuid; target library_users; rid uuid; req library_return_requests; result jsonb; nm text; pw text; b uuid;
begin
 select * into s from library_app_sessions where token_hash=encode(digest(p_token,'sha256'),'hex') and expires_at>now();
 if not found then raise exception 'Session expired. Sign in again.'; end if;
 if p_action='logout' then delete from library_app_sessions where token_hash=s.token_hash; return '{}'::jsonb; end if;
 if s.member_id is not null then
 if not exists(select 1 from library_members where id=s.member_id and active) then raise exception 'Account inactive'; end if;
 if p_action='profile' then
 return jsonb_build_object('member',(select to_jsonb(m) from library_members m where id=s.member_id),
 'loans',(select coalesce(jsonb_agg(x order by x.borrowed_at desc),'[]'::jsonb) from (select l.id,l.borrowed_at,l.due_at,l.returned_at,l.status,b.title,(l.status='borrowed' and l.due_at<now()) as overdue from library_loans l join library_books b on b.id=l.book_id where l.member_id=s.member_id order by l.borrowed_at desc limit 200) x));
 elsif p_action='change_pin' then
 select pin_hash into pw from library_member_pins where member_id=s.member_id for update;
 if crypt(coalesce(p_data->>'current_pin',''),pw)<>pw then raise exception 'Current PIN is incorrect'; end if;
 pw=p_data->>'pin'; if pw is null or pw !~ '^[0-9]{6,12}$' then raise exception 'PIN must contain 6 to 12 digits'; end if;
 update library_member_pins set pin_hash=crypt(pw,gen_salt('bf',10)) where member_id=s.member_id;
 delete from library_app_sessions where member_id=s.member_id and token_hash<>s.token_hash;
 return jsonb_build_object('ok',true);
 else raise exception 'Permission denied'; end if;
 end if;
 select * into u from library_users where id=s.user_id and active;
 if not found then raise exception 'Account inactive'; end if;
 if p_action='staff_list' then
 if u.role<>'admin' then raise exception 'Administrator access required'; end if;
 return (select coalesce(jsonb_agg(jsonb_build_object('id',id,'username',username,'full_name',full_name,'role',role,'active',active) order by username),'[]'::jsonb) from library_users);
 elsif p_action='staff_save' then
 if u.role<>'admin' then raise exception 'Administrator access required'; end if;
 perform pg_advisory_xact_lock(15001);
 rid=nullif(p_data->>'id','')::uuid;
 if rid is not null then
 select * into target from library_users where id=rid for update;
 if not found then raise exception 'Staff account not found'; end if;
 if rid=u.id and (p_data->>'role'<>'admin' or not (p_data->>'active')::boolean) then raise exception 'You cannot disable or demote your own account'; end if;
 if target.active and target.role='admin' and (p_data->>'role'<>'admin' or not (p_data->>'active')::boolean) and (select count(*) from library_users where active and role='admin')<=1 then raise exception 'Keep at least one active administrator'; end if;
 end if;
 nm=lower(trim(p_data->>'username')); pw=p_data->>'password';
 if nm is null or length(nm)<3 or length(trim(coalesce(p_data->>'full_name','')))=0 or coalesce(p_data->>'role','') not in ('admin','librarian') or p_data->>'active' is null then raise exception 'Complete username, name, role and status'; end if;
 if coalesce(pw,'')<>'' and (length(pw)<10 or octet_length(pw)>72) then raise exception 'Password must be at least 10 characters and at most 72 UTF-8 bytes'; end if;
 if rid is null then
 if coalesce(pw,'')='' then raise exception 'Password is required'; end if;
 insert into library_users(username,full_name,password_hash,role,active) values(nm,trim(p_data->>'full_name'),crypt(pw,gen_salt('bf',10)),p_data->>'role',(p_data->>'active')::boolean) returning id into rid;
 else
 update library_users set username=nm,full_name=trim(p_data->>'full_name'),role=p_data->>'role',active=(p_data->>'active')::boolean,password_hash=case when coalesce(pw,'')='' then password_hash else crypt(pw,gen_salt('bf',10)) end where id=rid;
 delete from library_app_sessions where user_id=rid and (rid<>u.id or coalesce(pw,'')<>'');
 end if;
 result=jsonb_build_object('id',rid);
 elsif p_action='member_save' then
 -- Use the existing member routine to retain compatibility with installed schemas.
 result=library_save_member(p_data->>'member_no',p_data->>'rfid_uid',p_data->>'full_name',p_data->>'member_type',p_data->>'grade_level',p_data->>'section',p_data->>'gender');
 elsif p_action='member_access' then
 mid=(p_data->>'id')::uuid;
 perform 1 from library_members where id=mid for update;
 if not found then raise exception 'Member not found'; end if;
 if p_data ? 'active' then update library_members set active=(p_data->>'active')::boolean,updated_at=now() where id=mid; end if;
 pw=p_data->>'pin';
 if coalesce(pw,'')<>'' then
 if pw !~ '^[0-9]{6,12}$' then raise exception 'PIN must contain 6 to 12 digits'; end if;
 insert into library_member_pins values(mid,crypt(pw,gen_salt('bf',10))) on conflict(member_id) do update set pin_hash=excluded.pin_hash;
 delete from library_login_limits where identity='member:'||lower((select rfid_uid from library_members where id=mid));
 end if;
 delete from library_app_sessions where member_id=mid;
 result=jsonb_build_object('ok',true);
 elsif p_action='return_list' then
 return (select coalesce(jsonb_agg(x order by x.created_at),'[]'::jsonb) from (select r.id,r.created_at,r.station_code,b.title,m.full_name,m.member_no,l.due_at from library_return_requests r join library_loans l on l.id=r.loan_id join library_books b on b.id=l.book_id join library_members m on m.id=l.member_id where r.status='pending') x);
 elsif p_action='return_review' then
 select * into req from library_return_requests where id=(p_data->>'id')::uuid and status='pending' for update;
 if not found then raise exception 'Return request already reviewed'; end if;
 if (p_data->>'approve')::boolean then
 update library_loans set status='returned',returned_at=now(),returned_by=u.username where id=req.loan_id and status='borrowed' returning book_id into b;
 if b is null then raise exception 'Loan is no longer active'; end if;
 update library_books set available_copies=least(total_copies,available_copies+1),updated_at=now() where id=b;
 end if;
 update library_return_requests set status=case when (p_data->>'approve')::boolean then 'approved' else 'rejected' end,reviewed_by=u.id,reviewed_at=now() where id=req.id;
 result=jsonb_build_object('ok',true);
 elsif p_action='backup' then
 if u.role<>'admin' then raise exception 'Administrator access required'; end if;
 return jsonb_build_object('format','SMPCS operational backup v1','created_at',now(),'members',(select coalesce(jsonb_agg(m),'[]') from library_members m),'books',(select coalesce(jsonb_agg(b),'[]') from library_books b),'loans',(select coalesce(jsonb_agg(l),'[]') from library_loans l),'attendance',(select coalesce(jsonb_agg(a),'[]') from library_attendance a),'return_requests',(select coalesce(jsonb_agg(r),'[]') from library_return_requests r));
 else raise exception 'Unknown action'; end if;
 insert into library_audit_log(actor_username,action,entity_type,entity_id) values(u.username,p_action,'account/service',coalesce(rid,mid,req.id)::text);
 return result;
end $$;

create or replace function public.library_station_service(p_station text,p_token text,p_action text,p_data jsonb) returns jsonb
language plpgsql security definer set search_path=public,extensions as $$
declare mid uuid; eid uuid; ts timestamptz; act text; last_ts timestamptz; result jsonb; lid uuid;
begin
 perform library_kiosk_auth(p_station,p_token);
 if p_action='return_request' then
 select l.id into lid from library_loans l join library_members m on m.id=l.member_id where l.id=(p_data->>'loan_id')::uuid and m.rfid_uid=p_data->>'rfid' and m.active and l.status='borrowed';
 if lid is null then raise exception 'Active loan not found for this card'; end if;
 insert into library_return_requests(loan_id,station_code) values(lid,upper(trim(p_station))) on conflict(loan_id) where status='pending' do nothing;
 return jsonb_build_object('ok',true);
 elsif p_action='attendance_event' then
 eid=(p_data->>'id')::uuid; ts=(p_data->>'scanned_at')::timestamptz;
 perform pg_advisory_xact_lock(hashtextextended(eid::text,0));
 select e.result into result from library_offline_events e where id=eid;
 if found then return result; end if;
 if ts is null or ts>now()+interval '2 minutes' or ts<now()-interval '30 days' then raise exception 'Scan timestamp outside 30-day sync window; ask librarian to review'; end if;
 select id into mid from library_members where rfid_uid=p_data->>'rfid' and active;
 if mid is null then raise exception 'Card unknown or inactive; ask librarian to review'; end if;
 perform pg_advisory_xact_lock(hashtextextended(mid::text,0));
 if exists(select 1 from library_attendance where member_id=mid and scanned_at>ts) then raise exception 'Newer attendance exists; ask librarian to review this offline scan'; end if;
 select action,scanned_at into act,last_ts from library_attendance where member_id=mid and (scanned_at at time zone 'Asia/Manila')::date=(ts at time zone 'Asia/Manila')::date order by scanned_at desc limit 1;
 if last_ts is not null and ts-last_ts<interval '10 seconds' then
 result=jsonb_build_object('action',act,'duplicate',true);
 else
 act=case when act='IN' then 'OUT' else 'IN' end;
 insert into library_attendance(member_id,action,scanned_at,station_code) values(mid,act,ts,upper(trim(p_station)));
 result=jsonb_build_object('action',act,'duplicate',false);
 end if;
 insert into library_offline_events values(eid,upper(trim(p_station)),result);
 return result;
 else raise exception 'Unknown service'; end if;
end $$;
-- Account writes must be authorized on the server, not by client-supplied role names.
revoke execute on function public.library_return(uuid,text) from public,anon,authenticated;
revoke execute on function public.library_login(text) from public,anon,authenticated;
revoke execute on function public.library_save_member(text,text,text,text,text,text,text) from public,anon,authenticated;
revoke execute on function public.library_account_login(text,text,text) from public;
revoke execute on function public.library_account_action(text,text,jsonb) from public;
revoke execute on function public.library_station_service(text,text,text,jsonb) from public;
grant execute on function public.library_account_login(text,text,text),public.library_account_action(text,text,jsonb),public.library_station_service(text,text,text,jsonb) to anon,authenticated;
commit;
