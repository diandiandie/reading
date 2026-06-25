# 数据库设计

使用 MySQL 8.0+。字段类型已按 MySQL 语法调整。

## 核心原则

- 所有业务数据都必须带 `family_id`，服务端查询时始终追加当前登录账号所属家庭条件。
- 奖励金额按孩子统计，打卡奖励和兑换流水都绑定 `child_id`。
- 图片文件不直接存数据库，数据库只保存文件路径和元信息，图片保存在服务器本地目录。
- 金额使用 `decimal(10,2)`，不使用浮点数。
- 删除建议先做软删除（status='deleted'），避免误删孩子历史打卡和奖励流水。打卡记录和兑换记录使用物理删除。

## 数据库配置

```text
host: localhost
port: 3306
database: reading
user: root
password: YOUR_PASSWORD
charset: utf8mb4
```

连接字符串：`mysql+pymysql://root:YOUR_PASSWORD@localhost:3306/reading?charset=utf8mb4`

## 表结构

```sql
CREATE TABLE families (
  id VARCHAR(36) PRIMARY KEY,
  name VARCHAR(80) NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'active',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE users (
  id VARCHAR(36) PRIMARY KEY,
  phone VARCHAR(20) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,
  display_name VARCHAR(40) NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'active',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_users_phone (phone)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE family_users (
  id VARCHAR(36) PRIMARY KEY,
  family_id VARCHAR(36) NOT NULL,
  user_id VARCHAR(36) NOT NULL,
  role VARCHAR(20) NOT NULL DEFAULT 'parent',
  is_primary BOOLEAN NOT NULL DEFAULT FALSE,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uk_family_user (family_id, user_id),
  FOREIGN KEY (family_id) REFERENCES families(id),
  FOREIGN KEY (user_id) REFERENCES users(id),
  INDEX idx_family_users_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE children (
  id VARCHAR(36) PRIMARY KEY,
  family_id VARCHAR(36) NOT NULL,
  name VARCHAR(40) NOT NULL,
  avatar_url TEXT,
  birth_date DATE,
  is_default BOOLEAN NOT NULL DEFAULT FALSE,
  status VARCHAR(20) NOT NULL DEFAULT 'active',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  FOREIGN KEY (family_id) REFERENCES families(id),
  INDEX idx_children_family (family_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE reading_plans (
  id VARCHAR(36) PRIMARY KEY,
  family_id VARCHAR(36) NOT NULL,
  child_id VARCHAR(36) NOT NULL,
  title VARCHAR(120) NOT NULL,
  book_name VARCHAR(120),
  target_checkins INT NOT NULL DEFAULT 21,
  reward_per_checkin DECIMAL(10,2) NOT NULL DEFAULT 0,
  start_date DATE,
  end_date DATE,
  status VARCHAR(20) NOT NULL DEFAULT 'active',  -- active, completed, deleted
  note TEXT,
  created_by VARCHAR(36),
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  FOREIGN KEY (family_id) REFERENCES families(id),
  FOREIGN KEY (child_id) REFERENCES children(id),
  FOREIGN KEY (created_by) REFERENCES users(id),
  INDEX idx_plans_family_child (family_id, child_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE reading_checkins (
  id VARCHAR(36) PRIMARY KEY,
  family_id VARCHAR(36) NOT NULL,
  child_id VARCHAR(36) NOT NULL,
  plan_id VARCHAR(36) NOT NULL,
  checkin_date DATE NOT NULL,
  minutes INT NOT NULL DEFAULT 0,
  reward_amount DECIMAL(10,2) NOT NULL DEFAULT 0,
  note TEXT,
  created_by VARCHAR(36),
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  FOREIGN KEY (family_id) REFERENCES families(id),
  FOREIGN KEY (child_id) REFERENCES children(id),
  FOREIGN KEY (plan_id) REFERENCES reading_plans(id),
  FOREIGN KEY (created_by) REFERENCES users(id),
  INDEX idx_checkins_family_child_date (family_id, child_id, checkin_date DESC),
  INDEX idx_checkins_plan (plan_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE checkin_photos (
  id VARCHAR(36) PRIMARY KEY,
  family_id VARCHAR(36) NOT NULL,
  checkin_id VARCHAR(36) NOT NULL,
  file_url TEXT NOT NULL,
  object_key TEXT NOT NULL,
  mime_type VARCHAR(80),
  file_size INT,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (family_id) REFERENCES families(id),
  FOREIGN KEY (checkin_id) REFERENCES reading_checkins(id) ON DELETE CASCADE,
  INDEX idx_photos_checkin (checkin_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE reward_redemptions (
  id VARCHAR(36) PRIMARY KEY,
  family_id VARCHAR(36) NOT NULL,
  child_id VARCHAR(36) NOT NULL,
  redemption_date DATE NOT NULL,
  amount DECIMAL(10,2) NOT NULL,
  note TEXT,
  created_by VARCHAR(36),
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (family_id) REFERENCES families(id),
  FOREIGN KEY (child_id) REFERENCES children(id),
  FOREIGN KEY (created_by) REFERENCES users(id),
  INDEX idx_redemptions_family_child_date (family_id, child_id, redemption_date DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

## 奖励统计 SQL

单个孩子奖励余额：

```sql
SELECT
  c.id AS child_id,
  c.name AS child_name,
  COALESCE(SUM(rc.reward_amount), 0) AS earned_amount,
  COALESCE((
    SELECT SUM(rr.amount)
    FROM reward_redemptions rr
    WHERE rr.family_id = c.family_id
      AND rr.child_id = c.id
  ), 0) AS redeemed_amount,
  COALESCE(SUM(rc.reward_amount), 0) - COALESCE((
    SELECT SUM(rr.amount)
    FROM reward_redemptions rr
    WHERE rr.family_id = c.family_id
      AND rr.child_id = c.id
  ), 0) AS balance_amount
FROM children c
LEFT JOIN reading_checkins rc
  ON rc.family_id = c.family_id
 AND rc.child_id = c.id
WHERE c.family_id = :family_id
  AND c.status = 'active'
GROUP BY c.id, c.name, c.family_id
ORDER BY c.created_at;
```

## 数据隔离校验

服务端每个接口都应从登录态得到 `user_id`，再通过 `family_users` 得到允许访问的 `family_id`。不要相信前端传来的 `family_id`。

例如更新计划时：

```sql
UPDATE reading_plans
SET title = :title,
    book_name = :book_name,
    updated_at = NOW()
WHERE id = :plan_id
  AND family_id = :current_family_id;
```
# 数据库设计

推荐使用 PostgreSQL 或 MySQL。下面以 PostgreSQL 语法描述，字段类型可按实际数据库调整。

## 核心原则

- 所有业务数据都必须带 `family_id`，服务端查询时始终追加当前登录账号所属家庭条件。
- 奖励金额按孩子统计，打卡奖励和兑换流水都绑定 `child_id`。
- 图片文件不建议直接存数据库，数据库只保存对象存储地址、文件 key 和元信息。
- 金额使用 `decimal(10,2)`，不要使用浮点数。
- 删除建议先做软删除，避免误删孩子历史打卡和奖励流水。

## 表结构

```sql
create table families (
  id uuid primary key,
  name varchar(80) not null,
  status varchar(20) not null default 'active',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table users (
  id uuid primary key,
  phone varchar(20) not null unique,
  password_hash varchar(255) not null,
  display_name varchar(40) not null,
  status varchar(20) not null default 'active',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table family_users (
  id uuid primary key,
  family_id uuid not null references families(id),
  user_id uuid not null references users(id),
  role varchar(20) not null default 'parent',
  is_primary boolean not null default false,
  created_at timestamptz not null default now(),
  unique (family_id, user_id)
);

create table children (
  id uuid primary key,
  family_id uuid not null references families(id),
  name varchar(40) not null,
  avatar_url text,
  birth_date date,
  is_default boolean not null default false,
  status varchar(20) not null default 'active',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table reading_plans (
  id uuid primary key,
  family_id uuid not null references families(id),
  child_id uuid not null references children(id),
  title varchar(120) not null,
  book_name varchar(120),
  target_checkins integer not null default 21,
  reward_per_checkin decimal(10,2) not null default 0,
  start_date date,
  end_date date,
  status varchar(20) not null default 'active',
  note text,
  created_by uuid references users(id),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table reading_checkins (
  id uuid primary key,
  family_id uuid not null references families(id),
  child_id uuid not null references children(id),
  plan_id uuid not null references reading_plans(id),
  checkin_date date not null,
  minutes integer not null default 0,
  reward_amount decimal(10,2) not null default 0,
  note text,
  created_by uuid references users(id),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table checkin_photos (
  id uuid primary key,
  family_id uuid not null references families(id),
  checkin_id uuid not null references reading_checkins(id) on delete cascade,
  file_url text not null,
  object_key text not null,
  mime_type varchar(80),
  file_size integer,
  created_at timestamptz not null default now()
);

create table reward_redemptions (
  id uuid primary key,
  family_id uuid not null references families(id),
  child_id uuid not null references children(id),
  redemption_date date not null,
  amount decimal(10,2) not null,
  note text,
  created_by uuid references users(id),
  created_at timestamptz not null default now()
);
```

## 推荐索引

```sql
create index idx_family_users_user on family_users(user_id);
create index idx_children_family on children(family_id, status);
create index idx_plans_family_child on reading_plans(family_id, child_id, status);
create index idx_checkins_family_child_date on reading_checkins(family_id, child_id, checkin_date desc);
create index idx_checkins_plan on reading_checkins(plan_id);
create index idx_photos_checkin on checkin_photos(checkin_id);
create index idx_redemptions_family_child_date on reward_redemptions(family_id, child_id, redemption_date desc);
```

## 奖励统计 SQL

单个孩子奖励余额：

```sql
select
  c.id as child_id,
  c.name as child_name,
  coalesce(sum(rc.reward_amount), 0) as earned_amount,
  coalesce((
    select sum(rr.amount)
    from reward_redemptions rr
    where rr.family_id = c.family_id
      and rr.child_id = c.id
  ), 0) as redeemed_amount,
  coalesce(sum(rc.reward_amount), 0) - coalesce((
    select sum(rr.amount)
    from reward_redemptions rr
    where rr.family_id = c.family_id
      and rr.child_id = c.id
  ), 0) as balance_amount
from children c
left join reading_checkins rc
  on rc.family_id = c.family_id
 and rc.child_id = c.id
where c.family_id = :family_id
  and c.status = 'active'
group by c.id, c.name, c.family_id
order by c.created_at;
```

## 数据隔离校验

服务端每个接口都应从登录态得到 `user_id`，再通过 `family_users` 得到允许访问的 `family_id`。不要相信前端传来的 `family_id`。

例如更新计划时：

```sql
update reading_plans
set title = :title,
    book_name = :book_name,
    updated_at = now()
where id = :plan_id
  and family_id = :current_family_id;
```
