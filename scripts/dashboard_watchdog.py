"""Streamlit 看板守护进程（watchdog）。

为什么需要：看板进程从终端/会话启动时，会话结束子进程被一并回收
（老是被杀的根因）。本守护作为顶层独立进程运行：
  - 每 30s 健康检查（TCP 探测 + HTTP 200）
  - 看板挂了 → 自动重启（日志留痕）
  - 自身意外退出 → 由 Windows 计划任务（ONSTART）再次拉起，双保险

用法：
  python scripts/dashboard_watchdog.py            # 前台守护（调试）
  python scripts/dashboard_watchdog.py --install  # 安装计划任务（开机自启）
  python scripts/dashboard_watchdog.py --remove   # 移除计划任务
  python scripts/dashboard_watchdog.py --status   # 查看守护/看板状态
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from port_utils import http_ok, port_in_use, who_owns_port  # noqa: E402

PORT = 8765
TASK_NAME = "QuantDashboardWatchdog"
LOG = ROOT / "logs" / "watchdog.log"


def log(msg: str) -> None:
    LOG.parent.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{ts} {msg}\n")
    print(f"[watchdog] {msg}")


def start_dashboard() -> subprocess.Popen | None:
    """启动看板（找不到已监听进程时）。返回 Popen 或 None（已有人在跑/WMI 通道）。

    Windows 沙箱环境：subprocess 子进程会被 job object 回收（DETACHED 也躲不过，
    BREAKAWAY 权限被拒）。改走 WMI Win32_Process.Create——进程宿主在
    Wmiprvse 服务，不在沙箱 job 内，工具调用结束后持续存活。
    """
    if port_in_use(PORT):
        return None
    cmd = f'"{sys.executable}" -m streamlit run web/app.py ' \
          f'--server.port {PORT} --server.headless true'
    # 注意：WMI Create 无 shell，不支持 > 重定向（带 > 会导致参数错乱进程退出）。
    # streamlit 输出走自身 logger；此处不重定向。
    try:
        try:
            import win32com.client
            svc = win32com.client.Dispatch("WbemScripting.SWbemLocator")
            svcm = svc.ConnectServer(".", "root/cimv2")
            obj = svcm.Get("Win32_Process")
            method = obj.Methods_("Create")
            inp = method.InParameters.SpawnInstance_()
            inp.Properties_("CommandLine").Value = cmd
            inp.Properties_("CurrentDirectory").Value = str(ROOT)
            out = obj.ExecMethod_("Create", inp)
            if out.ReturnValue == 0:
                log(f"看板已启动 PID {out.ProcessId}（WMI 通道，端口 {PORT}）")
                return None
            log(f"WMI 启动失败 ReturnCode={out.ReturnValue}，回退 subprocess")
        except ImportError:
            log("pywin32 未安装，回退 subprocess")
    except Exception as e:  # noqa: BLE001
        log(f"WMI 通道异常: {type(e).__name__}: {e}")
    # 回退：传统 subprocess（非沙箱环境下可用）
    proc = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", "web/app.py",
         "--server.port", str(PORT), "--server.headless", "true"],
        cwd=str(ROOT),
        stdout=open(ROOT / "logs" / "streamlit.log", "ab"),
        stderr=open(ROOT / "logs" / "streamlit_err.log", "ab"),
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
        close_fds=True,
    )
    log(f"看板已启动 PID {proc.pid}（subprocess 通道，端口 {PORT}）")
    return proc


def run_forever(interval: int = 30) -> None:
    log(f"守护启动（每 {interval}s 健康检查，端口 {PORT}）")
    proc: subprocess.Popen | None = None
    fail_streak = 0
    while True:
        try:
            if port_in_use(PORT):
                if http_ok(PORT):
                    if fail_streak:
                        log(f"看板恢复健康（此前连续失败 {fail_streak} 次）")
                    fail_streak = 0
                else:
                    fail_streak += 1
                    if fail_streak >= 3:
                        log(f"端口被占但 HTTP 连续 {fail_streak} 次不健康：{who_owns_port(PORT)}")
            else:
                log(f"看板未监听（占用方：{who_owns_port(PORT)}），重新拉起")
                proc = start_dashboard() or proc
                fail_streak = 0
                # 给看板 10s 启动时间，下轮再验
            if proc is not None and proc.poll() is not None:
                log(f"看板进程退出码 {proc.returncode}，将重启")
                proc = None
        except Exception as e:  # noqa: BLE001
            log(f"守护循环异常: {type(e).__name__}: {e}")
        time.sleep(interval if port_in_use(PORT) else 10)


# ---- 自持久化：注册表 HKCU Run 键（登录自启；schtasks 被安全策略拉黑时的替代） ----
def task_cmd(action: str) -> None:
    import winreg
    run_key = r"Software\Microsoft\Windows\CurrentVersion\Run"
    py = Path(sys.executable).resolve()
    script = Path(__file__).resolve()
    if action == "install":
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, run_key, 0,
                                winreg.KEY_SET_VALUE) as k:
                winreg.SetValueEx(k, TASK_NAME, 0, winreg.REG_SZ,
                                  f'"{py}" "{script}"')
            print(f"已注册登录自启（HKCU\\...\\Run\\{TASK_NAME}）")
        except OSError as e:
            print(f"注册失败：{e}")
        # 立即拉起一次
        start_dashboard()
    elif action == "remove":
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, run_key, 0,
                                winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, TASK_NAME)
            print("已移除登录自启")
        except FileNotFoundError:
            print("未安装")
        except OSError as e:
            print(f"移除失败：{e}")
    elif action == "status":
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, run_key) as k:
                v, _ = winreg.QueryValueEx(k, TASK_NAME)
            print(f"登录自启：已安装 → {v}")
        except FileNotFoundError:
            print("登录自启：未安装")
        print(f"端口 {PORT}: {'占用' if port_in_use(PORT) else '空闲'}"
              f"（{who_owns_port(PORT)}），HTTP: {'OK' if http_ok(PORT) else 'FAIL'}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--install", action="store_true", help="注册登录自启（HKCU Run）")
    ap.add_argument("--remove", action="store_true", help="移除登录自启")
    ap.add_argument("--status", action="store_true", help="查看状态")
    ap.add_argument("--interval", type=int, default=30, help="健康检查间隔秒")
    args = ap.parse_args()
    if args.install:
        task_cmd("install")
    elif args.remove:
        task_cmd("remove")
    elif args.status:
        task_cmd("status")
    else:
        run_forever(args.interval)
