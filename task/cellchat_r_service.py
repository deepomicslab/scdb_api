# -*- coding: utf-8 -*-

"""
R Service Layer (Caching Mode)

- R environment and rpy2 are initialized ONCE when this module is imported.
- A singleton service `cellchat_service` manages a cache of R API objects.
- Each API call specifies an `rds_path`.
- The service loads the R object for that `rds_path` *once* and caches it for
  all future requests.
"""

import os
import sys
import json
import threading

# 隔离 ~/.local 的 site-packages，避免旧版 numpy/pandas 版本冲突
# conda env 自带兼容版本 (numpy 2.0.2 + pandas 2.2.3)
sys.path = [p for p in sys.path if '.local' not in p]

# ---------------------------
# 1. R Environment Setup (在 rpy2 导入前运行)
# ---------------------------
# !! 确保这些路径在你的生产环境中是正确的 !!
CONDAR_ENV = '/data3/platform/sc_db/cellchat/env'   # ← 你的 conda env 路径
R_HOME = os.path.join(CONDAR_ENV, 'lib', 'R')
R_BIN = os.path.join(CONDAR_ENV, 'bin')
LD_LIB = os.path.join(CONDAR_ENV, 'lib', 'R', 'lib')

os.environ['R_HOME'] = R_HOME
os.environ['PATH'] = R_BIN + ':' + os.environ.get('PATH', '')
os.environ['LD_LIBRARY_PATH'] = LD_LIB + ':' + os.environ.get('LD_LIBRARY_PATH', '')

print(f"Using R_HOME: {os.environ.get('R_HOME')}")

# ---------------------------
# 2. R 脚本路径
# ---------------------------
# !! 确保这个路径是正确的 !!
R_SCRIPT_PATH = '/data3/platform/sc_db/cellchat/api/api.R'

# ---------------------------
# 3. rpy2 导入与激活 (此操作很慢，但在模块加载时只执行一次)
# ---------------------------
try:
    from rpy2 import robjects
    from rpy2.robjects import r, globalenv
    from rpy2.robjects import pandas2ri
    from rpy2.robjects.conversion import localconverter  # ← 新增：用于多线程上下文管理
    # pandas2ri.activate() 已在 rpy2 3.6+ 废弃，改用 localconverter 显式上下文
    from rpy2.robjects.packages import importr
    print("✅ rpy2 imported successfully (R Service INIT).")
except Exception as e:
    print(f"FATAL: Failed to import rpy2. Check R environment variables. Error: {e}", file=sys.stderr)
    # R 无法加载，服务将无法工作
    sys.exit(1)

# ---------------------------
# 4. Source R 脚本 (只执行一次)
# ---------------------------
try:
    r['source'](R_SCRIPT_PATH)
    print(f"✅ Sourced R script successfully: {R_SCRIPT_PATH}")
except Exception as e:
    print(f"FATAL: Failed to source R script: {R_SCRIPT_PATH}. Error: {e}", file=sys.stderr)
    sys.exit(1)
    
# ---------------------------
# 5. 获取 R 函数的引用 (只执行一次)
# ---------------------------
try:
    R_create_api = r['create_api']
    R_get_pathways = r['call_get_pathways']
    R_get_circle = r['call_get_circle']
    R_get_spatial = r['call_get_spatial']
    R_get_pairLRs = r['call_get_pairLRs']
    R_get_heatmap = r['call_get_heatmap']
except Exception as e:
    print(f"FATAL: Could not find required functions (create_api, call_...) in R script. Error: {e}", file=sys.stderr)
    sys.exit(1)


# 自定义错误
class RServiceError(Exception):
    pass

# ---------------------------
# 6. 服务类 (Singleton)
# ---------------------------
class CellChatService:
    """
    管理有状态的 R 'cellchat_api' 对象缓存。
    """
    def __init__(self):
        # 核心缓存: { "rds_path": r_api_object }
        self.api_cache = {}
        self._lock = threading.Lock() # 确保缓存操作的线程安全
        print("CellChatService instance created (Cache is empty).")

    def _get_api(self, rds_path):
        """
        核心逻辑：从缓存中获取或创建 R API 对象。
        """
        # 1. 检查文件是否存在（快速失败）
        if not os.path.exists(rds_path):
            raise RServiceError(f"RDS file not found: {rds_path}")

        # 2. 尝试从缓存中获取
        api_object = self.api_cache.get(rds_path)
        if api_object:
            return api_object # 缓存命中，快速返回

        # 3. 缓存未命中，需要创建（加锁）
        with self._lock:
            # 再次检查，防止在等待锁时其他线程已经加载了它
            api_object = self.api_cache.get(rds_path)
            if api_object:
                return api_object

            # 真正创建
            print(f"🔹 [RService] Caching new RDS: {rds_path}")
            try:
                # 修复：用 localconverter 包装 R 调用，确保多线程上下文传递
                with localconverter(robjects.default_converter):
                    # 调用 R: new_api = create_api(rds_path)
                    new_api = R_create_api(rds_path)
                
                # 存入缓存
                self.api_cache[rds_path] = new_api
                print(f"✅ [RService] Successfully cached: {rds_path}")
                return new_api
            except Exception as e:
                print(f"❌ [RService] FAILED to load {rds_path}. Error: {e}", file=sys.stderr)
                raise RServiceError(f"Error creating R API from {rds_path}: {e}")

    def _call_r_json_method(self, r_function, rds_path, *args):
        """
        通用的R调用辅助函数。
        它首先获取API对象（来自缓存），然后调用R函数。
        """
        # 1. 从缓存获取 (或创建) R-side API 对象
        api_object = self._get_api(rds_path)
        
        # 2. 调用R函数
        try:
            # 修复：用 localconverter 包装 R 调用，确保多线程上下文传递
            with localconverter(robjects.default_converter):
                # 将 R-side api 对象和其它参数传给 R-side wrapper
                res = r_function(api_object, *args)
                # res[0] 是 R 返回的 JSON 字符串
                return json.loads(str(res[0]))
        except Exception as e:
            print(f"Error calling R function {r_function.__name__} for RDS {rds_path}: {e}", file=sys.stderr)
            raise RServiceError(f"R execution error: {e}")

    # --- 公共API方法 ---
    
    def get_pathways(self, rds_path):
        return self._call_r_json_method(R_get_pathways, rds_path)

    def get_circle(self, rds_path, signaling=None):
        if signaling:
            # 修复：signaling 需转换为 R StrVector
            signaling_r = robjects.StrVector([signaling])
            return self._call_r_json_method(R_get_circle, rds_path, signaling_r)
        else:
            return self._call_r_json_method(R_get_circle, rds_path)

    def get_spatial(self, rds_path, signaling=None):
        if signaling:
            # 修复：signaling 需转换为 R StrVector
            signaling_r = robjects.StrVector([signaling])
            return self._call_r_json_method(R_get_spatial, rds_path, signaling_r)
        else:
            return self._call_r_json_method(R_get_spatial, rds_path)

    def get_pairLRs(self, rds_path):
        return self._call_r_json_method(R_get_pairLRs, rds_path)

    def get_heatmap(self, rds_path, lrpair, sample_use=None):
        if lrpair is None:
             raise ValueError("lrpair cannot be None")
             
        # 修复：lrpair 转换为 R StrVector
        lrpair_r = robjects.StrVector([lrpair])
        sample_use_r = robjects.StrVector([sample_use]) if sample_use else None
        
        if sample_use:
            return self._call_r_json_method(R_get_heatmap, rds_path, lrpair_r, sample_use_r)
        else:
            return self._call_r_json_method(R_get_heatmap, rds_path, lrpair_r)

    # --- 管理方法 ---
    
    def get_status(self):
        """返回服务的当前状态。"""
        with self._lock:
            return {
                "cached_rds_files": list(self.api_cache.keys()),
                "cache_size": len(self.api_cache)
            }
            
    def clear_cache(self):
        """清空所有缓存。"""
        with self._lock:
            self.api_cache.clear()
            print("Cleared all R object cache.")


# ---------------------------
# 7. 创建单例实例
# ---------------------------
# 当你从Django的 `views.py` 或 `apps.py` 中 `import` 这个模块时，
# 下面的所有代码（1-5）都会执行，并且这个实例会被创建。
cellchat_service = CellChatService()