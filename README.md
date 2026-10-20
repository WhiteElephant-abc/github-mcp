# GitHub Code Search MCP Server

基于官方 MCP Python SDK 的 GitHub 代码搜索服务器，可通过任何 MCP 客户端（Claude Code、Claude Desktop 等）搜索全 GitHub 的代码、读取和下载任意仓库文件。

## 功能

| Tool | 说明 |
|------|------|
| `search_code` | 全 GitHub 代码搜索：关键词 + 任意仓库/语言/文件名/路径过滤，返回文件路径和匹配源码片段 |
| `search_repo` | 按名称搜索仓库，返回 owner/name、描述、语言、star 数 |
| `get_repo` | 获取仓库元信息（默认分支、可见性、star 数等），兼作仓库存在性检查 |
| `list_tree` | 获取仓库文件树，支持按子目录、深度和条目数过滤 |
| `read_code` | 读取任意仓库任意文件：支持分支/标签/commit 指定、按行范围读取（任意一行代码） |
| `download` | 下载任意仓库文件到本地：`/tmp/github-mcp/<owner>/<repo>/<仓库内路径>`，按原始字节保存 |

## 快速开始（Docker Compose）

```bash
cp .env.example .env
# 编辑 .env，填入你的 GITHUB_TOKEN
make up

# 验证（状态应为 healthy）
docker compose ps
```

> 构建需要 host 网络（pip 走宿主机代理），而 Compose v5 的 bake 要求显式
> `--allow=network.host`，且无法在 compose 文件中持久化。因此统一用 `make up`
> 构建并启动；等价的手动命令为：
>
> ```bash
> docker buildx bake -f docker-compose.yml --allow=network.host
> docker compose up -d --no-build
> ```

其他 Makefile 目标：`make down` 停止并删除容器，`make logs` 跟踪日志。

### 接入 AI 工具

MCP 服务器使用 **Streamable HTTP** 传输协议。任何支持 MCP 的客户端通过以下地址接入：

```
http://localhost:8000/mcp
```

示例（Claude Code）：

```bash
# 全局生效，所有项目可用
claude mcp add --scope user --transport http github-mcp http://localhost:8000/mcp

# 仅当前项目生效
claude mcp add --transport http github-mcp http://localhost:8000/mcp
```

### 可用工具

| 工具 | 用途 |
|---|---|
| `search_code(query, repo, language, filename, path, limit)` | 全 GitHub 代码搜索，`repo` 限定 owner/name 仓库，返回文件路径与匹配源码片段 |
| `search_repo(query, limit)` | 按名称搜索仓库，用于定位正确的 owner/name（如组织名拼写不确定时纠错） |
| `get_repo(repo)` | 获取仓库元信息，仓库不存在时给出相似仓库候选 |
| `list_tree(repo, ref, path, depth, limit)` | 获取仓库文件树，`path` 限定子目录，`depth` 限制目录深度，`limit` 限制条目数 |
| `read_code(repo, path, ref, start_line, max_lines)` | 读取任意仓库任意文件，`ref` 指定分支/commit，`start_line`/`max_lines` 定位任意行范围 |
| `download(repo, path, ref)` | 下载文件到 `/tmp/github-mcp/<owner>/<repo>/<仓库内路径>`，超过 1 MiB 自动回退 raw 端点 |

## 环境变量

| 变量 | 必填 | 说明 |
|------|------|------|
| `GITHUB_TOKEN` | 是 | GitHub 访问令牌（只需只读权限），code search API 必须认证 |
| `HOST` | 否 | 监听地址，默认 `0.0.0.0` |
| `PORT` | 否 | 监听端口，默认 `8000` |
| `MAX_RETRIES` | 否 | 单次请求最大尝试次数，默认 `3`；传输错误和 503 按 1/2/4… 秒指数退避重试 |
| `TIMEOUT` | 否 | API 请求超时秒数，默认 `20`；raw 大文件下载自动放大到 3 倍且不低于 60 秒 |
| `DOWNLOAD_ROOT` | 否 | `download` 工具的保存根目录，默认 `/tmp/github-mcp` |
| `HTTPS_PROXY` / `HTTP_PROXY` / `NO_PROXY` | 否 | 代理。compose 从宿主 shell 环境透传，服务端按 `HTTPS_PROXY` → `HTTP_PROXY` 顺序读取 |

## 本地运行（非 Docker）

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
GITHUB_TOKEN=<你的 GitHub token> .venv/bin/python server.py
```

## 说明

- GitHub code search 只索引仓库的**默认分支**
- `read_code` 和 `download` 遇到超过 1 MiB 的文件时自动回退到 `raw.githubusercontent.com`
- `download` 按原始字节写入，支持二进制文件
- 403/429 限流按 `Retry-After` / `X-RateLimit-Reset` 等待，恢复时刻在进程内所有请求间共享
- compose 配置将容器 `/tmp` 设为 tmpfs，并把 `/tmp/github-mcp` 绑定到宿主机同名目录，客户端可直接读取下载结果；若宿主 `/tmp` 本身是 tmpfs，下载文件会随宿主重启丢失
- 容器以 root 运行，宿主上下载文件的属主为 root；需要当前用户可写时，可给服务加 `user:` 或预先 `chown`
- 无 `GITHUB_TOKEN` 时 `search_code` 返回 401 提示；读取和下载公开仓库不受影响（受未认证限流约束）
