# 部署前清单

## 必做改造

- 把 `localStorage` 数据替换为后端接口。
- 使用服务端注册、登录和退出接口。
- 密码必须使用 `bcrypt`、`argon2` 等算法哈希保存，不能明文保存。
- 所有页面和接口使用 HTTPS。
- 照片上传接入对象存储，例如 S3、OSS、COS 或服务器本地受控目录。
- 限制上传文件类型、大小和数量，例如单张不超过 5MB，每次打卡最多 4 张。
- 服务端按登录账号解析 `family_id`，禁止前端自行指定家庭权限。

## 推荐技术方案

轻量部署方案：

- 前端：当前 HTML 拆分为普通静态页面，或迁移到 Vue / React。
- 后端：Node.js + Express / NestJS，或 Python FastAPI。
- 数据库：PostgreSQL。
- 图片：对象存储。
- 反向代理：Nginx。
- 进程管理：PM2、systemd 或 Docker Compose。

小规模家庭用户也可以先用：

- 后端：Node.js + Express。
- 数据库：SQLite 或 PostgreSQL。
- 图片：服务器本地目录。

后续用户增长后再迁移对象存储和 PostgreSQL。

## 环境变量

```text
APP_ENV=production
APP_BASE_URL=https://your-domain.example
DATABASE_URL=postgres://user:password@host:5432/reading
SESSION_SECRET=replace-with-long-random-string
UPLOAD_PROVIDER=local
UPLOAD_DIR=/var/www/reading/uploads
MAX_UPLOAD_MB=5
```

## 安全检查

- 登录接口限制错误次数，防止手机号密码暴力尝试。
- 注册接口增加验证码或短信校验，防止被批量注册。
- 图片上传需要校验 MIME 类型和真实文件头。
- 后端返回错误信息要克制，不泄露数据库、文件路径或堆栈。
- 数据库定期备份，至少每日一次。
- 管理后台如后续增加，需要单独角色和权限。

## 上线前验收

- 新手机号可以注册并进入家庭空间。
- 已注册手机号可以登录，错误密码不能登录。
- 添加多个孩子后，可以设置默认孩子。
- 为不同孩子创建计划后，打卡记录不会混到其他孩子。
- 奖励统计按孩子分别展示，兑换只扣对应孩子余额。
- 照片上传后刷新页面仍能显示。
- 退出登录后不能访问家庭数据接口。
- 两个不同家庭账号互相看不到数据。

## 迁移当前原型

当前文件 [reading-checkin.html](../reading-checkin.html) 可以继续作为产品原型使用。迁移到服务端时，建议按这个顺序：

1. 先实现认证、家庭、孩子接口。
2. 再实现计划和打卡接口。
3. 接入照片上传。
4. 实现奖励统计和兑换接口。
5. 把前端 `localStorage` 调用替换为 `fetch` 请求。
6. 做跨家庭数据隔离测试。
