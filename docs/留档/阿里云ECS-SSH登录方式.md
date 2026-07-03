# 阿里云 ECS SSH 登录方式

> 用途：记录 Codex 连接灵枢云端服务器的 SSH 登录方式，避免后续忘记公网 IP、用户名、私钥路径和排错步骤。
> 注意：本文只记录私钥文件路径和公钥授权方式，不记录私钥内容。

## 服务器信息

| 项 | 值 |
|---|---|
| 公网 IP | `120.27.202.2` |
| 内网 IP | `172.20.127.26` |
| 日常登录用户 | `CODEX` |
| 私钥路径 | `C:\Users\26455\Desktop\密钥\id_rsa` |
| 系统 | Alibaba Cloud Linux 3.2104 LTS |

`172.20.127.26` 是内网 IP，只有在同一 VPC、VPN、堡垒机或阿里云内网环境中才可访问。普通本机直连应使用公网 IP `120.27.202.2`。

## 常用登录命令

日常使用 `CODEX` 用户登录：

```powershell
ssh -i "C:\Users\26455\Desktop\密钥\id_rsa" CODEX@120.27.202.2
```

如需维护系统服务、安装依赖、查看 systemd：

```powershell
ssh -i "C:\Users\26455\Desktop\密钥\id_rsa" root@120.27.202.2
```

Codex 自动化命令建议加上超时和 known_hosts 文件：

```powershell
ssh -i "C:\Users\26455\Desktop\密钥\id_rsa" `
  -o BatchMode=yes `
  -o ConnectTimeout=15 `
  -o StrictHostKeyChecking=accept-new `
  -o UserKnownHostsFile="F:\项目\灵枢\.codex-runtime\ssh_known_hosts" `
  CODEX@120.27.202.2 "whoami && hostname && uname -a"
```

## 私钥权限修复

Windows OpenSSH 如果提示：

```text
WARNING: UNPROTECTED PRIVATE KEY FILE!
Permissions are too open.
```

在 PowerShell 中执行：

```powershell
$path = "C:\Users\26455\Desktop\密钥\id_rsa"
icacls $path /inheritance:r
icacls $path /grant:r "$env:USERNAME`:R"
icacls $path
```

期望结果类似：

```text
C:\Users\26455\Desktop\密钥\id_rsa 天选姬\26455:(R)
```

## CODEX 用户公钥授权修复

如果 `root` 能登录，但 `CODEX` 登录失败：

```text
Permission denied (publickey,...)
```

通常是 `/home/CODEX/.ssh` 权限或属主不对。先在本机导出公钥：

```powershell
ssh-keygen -y -f "C:\Users\26455\Desktop\密钥\id_rsa"
```

然后用 root 把公钥写入 `CODEX`：

```bash
install -d -m 700 -o CODEX -g CODEX /home/CODEX/.ssh
touch /home/CODEX/.ssh/authorized_keys
# 将公钥追加到 authorized_keys
chown -R CODEX:CODEX /home/CODEX/.ssh
chmod 700 /home/CODEX/.ssh
chmod 600 /home/CODEX/.ssh/authorized_keys
```

正确权限应为：

```text
drwx------ CODEX CODEX /home/CODEX/.ssh
-rw------- CODEX CODEX /home/CODEX/.ssh/authorized_keys
```

## 连通性排查

检查 22 端口：

```powershell
Test-NetConnection -ComputerName 120.27.202.2 -Port 22 -InformationLevel Detailed
```

常见结果：

| 现象 | 原因 | 处理 |
|---|---|---|
| `Connection timed out` | 安全组未放行、IP 写成内网 IP、服务器未开机 | 检查公网 IP、安全组 TCP 22、ECS 状态。 |
| `Permission denied (publickey)` | 公钥未绑定到目标用户或 `.ssh` 权限错误 | 重新绑定密钥对，或修复 `authorized_keys`。 |
| `UNPROTECTED PRIVATE KEY FILE` | 本机私钥 ACL 太开放 | 用 `icacls` 收紧权限。 |
| root 可登录，CODEX 不行 | CODEX 用户公钥/权限错误 | 修复 `/home/CODEX/.ssh` 属主和权限。 |

## 当前确认状态

已确认以下命令可登录：

```powershell
ssh -i "C:\Users\26455\Desktop\密钥\id_rsa" CODEX@120.27.202.2 "whoami && pwd"
```

返回：

```text
CODEX
/home/CODEX
```

