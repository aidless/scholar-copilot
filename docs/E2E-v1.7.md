# E2E v1.7 — 运营日报邮件通道

> 目标：日报推送此前只有 webhook 一条通道。很多自部署场合没有 IM 机器人，
> 但有现成 SMTP（企业邮/自建邮局），缺邮件通道等于日报功能默认用不上。
> 本轮补上邮件通道，并刻意验证「发信失败不会把 cron 拖垮」。

## 1. 设计

- **通道二选一，webhook 优先**：`SC_REPORT_WEBHOOK_URL` 非空 → POST webhook；
  否则 `SC_REPORT_EMAIL_TO` 非空 → SMTP 发邮件；都空 → `{"pushed": false, "reason": "no_channel_configured"}`。
- **口径仍单一真相源**：两个通道都先 `await summary(db, days)`（与
  `/admin/reports/summary` 同源），再 `format_text()` 渲染，绝不各写一遍 SQL。
- **失败软返回**：SMTP 连不上/认证失败 → `{"pushed": false, "channel": "email", "error": ...}`，
  不抛异常，避免 arq cron 到点反复记 error 日志刷屏。
- **配置项**（`backend/app/config.py`，全部 `SC_` 前缀）：
  `report_email_to` / `smtp_host` / `smtp_port`(587) / `smtp_user` / `smtp_password`
  / `smtp_from`（空则用 smtp_user）/ `smtp_starttls`(true) / `smtp_ssl`(false)。
- **实现要点**：`smtplib` 是阻塞库，放进 `asyncio.to_thread(_send_email_sync, text)`，
  不阻塞事件循环；`_build_email` 用 `EmailMessage` + `formataddr`，纯文本正文（UTF-8）。

## 2. 代码

- `backend/app/tasks/report.py`：
  - `_chosen_channel()` → `webhook` / `email` / `none`
  - `_build_email(text)` → `EmailMessage`（Subject=「Scholar Copilot 运营日报」，From 用 `formataddr`，To=收件人串）
  - `_send_email_sync(text)` → 建 SMTP/SSL 连接、可选 `starttls`、可选 `login`，`send_message`，`finally: quit()` 吞退出异常；返回收件人数
  - `push_daily_report()` 先判 `report_push_enabled`，再按 `_chosen_channel()` 分派

## 3. 启动自检（`backend/app/diagnostics.py`）

新增两条「配置看起来开了、实际发不出去」的启动警告：
- `SC_REPORT_PUSH_ENABLED=true` 但 webhook/邮箱都没配 → 「日报定时任务会空跑不发」
- 走邮件但 `SC_SMTP_HOST` 为空 → 「cron 到点会发信失败」

## 4. 测试

`backend/tests/test_report_push.py` 原有 6 项 + 新增 5 项：
1. `test_email_channel_selected_when_no_webhook`：webhook 空 + 有收件人 → 走 email，且**不碰 httpx**
2. `test_webhook_takes_priority_over_email`：两者都配 → webhook 优先，邮件函数不得被调
3. `test_email_failure_is_soft`：`_send_email_sync` 抛错 → `pushed=false`、`channel=email`、error 带原因
4. `test_build_email_headers`：Subject/From/To 正确（To 去空格比对，因 `EmailMessage` 会规范化逗号后空格）
5. `test_send_email_sync_requires_host`：无 `SC_SMTP_HOST` → 抛 `RuntimeError("SC_SMTP_HOST 未配置")`

`backend/tests/test_diagnostics.py` 新增 4 项（空跑告警 / 邮件缺 SMTP 告警 / 邮件配置完整不告警 / webhook 配置不告警）。

**RED→GREEN 反证**（按 AGENTS.md 第 21 条）：
- 邮件通道：把 `_chosen_channel` 的 email 分支去掉 → `test_email_channel_selected_when_no_webhook`、`test_webhook_takes_priority_over_email` 变红。
- diagnostics：用正则删掉 `if s.report_push_enabled:` 整块 → `test_report_push_enabled_without_channel_warns`、`test_report_email_channel_without_smtp_host_warns` 2 项变红；恢复后 19 项全绿（实测输出：`2 failed, 17 passed` → `19 passed`）。

## 5. 真网络实测（假 SMTP 服务器收信）

本机起一个最小 SMTP 服务器 `/tmp/fake_smtp.py`（socket 手写 EHLO/MAIL/RCPT/DATA 状态机，监听 127.0.0.1:18925），
再用环境变量把后端指向它跑 `push_daily_report()`：

```
SC_REPORT_PUSH_ENABLED=true  SC_REPORT_WEBHOOK_URL=（空）
SC_REPORT_EMAIL_TO=ops@example.com,lead@example.com
SC_SMTP_HOST=127.0.0.1  SC_SMTP_PORT=18925  SC_SMTP_STARTTLS=false
```

结果：
```
RESULT: {'pushed': True, 'channel': 'email', 'recipients': 2}
TEXT: Scholar Copilot 运营日报（近 1 天）/收入 ¥0.00 ｜ 新订单 0 ｜ 新用户 0/生成任务 无/Token 用量 in=0 out=0
```
假服务器收到 1 封，头部解析正确：
```
Subject: Scholar Copilot =?utf-8?b?6L+Q6JCl5pel5oql?=     （= 运营日报，RFC2047 编码正常）
From: Scholar Copilot <发件人>
To: ops@example.com,lead@example.com
Content-Type: text/plain; charset="utf-8"
（正文：三行，收入/新单/新用户一行、生成任务一行、Token 一行）
```

## 6. 未验证项（如实）
- 真实公网 SMTP（QQ 企业邮/阿里云 DirectMail/Gmail 应用专用密码）未逐家实测——
  只验了协议层（STARTTLS/SSL/login 分支按参数走），生产接入需用户自备账号。
- 附件/HTML 正文未做（当前纯文本，满足 IM/邮件告警场景）。
- 大批量收件人（>10）的收信方限流未压测。
