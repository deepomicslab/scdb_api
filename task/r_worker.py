# task/r_worker.py
import sys
import os
from multiprocessing.managers import BaseManager

# 1. 确保能导入当前目录的模块
sys.path.append(os.getcwd())

# 2. 导入你原本的 R 服务逻辑
# (请确保 cellchat_r_service.py 里的 R 环境配置和 rpy2 导入都是正常的、未注释的)
from task.cellchat_r_service import cellchat_service

# 3. 定义管理器
class RServiceManager(BaseManager):
    pass

# 4. 注册服务：把 cellchat_service 暴露给外部
# 这里的 callable 返回的就是那个单例对象
RServiceManager.register('get_cellchat_service', callable=lambda: cellchat_service)

def start_worker(socket_path, auth_key):
    """启动监听服务"""
    # 移除旧的 socket 文件，否则会报错 "Address already in use"
    if os.path.exists(socket_path):
        os.remove(socket_path)

    print(f"🚀 [R-Worker] 正在 Conda 环境中启动... (Socket: {socket_path})")
    
    # 绑定 Unix Domain Socket
    manager = RServiceManager(address=socket_path, authkey=auth_key)
    server = manager.get_server()
    
    print("✅ [R-Worker] 服务已就绪，等待 Django 连接...")
    server.serve_forever()

if __name__ == '__main__':
    # 从命令行接收参数
    if len(sys.path) < 3:
        # 默认参数 (测试用)
        socket = '/tmp/cellchat_r_socket'
        key = b'secret'
    else:
        socket = sys.argv[1]
        key = sys.argv[2].encode('utf-8')

    start_worker(socket, key)