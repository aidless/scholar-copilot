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

---

## 7. 微信真实回调网关（同日追加）

### 为什么
v1.2 的微信扫码登录只有 dev mock 一条路：`/wechat/mock-approve` 直接改库。
生产上走不通——真实链路是「微信服务器回调 → 验签 → 解析事件 → 推进扫码会话」。
本轮补上这条真实网关，**不需要真公众号即可实现并测试**：签名算法是公开的
sha1(字典序排序 [token,timestamp,nonce])，事件 XML 是我们自造的标准报文。

### 实现
- `backend/app/wechat.py`（纯计算，无网络无 DB，易测）：
  - `compute_signature(token, timestamp, nonce)` = `sha1("".join(sorted([token,ts,nonce])))`
  - `verify_signature(...)` 用 `hmac.compare_digest` 常数时间比对
  - `parse_event(xml_bytes)` → 扁平 dict（to_user/from_user/msg_type/event/event_key/content/msg_id），解析失败抛 `ValueError`
  - `extract_scene(event_key)`：`qrscene_abc` → `abc`
- `backend/app/routers/auth.py` 新增 3 端点：
  - `GET /auth/wechat/callback?signature&timestamp&nonce&echostr`：URL 校验握手，验签通过原样回 `echostr`（纯文本）
  - `POST /auth/wechat/callback?...`：接收事件推送，验签 → 解析 → 扫码事件（subscribe/SCAN）把对应 scene 从 `pending` 转 `scanned` 并记 `openid`；若该 openid 已绑定用户则直接 `confirmed`；恒回 `"success"`
  - `POST /auth/wechat/complete`：扫码后完成登录（用手机号建号/找号 + 绑定 openid + 确认会话，返回 token）
- 模型/迁移：`users.wechat_openid`（唯一，扫码绑定后免密登录）、`wechat_scenes.openid`；alembic `a7c1e2d4f6b8`（revises `ff5854424543`）；`deploy/init.sql` 同步
- 配置：`SC_WECHAT_TOKEN`（未配置时回调端点 503，不静默）

### 安全要点
- 未配 Token / 签名不符 → **一律 403**，不给探测者任何差分（谁都能打这个公网回调，必须先把门关死）
- 事件 XML 视为不可信输入：ElementTree 默认不展开外部实体，且我们不调用任何加载外部 DTD 的接口；解析失败 → 400
- 只处理 `pending` 状态的 scene（重复事件幂等，不会覆盖已确认会话）

### 测试（`backend/tests/test_wechat_callback.py`，14 项）
- 纯函数 5 项：签名与官方算法一致 / 验签 true·false / extract_scene 前缀剥离 / parse_event 字段 / 坏 XML 抛错
- 路由 9 项：URL 校验回 echostr / 签名错 403 / 未配 Token 503 / 事件签名错 403 / 扫码事件 → scanned / complete 建号绑定 → confirmed / **已绑定 openid 二次扫码自动登录** / 手机号非法 422 / scene 不存在 404
- **RED→GREEN 反证**：把 `verify_signature` 改成恒 `return True` → 3 项签名相关测试变红（`test_verify_signature_true_and_false` / `test_callback_get_bad_signature_403` / `test_event_scan_bad_signature_403`）；恢复后 14 项全绿。

### 测试数
全套 `pytest` = **121 passed**（107 + 微信 14；openapi 一致性门 5 项本就存在，新增 3 个端点只需重导出规格，用例数不变，重导出后 5 项仍全绿）。

---

## 8. 导出 LaTeX 编译服务化（同日追加）

### 为什么
v1.3 起 `format=tex` 只能产出 `.tex` 源文件，用户还得自己在本地装 TeX 编译；
`format=pdf` 走的是 docx→LibreOffice 路线。本轮补一条 **LaTeX 直接编译成 PDF** 的通道。

### 实现
- `backend/app/export/pdf.py` 新增 `tex_bytes_to_pdf(tex_bytes, timeout=300)`：
  - 引擎探测 `xelatex` → `lualatex` → `pdflatex`（中文用 ctex，优先 xelatex）
  - 临时目录写 `thesis.tex`，**编译两遍**解析交叉引用/目录；`-interaction=nonstopmode -halt-on-error` 防卡交互
  - 第一遍失败且无 PDF → 抛 `RuntimeError` 带 TeX 日志尾部 400 字符；无引擎 → 抛 `RuntimeError("本机未安装 TeX 发行版…")`
- `backend/app/routers/writing.py` 导出端点 `format` 白名单从 `^(docx|pdf|tex)$` 扩到 `^(docx|pdf|tex|latexpdf)$`；
  `latexpdf` 分支 = `build_thesis_tex(...)` → `tex_bytes_to_pdf(...)`，`RuntimeError` → HTTP 502（文案提示改用 tex/docx）。
- CI（`.github/workflows/ci.yml`）后端 job 的依赖安装段从「LibreOffice」扩成「LibreOffice + TeX」：
  追加 `texlive-xetex texlive-lang-chinese texlive-latex-recommended`，让 `test_tex_real_compile` 在 CI 真实编译而非 skip。

### 测试（`backend/tests/test_latex_compile.py`，5 项：4 跑 + 1 skip）
- `test_no_engine_raises`：无引擎 → `RuntimeError` 且文案含「未安装 TeX」（**强断言**，不接受「LaTeX 编译失败」这条分支蒙混）
- `test_engine_success_writes_and_returns_pdf`：monkeypatch 引擎存在 + 假 subprocess 写出 `thesis.pdf` → 返回 `%PDF-1.5` 字节
- `test_engine_fail_no_pdf_raises`：引擎返回码非 0 且无产物 → `RuntimeError("LaTeX 编译失败…")`
- `test_export_latexpdf_502_when_no_tex`：完整订单（下单→大纲→支付→逐章）导出 `format=latexpdf`，本机无 TeX → HTTP 502 且 detail 含「未安装 TeX」
- `test_tex_real_compile`（`skipif` 无 TeX）：真实 ctexart 编译产出 `%PDF`；本机 skip，CI 装 texlive 后执行
- **RED→GREEN 反证**：把 `if not engine: raise RuntimeError("未安装 TeX…")` 改成 `engine="/bin/true"` → `test_no_engine_raises` 与 `test_export_latexpdf_502_when_no_tex` 两项变红（证明断言真能区分「未安装」与「编译失败」两个分支）；恢复后全绿。

### 未验证项
- 本机无 TeX 发行版，真实编译只在 CI（装 texlive 后）执行；复杂模板（多级目录、大量交叉引用、参考文献 bibtex）未压测，当前只编译正文+披露表+免责声明的单文件。
