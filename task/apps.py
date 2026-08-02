from django.apps import AppConfig
import sys
import os
import subprocess
import time
import threading
from multiprocessing.managers import BaseManager

# 全局变量
r_proxy = None

# ================= 配置区 =================
CONDA_PYTHON = '/data3/platform/sc_db/cellchat/env/bin/python'
WORKER_SCRIPT = os.path.join(os.path.dirname(__file__), 'r_worker.py')
SOCKET_PATH = '/tmp/cellchat_r.sock'
AUTH_KEY = os.environ.get('R_AUTH_KEY', 'cellchat_secret_key').encode()

_proxy_lock = threading.Lock()


class RServiceManager(BaseManager):
    pass


RServiceManager.register('get_cellchat_service')


def get_r_proxy():
    """懒连接 R 服务：首次调用时建立连接，之后复用。

    gunicorn 多 worker 下 fork 会复制预建的 socket 连接（4 个 worker 共享
    同一条连接会串数据），因此不能在进程启动时预连——每个 worker 首次
    调用时各自 connect。runserver 单进程下语义与预连等价。
    """
    global r_proxy
    if r_proxy is None:
        with _proxy_lock:
            if r_proxy is None:
                manager = RServiceManager(address=SOCKET_PATH, authkey=AUTH_KEY)
                manager.connect()
                r_proxy = manager.get_cellchat_service()
    return r_proxy

class TaskConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'task'
    
    def ready(self):
        # 防止 runserver 重载机制导致重复执行
        if "runserver" in sys.argv and os.environ.get("RUN_MAIN") != "true":
            return

        # 同样排除 migrate 等命令
        if not any(x in sys.argv for x in ['runserver', 'gunicorn', 'uwsgi']):
            return

        print("🔹 [AppConfig] 初始化 R 子系统连接...")

        # 1. 启动子进程 (如果 socket 不存在)
        # 注意：这里我们假设如果有 socket，说明服务活着。
        # 如果 socket 是上次残留的死文件，可能需要手动清理，但 r_worker 启动时会清理旧的。
        if not os.path.exists(SOCKET_PATH):
            print("⚙️ 正在启动后台 R 进程 (Conda环境)...")
            subprocess.Popen(
                [CONDA_PYTHON, WORKER_SCRIPT, SOCKET_PATH, AUTH_KEY.decode('utf-8')],
                cwd=os.getcwd(),
                # stdout=sys.stdout, # 让子进程输出显示在主终端，方便调试
                # stderr=sys.stderr
            )
        
        # 2. ⏳ 等待 Socket 文件生成 (最多等 60 秒)
        # 连接本身已改为懒连接（get_r_proxy），这里只确保 R 子进程起来，
        # 避免首次请求时 socket 尚未就绪（r_worker 加载 CellChat 需约 30-40s）。
        print("⏳ 等待 R 服务就绪...", end='', flush=True)
        max_retries = 120  # 120次 * 0.5秒 = 60秒超时（r_worker source CellChat 约需 30-40s）
        connected = False
        
        for i in range(max_retries):
            if os.path.exists(SOCKET_PATH):
                connected = True
                print(" ✅") # 换行
                break
            time.sleep(0.5)
            print(".", end='', flush=True)
        
        if not connected:
            print("\n❌ [Timeout] R 服务启动超时 (超过60秒)，Socket 文件未生成。")
            # 这里不抛异常，避免 Django 启动失败，但由你自己决定
            return

        print("🔗 [Ready] R 服务已就绪，连接将在首次 CellChat 调用时建立（get_r_proxy）")