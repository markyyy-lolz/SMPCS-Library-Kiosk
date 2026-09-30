-- v1.6.0: run after 002_accounts_services.sql. Transactional and safe to rerun.
begin;
alter table library_books add column if not exists cover_data text;
alter table library_members add column if not exists school_year text;
alter table library_users drop constraint if exists library_users_role_check;
alter table library_users add constraint library_users_role_check check(role in ('admin','librarian','assistant'));
create table if not exists library_service_requests (
 id uuid primary key default gen_random_uuid(), kind text not null check(kind in ('registration','reservation','renewal','feedback','incident')),
 member_id uuid references library_members(id), book_id uuid references library_books(id), loan_id uuid references library_loans(id),
 data jsonb not null default '{}', status text not null default 'pending' check(status in ('pending','approved','rejected','resolved','cancelled')),
 created_at timestamptz not null default now(), reviewed_at timestamptz, reviewed_by uuid references library_users(id)
);
create unique index if not exists suite_reservation_unique on library_service_requests(member_id,book_id) where kind='reservation' and status='pending';
create unique index if not exists suite_renewal_unique on library_service_requests(loan_id) where kind='renewal' and status='pending';
create table if not exists library_announcements(id uuid primary key default gen_random_uuid(), title text not null, message text not null, expires_at timestamptz not null, created_at timestamptz not null default now());
create table if not exists library_retired_cards(rfid_uid text primary key, member_id uuid not null references library_members(id), retired_at timestamptz not null default now());
create table if not exists library_inventory_sessions(id uuid primary key default gen_random_uuid(), name text not null, created_at timestamptz not null default now(), completed_at timestamptz);
create table if not exists library_inventory_scans(session_id uuid references library_inventory_sessions(id),book_id uuid references library_books(id),observed_shelf text,scanned_at timestamptz not null default now(),primary key(session_id,book_id));
create table if not exists library_restore_points(id uuid primary key default gen_random_uuid(), created_at timestamptz not null default now(), snapshot jsonb not null);
do $$ declare t text; begin
 foreach t in array array['library_service_requests','library_announcements','library_retired_cards','library_inventory_sessions','library_inventory_scans','library_restore_points'] loop
 execute format('alter table %I enable row level security',t);execute format('revoke all on %I from public,anon,authenticated',t);
 end loop;
 -- Keep the original implementation internal; wrap with live role checks.
 if to_regprocedure('public.library_account_action_v2(text,text,jsonb)') is null then
 execute replace(pg_get_functiondef('public.library_account_action(text,text,jsonb)'::regprocedure),'''admin'',''librarian''','''admin'',''librarian'',''assistant''');
 alter function library_account_action(text,text,jsonb) rename to library_account_action_v2;
 end if;
end $$;
revoke all on function library_account_action_v2(text,text,jsonb) from public,anon,authenticated;

create or replace function library_suite_session(p_token text) returns library_app_sessions
language plpgsql security definer set search_path=public,extensions as $$
declare s library_app_sessions;
begin
 select * into s from library_app_sessions where token_hash=encode(digest(p_token,'sha256'),'hex') and expires_at>now();
 if not found then raise exception 'Session expired. Sign in again.'; end if;
 if s.user_id is not null and not exists(select 1 from library_users where id=s.user_id and active) then raise exception 'Account inactive'; end if;
 if s.member_id is not null and not exists(select 1 from library_members where id=s.member_id and active) then raise exception 'Account inactive'; end if;
 return s;
end $$;
revoke all on function library_suite_session(text) from public,anon,authenticated;

create or replace function library_account_action(p_token text,p_action text,p_data jsonb default '{}') returns jsonb
language plpgsql security definer set search_path=public,extensions as $$
declare s library_app_sessions; r text;
begin
 s=library_suite_session(p_token);
 select role into r from library_users where id=s.user_id;
 if r='assistant' and p_action not in ('return_list','logout') then raise exception 'Assistant access is read-only'; end if;
 return library_account_action_v2(p_token,p_action,p_data);
end $$;
revoke all on function library_account_action(text,text,jsonb) from public;
grant execute on function library_account_action(text,text,jsonb) to anon,authenticated;

-- Prevent retired cards from being reassigned by any write path.
create or replace function library_check_retired_card() returns trigger language plpgsql set search_path=public as $$
begin
 if new.rfid_uid is not null and exists(select 1 from library_retired_cards where rfid_uid=new.rfid_uid) then raise exception 'This RFID card was retired. Use a replacement card.'; end if;
 return new;
end $$;
drop trigger if exists check_retired_card on library_members;
create trigger check_retired_card before insert or update of rfid_uid on library_members for each row execute function library_check_retired_card();

create or replace function library_suite(p_token text,p_action text,p_data jsonb default '{}') returns jsonb
language plpgsql security definer set search_path=public,extensions as $$
declare s library_app_sessions; u library_users; req library_service_requests; result jsonb; rid uuid; mid uuid; bid uuid; lid uuid; oldcard text; entry jsonb; n int; v_kind text; tbl text; cols text; updates text; snap jsonb; start_at timestamptz; end_at timestamptz;
begin
 s=library_suite_session(p_token); select * into u from library_users where id=s.user_id;
 if p_action='catalog' then
 return (select coalesce(jsonb_agg(x order by x.title),'[]') from (select id,title,author,category,shelf,available_copies,total_copies,cover_data,accession_no from library_books where active and (coalesce(p_data->>'search','')='' or title ilike '%'||(p_data->>'search')||'%' or coalesce(author,'') ilike '%'||(p_data->>'search')||'%') order by title limit 200) x);
 elsif p_action='my_requests' and s.member_id is not null then
 return (select coalesce(jsonb_agg(x order by x.created_at desc),'[]') from (select r.*,b.title,(select count(*)+1 from library_service_requests q where q.kind='reservation' and q.status='pending' and q.book_id=r.book_id and (q.created_at,q.id)<(r.created_at,r.id)) as queue_position from library_service_requests r left join library_books b on b.id=r.book_id where r.member_id=s.member_id order by r.created_at desc limit 200) x);
 elsif p_action='request' and s.member_id is not null then
 v_kind=p_data->>'kind';
 if v_kind not in ('reservation','renewal','feedback') then raise exception 'Invalid request'; end if;
 if v_kind<>'feedback' and exists(select 1 from library_settings where key='maintenance' and value='true') then raise exception 'Kiosk transactions are paused for maintenance'; end if;
 if v_kind='reservation' then
 bid=(p_data->>'book_id')::uuid;
 perform 1 from library_books where id=bid and active and available_copies=0 for update;
 if not found then raise exception 'Reserve only unavailable books. Available books can be borrowed at the desk.'; end if;
 elsif v_kind='renewal' then
 lid=(p_data->>'loan_id')::uuid;
 select book_id into bid from library_loans where id=lid and member_id=s.member_id and status='borrowed' for update;
 if not found then raise exception 'Active loan not found'; end if;
 if (p_data->>'days')::int not between 1 and 30 then raise exception 'Choose 1–30 days'; end if;
 elsif length(trim(coalesce(p_data->>'message','')))<3 or length(p_data->>'message')>2000 then raise exception 'Feedback must be 3–2000 characters';
 end if;
 insert into library_service_requests(kind,member_id,book_id,loan_id,data) values(v_kind,s.member_id,bid,lid,p_data) returning id into rid;
 return jsonb_build_object('id',rid);
 elsif p_action='cancel_request' and s.member_id is not null then
 update library_service_requests set status='cancelled',reviewed_at=now() where id=(p_data->>'id')::uuid and member_id=s.member_id and status='pending' and kind in ('reservation','renewal');
 if not found then raise exception 'Request cannot be cancelled'; end if;
 return '{"ok":true}';
 elsif p_action='continue_session' and s.member_id is not null then
 update library_app_sessions set expires_at=now()+interval '5 minutes' where token_hash=s.token_hash;
 return '{"ok":true}';
 end if;
 if s.user_id is null then raise exception 'Staff access required'; end if;
 if p_action not in ('requests','notifications','reports','inventory_list','inventory_results','announcements') and u.role='assistant' then raise exception 'Assistant access is read-only'; end if;
 if p_action in ('import','promote','backup','restore','restore_points','maintenance','rfid_replace') and u.role<>'admin' then raise exception 'Administrator access required'; end if;
 if p_action='requests' then
 return (select coalesce(jsonb_agg(x order by x.created_at),'[]') from (select r.*,coalesce(m.full_name,r.data->>'full_name') as full_name,b.title from library_service_requests r left join library_members m on m.id=r.member_id left join library_books b on b.id=r.book_id where (coalesce(p_data->>'kind','All')='All' or r.kind=p_data->>'kind') and (coalesce(p_data->>'status','pending')='All' or r.status=p_data->>'status') order by r.created_at limit 1000) x);
 elsif p_action='notifications' then
 result=jsonb_build_array(jsonb_build_object('kind','overdue','count',(select count(*) from library_loans where status='borrowed' and due_at<now())),jsonb_build_object('kind','returns','count',(select count(*) from library_return_requests where status='pending')));
 result=result||(select coalesce(jsonb_agg(x),'[]') from (select kind,count(*) as count from library_service_requests where status='pending' group by kind) x);
 if to_regclass('public.library_loans') is not null then
 select count(*) into n from library_loans l where to_jsonb(l)->>'status' in ('pending','pending_verification') or to_jsonb(l)->>'verification_status'='pending' or (to_jsonb(l) ? 'verified_at' and l.status='borrowed' and to_jsonb(l)->>'verified_at' is null);
 result=result||jsonb_build_array(jsonb_build_object('kind','borrowing','count',n));
 end if;
 return result;
 elsif p_action='review' then
 select * into req from library_service_requests where id=(p_data->>'id')::uuid and status='pending' for update;
 if not found then raise exception 'Request already reviewed'; end if;
 if coalesce(p_data->>'decision','') not in ('approved','rejected','resolved') then raise exception 'Invalid decision'; end if;
 if p_data->>'decision'='approved' then
 if req.kind='registration' then
 if exists(select 1 from library_members where member_no=req.data->>'student_id' or rfid_uid=req.data->>'rfid') then raise exception 'Member number or RFID already registered'; end if;
 insert into library_members(member_no,rfid_uid,full_name,grade_level,section) values(req.data->>'student_id',req.data->>'rfid',req.data->>'full_name',req.data->>'grade_level',req.data->>'section') returning id into mid;
 update library_service_requests set member_id=mid where id=req.id;
 elsif req.kind='renewal' then
 perform 1 from library_books where id=req.book_id for update;
 if exists(select 1 from library_service_requests where book_id=req.book_id and kind='reservation' and status='pending') then raise exception 'Another member is waiting for this book'; end if;
 update library_loans set due_at=greatest(due_at,now())+make_interval(days => least(30,greatest(1,(req.data->>'days')::int))) where id=req.loan_id and status='borrowed';
 if not found then raise exception 'Loan is no longer active'; end if;
 elsif req.kind='reservation' then
 perform 1 from library_books where id=req.book_id and available_copies>0 for update;
 if not found then raise exception 'No copy is available yet'; end if;
 if exists(select 1 from library_service_requests where book_id=req.book_id and kind='reservation' and status='pending' and (created_at,id)<(req.created_at,req.id)) then raise exception 'Serve the first member in the reservation queue'; end if;
 -- Librarian confirms the physical handover, creating one loan atomically.
 insert into library_loans(member_id,book_id,borrowed_by) values(req.member_id,req.book_id,u.username) returning id into lid;
 if exists(select 1 from information_schema.columns where table_schema='public' and table_name='library_loans' and column_name='verified_at') then execute 'update library_loans set verified_at=now() where id=$1' using lid; end if;
 update library_books set available_copies=available_copies-1 where id=req.book_id;
 end if;
 end if;
 update library_service_requests set status=p_data->>'decision',reviewed_at=now(),reviewed_by=u.id,data=data||jsonb_build_object('staff_note',left(coalesce(p_data->>'note',''),2000)) where id=req.id;
 result=jsonb_build_object('ok',true);
 elsif p_action='rfid_replace' then
 mid=(p_data->>'member_id')::uuid; oldcard=null;
 if length(trim(coalesce(p_data->>'new_rfid','')))=0 then raise exception 'New RFID is required'; end if;
 select rfid_uid into oldcard from library_members where id=mid for update;
 if not found then raise exception 'Member not found'; end if;
 if oldcard=trim(p_data->>'new_rfid') then raise exception 'Choose a different card'; end if;
 update library_members set rfid_uid=trim(p_data->>'new_rfid'),updated_at=now() where id=mid;
 if oldcard is not null then insert into library_retired_cards values(oldcard,mid,now()) on conflict do nothing; end if;
 delete from library_app_sessions where member_id=mid;
 result='{"ok":true}';
 elsif p_action='promote' then
 if jsonb_array_length(p_data->'ids')<1 or length(trim(coalesce(p_data->>'school_year','')))<4 then raise exception 'Select members and enter school year'; end if;
 update library_members set grade_level=case when coalesce((p_data->>'archive')::boolean,false) then grade_level else p_data->>'grade_level' end, section=case when coalesce((p_data->>'archive')::boolean,false) then section else p_data->>'section' end,school_year=p_data->>'school_year',active=not coalesce((p_data->>'archive')::boolean,false),updated_at=now() where id in(select value::uuid from jsonb_array_elements_text(p_data->'ids'));
 get diagnostics n=row_count;
 delete from library_app_sessions where member_id in(select value::uuid from jsonb_array_elements_text(p_data->'ids'));
 result=jsonb_build_object('updated',n);
 elsif p_action='import' then
 if jsonb_typeof(p_data->'rows')<>'array' or jsonb_array_length(p_data->'rows')>1000 then raise exception 'Import up to 1000 rows per batch'; end if;
 n=0;
 for entry in select value from jsonb_array_elements(p_data->'rows') loop
 if p_data->>'kind'='members' then
 if trim(coalesce(entry->>'member_no',''))='' or trim(coalesce(entry->>'full_name',''))='' then raise exception 'Member number and name required'; end if;
 insert into library_members(member_no,rfid_uid,full_name,grade_level,section,member_type) values(trim(entry->>'member_no'),nullif(trim(entry->>'rfid_uid'),''),trim(entry->>'full_name'),entry->>'grade_level',entry->>'section',coalesce(nullif(entry->>'member_type',''),'student'));
 elsif p_data->>'kind'='books' then
 if trim(coalesce(entry->>'accession_no',''))='' or trim(coalesce(entry->>'title',''))='' or coalesce((entry->>'total_copies')::int,1)<1 then raise exception 'Accession number, title and positive copies required'; end if;
 insert into library_books(accession_no,book_rfid,title,author,category,shelf,total_copies,available_copies) values(trim(entry->>'accession_no'),nullif(trim(entry->>'book_rfid'),''),trim(entry->>'title'),entry->>'author',entry->>'category',entry->>'shelf',coalesce((entry->>'total_copies')::int,1),coalesce((entry->>'total_copies')::int,1));
 else raise exception 'Invalid import kind'; end if;
 n=n+1;
 end loop;
 result=jsonb_build_object('imported',n);
 elsif p_action='book_details' then
 if length(coalesce(p_data->>'cover_data',''))>400000 then raise exception 'Cover image too large'; end if;
 update library_books set shelf=p_data->>'shelf',cover_data=p_data->>'cover_data',updated_at=now() where id=(p_data->>'id')::uuid;
 if not found then raise exception 'Book not found'; end if;
 result='{"ok":true}';
 elsif p_action='incident' then
 if p_data->>'type' not in ('lost','damaged') or length(trim(coalesce(p_data->>'message','')))<3 then raise exception 'Choose lost/damaged and enter remarks'; end if;
 lid=(p_data->>'loan_id')::uuid;
 select member_id,book_id into mid,bid from library_loans where id=lid and status in ('borrowed','lost') for update;
 if not found then raise exception 'Active or lost loan required'; end if;
 if p_data->>'type'='lost' then update library_loans set status='lost' where id=lid; end if;
 insert into library_service_requests(kind,member_id,book_id,loan_id,data) values('incident',mid,bid,lid,p_data);
 result='{"ok":true}';
 elsif p_action='announcements' then
 return (select coalesce(jsonb_agg(a order by created_at desc),'[]') from library_announcements a);
 elsif p_action='announce' then
 if trim(coalesce(p_data->>'title',''))='' or length(coalesce(p_data->>'message','')) not between 1 and 2000 or (p_data->>'expires_at')::timestamptz<=now() then raise exception 'Enter title, message and a future expiry'; end if;
 insert into library_announcements(title,message,expires_at) values(left(p_data->>'title',120),p_data->>'message',(p_data->>'expires_at')::timestamptz);
 result='{"ok":true}';
 elsif p_action='announcement_remove' then
 delete from library_announcements where id=(p_data->>'id')::uuid;result='{"ok":true}';
 elsif p_action='maintenance' then
 insert into library_settings(key,value) values('maintenance',case when (p_data->>'enabled')::boolean then 'true' else 'false' end),('maintenance_message',left(coalesce(p_data->>'message','Please return later.'),500)) on conflict(key) do update set value=excluded.value,updated_at=now();result='{"ok":true}';
 elsif p_action='inventory_list' then
 return (select coalesce(jsonb_agg(i order by created_at desc),'[]') from library_inventory_sessions i);
 elsif p_action='inventory_start' then
 insert into library_inventory_sessions(name) values(coalesce(nullif(trim(p_data->>'name'),''),'Inventory')) returning id into rid;result=jsonb_build_object('id',rid);
 elsif p_action='inventory_scan' then
 rid=(p_data->>'session_id')::uuid;
 perform 1 from library_inventory_sessions where id=rid and completed_at is null for update;
 if not found then raise exception 'Select an open inventory session'; end if;
 select id into bid from library_books where book_rfid=p_data->>'rfid' or accession_no=p_data->>'rfid';
 if not found then raise exception 'Unknown RFID / accession number'; end if;
 insert into library_inventory_scans values(rid,bid,p_data->>'shelf',now()) on conflict(session_id,book_id) do update set observed_shelf=excluded.observed_shelf,scanned_at=excluded.scanned_at;result='{"ok":true}';
 elsif p_action='inventory_close' then
 update library_inventory_sessions set completed_at=now() where id=(p_data->>'session_id')::uuid;result='{"ok":true}';
 elsif p_action='inventory_results' then
 return (select coalesce(jsonb_agg(x order by x.title),'[]') from (select b.title,b.accession_no,b.shelf,i.observed_shelf,b.available_copies,case when i.book_id is null and b.available_copies>0 then 'Not scanned / check shelf' when i.book_id is null then 'On loan / unavailable' when coalesce(i.observed_shelf,'')<>coalesce(b.shelf,'') then 'Misplaced' else 'Found' end as status from library_books b left join library_inventory_scans i on i.book_id=b.id and i.session_id=(p_data->>'session_id')::uuid where b.active) x);
 elsif p_action='reports' then
 start_at=(p_data->>'start')::timestamptz; end_at=(p_data->>'end')::timestamptz;
 if start_at is null or end_at is null or end_at<=start_at then raise exception 'Invalid date range'; end if;
 if p_data->>'kind'='attendance' then
 return (select coalesce(jsonb_agg(x order by x.scanned_at),'[]') from (select a.id,m.full_name,m.member_no,a.action,a.scanned_at,a.station_code from library_attendance a join library_members m on m.id=a.member_id where a.scanned_at>=start_at and a.scanned_at<end_at order by a.scanned_at limit 10001) x);
 else
 return (select coalesce(jsonb_agg(x order by x.borrowed_at),'[]') from (select l.id,m.full_name,m.member_no,b.title,l.status,l.borrowed_at,l.due_at,l.returned_at from library_loans l join library_members m on m.id=l.member_id join library_books b on b.id=l.book_id where case when p_data->>'kind'='returned' then l.returned_at>=start_at and l.returned_at<end_at when p_data->>'kind'='overdue' then l.status='borrowed' and l.due_at<now() and l.due_at>=start_at and l.due_at<end_at else l.borrowed_at>=start_at and l.borrowed_at<end_at end order by l.borrowed_at limit 10001) x);
 end if;
 elsif p_action='backup' then
 snap=library_account_action_v2(p_token,'backup','{}');
 foreach tbl in array array['library_service_requests','library_announcements','library_inventory_sessions','library_inventory_scans','library_retired_cards'] loop
 execute format('select coalesce(jsonb_agg(t),''[]''::jsonb) from %I t',tbl) into result;snap=snap||jsonb_build_object(tbl,result);
 end loop;
 return snap||jsonb_build_object('format','SMPCS operational backup v2');
 elsif p_action='restore_points' then
 return (select coalesce(jsonb_agg(jsonb_build_object('id',id,'created_at',created_at) order by created_at desc),'[]') from library_restore_points);
 elsif p_action='restore' then
 if p_data->>'confirmation'<>'RESTORE' then raise exception 'Type RESTORE to confirm'; end if;
 snap=p_data->'snapshot';
 if p_data ? 'restore_id' then select snapshot into snap from library_restore_points where id=(p_data->>'restore_id')::uuid; end if;
 if coalesce(snap->>'format','') not in ('SMPCS operational backup v1','SMPCS operational backup v2') then raise exception 'Unsupported backup format'; end if;
 lock table library_members,library_books,library_loans,library_attendance,library_return_requests,library_service_requests,library_inventory_sessions,library_inventory_scans in share row exclusive mode;
 insert into library_restore_points(snapshot) values(library_suite(p_token,'backup','{}'));
 foreach tbl in array array['library_members','library_books','library_loans','library_attendance','library_return_requests','library_service_requests','library_announcements','library_inventory_sessions','library_inventory_scans','library_retired_cards'] loop
 v_kind=case tbl when 'library_members' then 'members' when 'library_books' then 'books' when 'library_loans' then 'loans' when 'library_attendance' then 'attendance' when 'library_return_requests' then 'return_requests' else tbl end;
 if snap ? v_kind then
 if jsonb_typeof(snap->v_kind)<>'array' then raise exception 'Invalid backup rows: %',v_kind; end if;
 select string_agg(quote_ident(column_name),','),string_agg(format('%I=excluded.%I',column_name,column_name),',') into cols,updates from information_schema.columns where table_schema='public' and table_name=tbl and is_generated='NEVER' and is_identity='NO';
 -- Inventory scans and retired cards have compound / natural keys.
 oldcard=case tbl when 'library_inventory_scans' then 'session_id,book_id' when 'library_retired_cards' then 'rfid_uid' else 'id' end;
 execute format('insert into %I (%s) select %s from jsonb_populate_recordset(null::%I,$1) on conflict (%s) do update set %s',tbl,cols,cols,tbl,oldcard,updates) using snap->v_kind;
 end if;
 end loop;
 -- Reconcile current stock, including records created after the snapshot.
 update library_books b set available_copies=greatest(0,total_copies-(select count(*) from library_loans l where l.book_id=b.id and l.status in ('borrowed','lost','pending','pending_verification')));
 delete from library_app_sessions where member_id is not null;
 delete from library_restore_points where id in(select id from library_restore_points order by created_at desc offset 7);
 result='{"ok":true}';
 else raise exception 'Unknown suite action';
 end if;
 insert into library_audit_log(actor_username,action,entity_type,entity_id) values(u.username,p_action,'library suite',coalesce(rid,mid,bid,req.id)::text);
 return result;
end $$;
revoke all on function library_suite(text,text,jsonb) from public;
grant execute on function library_suite(text,text,jsonb) to anon,authenticated;

create or replace function library_suite_station(p_station text,p_token text,p_action text,p_data jsonb default '{}') returns jsonb
language plpgsql security definer set search_path=public,extensions as $$
declare rid uuid;
begin
 perform library_kiosk_auth(p_station,p_token);
 if p_action='status' then
 return jsonb_build_object('maintenance',coalesce((select value='true' from library_settings where key='maintenance'),false),'message',(select value from library_settings where key='maintenance_message'),'announcements',(select coalesce(jsonb_agg(a order by created_at desc),'[]') from library_announcements a where expires_at>now()));
 elsif p_action='register' then
 if exists(select 1 from library_settings where key='maintenance' and value='true') then raise exception 'Registration paused for maintenance'; end if;
 if length(trim(coalesce(p_data->>'full_name','')))<2 or trim(coalesce(p_data->>'student_id',''))='' or trim(coalesce(p_data->>'rfid',''))='' then raise exception 'Complete name, member number and RFID'; end if;
 if exists(select 1 from library_members where member_no=p_data->>'student_id' or rfid_uid=p_data->>'rfid') then raise exception 'Already registered. Ask the librarian.'; end if;
 perform pg_advisory_xact_lock(hashtextextended(p_data->>'rfid',0));
 if exists(select 1 from library_service_requests where kind='registration' and status='pending' and (data->>'rfid'=p_data->>'rfid' or data->>'student_id'=p_data->>'student_id')) then raise exception 'Registration is already pending'; end if;
 insert into library_service_requests(kind,data) values('registration',p_data||jsonb_build_object('station',p_station)) returning id into rid;return jsonb_build_object('id',rid);
 else raise exception 'Unknown station service'; end if;
end $$;
revoke all on function library_suite_station(text,text,text,jsonb) from public;
grant execute on function library_suite_station(text,text,text,jsonb) to anon,authenticated;
-- Guard existing staff write RPCs, including installations with extra overloads.
create or replace function library_staff_rpc(p_token text,p_name text,p_args jsonb) returns jsonb
language plpgsql security definer set search_path=public,extensions as $$
declare s library_app_sessions; role_name text; f record; args text; result jsonb;
begin
 s=library_suite_session(p_token);select role into role_name from library_users where id=s.user_id;
 if role_name is null or role_name='assistant' then raise exception 'Librarian access required'; end if;
 if p_name not in ('library_save_book','library_verify_loan','library_reject_loan','library_register_station') then raise exception 'Unsupported staff action'; end if;
 if p_name='library_register_station' and role_name<>'admin' then raise exception 'Administrator access required'; end if;
 if p_args ? 'p_actor' then p_args=jsonb_set(p_args,'{p_actor}',to_jsonb((select username from library_users where id=s.user_id))); end if;
 for f in select p.* from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname='public' and p.proname=p_name loop
 if (select count(*) from jsonb_object_keys(p_args))=f.pronargs and not exists(select 1 from jsonb_object_keys(p_args) k where not k=any(f.proargnames)) then
 select string_agg(format('%I => ($1->>%L)::%s',f.proargnames[i],f.proargnames[i],format_type(f.proargtypes[i-1],null)),',') into args from generate_series(1,f.pronargs) i;
 execute format('select to_jsonb(public.%I(%s))',p_name,args) into result using p_args;
 insert into library_audit_log(actor_username,action,entity_type) values((select username from library_users where id=s.user_id),p_name,'staff action');
 return result;
 end if;
 end loop;
 raise exception 'Staff routine signature not found; apply your circulation schema first';
end $$;
revoke all on function library_staff_rpc(text,text,jsonb) from public;
grant execute on function library_staff_rpc(text,text,jsonb) to anon,authenticated;
do $$ declare f record; begin
 for f in select p.oid::regprocedure as signature from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname='public' and p.proname in ('library_save_book','library_verify_loan','library_reject_loan','library_register_station') loop
 execute format('revoke all on function %s from public,anon,authenticated',f.signature);
 end loop;
end $$;
create or replace function library_maintenance_guard() returns trigger language plpgsql security definer set search_path=public as $$
begin
 if exists(select 1 from library_settings where key='maintenance' and value='true') then raise exception 'Library borrowing is paused for maintenance'; end if;
 return new;
end $$;
drop trigger if exists maintenance_guard on library_loans;
create trigger maintenance_guard before insert on library_loans for each row execute function library_maintenance_guard();

commit;
