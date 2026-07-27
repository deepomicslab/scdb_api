import os
import glob
import json
import time
import subprocess
from dataset.models import Dataset
from task.apps import r_proxy


class CellChatMixin:
    """CellChat cell-cell interaction result methods for Scstquery."""

    def run_cellchat_api(self, rds_path, method, signaling=None, lrpair=None, output_file=None):
        import time, os, subprocess, json

        if output_file is None:
            timestamp = int(time.time())
            filename = f"api_{method}_{signaling or 'default'}_{timestamp}.json"
            output_file = os.path.join("/tmp", filename)

        cmd = [
            "/data3/platform/sc_db/miniconda3/bin/conda", "run", "-p", "/data3/platform/sc_db/cellchat/env",
            "Rscript", "/data3/platform/sc_db/cellchat/api/api.R",
            f"--rds_path={rds_path}",
            f"--method={method}",
            f"--output_file={output_file}"
        ]
        if signaling:
            cmd.append(f"--signaling={signaling}")
        if lrpair:
            cmd.append(f"--lrpair={lrpair}")

        print("Running command:", " ".join(cmd))

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            if os.path.exists(output_file):
                os.unlink(output_file)
            raise RuntimeError(f"R script error: {result.stderr}")

        if os.path.exists(output_file):
            try:
                with open(output_file, 'r') as f:
                    output = json.load(f)
                os.unlink(output_file)
                return output
            except json.JSONDecodeError as e:
                os.unlink(output_file)
                print("Raw R output:\n", result.stdout)
                raise e
        else:
            raise RuntimeError("Output file not created")

    
    def _find_cellchat_rds(self, dataset, mapping_method=None):
        """根据 dataset_id 定位 subtask_cellchat 的 RDS 文件"""
        if getattr(self, '_is_demo', False):
            if mapping_method:
                method_path = os.path.join(self.path, 'result', 'sc_st_mapping', mapping_method, 'cellchat_result.rds')
                if os.path.exists(method_path):
                    return method_path
            rds_files = glob.glob(os.path.join(self.path, 'result', 'cellchat', '*.rds'))
            return rds_files[0] if rds_files else None
        if not dataset:
            raise ValueError('dataset is required')
        try:
            db_obj = Dataset.objects.get(dataset_id=dataset)
        except Dataset.DoesNotExist:
            return None
        base = os.path.join(self.path, f'dataset_{db_obj.title}', 'subtask_cellchat', 'result')
        if mapping_method:
            new_path = os.path.join(base, 'sc_st_mapping', mapping_method, 'cellchat_result.rds')
            if os.path.exists(new_path):
                return new_path
        old_path = os.path.join(base, 'cellchat_result.rds')
        return old_path if os.path.exists(old_path) else None

    def getCellChatPathways(self, dataset=None, mapping_method=None):
        rds_path = self._find_cellchat_rds(dataset, mapping_method)
        if not rds_path:
            return {'data': {}, 'status': 'error', 'message': 'CellChat rds file not found'}
        if not r_proxy:
            return {'data': {}, 'status': 'error', 'message': "CellChat R Service not linked"}
        try:
            data = r_proxy.get_pathways(rds_path)
            return {'data': data, 'status': 'success'}
        except Exception as e:
            return {'data': {}, 'status': 'error', 'message': str(e)}

    def getCellChatCircleData(self, pathway, dataset=None, mapping_method=None):
        rds_path = self._find_cellchat_rds(dataset, mapping_method)
        if not rds_path:
            return {'data': {}, 'status': 'error', 'message': 'CellChat rds file not found'}
        if not r_proxy:
            return {'data': {}, 'status': 'error', 'message': "CellChat R Service not linked"}
        try:
            data = r_proxy.get_circle(rds_path, signaling=pathway)
            return {'data': data, 'status': 'success'}
        except Exception as e:
            return {'data': {}, 'status': 'error', 'message': str(e)}

    def _read_tissue_hires_scalef(self, dataset):
        """从原始 h5ad 的 uns/spatial 读 tissue_hires_scalef（fullres->hires 缩放因子）"""
        try:
            db_obj = Dataset.objects.get(dataset_id=dataset)
        except Dataset.DoesNotExist:
            return None
        if not db_obj.file_path or not os.path.exists(db_obj.file_path):
            return None
        try:
            import h5py
            with h5py.File(db_obj.file_path, 'r') as f:
                uns_spatial = f.get('uns/spatial')
                if not uns_spatial:
                    return None
                for lib in uns_spatial.keys():
                    sf_path = f'uns/spatial/{lib}/scalefactors/tissue_hires_scalef'
                    if sf_path in f:
                        val = f[sf_path][()]
                        return float(val)
        except Exception as e:
            print(f'[_read_tissue_hires_scalef] error: {e}')
        return None

    def getCellChatSpatialData(self, pathway, dataset=None, mapping_method=None):
        rds_path = self._find_cellchat_rds(dataset, mapping_method)
        if not rds_path:
            return {'data': {}, 'status': 'error', 'message': 'CellChat rds file not found'}
        if not r_proxy:
            return {'data': {}, 'status': 'error', 'message': "CellChat R Service not linked"}
        try:
            data = r_proxy.get_spatial(rds_path, signaling=pathway)
            # R 端 CellChat 返回的 background_spots 坐标是 fullres 像素，
            # 而 getImg 返回的 H&E 底图是 hires 缩略图，需乘 tissue_hires_scalef 对齐
            if data and isinstance(data, dict) and 'background_spots' in data and dataset:
                scalef = self._read_tissue_hires_scalef(dataset)
                if scalef and scalef != 1.0:
                    spots = data['background_spots']
                    if isinstance(spots, dict):
                        for spot_id, spot in spots.items():
                            if isinstance(spot, dict) and 'x' in spot and 'y' in spot:
                                spot['x'] = float(spot['x']) * scalef
                                spot['y'] = float(spot['y']) * scalef
            return {'data': data, 'status': 'success'}
        except Exception as e:
            return {'data': {}, 'status': 'error', 'message': str(e)}

    def getCellChatHeatmapData(self, LR_pair, dataset=None, mapping_method=None):
        rds_path = self._find_cellchat_rds(dataset, mapping_method)
        if not rds_path:
            return {'data': {}, 'status': 'error', 'message': 'CellChat rds file not found'}
        if not r_proxy:
            return {'data': {}, 'status': 'error', 'message': "CellChat R Service not linked"}
        try:
            data = r_proxy.get_heatmap(rds_path, lrpair=LR_pair)
            return {'data': data, 'status': 'success'}
        except Exception as e:
            return {'data': {}, 'status': 'error', 'message': str(e)}

    def getCellChatLRPairs(self, dataset=None, mapping_method=None):
        rds_path = self._find_cellchat_rds(dataset, mapping_method)
        if not rds_path:
            return {'data': {}, 'status': 'error', 'message': 'CellChat rds file not found'}
        if not r_proxy:
            return {'data': {}, 'status': 'error', 'message': "CellChat R Service not linked"}
        try:
            data = r_proxy.get_pairLRs(rds_path)
            return {'data': data, 'status': 'success'}
        except Exception as e:
            return {'data': {}, 'status': 'error', 'message': str(e)}
