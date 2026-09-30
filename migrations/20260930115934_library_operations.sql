-- Apply AFTER 003_library_suite.sql. Existing loans remain intact.
begin;
create schema if not exists library_private;
revoke all on schema library_private from public,anon,authenticated;
alter table library_members add column if not exists merged_into uuid references library_members(id);
alter table library_books add column if not exists merged_into uuid references library_books(id);
alter table library_loans add column if not exists verified_at timestamptz;
create table if not exists library_copies(
 id uuid primary key default gen_random_uuid(),book_id uuid not null references library_books(id),accession text not null unique,
 rfid text unique,shelf text,condition text not null default 'good' check(condition in ('good','quarantine','lost','retired')),
 notes text not null default '',needs_verification boolean not null default false,created_at timestamptz not null default now()
);
alter table library_loans add column if not exists copy_id uuid references library_copies(id);
create table if not exists library_borrow_rules(member_type text primary key,max_books int not null check(max_books between 1 and 50),loan_days int not null check(loan_days between 1 and 180),block_overdue boolean not null default true);
insert into library_borrow_rules values('student',3,7,true),('employee',5,14,true),('teacher',5,14,true),('guest',1,3,true),('staff',5,14,true),('other',2,7,true) on conflict do nothing;
create table if not exists library_closed_dates(day date primary key,reason text not null);
create table if not exists library_open_days(day int primary key check(day between 0 and 6));
insert into library_open_days select generate_series(1,5) where not exists(select 1 from library_open_days);
create table if not exists library_pickups(request_id uuid primary key references library_service_requests(id),copy_id uuid not null references library_copies(id),deadline timestamptz not null,state text not null default 'ready' check(state in ('ready','collected','expired','cancelled')));
create unique index if not exists one_copy_hold on library_pickups(copy_id) where state='ready';
create table if not exists library_ops_requests(id uuid primary key default gen_random_uuid(),kind text not null check(kind in ('acquisition','profile','attendance')),member_id uuid references library_members(id),created_by uuid references library_users(id),data jsonb not null,status text not null default 'pending' check(status in ('pending','approved','rejected','under_review','ordered','added')),note text not null default '',created_at timestamptz not null default now(),reviewed_at timestamptz,reviewed_by uuid references library_users(id));
create table if not exists library_reading_lists(id uuid primary key default gen_random_uuid(),name text not null,subject text not null,grade text not null,created_by uuid references library_users(id));
create table if not exists library_reading_items(list_id uuid references library_reading_lists(id),book_id uuid references library_books(id),primary key(list_id,book_id));
create table if not exists library_class_visits(id uuid primary key default gen_random_uuid(),section text not null,teacher text not null,starts_at timestamptz not null,ends_at timestamptz not null,seats int not null check(seats>0),status text not null default 'booked' check(status in ('booked','cancelled')),created_by uuid references library_users(id),check(ends_at>starts_at));
create table if not exists library_handover(id uuid primary key default gen_random_uuid(),message text not null,created_by uuid references library_users(id),created_at timestamptz not null default now(),resolved_at timestamptz,resolved_by uuid references library_users(id));
create table if not exists library_saved_filters(id uuid primary key default gen_random_uuid(),user_id uuid not null references library_users(id),name text not null,data jsonb not null,unique(user_id,name));
create table if not exists library_closing_reports(id uuid primary key default gen_random_uuid(),day date not null,created_at timestamptz not null default now(),created_by uuid references library_users(id),summary jsonb not null);
create table if not exists library_copy_scans(session_id uuid references library_inventory_sessions(id),copy_id uuid references library_copies(id),shelf text,scanned_at timestamptz not null default now(),primary key(session_id,copy_id));
do $$ declare t text; begin
 foreach t in array array['library_copies','library_borrow_rules','library_closed_dates','library_open_days','library_pickups','library_ops_requests','library_reading_lists','library_reading_items','library_class_visits','library_handover','library_saved_filters','library_closing_reports','library_copy_scans'] loop
 execute format('alter table %I enable row level security',t);execute format('revoke all on %I from public,anon,authenticated',t);
 end loop;
end $$;
create index if not exists copy_book on library_copies(book_id);
create index if not exists ops_request_member on library_ops_requests(member_id,created_at desc);
create index if not exists attendance_latest on library_attendance(member_id,scanned_at desc,id desc);
-- Seed only catalog records with no copy records. Never invent extra stock on rerun.
do $$ declare b record; l record; cid uuid; i int; total int; used int; begin
 for b in select * from library_books where not exists(select 1 from library_copies c where c.book_id=library_books.id) loop
 select count(*) into used from library_loans where book_id=b.id and status in ('borrowed','lost');total=greatest(b.total_copies,used);i=0;
 for l in select id from library_loans where book_id=b.id and status in ('borrowed','lost') order by borrowed_at,id loop
 i=i+1;
 insert into library_copies(book_id,accession,rfid,shelf,needs_verification,notes) values(b.id,'COPY-'||b.id||'-'||i,case when i=1 then b.book_rfid end,b.shelf,true,'Migrated active loan; verify physical copy assignment.') returning id into cid;
 update library_loans set copy_id=cid where id=l.id;
 end loop;
 while i<total loop
 i=i+1;insert into library_copies(book_id,accession,rfid,shelf,condition,needs_verification,notes) values(b.id,'COPY-'||b.id||'-'||i,case when i=1 then b.book_rfid end,b.shelf,case when i-used<=b.available_copies then 'good' else 'quarantine' end,true,'Generated from legacy copy count; verify accession/RFID.');
 end loop;
 end loop;
end $$;
create unique index if not exists one_active_loan_per_copy on library_loans(copy_id) where status in ('borrowed','lost') and copy_id is not null;

create or replace function library_private.open_date(d date) returns date language plpgsql set search_path=public,pg_temp as $$
declare x date=d; i int;begin
 for i in 0..366 loop
 if exists(select 1 from library_open_days where day=extract(dow from x)::int) and not exists(select 1 from library_closed_dates where day=x) then return x; end if;
 x=x+1;
 end loop;raise exception 'No open library date within one year. Review the calendar.';
end $$;
create or replace function library_private.stock(bid uuid) returns void language sql set search_path=public,pg_temp as $$
 update library_books b set total_copies=(select count(*) from library_copies c where c.book_id=bid and condition<>'retired'),available_copies=(select count(*) from library_copies c where c.book_id=bid and condition='good' and not needs_verification and not exists(select 1 from library_loans l where l.copy_id=c.id and l.status in ('borrowed','lost')) and not exists(select 1 from library_pickups h where h.copy_id=c.id and h.state='ready' and h.deadline>now())) where b.id=bid;
$$;
create or replace function library_private.expire_pickups() returns void language plpgsql set search_path=public,pg_temp as $$
declare r record;begin
 perform pg_advisory_xact_lock(17000);
 for r in update library_pickups set state='expired' where state='ready' and deadline<=now() returning request_id,copy_id loop
 update library_service_requests set status='cancelled',reviewed_at=now(),data=data||'{"staff_note":"Pickup deadline expired; please reserve again."}'::jsonb where id=r.request_id;
 perform library_private.stock((select book_id from library_copies where id=r.copy_id));
 end loop;
end $$;
create or replace function library_private.loan_guard() returns trigger language plpgsql security definer set search_path=public,pg_temp as $$
declare m library_members; rule library_borrow_rules; c library_copies; cap date;begin
 perform pg_advisory_xact_lock(17000);
 if new.status='borrowed' and (tg_op='INSERT' or new.copy_id is distinct from old.copy_id or new.status is distinct from old.status or new.due_at is distinct from old.due_at) then
 select * into m from library_members where id=new.member_id and active and merged_into is null;
 if not found then raise exception 'Member is inactive'; end if;
 select * into rule from library_borrow_rules where member_type=m.member_type;
 if not found then select * into rule from library_borrow_rules where member_type='student';end if;
 if (select count(*) from library_loans where member_id=m.id and status in ('borrowed','lost') and id<>new.id)>=rule.max_books then raise exception 'Borrowing limit reached';end if;
 if rule.block_overdue and exists(select 1 from library_loans where member_id=m.id and status='borrowed' and due_at<now() and id<>new.id) then raise exception 'Return overdue books before borrowing';end if;
 perform library_private.expire_pickups();
 if new.copy_id is null then
 select * into c from library_copies cc where cc.book_id=new.book_id and condition='good' and not needs_verification and not exists(select 1 from library_loans l where l.copy_id=cc.id and l.status in ('borrowed','lost') and l.id<>new.id) and not exists(select 1 from library_pickups h where h.copy_id=cc.id and h.state='ready') order by accession limit 1;
 new.copy_id=c.id;
 else select * into c from library_copies where id=new.copy_id;end if;
 if c.id is null or c.book_id<>new.book_id or c.condition<>'good' or c.needs_verification then raise exception 'Copy is unavailable or needs librarian verification';end if;
 if exists(select 1 from library_loans where copy_id=c.id and status in ('borrowed','lost') and id<>new.id) then raise exception 'This copy is already on loan';end if;
 if exists(select 1 from library_pickups h join library_service_requests r on r.id=h.request_id where h.copy_id=c.id and h.state='ready' and r.member_id<>new.member_id) then raise exception 'Copy reserved for another member';end if;
 if new.due_at is null then raise exception 'Return date required';end if;
 cap=library_private.open_date((now() at time zone 'Asia/Manila')::date+rule.loan_days);
 if (new.due_at at time zone 'Asia/Manila')::date>cap then raise exception 'Due date exceeds this member type borrowing rule';end if;
 if (new.due_at at time zone 'Asia/Manila')::date<=(now() at time zone 'Asia/Manila')::date then raise exception 'Choose a future return date';end if;
 if library_private.open_date((new.due_at at time zone 'Asia/Manila')::date)<>(new.due_at at time zone 'Asia/Manila')::date then raise exception 'Library closed on selected return date';end if;
 end if;return new;
end $$;
create or replace function library_private.loan_stock() returns trigger language plpgsql security definer set search_path=public,pg_temp as $$
begin perform library_private.stock(coalesce(new.book_id,old.book_id));if tg_op='UPDATE' and old.book_id<>new.book_id then perform library_private.stock(old.book_id);end if;return null;end $$;
drop trigger if exists ops_loan_guard on library_loans;
create trigger ops_loan_guard before insert or update of status,due_at,copy_id on library_loans for each row execute function library_private.loan_guard();
drop trigger if exists ops_loan_stock on library_loans;
create trigger ops_loan_stock after insert or update or delete on library_loans for each row execute function library_private.loan_stock();
-- Give new catalog additions separate copy records too.
create or replace function library_private.seed_book() returns trigger language plpgsql security definer set search_path=public,pg_temp as $$
declare i int;begin
 for i in 1..new.total_copies loop insert into library_copies(book_id,accession,rfid,shelf,needs_verification) values(new.id,'COPY-'||new.id||'-'||i,case when i=1 then new.book_rfid end,new.shelf,true);end loop;
 perform library_private.stock(new.id);return null;
end $$;
drop trigger if exists ops_seed_book on library_books;
create trigger ops_seed_book after insert on library_books for each row execute function library_private.seed_book();
-- Preserve original APIs behind wrappers; only wrappers remain callable.
do $$ begin
 if to_regprocedure('library_suite_v3(text,text,jsonb)') is null then alter function library_suite(text,text,jsonb) rename to library_suite_v3;end if;
 if to_regprocedure('library_account_action_v3(text,text,jsonb)') is null then alter function library_account_action(text,text,jsonb) rename to library_account_action_v3;end if;
end $$;
revoke all on function library_suite_v3(text,text,jsonb),library_account_action_v3(text,text,jsonb) from public,anon,authenticated;

-- Ready reservations advance automatically when a copy becomes available. Staff still
-- verifies the handover; the queue never creates a loan without that confirmation.
create or replace function library_private.queue() returns void language plpgsql set search_path=public,pg_temp as $$
declare r record;c uuid;begin
 perform library_private.expire_pickups();
 for r in select q.* from library_service_requests q join library_members m on m.id=q.member_id where q.kind='reservation' and q.status='pending' and m.active and not exists(select 1 from library_pickups p where p.request_id=q.id) order by q.created_at,q.id loop
 select cc.id into c from library_copies cc where book_id=r.book_id and condition='good' and not needs_verification and not exists(select 1 from library_loans l where l.copy_id=cc.id and l.status in ('borrowed','lost')) and not exists(select 1 from library_pickups p where p.copy_id=cc.id and p.state='ready') order by accession limit 1;
 if c is not null then
 insert into library_pickups(request_id,copy_id,deadline) values(r.id,c,(library_private.open_date((now() at time zone 'Asia/Manila')::date+2)+time '17:00') at time zone 'Asia/Manila');
 update library_service_requests set data=data||jsonb_build_object('pickup_deadline',(select deadline from library_pickups where request_id=r.id),'staff_note','Ready for pickup. Bring your library card to the librarian.') where id=r.id;
 perform library_private.stock(r.book_id);
 end if;
 end loop;
end $$;
create or replace function library_operations(p_token text,p_action text,p_data jsonb default '{}') returns jsonb language plpgsql security definer set search_path=public,extensions,pg_temp as $$
#variable_conflict use_column
declare s library_app_sessions;u library_users;r library_ops_requests;c library_copies;b uuid;mid uuid;rid uuid;res jsonb;v text;q text;src uuid;dst uuid;preview jsonb;n int;cap int;old jsonb;day date;rr library_borrow_rules;req library_service_requests;pk library_pickups;cols text;ups text;tbl text;key text;snap jsonb;
begin
 s=library_suite_session(p_token);select * into u from library_users where id=s.user_id;
 if p_action='reading' then
 return (select coalesce(jsonb_agg(x),'[]') from (select l.*,(select coalesce(jsonb_agg(jsonb_build_object('id',b.id,'title',b.title,'author',b.author,'shelf',b.shelf,'available',b.available_copies) order by b.title),'[]') from library_reading_items i join library_books b on b.id=i.book_id where i.list_id=l.id) books from library_reading_lists l order by subject,grade,name) x);
 elsif p_action='my_operations' and s.member_id is not null then
 return (select coalesce(jsonb_agg(x order by x.created_at desc),'[]') from (select * from library_ops_requests where member_id=s.member_id order by created_at desc limit 500) x);
 elsif p_action='submit' and s.member_id is not null then
 v=p_data->>'kind';
 if v is null or v not in ('acquisition','profile','attendance') then raise exception 'Invalid request kind';end if;
 if length(trim(coalesce(p_data->>'reason','')))<3 or length(p_data::text)>5000 then raise exception 'Provide a reason (3 characters minimum; request maximum 5000 characters)';end if;
 if v='acquisition' and length(trim(coalesce(p_data->>'title','')))<2 then raise exception 'Enter a book title';end if;
 if v='profile' and length(trim(coalesce(p_data->>'full_name','')))<2 then raise exception 'Enter the corrected full name';end if;
 if v='attendance' then
 perform 1 from library_attendance where id=(p_data->>'attendance_id')::uuid and member_id=s.member_id;
 if not found then raise exception 'Select your attendance entry';end if;
 if coalesce(p_data->>'action','') not in ('IN','OUT') or (p_data->>'scanned_at')::timestamptz>now() then raise exception 'Invalid attendance correction';end if;
 end if;
 insert into library_ops_requests(kind,member_id,data) values(v,s.member_id,p_data) returning id into rid;
 return jsonb_build_object('id',rid);
 elsif p_action='my_attendance' and s.member_id is not null then
 return (select coalesce(jsonb_agg(x order by x.scanned_at desc),'[]') from (select * from library_attendance where member_id=s.member_id order by scanned_at desc limit 100) x);
 elsif p_action='clearance' and s.member_id is not null then mid=s.member_id;
 else
 if u.id is null then raise exception 'Staff access required';end if;
 if u.role='assistant' and p_action not in ('search','copies','copy_history','calendar','rules','clearance','requests','reading','occupancy','visits','handover','filters','filter_save','filter_delete','closing','closing_history','duplicates','merge_preview','pickups') then raise exception 'Assistant access is read-only';end if;
 if p_action in ('calendar_save','rule_save','merge','capacity','restore','backup') and u.role<>'admin' then raise exception 'Administrator access required';end if;
 mid=nullif(p_data->>'member_id','')::uuid;
 end if;
 perform pg_advisory_xact_lock(17000);
 if p_action in ('copies','pickups','occupancy','closing','search','copy_save','collect') then perform library_private.queue();end if;
 if p_action='clearance' then
 if mid is null or not exists(select 1 from library_members where id=mid) then raise exception 'Select a member';end if;
 return jsonb_build_object('member',(select jsonb_build_object('name',full_name,'member_no',member_no) from library_members where id=mid),'checked_at',now(),'loans',(select coalesce(jsonb_agg(jsonb_build_object('id',l.id,'title',b.title,'accession',c.accession,'due_at',l.due_at,'status',l.status)),'[]') from library_loans l join library_books b on b.id=l.book_id left join library_copies c on c.id=l.copy_id where member_id=mid and l.status in ('borrowed','lost')),'incidents',(select coalesce(jsonb_agg(r),'[]') from library_service_requests r where member_id=mid and kind='incident' and status='pending'));
 elsif p_action='search' then
 q='%'||left(coalesce(p_data->>'search',''),100)||'%';v=coalesce(p_data->>'kind','All');
 return (select coalesce(jsonb_agg(x),'[]') from (select 'Member' kind,id,full_name label,member_no reference,concat_ws(' / ',grade_level,section) detail from library_members where merged_into is null and v in ('All','Member') and concat_ws(' ',full_name,member_no,rfid_uid,section) ilike q union all select 'Book',id,title,accession_no,concat_ws(' / ',author,shelf) from library_books where merged_into is null and v in ('All','Book') and concat_ws(' ',title,author,isbn,accession_no,book_rfid) ilike q union all select 'Copy',c.id,b.title,c.accession,concat_ws(' / ',c.rfid,c.shelf,c.condition) from library_copies c join library_books b on b.id=c.book_id where v in ('All','Copy') and concat_ws(' ',b.title,c.accession,c.rfid) ilike q union all select 'Loan',l.id,b.title,m.member_no,concat_ws(' / ',m.full_name,l.status,l.due_at) from library_loans l join library_books b on b.id=l.book_id join library_members m on m.id=l.member_id where v in ('All','Loan') and concat_ws(' ',b.title,m.member_no,m.full_name,l.id) ilike q limit 500) x);
 elsif p_action='copies' then
 return (select coalesce(jsonb_agg(x order by x.title,x.accession),'[]') from (select c.*,b.title,case when exists(select 1 from library_loans l where l.copy_id=c.id and l.status in ('borrowed','lost')) then 'On loan / unresolved' when exists(select 1 from library_pickups h where h.copy_id=c.id and h.state='ready') then 'Reserved' when c.needs_verification then 'Needs verification' else c.condition end availability from library_copies c join library_books b on b.id=c.book_id where (p_data->>'book_id' is null or c.book_id=(p_data->>'book_id')::uuid) and concat_ws(' ',b.title,c.accession,c.rfid,c.shelf) ilike '%'||coalesce(p_data->>'search','')||'%' limit 1000) x);
 elsif p_action='copy_history' then
 return (select coalesce(jsonb_agg(x order by x.borrowed_at desc),'[]') from (select l.*,m.full_name,m.member_no from library_loans l join library_members m on m.id=l.member_id where copy_id=(p_data->>'id')::uuid) x);
 elsif p_action='copy_save' then
 rid=nullif(p_data->>'id','')::uuid;b=(p_data->>'book_id')::uuid;
 if length(trim(coalesce(p_data->>'accession',''))) not between 1 and 80 then raise exception 'Accession is required';end if;
 if not exists(select 1 from library_books where id=b and active and merged_into is null) then raise exception 'Active book required';end if;
 if exists(select 1 from library_copies cc where cc.id is distinct from rid and (cc.accession=nullif(trim(p_data->>'rfid'),'') or cc.rfid=trim(p_data->>'accession'))) then raise exception 'RFID conflicts with another accession, or accession conflicts with another RFID';end if;
 if rid is not null then
 select * into c from library_copies where id=rid for update;
 if not found or c.book_id<>b then raise exception 'Copy not found';end if;
 if (p_data->>'condition') in ('retired','lost') and exists(select 1 from library_loans where copy_id=rid and status='borrowed') then raise exception 'Resolve the active loan first';end if;
 old=to_jsonb(c);
 update library_copies set accession=trim(p_data->>'accession'),rfid=nullif(trim(p_data->>'rfid'),''),shelf=p_data->>'shelf',condition=p_data->>'condition',notes=left(coalesce(p_data->>'notes',''),2000),needs_verification=not coalesce((p_data->>'verified')::boolean,false) where id=rid;
 else
 insert into library_copies(book_id,accession,rfid,shelf,condition,notes,needs_verification) values(b,trim(p_data->>'accession'),nullif(trim(p_data->>'rfid'),''),p_data->>'shelf',p_data->>'condition',left(coalesce(p_data->>'notes',''),2000),not coalesce((p_data->>'verified')::boolean,false)) returning id into rid;
 end if;
 perform library_private.stock(b);perform library_private.queue();
 elsif p_action='calendar' then
 return jsonb_build_object('open_days',(select jsonb_agg(day order by day) from library_open_days),'closed',(select coalesce(jsonb_agg(c order by day),'[]') from library_closed_dates c));
 elsif p_action='calendar_save' then
 if jsonb_typeof(p_data->'open_days')<>'array' or jsonb_array_length(p_data->'open_days')<1 then raise exception 'Choose at least one open day';end if;
 delete from library_open_days;insert into library_open_days select distinct value::int from jsonb_array_elements_text(p_data->'open_days');
 delete from library_closed_dates;insert into library_closed_dates select (x->>'day')::date,left(x->>'reason',200) from jsonb_array_elements(p_data->'closed') x;
 elsif p_action='rules' then return (select jsonb_agg(r order by member_type) from library_borrow_rules r);
 elsif p_action='rule_save' then
 if coalesce(p_data->>'member_type','') not in ('student','employee','teacher','guest','staff','other') then raise exception 'Invalid member type';end if;
 insert into library_borrow_rules values(p_data->>'member_type',(p_data->>'max_books')::int,(p_data->>'loan_days')::int,coalesce((p_data->>'block_overdue')::boolean,true)) on conflict(member_type) do update set max_books=excluded.max_books,loan_days=excluded.loan_days,block_overdue=excluded.block_overdue;
 elsif p_action='requests' then
 return (select coalesce(jsonb_agg(x order by x.created_at desc),'[]') from (select r.*,m.full_name,m.member_no from library_ops_requests r left join library_members m on m.id=r.member_id order by created_at desc limit 1000) x);
 elsif p_action='review' then
 select * into r from library_ops_requests where id=(p_data->>'id')::uuid for update;
 if not found or r.status in ('approved','rejected','added') then raise exception 'Request already completed';end if;
 v=p_data->>'status';
 if v is null or (r.kind='acquisition' and v not in ('under_review','ordered','added','rejected')) or (r.kind<>'acquisition' and v not in ('approved','rejected')) then raise exception 'Invalid decision';end if;
 if r.kind='acquisition' and v='added' and not exists(select 1 from library_books where id=nullif(p_data->>'book_id','')::uuid and active) then raise exception 'Select the added catalog book';end if;
 if v='approved' and r.kind='profile' then
 select to_jsonb(m) into old from library_members m where id=r.member_id;
 update library_members set full_name=trim(r.data->>'full_name'),grade_level=r.data->>'grade_level',section=r.data->>'section',updated_at=now() where id=r.member_id;
 elsif v='approved' and r.kind='attendance' then
 select to_jsonb(a) into old from library_attendance a where id=(r.data->>'attendance_id')::uuid and member_id=r.member_id for update;
 if old is null then raise exception 'Attendance entry no longer exists';end if;
 if r.data->>'action' not in ('IN','OUT') or (r.data->>'scanned_at')::timestamptz>now() then raise exception 'Invalid attendance correction';end if;
 update library_attendance set action=r.data->>'action',scanned_at=(r.data->>'scanned_at')::timestamptz,notes=concat_ws(' | ',notes,'Correction: '||(r.data->>'reason')) where id=(r.data->>'attendance_id')::uuid;
 end if;
 update library_ops_requests set status=v,note=left(coalesce(p_data->>'note',''),2000),reviewed_at=now(),reviewed_by=u.id,data=data||jsonb_build_object('catalog_book_id',p_data->>'book_id') where id=r.id;rid=r.id;
 elsif p_action='reading_save' then
 rid=nullif(p_data->>'id','')::uuid;
 if length(trim(coalesce(p_data->>'name','')))<2 then raise exception 'Reading list name required';end if;
 if rid is null then insert into library_reading_lists(name,subject,grade,created_by) values(p_data->>'name',coalesce(p_data->>'subject',''),coalesce(p_data->>'grade',''),u.id) returning id into rid;
 else update library_reading_lists set name=p_data->>'name',subject=coalesce(p_data->>'subject',''),grade=coalesce(p_data->>'grade','') where id=rid;if not found then raise exception 'List not found';end if;end if;
 delete from library_reading_items where list_id=rid;insert into library_reading_items select rid,value::uuid from jsonb_array_elements_text(p_data->'book_ids');
 elsif p_action='reading_delete' then
 delete from library_reading_items where list_id=(p_data->>'id')::uuid;delete from library_reading_lists where id=(p_data->>'id')::uuid;
 elsif p_action='occupancy' then
 return jsonb_build_object('capacity',coalesce((select value::int from library_settings where key='capacity'),50),'people',(select coalesce(jsonb_agg(x order by scanned_at),'[]') from (select a.*,m.full_name,m.member_no,(a.scanned_at at time zone 'Asia/Manila')::date<(now() at time zone 'Asia/Manila')::date stale from (select distinct on(member_id) * from library_attendance order by member_id,scanned_at desc,id desc) a join library_members m on m.id=a.member_id where action='IN') x));
 elsif p_action='capacity' then
 n=(p_data->>'capacity')::int;if n not between 1 and 10000 then raise exception 'Capacity must be 1–10000';end if;
 insert into library_settings(key,value) values('capacity',n::text) on conflict(key) do update set value=excluded.value;
 elsif p_action='attendance_correct' then
 if length(trim(coalesce(p_data->>'reason','')))<3 then raise exception 'Correction reason required';end if;
 select to_jsonb(a) into old from library_attendance a where id=(p_data->>'id')::uuid for update;
 if old is null then raise exception 'Entry not found';end if;
 if coalesce(p_data->>'action','') not in ('IN','OUT') or (p_data->>'scanned_at')::timestamptz>now() then raise exception 'Invalid correction';end if;
 update library_attendance set action=p_data->>'action',scanned_at=(p_data->>'scanned_at')::timestamptz,notes=concat_ws(' | ',notes,'Correction: '||(p_data->>'reason')) where id=(p_data->>'id')::uuid;
 elsif p_action='visits' then return (select coalesce(jsonb_agg(v order by starts_at desc),'[]') from library_class_visits v);
 elsif p_action='visit_save' then
 if length(trim(coalesce(p_data->>'section','')))<1 or length(trim(coalesce(p_data->>'teacher','')))<2 then raise exception 'Section and teacher required';end if;
 cap=coalesce((select value::int from library_settings where key='capacity'),50);
 if (p_data->>'seats')::int>cap then raise exception 'Booking exceeds library capacity';end if;
 if (p_data->>'ends_at')::timestamptz<=(p_data->>'starts_at')::timestamptz or (p_data->>'starts_at')::timestamptz<now() then raise exception 'Choose a future start and later end';end if;
 if exists(select 1 from generate_series(((p_data->>'starts_at')::timestamptz at time zone 'Asia/Manila')::date,(((p_data->>'ends_at')::timestamptz-interval '1 microsecond') at time zone 'Asia/Manila')::date,interval '1 day') d where library_private.open_date(d::date)<>d::date) then raise exception 'Booking overlaps a closed date';end if;
 if exists(select 1 from library_class_visits where status='booked' and tstzrange(starts_at,ends_at,'[)') && tstzrange((p_data->>'starts_at')::timestamptz,(p_data->>'ends_at')::timestamptz,'[)')) then raise exception 'This time overlaps an existing class visit';end if;
 insert into library_class_visits(section,teacher,starts_at,ends_at,seats,created_by) values(p_data->>'section',p_data->>'teacher',(p_data->>'starts_at')::timestamptz,(p_data->>'ends_at')::timestamptz,(p_data->>'seats')::int,u.id) returning id into rid;
 elsif p_action='visit_cancel' then update library_class_visits set status='cancelled' where id=(p_data->>'id')::uuid;
 elsif p_action='handover' then return (select coalesce(jsonb_agg(x order by x.created_at desc),'[]') from (select h.*,u.full_name from library_handover h left join library_users u on u.id=h.created_by order by h.created_at desc limit 500) x);
 elsif p_action='handover_add' then
 if length(trim(coalesce(p_data->>'message','')))<3 then raise exception 'Write a handover note';end if;
 insert into library_handover(message,created_by) values(left(p_data->>'message',4000),u.id) returning id into rid;
 elsif p_action='handover_resolve' then update library_handover set resolved_at=now(),resolved_by=u.id where id=(p_data->>'id')::uuid and resolved_at is null;
 elsif p_action='filters' then return (select coalesce(jsonb_agg(f order by name),'[]') from library_saved_filters f where user_id=u.id);
 elsif p_action='filter_save' then
 if length(trim(coalesce(p_data->>'name','')))<1 then raise exception 'Filter name required';end if;
 insert into library_saved_filters(user_id,name,data) values(u.id,left(p_data->>'name',100),jsonb_build_object('search',left(coalesce(p_data->>'search',''),100),'kind',p_data->>'kind')) on conflict(user_id,name) do update set data=excluded.data;
 elsif p_action='filter_delete' then delete from library_saved_filters where id=(p_data->>'id')::uuid and user_id=u.id;
 elsif p_action='closing_history' then return (select coalesce(jsonb_agg(x order by x.created_at desc),'[]') from (select * from library_closing_reports order by created_at desc limit 100) x);
 elsif p_action in ('closing','closing_save') then
 day=coalesce((p_data->>'day')::date,(now() at time zone 'Asia/Manila')::date);
 res=jsonb_build_object('day',day,'generated_at',now(),'borrowed',(select count(*) from library_loans where (borrowed_at at time zone 'Asia/Manila')::date=day),'returned',(select count(*) from library_loans where (returned_at at time zone 'Asia/Manila')::date=day),'visits',(select count(*) from library_attendance where action='IN' and (scanned_at at time zone 'Asia/Manila')::date=day),'overdue_now',(select count(*) from library_loans where status='borrowed' and due_at<now()),'pending_corrections',(select count(*) from library_ops_requests where kind in ('attendance','profile') and status='pending'),'open_handover_notes',(select count(*) from library_handover where resolved_at is null),'occupancy',library_operations(p_token,'occupancy','{}'));
 if p_action='closing' then return res;end if;
 insert into library_closing_reports(day,created_by,summary) values(day,u.id,res) returning id into rid;
 elsif p_action='pickups' then return (select coalesce(jsonb_agg(x order by x.deadline),'[]') from (select p.*,m.full_name,m.member_no,b.title,c.accession from library_pickups p join library_service_requests r on r.id=p.request_id join library_members m on m.id=r.member_id join library_books b on b.id=r.book_id join library_copies c on c.id=p.copy_id where p.state='ready') x);
 elsif p_action='collect' then
 select * into pk from library_pickups where request_id=(p_data->>'id')::uuid and state='ready' and deadline>now() for update;
 if not found then raise exception 'Pickup expired or already completed';end if;
 select * into req from library_service_requests where id=pk.request_id;
 select br.* into rr from library_borrow_rules br join library_members m on m.member_type=br.member_type where m.id=req.member_id;
 if not found then select * into rr from library_borrow_rules where member_type='student';end if;
 insert into library_loans(member_id,book_id,copy_id,borrowed_by,due_at,verified_at) values(req.member_id,req.book_id,pk.copy_id,u.username,(library_private.open_date((now() at time zone 'Asia/Manila')::date+rr.loan_days)+time '17:00') at time zone 'Asia/Manila',now()) returning id into rid;
 update library_pickups set state='collected' where request_id=req.id;update library_service_requests set status='approved',reviewed_at=now(),reviewed_by=u.id,loan_id=rid where id=req.id;perform library_private.stock(req.book_id);
 elsif p_action in ('verify_loan','reject_loan') then
 update library_loans set verified_at=case when p_action='verify_loan' then now() else verified_at end,status=case when p_action='reject_loan' then 'cancelled' else status end where id=(p_data->>'id')::uuid and status='borrowed' and verified_at is null returning book_id into b;
 if not found then raise exception 'Request already reviewed';end if;perform library_private.stock(b);perform library_private.queue();
 elsif p_action='resolve_lost' then
 if length(trim(coalesce(p_data->>'reason','')))<3 or coalesce(p_data->>'resolution','') not in ('found','written_off') then raise exception 'Choose a resolution and provide a reason';end if;
 select to_jsonb(l),l.copy_id,l.book_id into old,rid,b from library_loans l where l.id=(p_data->>'id')::uuid and l.status='lost' for update;
 if not found then raise exception 'Select an unresolved lost loan';end if;
 update library_copies set condition=case when p_data->>'resolution'='found' then 'quarantine' else 'retired' end,needs_verification=true,notes=concat_ws(' | ',notes,p_data->>'reason') where id=rid;
 update library_loans set status=case when p_data->>'resolution'='found' then 'returned' else 'cancelled' end,returned_at=now(),returned_by=u.username,notes=concat_ws(' | ',notes,'Lost resolution: '||(p_data->>'resolution')||' — '||(p_data->>'reason')) where id=(p_data->>'id')::uuid;
 update library_service_requests set status='resolved',reviewed_at=now(),reviewed_by=u.id,data=data||jsonb_build_object('staff_note',p_data->>'reason') where loan_id=(p_data->>'id')::uuid and kind='incident' and status='pending';
 perform library_private.stock(b);perform library_private.queue();
 elsif p_action='duplicates' then
 return (select coalesce(jsonb_agg(x),'[]') from (select 'Member' kind,lower(trim(full_name)) match,array_agg(id order by member_no) ids,string_agg(member_no,', ' order by member_no) records from library_members where merged_into is null group by lower(trim(full_name)) having count(*)>1 union all select 'Book',lower(trim(title))||' / '||lower(coalesce(author,'')),array_agg(id order by accession_no),string_agg(accession_no,', ' order by accession_no) from library_books where merged_into is null group by lower(trim(title)),lower(coalesce(author,'')) having count(*)>1) x);
 elsif p_action in ('merge_preview','merge') then
 src=(p_data->>'source')::uuid;dst=(p_data->>'target')::uuid;v=p_data->>'kind';
 if src=dst or src is null or dst is null then raise exception 'Select two different records';end if;
 if v='Member' then
 if (select count(*) from library_members where id in(src,dst) and merged_into is null)<>2 then raise exception 'Member unavailable';end if;
 preview=jsonb_build_object('source',(select to_jsonb(m) from library_members m where id=src),'target',(select to_jsonb(m) from library_members m where id=dst),'loans',(select count(*) from library_loans where member_id=src),'attendance',(select count(*) from library_attendance where member_id=src),'requests',(select count(*) from library_service_requests where member_id=src)+(select count(*) from library_ops_requests where member_id=src));
 elsif v='Book' then
 if (select count(*) from library_books where id in(src,dst) and merged_into is null)<>2 then raise exception 'Book unavailable';end if;
 preview=jsonb_build_object('source',(select to_jsonb(b)-'cover_data' from library_books b where id=src),'target',(select to_jsonb(b)-'cover_data' from library_books b where id=dst),'copies',(select count(*) from library_copies where book_id=src),'loans',(select count(*) from library_loans where book_id=src),'requests',(select count(*) from library_service_requests where book_id=src));
 else raise exception 'Invalid merge kind';end if;
 preview=preview||jsonb_build_object('fingerprint',encode(digest(preview::text,'sha256'),'hex'));
 if p_action='merge_preview' then return preview;end if;
 if coalesce(p_data->>'confirmation','')<>'MERGE' or p_data->>'fingerprint' is distinct from preview->>'fingerprint' then raise exception 'Preview changed; review again and type MERGE';end if;
 if exists(select 1 from library_service_requests where status='pending' and ((v='Member' and member_id in(src,dst)) or (v='Book' and book_id in(src,dst)))) then raise exception 'Resolve pending requests before merging';end if;
 if v='Member' then
 update library_loans set member_id=dst where member_id=src;update library_attendance set member_id=dst where member_id=src;update library_service_requests set member_id=dst where member_id=src;update library_ops_requests set member_id=dst where member_id=src;update library_retired_cards set member_id=dst where member_id=src;
 delete from library_app_sessions where member_id in(src,dst);update library_members set active=false,merged_into=dst where id=src;
 else
 update library_copies set book_id=dst where book_id=src;update library_loans set book_id=dst where book_id=src;update library_service_requests set book_id=dst where book_id=src;
 insert into library_reading_items select list_id,dst from library_reading_items where book_id=src on conflict do nothing;delete from library_reading_items where book_id=src;
 update library_books set active=false,merged_into=dst where id=src;perform library_private.stock(src);perform library_private.stock(dst);
 end if;old=preview;
 else raise exception 'Unknown operations action: %',p_action;
 end if;
 insert into library_audit_log(actor_username,action,entity_type,entity_id,details) values(u.username,p_action,'library operations',coalesce(rid,mid)::text,jsonb_build_object('before',old,'input',p_data));
 return coalesce(res,jsonb_build_object('ok',true,'id',rid));
end $$;
create or replace function library_suite(p_token text,p_action text,p_data jsonb default '{}') returns jsonb language plpgsql security definer set search_path=public,extensions,pg_temp as $$
declare s library_app_sessions;u library_users;r library_service_requests;res jsonb;snap jsonb;tbl text;key text;cols text;ups text;pk text;b uuid;d date;rules library_borrow_rules;
begin
 s=library_suite_session(p_token);select * into u from library_users where id=s.user_id;
 perform pg_advisory_xact_lock(17000);
 perform library_private.queue();
 if p_action='inventory_scan' then
 if u.id is null or u.role='assistant' then raise exception 'Librarian access required';end if;
 perform 1 from library_inventory_sessions where id=(p_data->>'session_id')::uuid and completed_at is null for update;
 if not found then raise exception 'Inventory session closed or missing';end if;
 insert into library_copy_scans(session_id,copy_id,shelf) select (p_data->>'session_id')::uuid,id,p_data->>'shelf' from library_copies where rfid=p_data->>'rfid' or accession=p_data->>'rfid' on conflict(session_id,copy_id) do update set shelf=excluded.shelf,scanned_at=now();
 if not found then raise exception 'Physical copy RFID/accession not registered';end if;
 return '{"ok":true}';
 elsif p_action='inventory_results' then
 if u.id is null then raise exception 'Staff access required';end if;
 return (select coalesce(jsonb_agg(x order by x.title),'[]') from (select c.id,b.title,c.accession book_rfid,c.shelf,sc.shelf observed_shelf,case when sc.copy_id is null then case when exists(select 1 from library_loans l where l.copy_id=c.id and status in ('borrowed','lost')) then 'On loan / unresolved' else 'Unscanned' end when coalesce(sc.shelf,'')<>coalesce(c.shelf,'') then 'Misplaced' else 'Found' end status from library_copies c join library_books b on b.id=c.book_id left join library_copy_scans sc on sc.copy_id=c.id and sc.session_id=(p_data->>'session_id')::uuid where c.condition<>'retired') x);
 elsif p_action='backup' then
 if u.id is null or u.role<>'admin' then raise exception 'Administrator access required';end if;
 snap=library_suite_v3(p_token,'backup','{}');
 foreach tbl in array array['library_copies','library_borrow_rules','library_closed_dates','library_open_days','library_pickups','library_ops_requests','library_reading_lists','library_reading_items','library_class_visits','library_handover','library_saved_filters','library_closing_reports','library_copy_scans'] loop
 execute format('select coalesce(jsonb_agg(t),''[]''::jsonb) from %I t',tbl) into res;snap=snap||jsonb_build_object(tbl,res);
 end loop;return snap||jsonb_build_object('format','SMPCS operational backup v3');
 elsif p_action='restore' then
 if u.id is null or u.role<>'admin' or coalesce(p_data->>'confirmation','')<>'RESTORE' then raise exception 'Administrator and RESTORE confirmation required';end if;
 snap=p_data->'snapshot';if p_data ? 'restore_id' then select snapshot into snap from library_restore_points where id=(p_data->>'restore_id')::uuid;end if;
 if coalesce(snap->>'format','')<>'SMPCS operational backup v3' then raise exception 'Use a v1.7 operational backup. Restore older snapshots on a separate pre-v1.7 database, then migrate, to protect copy assignments.';end if;
 insert into library_restore_points(snapshot) values(library_suite(p_token,'backup','{}'));
 -- Only the owner function can suspend these triggers, within this transaction.
 alter table library_books disable trigger ops_seed_book;
 alter table library_loans disable trigger maintenance_guard;
 alter table library_loans disable trigger ops_loan_guard;
 alter table library_loans disable trigger ops_loan_stock;
 foreach tbl in array array['library_members','library_books','library_copies','library_loans','library_attendance','library_return_requests','library_service_requests','library_announcements','library_inventory_sessions','library_inventory_scans','library_retired_cards','library_borrow_rules','library_closed_dates','library_open_days','library_pickups','library_ops_requests','library_reading_lists','library_reading_items','library_class_visits','library_handover','library_saved_filters','library_closing_reports','library_copy_scans'] loop
 key=case tbl when 'library_members' then 'members' when 'library_books' then 'books' when 'library_loans' then 'loans' when 'library_attendance' then 'attendance' when 'library_return_requests' then 'return_requests' else tbl end;
 if jsonb_typeof(snap->key) is distinct from 'array' then raise exception 'Missing backup table: %',key;end if;
 pk=case tbl when 'library_inventory_scans' then 'session_id,book_id' when 'library_retired_cards' then 'rfid_uid' when 'library_borrow_rules' then 'member_type' when 'library_closed_dates' then 'day' when 'library_open_days' then 'day' when 'library_pickups' then 'request_id' when 'library_reading_items' then 'list_id,book_id' when 'library_copy_scans' then 'session_id,copy_id' else 'id' end;
 select string_agg(quote_ident(column_name),','),string_agg(format('%I=excluded.%I',column_name,column_name),',') into cols,ups from information_schema.columns where table_schema='public' and table_name=tbl and is_generated='NEVER' and is_identity='NO';
 if tbl in ('library_open_days','library_closed_dates') then execute format('delete from %I',tbl);end if;
 execute format('insert into %I (%s) select %s from jsonb_populate_recordset(null::%I,$1) on conflict (%s) do update set %s',tbl,cols,cols,tbl,pk,ups) using snap->key;
 end loop;
 if exists(select 1 from library_loans l join library_copies c on c.id=l.copy_id where l.book_id<>c.book_id) then raise exception 'Backup copy and book mismatch';end if;
 alter table library_loans enable trigger maintenance_guard;
 alter table library_books enable trigger ops_seed_book;alter table library_loans enable trigger ops_loan_guard;alter table library_loans enable trigger ops_loan_stock;
 for b in select id from library_books loop perform library_private.stock(b);end loop;
 delete from library_app_sessions where member_id is not null;
 delete from library_restore_points where id in(select id from library_restore_points order by created_at desc offset 7);
 insert into library_audit_log(actor_username,action,entity_type) values(u.username,'restore','operations backup');return '{"ok":true}';
 elsif p_action='review' then
 select * into r from library_service_requests where id=(p_data->>'id')::uuid and status='pending';
 if u.id is null or u.role='assistant' then raise exception 'Librarian access required';end if;
 if r.kind='reservation' and p_data->>'decision'='approved' then
 if not exists(select 1 from library_pickups where request_id=r.id and state='ready') then raise exception 'No copy ready yet; serve the first person in queue';end if;
 return library_operations(p_token,'collect',jsonb_build_object('id',r.id));
 elsif r.kind='renewal' and p_data->>'decision'='approved' then
 if exists(select 1 from library_service_requests where book_id=r.book_id and kind='reservation' and status='pending') then raise exception 'Another member is waiting';end if;
 select br.* into rules from library_borrow_rules br join library_members m on br.member_type=m.member_type where m.id=r.member_id;
 if not found then select * into rules from library_borrow_rules where member_type='student';end if;
 select library_private.open_date(least((due_at at time zone 'Asia/Manila')::date+(r.data->>'days')::int,(now() at time zone 'Asia/Manila')::date+rules.loan_days)) into d from library_loans where id=r.loan_id and status='borrowed';
 if d is null or d<=(select (due_at at time zone 'Asia/Manila')::date from library_loans where id=r.loan_id) then raise exception 'Renewal would exceed the borrowing rule';end if;
 update library_loans set due_at=(d+time '17:00') at time zone 'Asia/Manila' where id=r.loan_id;
 update library_service_requests set status='approved',reviewed_at=now(),reviewed_by=u.id,data=data||jsonb_build_object('staff_note',p_data->>'note') where id=r.id;
 insert into library_audit_log(actor_username,action,entity_type,entity_id) values(u.username,'renewal','loan',r.loan_id::text);return '{"ok":true}';
 end if;
 end if;
 res=library_suite_v3(p_token,p_action,p_data);
 if p_action in ('cancel_request','review') then
 update library_pickups set state='cancelled' where request_id=(p_data->>'id')::uuid and state='ready' and exists(select 1 from library_service_requests where id=(p_data->>'id')::uuid and status in ('cancelled','rejected'));
 perform library_private.queue();
 for b in select distinct c.book_id from library_copies c join library_pickups p on p.copy_id=c.id where p.request_id=(p_data->>'id')::uuid loop perform library_private.stock(b);end loop;
 end if;return res;
end $$;
create or replace function library_account_action(p_token text,p_action text,p_data jsonb default '{}') returns jsonb language plpgsql security definer set search_path=public,extensions,pg_temp as $$
declare s library_app_sessions;u library_users;r library_return_requests;b uuid;begin
 s=library_suite_session(p_token);select * into u from library_users where id=s.user_id;
 if p_action='backup' then return library_suite(p_token,'backup',p_data);end if;
 if p_action='return_review' then
 if u.id is null or u.role not in ('admin','librarian') then raise exception 'Librarian access required';end if;
 perform pg_advisory_xact_lock(17000);
 select * into r from library_return_requests where id=(p_data->>'id')::uuid and status='pending' for update;
 if not found then raise exception 'Return already reviewed';end if;
 if (p_data->>'approve')::boolean then
 update library_loans set status='returned',returned_at=now(),returned_by=u.username where id=r.loan_id and status='borrowed' returning book_id into b;
 if not found then raise exception 'Loan no longer active';end if;
 end if;
 update library_return_requests set status=case when (p_data->>'approve')::boolean then 'approved' else 'rejected' end,reviewed_by=u.id,reviewed_at=now() where id=r.id;
 perform library_private.queue();
 insert into library_audit_log(actor_username,action,entity_type,entity_id,details) values(u.username,'return_review','loan',r.loan_id::text,p_data);return '{"ok":true}';
 end if;return library_account_action_v3(p_token,p_action,p_data);
end $$;
create or replace function library_operations_station(p_station text,p_token text,p_action text,p_data jsonb default '{}') returns jsonb language plpgsql security definer set search_path=public,extensions,pg_temp as $$
declare m library_members;c library_copies;b library_books;rr library_borrow_rules;lid uuid;d date;begin
 perform library_kiosk_auth(p_station,p_token);perform pg_advisory_xact_lock(17000);
 if exists(select 1 from library_settings where key='maintenance' and value='true') then raise exception 'Library transactions paused for maintenance';end if;
 select * into m from library_members where rfid_uid=p_data->>'member_rfid' and active and merged_into is null;
 if not found then raise exception 'Tap an active member card';end if;
 perform library_private.queue();
 select * into c from library_copies where rfid=p_data->>'scan' or accession=p_data->>'scan';
 if not found then raise exception 'Copy RFID/accession is not registered. Ask the librarian to verify this physical copy.';end if;
 select * into b from library_books where id=c.book_id and active;
 if not found then raise exception 'Book inactive';end if;
 select * into rr from library_borrow_rules where member_type=m.member_type;
 if not found then select * into rr from library_borrow_rules where member_type='student';end if;
 d=library_private.open_date((now() at time zone 'Asia/Manila')::date+rr.loan_days);
 if p_action='find' then
 return jsonb_build_object('id',b.id,'copy_id',c.id,'title',b.title,'accession',c.accession,'scan',p_data->>'scan','default_due',d,'today',(now() at time zone 'Asia/Manila')::date,'open_days',(select jsonb_agg(day) from library_open_days),'closed_dates',(select coalesce(jsonb_agg(day),'[]') from library_closed_dates));
 elsif p_action='borrow' then
 if c.needs_verification then raise exception 'Copy needs librarian verification';end if;
 insert into library_loans(member_id,book_id,copy_id,due_at,borrowed_by) values(m.id,b.id,c.id,((p_data->>'due_date')::date+time '17:00') at time zone 'Asia/Manila',p_station) returning id into lid;
 update library_pickups set state='collected' where copy_id=c.id and state='ready' and request_id in(select id from library_service_requests where member_id=m.id);
 update library_service_requests set status='approved',loan_id=lid,reviewed_at=now() where id in(select request_id from library_pickups where copy_id=c.id and state='collected') and status='pending';
 perform library_private.stock(b.id);return jsonb_build_object('id',lid);
 elsif p_action='return' then
 select id into lid from library_loans where copy_id=c.id and member_id=m.id and status='borrowed';
 if lid is null then raise exception 'This physical copy is not borrowed by this member';end if;
 perform library_station_service(p_station,p_token,'return_request',jsonb_build_object('loan_id',lid,'rfid',m.rfid_uid));return jsonb_build_object('title',b.title,'accession',c.accession);
 else raise exception 'Unknown station action';end if;
end $$;
-- Legacy book-level borrowing cannot distinguish physical copies. New clients use
-- the authenticated station endpoint; the old callable borrow path is retired.
do $$ declare f record;b uuid;begin
 for f in select oid::regprocedure sig from pg_proc where pronamespace='public'::regnamespace and proname='library_borrow' loop execute format('revoke all on function %s from public,anon,authenticated',f.sig);end loop;
 for b in select id from library_books loop perform library_private.stock(b);end loop;
end $$;
revoke all on all functions in schema library_private from public,anon,authenticated;
revoke all on function library_operations(text,text,jsonb),library_operations_station(text,text,text,jsonb),library_suite(text,text,jsonb),library_account_action(text,text,jsonb) from public;
grant execute on function library_operations(text,text,jsonb),library_operations_station(text,text,text,jsonb),library_suite(text,text,jsonb),library_account_action(text,text,jsonb) to anon,authenticated;
-- Preserve the staff entry point while replacing unsafe book-level counters.
do $$ begin
 if to_regprocedure('library_staff_rpc_v3(text,text,jsonb)') is null then alter function library_staff_rpc(text,text,jsonb) rename to library_staff_rpc_v3;end if;
end $$;
revoke all on function library_staff_rpc_v3(text,text,jsonb) from public,anon,authenticated;
create or replace function library_staff_rpc(p_token text,p_name text,p_args jsonb default '{}') returns jsonb language plpgsql security definer set search_path=public,extensions,pg_temp as $$
declare s library_app_sessions;u library_users;b library_books;res jsonb;begin
 s=library_suite_session(p_token);select * into u from library_users where id=s.user_id;
 if u.id is null or u.role='assistant' then raise exception 'Librarian access required';end if;
 perform pg_advisory_xact_lock(17000);
 if p_name in ('library_verify_loan','library_reject_loan') then return library_operations(p_token,case when p_name='library_verify_loan' then 'verify_loan' else 'reject_loan' end,jsonb_build_object('id',p_args->>'p_loan_id'));end if;
 if p_name='library_save_book' then
 select * into b from library_books where accession_no=p_args->>'p_accession_no';
 if found and b.total_copies is distinct from (p_args->>'p_total_copies')::int then raise exception 'Manage stock in Library Services → Physical copies. Add or retire each physical copy there.';end if;
 end if;
 res=library_staff_rpc_v3(p_token,p_name,p_args);
 if p_name='library_save_book' then select * into b from library_books where accession_no=p_args->>'p_accession_no';perform library_private.stock(b.id);end if;
 return res;
end $$;
revoke all on function library_staff_rpc(text,text,jsonb) from public;
grant execute on function library_staff_rpc(text,text,jsonb) to anon,authenticated;

notify pgrst,'reload schema';
commit;
