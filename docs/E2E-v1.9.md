# E2E 验证记录 · v1.9（产品线 + 工程：多文体 / 版本回滚 / 摘要 / 文件上传对象存储）

> 目的：把清单里的产品线缺口（多文体、大纲版本回滚与章节重排、摘要生成）与工程缺口（文件上传 + 对象存储）补成真的，每项留可复算证据。

## 1. 多文体（#5 writing_type）

**问题**：系统只支持一种「毕业论文」文体，`writing_orders` 无 `writing_type`，大纲/正文 prompt 全是单一模板。

**改后**：
- 新文件 `backend/app/writing/genres.py`——`GENRES` 六键，每键 `label/outline_hint/writing_hint`：
  | key | label | 结构要点（outline_hint 摘要） |
  |---|---|---|
  | `thesis` | 毕业论文 | 绪论/文献综述/研究方法/结果分析/结论 |
  | `literature_review` | 文献综述 | 引言/主题分块综述/争议与空白/结论 |
  | `proposal` | 开题报告 | 选题背景/研究问题/方法路线/进度与可行性 |
  | `journal_article` | 期刊论文 | Abstract/Intro/Method/Results/Discussion |
  | `task_book` | 任务书 | 任务目标/内容与要求/进度安排/参考资料 |
  | `course_paper` | 课程论文 | 引言/理论基础/分析/小结 |
- `outline_prompts.build_outline_user_prompt(...)` 新增 `writing_type/genre_label/genre_hint`，非空时注入「文体类型 / 文体结构要求」段。
- `tasks/local.py::_run_outline` 传 `order.writing_type`（`getattr` 兜底，兼容旧数据）。
- `create_order` 校验 `genres.is_valid(body.writing_type)`，非法 422；默认 `thesis`（`DEFAULT_WRITING_TYPE`）。

**测试** `backend/tests/test_genres.py` **5 passed**：六键有效/非法键/默认值/outline_hint 注入到 prompt/未知文体下单 422。

## 2. 大纲版本回滚 + 章节重排/删除（#11）

**问题**：`GET /orders/{id}/outline` 只返最新版本；大纲被重新生成后旧版本不可恢复；章节只能改不能重排/删。

**改后**（`backend/app/routers/writing.py`）：
- `GET /orders/{id}/outline/versions` → `[{version, created_at}]`
- `GET /orders/{id}/outline/versions/{version}` → 指定版本（不存在 404）
- `POST /orders/{id}/outline/rollback` body `RollbackIn{version}`，`?rebuild_chapters=true` 时按目标大纲重建章节：**append-only**——不删除历史版本，新增 `version = max+1` 复制目标版本 `content_md/tree_json`；重建则删旧章按目标 `tree` 的 `get_chapters` 重建，订单状态回 `outline_done`。
- `POST /orders/{id}/chapters/reorder` body `ReorderIn{node_ids}`：`node_ids` 必须与现有章节集合「不重不漏」否则 422，重排后 `idx` 从 1 连续重编。**注意声明顺序必须在 `/chapters/{node_id}` 之前**，否则 `reorder` 会被当成 node_id 吞掉。
- `DELETE /orders/{id}/chapters/{node_id}`：删除后剩余章节 `idx` 连续重编，返回 204。

全部走 `_get_owned_order` 属主校验（IDOR 404）。

**测试** `backend/tests/test_writing_versions.py` **9 passed**：版本随重生成推进、回滚生成 v3 且内容等于目标版本、按目标 tree 重建章节、未知版本 404、章节反转重排、node_ids 错集 422、删除后 idx 重编、跨用户 404。

## 3. 摘要生成（#6 abstract）

**问题**：无摘要生成，原站有 `abst/abstEn` 能力。

**改后**：
- 新文件 `backend/app/prompts/abstract_prompts.py`：`ABSTRACT_SYSTEM_ZH/EN`（一段式，中 200-350 字 / 英 150-250 词，禁引用标号与图表编号）+ `build_abstract_user_prompt(title, body_md, max_chars=6000)`。
- `POST /orders/{id}/abstract?lang=zh|en`（`dependencies=[Depends(rate_limit_llm)]`）：需 ≥1 个 done 章节否则 409；`lang` 非 zh/en → 422；返回 `{abstract, lang, model, tokens_in, tokens_out}`。

**测试** `backend/tests/test_abstract.py` **5 passed**：无章节 409 / zh 正常 / en 正常 / 非法 lang 422 / 跨用户 404。

> 踩坑：`pay_method` 必须匹配 `^(wechat|alipay)$`，测试建单用 `"alipay"`。

## 4. 文件上传 + 对象存储（#2 / #14）

**问题**：`grep UploadFile` = 0，系统零文件上传；导出全在内存、无对象存储。

**改后**：
- 新文件 `backend/app/storage.py`：`LocalStorage`（默认，落 `SC_STORAGE_DIR`，`_path` 做目录穿越防护）+ `S3Storage`（boto3 可选，`SC_S3_*`，`generate_presigned_url`）+ `get_storage()` 惰性单例 + `reset_storage()` + `make_key(tenant, ext)` + `sha256_hex` + `StorageError`。
- 新模型 `backend/app/models.py::UploadedFile`（表 `uploaded_files`：`id/tenant_id/owner_id/order_id/kind/filename/content_type/size/storage_key/sha256/created_at`，tenant/owner/order/sha256 建索引）。
- 新迁移 `backend/migrations/versions/b2d3e4f5a6c7_v1_9_uploaded_files.py`（down_revision `a7c1e2d4f6b8`）；迁移-模型一致性门通过。
- 新路由 `backend/app/routers/files.py`：
  | 方法 | 路径 | 说明 |
  |---|---|---|
  | POST | `/files` | multipart `upload` + Form `kind`/`order_id`；扩展名白名单 `ALLOWED_EXT` 否则 422；> `SC_MAX_UPLOAD_MB` → 413；空文件 422；成功 201 |
  | GET | `/files` | 本人文件列表，支持 `order_id`/`kind` 过滤 |
  | GET | `/files/{id}` | 元数据 |
  | GET | `/files/{id}/download` | 流式下载，中文文件名 `quote` |
  | GET | `/files/{id}/signed-url` | S3 返预签名 URL；本地返应用内下载路径 |
  | DELETE | `/files/{id}` | 删除存储对象 + 记录，204 |
- 全部走 `ownership_filter`（IDOR：非本人一律 404）。
- `config.py` 加 `storage_backend/storage_dir/max_upload_mb/s3_endpoint/s3_bucket/s3_access_key/s3_secret_key/s3_region`；`.env.example` 加 `SC_STORAGE_*` / `SC_MAX_UPLOAD_MB` / `SC_S3_*`；`pyproject.toml` 加 `python-multipart>=0.0.9` + `s3 = ["boto3>=1.34"]` extra。

**测试** `backend/tests/test_files.py` **9 passed**：上传→下载回读字节一致 / 坏扩展名 422 / 空文件 422 / 超限 413（monkeypatch `max_upload_mb=0`）/ 列表与 kind 过滤 / 跨用户下载与 signed-url 404 / 删除后取 404 / 本地 signed-url 形态 / 存储键目录穿越防护。

## 5. 版本与全套测试

- 版本 1.8.0 → **1.9.0**（`backend/app/main.py::VERSION`、`backend/pyproject.toml`、README 徽章）。
- openapi 由 60 → **69 路径 / 27 schema** 重导出（新增 `/files*`、`/orders/{id}/abstract`、`/orders/{id}/outline/versions*`、`/orders/{id}/chapters/reorder`、`DELETE /orders/{id}/chapters/{node_id}`）。
- 全套 `pytest tests/` = **187 passed, 1 skipped**（+28 项：文体 5 + 版本 9 + 摘要 5 + 文件 9）。
- CI：backend job 需补 `pip install ".[dev]"`（dev extras 含 fakeredis）已在 v1.7 段修好；本轮新增依赖 `python-multipart` 已进主依赖。

## 6. 未验证项（如实记录）

- S3/MinIO 后端未在真实对象存储上联调（`S3Storage` 依赖 boto3，CI 与本机默认走 `LocalStorage`；预签名 URL 生成未对真实桶验证）。
- 文件上传未接前端 UI（本轮只做后端端点 + 存储层，前端上传控件属后续）。
- 多文体仅接了大纲 prompt；正文分章 prompt 的文体差异（`writing_hint`）尚未在 `chapter` 生成链路里注入。
