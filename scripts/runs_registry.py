"""运行留痕注册表（console / scheduler 所有任务执行的持久化历史）。

存储：data/console_runs.json —— 记录数组（append-only，上限 500 条，超出裁最旧）

每条记录：
    id        运行标识（时间戳+key+pid）
    key       任务键（run_paper_qmt / backtest / daily_job / ...）
    label     人读标签（模拟盘（QMT）λ=0.5 TopN=30）
    cmd       命令行
    log       日志文件绝对路径
    pid       进程号（用于失联后补判存活）
    status    running / done / failed / aborted
    exit_code 进程退出码（失联补判时为 null）
    ts_start  开始时间 ISO
    ts_end    结束时间 ISO
    duration_s 耗时秒

红线：
- 原子写（tmp + os.replace），防半截 JSON
- 失联补判：status=running 但进程已死 → 按日志尾部有无 Traceback 判 done/failed
- 幂等：finish_run 重复调用安全
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS_FILE = ROOT / "data" / "console_runs.json"
MAX_RUNS = 500


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _load_raw() -> list[dict]:
    if not RUNS_FILE.exists():
        return []
    try:
        data = json.loads(RUNS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _save_raw(runs: list[dict]) -> None:
    RUNS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = RUNS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(runs[-MAX_RUNS:], ensure_ascii=False, indent=1),
                   encoding="utf-8")
    os.replace(tmp, RUNS_FILE)


def _pid_alive(pid: int) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        import psutil  # type: ignore
        return psutil.pid_exists(pid)
    except ImportError:
        import subprocess
        try:
            # tasklist 输出为 GBK，errors=ignore 防解码线程崩
            out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"],
                                  capture_output=True, timeout=10)
            return str(pid).encode() in out.stdout
        except Exception:  # noqa: BLE001
            return False


def start_run(key: str, label: str, cmd: str, log: str, pid: int) -> str:
    """登记一次运行（status=running）。返回运行 id。"""
    rid = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{key}_{pid}"
    runs = _load_raw()
    runs.append({
        "id": rid, "key": key, "label": label, "cmd": cmd, "log": log,
        "pid": pid, "status": "running", "exit_code": None,
        "ts_start": _now(), "ts_end": None, "duration_s": None,
    })
    _save_raw(runs)
    return rid


def finish_run(rid: str, status: str, exit_code: int | None = None) -> None:
    """回写终态（done/failed/aborted）。重复调用安全。"""
    runs = _load_raw()
    for r in runs:
        if r.get("id") == rid and r.get("status") == "running":
            r["status"] = status
            r["exit_code"] = exit_code
            r["ts_end"] = _now()
            try:
                t0 = datetime.strptime(r["ts_start"], "%Y-%m-%d %H:%M:%S")
                r["duration_s"] = round((datetime.now() - t0).total_seconds(), 1)
            except ValueError:
                pass
            break
    _save_raw(runs)


def _log_has_traceback(log_path: str) -> bool:
    try:
        return "Traceback (most recent call last)" in Path(log_path).read_text(
            encoding="utf-8", errors="replace")[-4000:]
    except OSError:
        return False


def reconcile() -> None:
    """失联补判：status=running 但进程已死的记录 → 按日志判 done/failed。

    适用场景：浏览器会话刷新（session_state 丢失）后 poll_task 不再回写，
    注册表里的 running 记录由本函数在读取时收敛。
    """
    runs = _load_raw()
    changed = False
    for r in runs:
        if r.get("status") != "running":
            continue
        # 刚登记 5 秒内的进程可能还在启动，不误判
        try:
            t0 = datetime.strptime(r["ts_start"], "%Y-%m-%d %H:%M:%S")
            if (datetime.now() - t0).total_seconds() < 5:
                continue
        except ValueError:
            pass
        if not _pid_alive(int(r.get("pid") or 0)):
            r["status"] = "failed" if _log_has_traceback(r.get("log", "")) else "done"
            r["ts_end"] = _now()
            changed = True
    if changed:
        _save_raw(runs)


def load_runs(key: str | None = None, limit: int = 100) -> list[dict]:
    """读取运行历史（新→旧）。key 过滤可选。"""
    reconcile()
    runs = _load_raw()
    if key:
        runs = [r for r in runs if r.get("key") == key]
    return list(reversed(runs))[:limit]


def stats() -> dict:
    """汇总统计（今日运行数 / 成功率 / 最近一次运行）。"""
    runs = _load_raw()
    today = datetime.now().strftime("%Y-%m-%d")
    today_runs = [r for r in runs if (r.get("ts_start") or "").startswith(today)]
    done = sum(1 for r in today_runs if r.get("status") == "done")
    failed = sum(1 for r in today_runs if r.get("status") == "failed")
    running = sum(1 for r in runs if r.get("status") == "running")
    return {
        "total": len(runs),
        "today": len(today_runs),
        "today_done": done,
        "today_failed": failed,
        "running": running,
        "last": runs[-1] if runs else None,
    }


if __name__ == "__main__":
    # CLI 自检：python scripts/runs_registry.py → 打印最近 20 条
    for r in load_runs(limit=20):
        print(f"{r['ts_start']}  {r['status']:<8} {r['key']:<14} {r['label']}")
