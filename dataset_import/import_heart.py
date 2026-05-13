import os
import sys
import django

# ================= 1. 配置区域 =================
BASE_DIR = "/data3/platform/sc_db/scgpt/data/cellxgene/st/heart"
ORGAN_NAME = "Heart"
DEFAULT_DISEASE = "Normal"

# ⛔️ 黑名单：这些文件会被直接跳过
SKIP_FILES = {
    "10a8514a-f843-4d81-835b-18de32b1f8a3.h5ad",
    "31c4fea3-8f50-44ad-b012-fc8274b30bf3.h5ad",
    "366b22f0-58e7-47d3-824f-e88c6fb28f6b.h5ad",
    "42c47fef-56e5-4133-9201-e2254bdc15e5.h5ad",
    "4c861bfb-8276-49d7-8b64-6d905a8b887a.h5ad",
    "4dfc0978-303f-4550-8dcd-0f084f4ea089.h5ad",
    "6a802eb8-81f1-4904-9474-0ff315850d72.h5ad",
    "b2df9cc2-2c45-4d3e-9334-273d13035dc3.h5ad",
    "fbed512d-5a63-434a-80fb-356bb6e9987e.h5ad",
}

# DRY_RUN = True  # 空跑检查
DRY_RUN = False # 正式写入
# ===========================================

sys.path.append(os.getcwd())
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'scdb_api.settings')
django.setup()

from dataset.models import Dataset

def generate_dataset_id(organ, disease, index):
    return f"{organ.capitalize()}_{disease}_{index:03d}"

def run_import():
    print(f"🚀 开始扫描 Heart 根目录 (不包含子文件夹): {BASE_DIR}")
    
    idx_counter = 1 
    total_files = 0
    skipped_count = 0
    
    # ★ 修改点：使用 listdir 只获取当前层级的文件名
    all_items = os.listdir(BASE_DIR)
    # 为了保证 ID 生成顺序一致，最好排个序
    all_items.sort() 

    for file_name in all_items:
        full_path = os.path.join(BASE_DIR, file_name)
        
        # 1. 严格检查：必须是文件 (跳过所有文件夹)
        if not os.path.isfile(full_path):
            # print(f"   📂 忽略文件夹: {file_name}")
            continue
            
        # 2. 必须是 .h5ad
        if not file_name.endswith('.h5ad'):
            continue

        # 3. 黑名单检查
        if file_name in SKIP_FILES:
            print(f"🙈 [跳过-黑名单] {file_name}")
            skipped_count += 1
            continue
            
        if 'donor_stats' in file_name:
            continue

        # === 准备入库 ===
        ds_id = generate_dataset_id(ORGAN_NAME, DEFAULT_DISEASE, idx_counter)
        idx_counter += 1
        
        title = file_name.replace('.h5ad', '')

        print(f"📄 发现: {file_name}")
        print(f"   🆔 ID: {ds_id} | Path: {full_path}")

        if not DRY_RUN:
            try:
                obj, created = Dataset.objects.update_or_create(
                    dataset_id=ds_id,
                    defaults={
                        'title': title,
                        'file_path': full_path,
                        'organ': ORGAN_NAME,
                        'disease': DEFAULT_DISEASE,
                        'description': "Imported from Heart root dir only"
                    }
                )
                status = "🆕" if created else "♻️"
                print(f"   ✅ {status} 成功")
            except Exception as e:
                print(f"   ❌ 失败: {e}")
        
        total_files += 1

    print("="*30)
    print(f"🏁 结束。共入库: {total_files} 个文件。")
    print(f"🗑️ 跳过黑名单文件: {skipped_count} 个")

if __name__ == '__main__':
    run_import()