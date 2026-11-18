-- 사용자 분석 기록 삭제 및 프로필 민감정보 초기화 RPC 생성
-- * 계정 탈퇴가 아닌, 서비스 내 수집 데이터(기록 및 동의/식단 정보)만 초기화합니다.
begin;

alter table profiles
  add column if not exists consented_at timestamptz,
  add column if not exists consent_version varchar(20);

drop policy if exists "scan_logs_delete_own" on scan_logs;
create policy "scan_logs_delete_own"
  on scan_logs for delete
  using (profile_id in (select id from profiles where user_id = auth.uid()));

create or replace function delete_my_data()
returns int
language plpgsql
security invoker
set search_path = public
as $$
declare
  n int;
begin
  delete from scan_logs
   where profile_id in (select id from profiles where user_id = auth.uid());
  get diagnostics n = row_count;

  update profiles
     set allergies = null, religious_diet = null, vegetarian_type = null,
         consented_at = null, consent_version = null
   where user_id = auth.uid();

  return n;
end;
$$;

revoke all on function delete_my_data() from public, anon;
grant execute on function delete_my_data() to authenticated;

commit;