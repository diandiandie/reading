# 后端接口草案

接口建议统一返回 JSON，认证方式可用 Cookie Session 或 JWT。部署给普通家庭使用时，推荐 Cookie Session + HTTPS，减少前端保存令牌的风险。

## 认证

### 注册

`POST /api/auth/register`

请求：

```json
{
  "phone": "13800000000",
  "password": "your_password",
  "familyName": "琪琪家",
  "parentName": "妈妈",
  "defaultChildName": "琪琪"
}
```

处理：

- 校验手机号未注册。
- 密码哈希后保存。
- 创建家庭、家长账号、家庭成员关系、默认孩子。
- 登录成功后返回当前家庭摘要。

### 登录

`POST /api/auth/login`

请求：

```json
{
  "phone": "13800000000",
  "password": "your_password"
}
```

### 退出

`POST /api/auth/logout`

### 当前登录态

`GET /api/me`

返回：

```json
{
  "user": { "id": "uuid", "phone": "13800000000", "displayName": "妈妈" },
  "family": { "id": "uuid", "name": "琪琪家" },
  "defaultChildId": "uuid"
}
```

## 孩子

`GET /api/children`

`POST /api/children`

```json
{
  "name": "小宇",
  "birthDate": "2017-09-01",
  "isDefault": true
}
```

`PATCH /api/children/:childId`

`POST /api/children/:childId/default`

## 读书计划

`GET /api/plans?childId=uuid&status=active`

`POST /api/plans`

```json
{
  "childId": "uuid",
  "title": "《窗边的小豆豆》共读",
  "bookName": "窗边的小豆豆",
  "targetCheckins": 21,
  "rewardPerCheckin": "2.00",
  "startDate": "2026-06-23",
  "endDate": "2026-07-14",
  "note": "每天阅读 20 分钟并记录一句感想。"
}
```

`PATCH /api/plans/:planId`

`POST /api/plans/:planId/complete`

## 打卡

`GET /api/checkins?childId=uuid&planId=uuid&from=2026-06-01&to=2026-06-30`

`POST /api/checkins`

建议使用 `multipart/form-data`，支持照片上传：

```text
childId=uuid
planId=uuid
checkinDate=2026-06-23
minutes=20
rewardAmount=2.00
note=今天主动复述了故事。
photos[]=file
```

服务端保存打卡后，把图片上传到对象存储，再写入 `checkin_photos`。

## 奖励

### 按孩子统计

`GET /api/rewards/children`

返回：

```json
[
  {
    "childId": "uuid",
    "childName": "琪琪",
    "earnedAmount": "42.00",
    "redeemedAmount": "20.00",
    "balanceAmount": "22.00",
    "redemptionCount": 2
  }
]
```

### 兑换记录

`GET /api/redemptions?childId=uuid`

`POST /api/redemptions`

```json
{
  "childId": "uuid",
  "redemptionDate": "2026-06-23",
  "amount": "10.00",
  "note": "兑换一本书"
}
```

服务端应校验兑换金额不能大于该孩子当前可兑换余额，除非业务允许透支。

## 看板

`GET /api/dashboard`

返回：

```json
{
  "activePlanCount": 2,
  "todayCheckinCount": 1,
  "totalCheckinCount": 12,
  "defaultChildRewardBalance": "22.00",
  "recentCheckins": []
}
```

## 权限要求

- 所有业务接口必须登录。
- 服务端根据登录用户查 `family_users`，得到 `current_family_id`。
- 所有查询、更新、删除都必须限制在 `current_family_id` 内。
- `childId`、`planId`、`checkinId`、`redemptionId` 都要二次校验属于当前家庭。
