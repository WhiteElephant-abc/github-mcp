"""GitHub Code Search MCP Server — 提供 GitHub 代码搜索和文件读取工具"""

import asyncio
import base64
import os
import time
from typing import Annotated

import httpx
from mcp.server.mcpserver import MCPServer
from pydantic import Field

API_BASE = "https://api.github.com"
RAW_BASE = "https://raw.githubusercontent.com"
TOKEN = os.getenv("GITHUB_TOKEN", "")
MAX_LINES = 2000
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
TIMEOUT = int(os.getenv("TIMEOUT", "20"))
_next_request_time = 0.0  # 全局共享的限流恢复时刻（epoch 秒），所有请求共用

mcp = MCPServer("GitHub Code Search")


def _client(timeout: float) -> httpx.AsyncClient:
    """构造 httpx 客户端：手动指定代理，避免解析 NO_PROXY 中的 IPv6 条目报错"""
    proxy_url = os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY")
    return httpx.AsyncClient(timeout=timeout, trust_env=False, proxy=proxy_url)


async def _get(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: dict | None = None,
    headers: dict | None = None,
) -> httpx.Response:
    """GET 请求：传输层错误指数退避重试，限流按 Retry-After / X-RateLimit-Reset 等待，恢复时刻全局共享"""
    global _next_request_time
    now = time.time()
    if _next_request_time > now:
        wait = _next_request_time - now
        print(f"[github-mcp] 共享限流窗口内，提前等待 {wait:.0f}s url={url}", flush=True)
        await asyncio.sleep(wait)
    for attempt in range(MAX_RETRIES):
        try:
            resp = await client.get(url, params=params, headers=headers)
            if resp.status_code in (403, 429) and attempt < MAX_RETRIES - 1:
                wait = None
                retry_after = resp.headers.get("Retry-After")
                if retry_after:
                    wait = max(1.0, float(retry_after))
                elif resp.headers.get("X-RateLimit-Remaining") == "0":
                    reset = resp.headers.get("X-RateLimit-Reset")
                    if reset:
                        wait = max(1.0, float(reset) - time.time())
                if wait is not None:
                    _next_request_time = max(_next_request_time, time.time() + wait)
                    print(
                        f"[github-mcp] 限流 {resp.status_code} 等待 {wait:.0f}s 后重试"
                        f"（共享恢复时刻 {_next_request_time:.0f}） url={url}",
                        flush=True,
                    )
                    await asyncio.sleep(wait)
                    continue
            return resp
        except httpx.TransportError as e:
            print(
                f"[github-mcp] 传输错误 {type(e).__name__}，第 {attempt + 1}/{MAX_RETRIES} 次尝试失败，"
                f"退避 {2 ** attempt}s 后重试 url={url}",
                flush=True,
            )
            if attempt == MAX_RETRIES - 1:
                raise
            await asyncio.sleep(2**attempt)
    raise httpx.TransportError("unreachable")


def _headers(*, text_match: bool = False) -> dict[str, str]:
    headers: dict[str, str] = {
        "Accept": (
            "application/vnd.github.text-match+json"
            if text_match
            else "application/vnd.github+json"
        ),
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "github-mcp",
    }
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    return headers


def _api_error(resp: httpx.Response) -> str:
    """根据 GitHub API 响应构建可读的错误信息"""
    if resp.status_code == 401:
        return "未提供或无效的 GITHUB_TOKEN，代码搜索必须认证"
    if resp.status_code == 403:
        remaining = resp.headers.get("X-RateLimit-Remaining")
        hint = f"（剩余额度 {remaining}）" if remaining else ""
        try:
            msg = resp.json().get("message", "")
        except ValueError:
            msg = ""
        if msg:
            return f"GitHub API 拒绝: {msg}{hint}"
        return f"GitHub API 限流或仓库访问被拒绝{hint}"
    if resp.status_code == 404:
        return "未找到：仓库或路径不存在（或 token 无访问权限）"
    try:
        msg = resp.json().get("message", resp.text)
    except ValueError:
        msg = resp.text
    return f"GitHub API 错误 {resp.status_code}: {msg}"


@mcp.tool()
async def search_code(
    query: Annotated[str, Field(description="搜索关键词，GitHub code search 语法，例如 'fun Any?.toString'。高级限定符也可直接内联传入（如 'foo in:file'）")],
    repo: Annotated[str | None, Field(description="限定仓库，格式 owner/name，例如 'JetBrains/kotlin'。不传则搜索全 GitHub 所有仓库")] = None,
    language: Annotated[str | None, Field(description="按语言过滤，例如 'kotlin'")] = None,
    filename: Annotated[str | None, Field(description="按文件名过滤（精确匹配，glob 通配符如 *.kt 不生效），例如 'String.kt'")] = None,
    path: Annotated[str | None, Field(description="按文件路径过滤，例如 'stdlib/common/src'")] = None,
    limit: Annotated[int, Field(description="返回结果数量，默认 10，最大 50")] = 10,
) -> str:
    """在 GitHub 上搜索任意仓库中的代码。

    通过 GitHub code search API 全站搜索代码，默认只索引仓库的默认分支。
    搜索结果包含仓库名、文件路径、URL 和匹配的源码片段。"""
    q = query
    if repo:
        q += f" repo:{repo}"
    if language:
        q += f" language:{language}"
    if filename:
        q += f" filename:{filename}"
    if path:
        q += f" path:{path}"
    per_page = max(1, min(int(limit), 50))

    try:
        async with _client(TIMEOUT) as client:
            resp = await _get(
                client,
                f"{API_BASE}/search/code",
                params={"q": q, "per_page": per_page},
                headers=_headers(text_match=True),
            )
    except Exception as e:
        cause = f" cause={e.__cause__!r}" if e.__cause__ else ""
        return f"搜索失败: API 服务不可用 ({type(e).__name__}: {e!r}{cause})"

    if resp.status_code != 200:
        return f"搜索失败: {_api_error(resp)}"

    data = resp.json()
    items = data.get("items", [])
    total = data.get("total_count", 0)
    if not items:
        return f"未找到与 '{q}' 相关的代码。"

    lines = [f"搜索 '{q}' 的结果，共 {total} 处匹配（显示前 {len(items)} 条）:\n"]
    for i, item in enumerate(items, 1):
        name = item["repository"]["full_name"]
        file_path = item["path"]
        lines.append(f"{i}. **{name}** — `{file_path}`")
        lines.append(f"   {item['html_url']}")
        for match in item.get("text_matches", []):
            fragment = match.get("fragment", "").strip()
            if fragment:
                for fl in fragment.splitlines()[:5]:
                    lines.append(f"   > {fl}")
        lines.append("")
    return "\n".join(lines)


@mcp.tool()
async def read_code(
    repo: Annotated[str, Field(description="仓库名，格式 owner/name，例如 'JetBrains/kotlin'")],
    path: Annotated[str, Field(description="文件路径，例如 'libraries/stdlib/src/kotlin/kotlin.kt'")],
    ref: Annotated[str | None, Field(description="分支、标签或 commit SHA。不传则使用仓库默认分支")] = None,
    start_line: Annotated[int, Field(description="起始行号（从 1 开始），只返回该行起的部分")] = 1,
    max_lines: Annotated[int, Field(description="返回行数，默认 500，最大 2000")] = 500,
) -> str:
    """读取 GitHub 任意仓库中指定文件的内容。

    根据仓库、文件路径和分支读取源码，支持只读取指定行范围（start_line / max_lines），
    便于定位任意一行代码。返回带行号的源码和文件元信息。"""
    start_line = max(1, int(start_line))
    max_lines = max(1, min(int(max_lines), MAX_LINES))

    try:
        async with _client(TIMEOUT) as client:
            url = f"{API_BASE}/repos/{repo}/contents/{path}"
            params = {"ref": ref} if ref else None
            resp = await _get(client, url, params=params, headers=_headers())

            if resp.status_code == 404:
                # GitHub 对无权限资源伪装 404，用仓库元信息探针区分"仓库不存在"与"路径不存在"
                info = await _get(client, f"{API_BASE}/repos/{repo}", headers=_headers())
                if info.status_code == 404:
                    return "读取失败: 仓库不存在或 token 无权限访问该仓库"
                if info.status_code != 200:
                    return f"读取失败: 仓库探测异常: {_api_error(info)}"
                params = {"ref": ref or info.json()["default_branch"]}
                resp = await _get(client, url, params=params, headers=_headers())
    except Exception as e:
        cause = f" cause={e.__cause__!r}" if e.__cause__ else ""
        return f"读取失败: API 服务不可用 ({type(e).__name__}: {e!r}{cause})"

    if resp.status_code == 404:
        return "读取失败: 文件路径不存在或 ref 无效（仓库可访问，请检查 path/ref 参数）"
    if resp.status_code != 200:
        return f"读取失败: {_api_error(resp)}"

    body = resp.json()
    content = body.get("content")
    if content is None:
        # 文件超过 1 MiB 时 contents API 只返回 blob 链接，回退 raw 端点
        try:
            async with _client(max(TIMEOUT * 3, 60)) as client:
                raw = await _get(client, f"{RAW_BASE}/{repo}/{ref or 'HEAD'}/{path}")
        except Exception as e:
            cause = f" cause={e.__cause__!r}" if e.__cause__ else ""
            return f"读取失败: API 服务不可用 ({type(e).__name__}: {e!r}{cause})"
        if raw.status_code != 200:
            return f"读取失败: 文件超过 contents API 大小限制且 raw 获取失败 ({raw.status_code})"
        text = raw.text
        sha = ""
        size = len(raw.content)
    else:
        text = base64.b64decode(content).decode("utf-8", errors="replace")
        sha = body.get("sha", "")
        size = body.get("size", len(text))

    all_lines = text.splitlines()
    total = len(all_lines)
    if start_line > total:
        return (
            f"# {repo} — {path}\n"
            f"ref={ref or 'default'}  | 共 {total} 行  | start_line={start_line} 超出文件范围"
        )
    end = min(start_line - 1 + max_lines, total)
    selected = all_lines[start_line - 1 : end]
    width = len(str(end))

    out = [
        f"# {repo} — {path}",
        f"ref={ref or 'default'}  | 共 {total} 行  | 显示 {start_line}-{end}  | sha={sha[:12]}  | size={size}",
    ]
    out.extend(f"{i:>{width}} | {line}" for i, line in enumerate(selected, start_line))
    return "\n".join(out)


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    mcp.run(transport="streamable-http", host=host, port=port)
