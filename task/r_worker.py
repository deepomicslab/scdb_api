# task/r_worker.py
import sys
import os
import time
import threading
from multiprocessing.managers import BaseManager

# 1. Make sure the current directory's modules can be imported
sys.path.append(os.getcwd())

# 2. Import the original R service logic
# (make sure the R environment config and rpy2 import in cellchat_r_service.py
# are correct and not commented out)
from task.cellchat_r_service import cellchat_service

# 3. Define the manager
class RServiceManager(BaseManager):
    pass

# 4. Register the service: expose cellchat_service to the outside
# The callable here returns that singleton object
RServiceManager.register('get_cellchat_service', callable=lambda: cellchat_service)

def start_worker(socket_path, auth_key):
    """Start the listening service"""
    # Remove the old socket file, otherwise it errors with "Address already in use"
    if os.path.exists(socket_path):
        os.remove(socket_path)

    print(f"🚀 [R-Worker] Starting in the Conda environment... (Socket: {socket_path})")
    
    # Bind the Unix Domain Socket
    manager = RServiceManager(address=socket_path, authkey=auth_key)
    server = manager.get_server()

    # Parent-process death watchdog: when Django exits (including Ctrl+C/SIGKILL),
    # r_worker cleans up the socket and exits
    parent_pid = os.getppid()
    def _watchdog():
        while True:
            if os.getppid() != parent_pid:
                print("🛑 [R-Worker] Parent process (Django) exited, cleaning up socket and terminating.")
                try:
                    os.remove(socket_path)
                except OSError:
                    pass
                os._exit(0)
            time.sleep(1)
    threading.Thread(target=_watchdog, daemon=True).start()

    print("✅ [R-Worker] Service ready, waiting for Django to connect...")
    server.serve_forever()

if __name__ == '__main__':
    # Receive parameters from the command line
    if len(sys.argv) < 3:
        # Default parameters (for testing)
        socket = '/tmp/cellchat_r_socket'
        key = b'secret'
    else:
        socket = sys.argv[1]
        key = sys.argv[2].encode('utf-8')

    start_worker(socket, key)