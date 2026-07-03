# 灵镜管理台设计文档

> 日期：2026-06-17
> 状态：已批准

## 概述

灵镜管理台是一个独立的Electron桌面应用，用于远程管理灵枢云端数据。采用**密钥文件 + 账号密码双重认证**机制，确保只有持有合法密钥文件的管理员才能访问后台。

## 架构

```
灵镜管理台 (Electron exe)
  ├── Vue3 + Element Plus (管理界面)
  ├── preload.js (密钥管理 + HMAC签名)
  └── Electron safeStorage (密钥加密存储)
        │
        │ HTTPS
        ▼
远程服务器 (120.27.202.2)
  ├── Nginx (80 → 127.0.0.1:8787)
  ├── FastAPI 后端 (HMAC验证 + 管理API)
  └── SQLite (admin_keys + admin_users + admin_auth_tokens)
```

## 密钥文件机制

### 格式 (.lingshu-key)

```json
{
  "key_id": "ak_xxxxxxxx",
  "secret": "base64编码的32字节随机密钥",
  "issued_to": "管理员用户名",
  "issued_at": "2026-06-17T12:00:00Z",
  "server_host": "120.27.202.2"
}
```

### 生命周期

1. **颁发**：服务器生成密钥 → 导出 `.lingshu-key` 文件 → 安全渠道分发
2. **使用**：管理员在灵镜中导入密钥 → safeStorage加密存储 → 每次请求计算HMAC签名
3. **吊销**：服务器删除 admin_keys 记录 → 密钥立即失效

## 双重认证流程

### 登录

1. 管理员导入密钥文件（首次）或使用已存储的密钥
2. 客户端用密钥secret对 `timestamp` 做HMAC-SHA256
3. 发送 `{key_id, timestamp, hmac, username, password}` 到 `/api/admin/auth/login`
4. 服务器验证：HMAC签名 → 密码 → 返回token

### 后续请求

每个API请求携带：
- `Authorization: Bearer <token>`
- `X-Client-Sig: HMAC-SHA256(secret, timestamp + method + path)`
- `X-Client-Ts: <timestamp>`

服务器同时验证token和签名。

## 服务器端数据库

```sql
CREATE TABLE admin_keys (
    key_id TEXT PRIMARY KEY,
    admin_user_id INTEGER NOT NULL,
    secret_encrypted TEXT NOT NULL,     -- AES加密的密钥明文
    key_fingerprint TEXT NOT NULL,      -- 密钥指纹
    status TEXT NOT NULL DEFAULT 'active',
    issued_at TEXT NOT NULL,
    last_used_at TEXT,
    expires_at TEXT,
    FOREIGN KEY (admin_user_id) REFERENCES admin_users(id)
);
```

服务器主密钥通过环境变量 `ADMIN_MASTER_KEY` 注入，用于AES加解密密钥。

## 灵镜Electron应用结构

```
lingjing-app/
├── electron/
│   ├── main.js          # 主进程（不启动本地后端，连接远程）
│   ├── preload.js       # 密钥管理 + HMAC签名 + safeStorage
│   └── splash.html
├── src/
│   ├── App.vue          # 管理台界面（复用cloud-admin）
│   ├── main.ts
│   └── styles.css
├── package.json         # appId: com.lingshu.admin
├── vite.config.ts
└── electron-builder.yml
```

### 与灵枢主程序的区别

| 项目 | 灵枢 | 灵镜 |
|---|---|---|
| 后端 | 启动本地Python | 连接远程服务器 |
| 认证 | 用户token | 密钥文件 + 管理员token + HMAC签名 |
| 打包 | com.lingshu.app | com.lingshu.admin |
| 功能 | 写作工具 | 后台管理 |

## 安全特性

- 密钥文件不通过网络传输（只传HMAC签名）
- 密钥文件用Electron safeStorage加密存储在本地
- 服务器端密钥AES加密存储
- 密钥可吊销、可设过期时间
- 登录5次失败锁定15分钟
- API文档已禁用
- 安全响应头已添加
- 8787端口已封堵公网访问

## 实现步骤

1. 创建 lingjing-app Electron项目骨架
2. 复用cloud-admin前端代码
3. 实现preload.js密钥管理
4. 实现服务器端admin_keys表和HMAC验证
5. 修改登录流程支持双重认证
6. 打包测试
