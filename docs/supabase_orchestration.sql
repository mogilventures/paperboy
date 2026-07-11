-- Backend-owned state for replacing Paperboy's n8n workflows.
-- Apply manually in the shared Supabase project before setting
-- ORCHESTRATION_ENABLED=true on Fly.io.

create table if not exists public.orchestration_runs (
    source_date date primary key,
    run_id uuid not null,
    status text not null check (
        status in ('running', 'completed', 'completed_with_errors', 'failed')
    ),
    started_at timestamptz not null default now(),
    heartbeat_at timestamptz not null default now(),
    completed_at timestamptz,
    total_profiles integer not null default 0,
    sent_count integer not null default 0,
    failed_count integer not null default 0,
    skipped_count integer not null default 0,
    last_error text,
    unique (source_date, run_id)
);

create table if not exists public.orchestration_deliveries (
    source_date date not null,
    run_id uuid not null,
    profile_id uuid not null,
    user_id uuid not null,
    profile_snapshot jsonb not null,
    task_id text,
    status text not null check (
        status in (
            'pending', 'generating', 'generated', 'sending', 'sent', 'failed',
            'ambiguous'
        )
    ),
    email_id text,
    email_attempted_at timestamptz,
    email_sent_at timestamptz,
    last_error text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    primary key (source_date, user_id),
    foreign key (source_date, run_id)
        references public.orchestration_runs(source_date, run_id)
        on update cascade
        on delete cascade
);

create index if not exists orchestration_deliveries_task_id_idx
    on public.orchestration_deliveries(task_id)
    where task_id is not null;

alter table public.orchestration_runs enable row level security;
alter table public.orchestration_deliveries enable row level security;

-- Browser clients do not need access. The backend uses a service-role client,
-- which bypasses RLS. Explicit revokes make that boundary visible.
revoke all on public.orchestration_runs from anon, authenticated;
revoke all on public.orchestration_deliveries from anon, authenticated;
grant all on public.orchestration_runs to service_role;
grant all on public.orchestration_deliveries to service_role;

create or replace function public.claim_orchestration_run(
    p_source_date date,
    p_run_id uuid,
    p_stale_before timestamptz,
    p_retry_failed boolean default false
) returns boolean
language plpgsql
security definer
set search_path = public
as $$
declare
    affected_rows integer;
begin
    insert into public.orchestration_runs (
        source_date,
        run_id,
        status,
        started_at,
        heartbeat_at,
        completed_at,
        total_profiles,
        sent_count,
        failed_count,
        skipped_count,
        last_error
    ) values (
        p_source_date,
        p_run_id,
        'running',
        now(),
        now(),
        null,
        0,
        0,
        0,
        0,
        null
    )
    on conflict (source_date) do update
    set run_id = excluded.run_id,
        status = 'running',
        started_at = now(),
        heartbeat_at = now(),
        completed_at = null,
        total_profiles = 0,
        sent_count = 0,
        failed_count = 0,
        skipped_count = 0,
        last_error = null
    where (
        orchestration_runs.status = 'running'
        and orchestration_runs.heartbeat_at < p_stale_before
    ) or (
        p_retry_failed
        and orchestration_runs.status in ('failed', 'completed_with_errors')
    );

    get diagnostics affected_rows = row_count;
    return affected_rows = 1;
end;
$$;

revoke all on function public.claim_orchestration_run(
    date, uuid, timestamptz, boolean
) from public, anon, authenticated;
grant execute on function public.claim_orchestration_run(
    date, uuid, timestamptz, boolean
) to service_role;

-- Fence each delivery to the currently claimed run. A worker that wakes after
-- its lease was taken over cannot move delivery state back to its stale run_id.
create or replace function public.claim_orchestration_delivery(
    p_source_date date,
    p_run_id uuid,
    p_profile_id uuid,
    p_user_id uuid,
    p_profile_snapshot jsonb
) returns setof public.orchestration_deliveries
language plpgsql
security definer
set search_path = public
as $$
begin
    if not exists (
        select 1
        from public.orchestration_runs
        where source_date = p_source_date
          and run_id = p_run_id
          and status = 'running'
    ) then
        return;
    end if;

    insert into public.orchestration_deliveries (
        source_date, run_id, profile_id, user_id, profile_snapshot, status
    ) values (
        p_source_date, p_run_id, p_profile_id, p_user_id,
        p_profile_snapshot, 'pending'
    )
    on conflict (source_date, user_id) do update
    set run_id = excluded.run_id,
        profile_id = excluded.profile_id,
        updated_at = now()
    where orchestration_deliveries.status <> 'sent';

    return query
    select *
    from public.orchestration_deliveries
    where source_date = p_source_date
      and user_id = p_user_id;
end;
$$;

revoke all on function public.claim_orchestration_delivery(
    date, uuid, uuid, uuid, jsonb
) from public, anon, authenticated;
grant execute on function public.claim_orchestration_delivery(
    date, uuid, uuid, uuid, jsonb
) to service_role;

-- Profile linkage is part of the shared frontend contract. Fence it in the
-- same statement that verifies the active run so a stale worker cannot replace
-- a newer task_id/task_html after takeover.
create or replace function public.update_orchestration_profile(
    p_source_date date,
    p_run_id uuid,
    p_profile_id uuid,
    p_task_id text,
    p_html text default null
) returns boolean
language plpgsql
security definer
set search_path = public
as $$
begin
    if not exists (
        select 1
        from public.orchestration_runs
        where source_date = p_source_date
          and run_id = p_run_id
          and status = 'running'
    ) then
        return false;
    end if;

    if p_html is null then
        update public.profiles
        set task_id = p_task_id,
            started_at = now()
        where id = p_profile_id;
    else
        update public.profiles
        set task_id = p_task_id,
            task_html = p_html,
            completed_at = now()
        where id = p_profile_id;
    end if;

    return found;
end;
$$;

revoke all on function public.update_orchestration_profile(
    date, uuid, uuid, text, text
) from public, anon, authenticated;
grant execute on function public.update_orchestration_profile(
    date, uuid, uuid, text, text
) to service_role;
