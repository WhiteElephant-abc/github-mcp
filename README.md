# GitHub Code Search MCP Server

基于官方 MCP Python SDK 的 GitHub 代码搜索服务器，可通过任何 MCP 客户端（Claude Code、Claude Desktop 等）搜索全 GitHub 的代码并读取任意文件内容。

## 功能

| Tool | 说明 |
|------|------|
| `search_code` | 全 GitHub 代码搜索：关键词 + 任意仓库/语言/文件名/路径过滤，返回文件路径和匹配源码片段 |
| `read_code` | 读取任意仓库任意文件：支持分支/标签/commit 指定、按行范围读取（任意一行代码） |

## 快速开始（Docker Compose）

```bash
cp .env.example .env
# 编辑 .env，填入你的 GITHUB_TOKEN
docker compose up --build -d

# 验证
docker compose ps
curl http://localhost:8000/mcp  # 应返回 MCP endpoint 信息
```

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
| `read_code(repo, path, ref, start_line, max_lines)` | 读取任意仓库任意文件，`ref` 指定分支/commit，`start_line`/`max_lines` 定位任意行范围 |

## 环境变量

| 变量 | 必填 | 说明 |
|------|------|------|
| `GITHUB_TOKEN` | 是 | GitHub 访问令牌（只需只读权限），code search API 必须认证 |
| `HOST` | 否 | 监听地址，默认 `0.0.0.0` |
| `PORT` | 否 | 监听端口，默认 `8000` |
| `HTTPS_PROXY` / `NO_PROXY` | 否 | 代理。由 compose 启动时从宿主 shell 环境自动透传（`${HTTPS_PROXY:-}`），无需在 `.env` 配置 |

## 本地运行（非 Docker）

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
GITHUB_TOKEN=<你的 GitHub token> .venv/bin/python server.py
```

## 说明

- GitHub code search 只索引仓库的**默认分支**
- 读取大文件（>1 MiB）时自动回退到 `raw.githubusercontent.com`
- 无 `GITHUB_TOKEN` 时搜索会返回 401 错误提示
