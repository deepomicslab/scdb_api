import os
import sys
import django

# ================= 1. 配置区域 =================
BASE_DIR = "/data3/platform/sc_db/scgpt/data/cellxgene/st/liver"
ORGAN_NAME = "Liver"
DEFAULT_DISEASE = "Normal"

# DRY_RUN = True  # 先空跑检查 ID 顺序
DRY_RUN = False # 正式写入
# ===========================================

sys.path.append(os.getcwd())
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'scdb_api.settings')
django.setup()

from dataset.models import Dataset

def generate_dataset_id(organ, disease, index):
    return f"{organ.capitalize()}_{disease}_{index:03d}"

def run_import():
    print(f"🚀 开始扫描 Liver 根目录: {BASE_DIR}")
    
    idx_counter = 1 
    total_files = 0
    
    # 1. 获取文件列表并排序 (保证 ID 生成顺序固定)
    all_items = os.listdir(BASE_DIR)
    all_items.sort()

    for file_name in all_items:
        full_path = os.path.join(BASE_DIR, file_name)
        
        # 2. 严格过滤：必须是文件
        if not os.path.isfile(full_path):
            continue
            
        # 3. 必须是 .h5ad
        if not file_name.endswith('.h5ad'):
            continue

        # 4. 排除统计文件
        if 'donor_stats' in file_name:
            continue

        # === 准备入库 ===
        # 生成 ID: Liver_Normal_001 ...
        ds_id = generate_dataset_id(ORGAN_NAME, DEFAULT_DISEASE, idx_counter)
        idx_counter += 1
        
        title = file_name.replace('.h5ad', '')

        print(f"📄 发现: {file_name}")
        print(f"   🆔 ID: {ds_id} | 🏷️ Disease: {DEFAULT_DISEASE}")

        if not DRY_RUN:
            try:
                obj, created = Dataset.objects.update_or_create(
                    dataset_id=ds_id,
                    defaults={
                        'title': title,
                        'file_path': full_path,
                        'organ': ORGAN_NAME,
                        'disease': DEFAULT_DISEASE,
                        'description': "Imported from Liver root dir"
                    }
                )
                status = "🆕" if created else "♻️"
                print(f"   ✅ {status} 成功 (Spots: {obj.n_spots})")
            except Exception as e:
                print(f"   ❌ 失败: {e}")
        
        total_files += 1

    print("="*30)
    print(f"🏁 结束。共入库: {total_files} 个文件。")

if __name__ == '__main__':
    run_import()