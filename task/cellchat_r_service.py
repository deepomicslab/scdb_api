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

# Isolate ~/.local site-packages to avoid conflicts with old numpy/pandas versions
# The conda env ships compatible versions (numpy 2.0.2 + pandas 2.2.3)
sys.path = [p for p in sys.path if '.local' not in p]

# ---------------------------
# 1. R Environment Setup (run before rpy2 is imported)
# ---------------------------
# !! Make sure these paths are correct in your production environment !!
CONDAR_ENV = '/data3/platform/sc_db/cellchat/env'   # <- your conda env path
R_HOME = os.path.join(CONDAR_ENV, 'lib', 'R')
R_BIN = os.path.join(CONDAR_ENV, 'bin')
LD_LIB = os.path.join(CONDAR_ENV, 'lib', 'R', 'lib')

os.environ['R_HOME'] = R_HOME
os.environ['PATH'] = R_BIN + ':' + os.environ.get('PATH', '')
os.environ['LD_LIBRARY_PATH'] = LD_LIB + ':' + os.environ.get('LD_LIBRARY_PATH', '')

print(f"Using R_HOME: {os.environ.get('R_HOME')}")

# ---------------------------
# 2. R script path
# ---------------------------
# !! Make sure this path is correct !!
R_SCRIPT_PATH = '/data3/platform/sc_db/cellchat/api/api.R'

# ---------------------------
# 3. rpy2 import and activation (slow, but only runs once at module load)
# ---------------------------
try:
    from rpy2 import robjects
    from rpy2.robjects import r, globalenv
    from rpy2.robjects import pandas2ri
    from rpy2.robjects.conversion import localconverter  # new: for multithreaded context management
    # pandas2ri.activate() is deprecated in rpy2 3.6+, use explicit localconverter contexts instead
    from rpy2.robjects.packages import importr
    print("✅ rpy2 imported successfully (R Service INIT).")
except Exception as e:
    print(f"FATAL: Failed to import rpy2. Check R environment variables. Error: {e}", file=sys.stderr)
    # R failed to load, the service will not work
    sys.exit(1)

# ---------------------------
# 4. Source the R script (only once)
# ---------------------------
try:
    r['source'](R_SCRIPT_PATH)
    print(f"✅ Sourced R script successfully: {R_SCRIPT_PATH}")
except Exception as e:
    print(f"FATAL: Failed to source R script: {R_SCRIPT_PATH}. Error: {e}", file=sys.stderr)
    sys.exit(1)
    
# ---------------------------
# 5. Get references to the R functions (only once)
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


# Custom error
class RServiceError(Exception):
    pass

# ---------------------------
# 6. Service class (Singleton)
# ---------------------------
class CellChatService:
    """
    Manages a cache of stateful R 'cellchat_api' objects.
    """
    def __init__(self):
        # Core cache: { "rds_path": r_api_object }
        self.api_cache = {}
        self._lock = threading.Lock() # thread safety for cache operations
        print("CellChatService instance created (Cache is empty).")

    def _get_api(self, rds_path):
        """
        Core logic: get or create the R API object from the cache.
        """
        # 1. Check the file exists (fail fast)
        if not os.path.exists(rds_path):
            raise RServiceError(f"RDS file not found: {rds_path}")

        # 2. Try to get it from the cache
        api_object = self.api_cache.get(rds_path)
        if api_object:
            return api_object # cache hit, return fast

        # 3. Cache miss, need to create it (locked)
        with self._lock:
            # Re-check, in case another thread already loaded it while waiting for the lock
            api_object = self.api_cache.get(rds_path)
            if api_object:
                return api_object

            # Actually create it
            print(f"🔹 [RService] Caching new RDS: {rds_path}")
            try:
                # Fix: wrap the R call in localconverter so the context is passed across threads
                with localconverter(robjects.default_converter):
                    # Call R: new_api = create_api(rds_path)
                    new_api = R_create_api(rds_path)
                
                # Store in cache
                self.api_cache[rds_path] = new_api
                print(f"✅ [RService] Successfully cached: {rds_path}")
                return new_api
            except Exception as e:
                print(f"❌ [RService] FAILED to load {rds_path}. Error: {e}", file=sys.stderr)
                raise RServiceError(f"Error creating R API from {rds_path}: {e}")

    def _call_r_json_method(self, r_function, rds_path, *args):
        """
        Generic R-call helper.
        It first gets the API object (from the cache), then calls the R function.
        """
        # 1. Get (or create) the R-side API object from the cache
        api_object = self._get_api(rds_path)
        
        # 2. Call the R function
        try:
            # Fix: wrap the R call in localconverter so the context is passed across threads
            with localconverter(robjects.default_converter):
                # Pass the R-side api object and other args to the R-side wrapper
                res = r_function(api_object, *args)
                # res[0] is the JSON string returned by R
                return json.loads(str(res[0]))
        except Exception as e:
            print(f"Error calling R function {r_function.__name__} for RDS {rds_path}: {e}", file=sys.stderr)
            raise RServiceError(f"R execution error: {e}")

    # --- Public API methods ---
    
    def get_pathways(self, rds_path):
        return self._call_r_json_method(R_get_pathways, rds_path)

    def get_circle(self, rds_path, signaling=None):
        if signaling:
            # Fix: signaling must be converted to an R StrVector
            signaling_r = robjects.StrVector([signaling])
            return self._call_r_json_method(R_get_circle, rds_path, signaling_r)
        else:
            return self._call_r_json_method(R_get_circle, rds_path)

    def get_spatial(self, rds_path, signaling=None):
        if signaling:
            # Fix: signaling must be converted to an R StrVector
            signaling_r = robjects.StrVector([signaling])
            return self._call_r_json_method(R_get_spatial, rds_path, signaling_r)
        else:
            return self._call_r_json_method(R_get_spatial, rds_path)

    def get_pairLRs(self, rds_path):
        return self._call_r_json_method(R_get_pairLRs, rds_path)

    def get_heatmap(self, rds_path, lrpair, sample_use=None):
        if lrpair is None:
             raise ValueError("lrpair cannot be None")
             
        # Fix: lrpair must be converted to an R StrVector
        lrpair_r = robjects.StrVector([lrpair])
        sample_use_r = robjects.StrVector([sample_use]) if sample_use else None
        
        if sample_use:
            return self._call_r_json_method(R_get_heatmap, rds_path, lrpair_r, sample_use_r)
        else:
            return self._call_r_json_method(R_get_heatmap, rds_path, lrpair_r)

    # --- Management methods ---
    
    def get_status(self):
        """Return the current status of the service."""
        with self._lock:
            return {
                "cached_rds_files": list(self.api_cache.keys()),
                "cache_size": len(self.api_cache)
            }
            
    def clear_cache(self):
        """Clear all caches."""
        with self._lock:
            self.api_cache.clear()
            print("Cleared all R object cache.")


# ---------------------------
# 7. Create the singleton instance
# ---------------------------
# When you `import` this module from Django's `views.py` or `apps.py`,
# all the code above (1-5) runs, and this instance is created.
cellchat_service = CellChatService()