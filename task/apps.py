from django.apps import AppConfig
import sys
import os
import subprocess
import time
from multiprocessing.managers import BaseManager

# 全局变量
r_proxy = None

class RServiceManager(BaseManager):
    pass

RServiceManager.register('get_cellchat_service')

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

        global r_proxy

        # ================= 配置区 =================
        # 你的 Conda Python 路径
        CONDA_PYTHON = '/data3/platform/sc_db/cellchat/env/bin/python'
        # Worker 脚本路径
        WORKER_SCRIPT = os.path.join(os.path.dirname(__file__), 'r_worker.py')
        # 通信 Socket 路径
        SOCKET_PATH = '/tmp/cellchat_r.sock'
        # 通信密钥
        AUTH_KEY = b'cellchat_secret_key'
        # ==========================================

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
        
        # 2. ⏳【关键修改】循环等待 Socket 文件生成 (最多等 20 秒)
        print("⏳ 等待 R 服务就绪...", end='', flush=True)
        max_retries = 40  # 40次 * 0.5秒 = 20秒超时
        connected = False
        
        for i in range(max_retries):
            if os.path.exists(SOCKET_PATH):
                connected = True
                print(" ✅") # 换行
                break
            time.sleep(0.5)
            print(".", end='', flush=True)
        
        if not connected:
            print("\n❌ [Timeout] R 服务启动超时 (超过20秒)，Socket 文件未生成。")
            # 这里不抛异常，避免 Django 启动失败，但由你自己决定
            return

        # 3. 连接
        try:
            # 这里的 address 必须是 socket 路径
            manager = RServiceManager(address=SOCKET_PATH, authkey=AUTH_KEY)
            manager.connect()
            
            # 获取代理对象
            r_proxy = manager.get_cellchat_service()
            
            print("🔗 [Link Success] Django 已成功连接到 R 进程！")
            # 测试调用一下，确认通路正常
            status = r_proxy.get_status()
            print(f"   📊 R 服务状态: {status}")
            
        except Exception as e:
            print(f"\n❌ [Link Error] 连接失败: {e}")