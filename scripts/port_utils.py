"""端口检测工具（多环境启动前防冲突用）。

用法（其他脚本导入）：
    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
    from port_utils import port_in_use, find_free_port, who_owns_port

    if port_in_use(8765):
        port = find_free_port(8766)   # 8765 被占 → 自动找下一个空闲端口

命令行快查：
    python scripts/port_utils.py 8765
"""
from __future__ import annotations

import socket
import subprocess


def port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """端口是否被占用（TCP connect 探测；连得上=占用）。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1.0)
        return s.connect_ex((host, port)) == 0


def _run(cmd: list[str]) -> str:
    """跑命令并安全解码（中文 Windows 输出 GBK，容错解码不抛异常）。"""
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=10)
        return r.stdout.decode("utf-8", errors="ignore") or ""
    except Exception:  # noqa: BLE001
        return ""


def listening_pids(port: int) -> list[str]:
    """占用端口处于 LISTENING 状态的进程 PID 列表（netstat -ano）。"""
    out = _run(["netstat", "-ano"])
    pids: list[str] = []
    for line in out.splitlines():
        parts = line.split()
        # TCP    0.0.0.0:8765    0.0.0.0:0    LISTENING    12345
        if len(parts) >= 5 and parts[0] == "TCP" and "LISTENING" in line:
            if parts[1].endswith(f":{port}"):
                pids.append(parts[-1])
    return sorted(set(pids))


def pid_name(pid: str) -> str:
    """PID → 进程名（tasklist CSV 查询）。"""
    out = _run(["tasklist", "/FO", "CSV", "/NH"])
    for line in out.splitlines():
        cols = [c.strip('"') for c in line.split('","')]
        if len(cols) >= 2 and cols[1] == pid:
            return cols[0]
    return "?"


def who_owns_port(port: int) -> str:
    """占用端口的进程描述（进程名 + PID）。"""
    pids = listening_pids(port)
    if not pids:
        return "(无监听)"
    return ", ".join(f"{pid_name(p)}(PID {p})" for p in pids)


def find_free_port(start: int = 8765, tries: int = 20) -> int:
    """从 start 起找第一个空闲端口（其他环境启动前用）。"""
    for port in range(start, start + tries):
        if not port_in_use(port):
            return port
    raise RuntimeError(f"端口 {start}~{start + tries - 1} 全被占用")


def http_ok(port: int, path: str = "/", timeout: float = 5.0) -> bool:
    """HTTP 健康检查（200 即健康）。"""
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=timeout) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


if __name__ == "__main__":
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    print(f"端口 {port}: {'占用' if port_in_use(port) else '空闲'}")
    if port_in_use(port):
        print(f"  占用进程: {who_owns_port(port)}")
        print(f"  HTTP 健康: {'OK' if http_ok(port) else 'FAIL'}")
