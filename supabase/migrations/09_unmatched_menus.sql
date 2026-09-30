-- [제안] 미매칭 메뉴 수집 테이블 (현재는 app/data/unmatched_menus.json 파일로 운영)
-- 여러 사용자가 쓰는 배포 환경에서 수집을 모으려면 이 테이블로 옮긴다.
create table if not exists unmatched_menus (
  id uuid primary key default gen_random_uuid(),
  name text unique not null,
  hit_count int not null default 1,
  status varchar(20) not null default '대기',   -- 대기 | 검수중 | DB 추가됨 | 제외
  first_seen timestamptz default now(),
  last_seen timestamptz default now()
);

alter table unmatched_menus enable row level security;
create policy "unmatched_insert_any" on unmatched_menus for insert with check (true);
create policy "unmatched_read_any" on unmatched_menus for select using (true);
