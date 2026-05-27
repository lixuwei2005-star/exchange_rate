# rate.005917.xyz

CNY → MYR 汇率对比工具，给在马来西亚的中国留学生用。比较各家银行、卡组织、汇款服务的实际到账金额。

> **看代码前先读 [`CLAUDE.md`](./CLAUDE.md)。** 那里讲清了汇率方向、术语、数据模型、AI 配置方式等所有非显然的约定。本文件只负责让人跑起来。

## Quickstart

```bash
cp .env.example .env       # 唯一手动步骤
make dev                   # docker compose up — backend :8000, frontend :3000
```

打开 <http://localhost:3000> 看公共主页，<http://localhost:3000/admin> 登录后台（默认 `admin` / `changeme`，登录后到 `/admin/ai` 填 LLM endpoint 才能用 AI summary 功能）。

## 目录概览

- `backend/` — FastAPI + SQLAlchemy 2.0 async + APScheduler。所有汇率源在 `app/scrapers/`。
- `frontend/` — Next.js 14 App Router + TypeScript + Tailwind。
- `prompts/` — 项目分阶段的构建 prompt（开发文档）。
- `CLAUDE.md` — 项目权威文档，所有不显然的设计决策都在这里。

## 常用命令

`make help` 列出所有 make 目标。最常用：

| 命令 | 作用 |
|------|------|
| `make dev` | 起开发环境 |
| `make down` | 停掉容器（保留数据） |
| `make clean` | 停掉并删除 volume（重置 SQLite） |
| `make test` | 跑 pytest + vitest |
| `make lint` | Ruff + Black + ESLint + Prettier 全部 check |
| `make fernet-key` | 生成新的 Fernet key（部署前 .env 必换） |

## 部署

OCI 新加坡，docker-compose 直接拉起。Nginx 由 BaoTa 管理，配置不在仓库里。具体步骤见 `CLAUDE.md` §11、§14、§17。

## 状态

逐 phase 推进，详见 `prompts/`。

## License

私有项目，未授权请勿使用。
