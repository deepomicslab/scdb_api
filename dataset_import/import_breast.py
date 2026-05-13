import os
import sys
import django

# ================= 配置区域 =================
BASE_DIR = "/data3/platform/sc_db/scgpt/data/cellxgene/st/breast"
ORGAN_NAME = "Breast"

# 映射表
FOLDER_TO_DISEASE_MAP = {
    'cancer': 'Cancer',
    'GSE195665': 'Normal',  # 我帮你把这俩设为 Normal 了，你可以改回去
    'GSE213688': 'Normal',
}

# DRY_RUN = True
DRY_RUN = False
# ===========================================

sys.path.append(os.getcwd())
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'scdb_api.settings')
django.setup()

from dataset.models import Dataset

def generate_dataset_id(organ, disease, index):
    clean_disease = disease.replace('-', '_').capitalize()
    return f"{organ.capitalize()}_{clean_disease}_{index:03d}"

def run_import():
    print(f"🚀 开始扫描目录: {BASE_DIR}")
    
    counters = {}
    total_files = 0

    for root, dirs, files in os.walk(BASE_DIR):
        # 🔍 Debug: 看看当前走到哪了
        # print(f"正在检查目录: {root}") 
        
        # ⛔️ 修正后的排除规则：
        # 只有当当前文件夹的名字【正好是】'sc' 时才跳过
        if os.path.basename(root) == 'sc':
            # print(f"   🚫 跳过 sc 目录: {root}")
            continue
            
        current_folder_name = os.path.basename(root)
        
        # 跳过根目录本身 (因为文件都在子文件夹里)
        if root == BASE_DIR:
            continue

        disease_label = FOLDER_TO_DISEASE_MAP.get(current_folder_name, current_folder_name)
        
        if disease_label not in counters:
            counters[disease_label] = 1

        for file in files:
            if not file.endswith('.h5ad'):
                continue
            if 'donor_stats' in file:
                continue

            full_path = os.path.join(root, file)
            idx = counters[disease_label]
            ds_id = generate_dataset_id(ORGAN_NAME, disease_label, idx)
            counters[disease_label] += 1
            
            title = file.replace('.h5ad', '')

            print(f"📄 [找到文件] {file}")
            print(f"   器官: {ORGAN_NAME} | 病: {disease_label} | ID: {ds_id} | path: {full_path}")

            if not DRY_RUN:
                try:
                    obj, created = Dataset.objects.update_or_create(
                        dataset_id=ds_id,
                        defaults={
                            'title': title,
                            'file_path': full_path,
                            'organ': ORGAN_NAME,
                            'disease': disease_label,
                            'description': ""
                        }
                    )
                    # 只有真正操作数据库时才打印这些
                    print(f"   ✅ 入库成功 (Spots: {obj.n_spots})")
                except Exception as e:
                    print(f"   ❌ 失败: {e}")
            
            total_files += 1

    print("="*30)
    print(f"🏁 扫描结束。共处理 {total_files} 个文件。")
    if total_files == 0:
        print("❓ 依然没有文件？请检查 BASE_DIR 路径是否完全正确（不要有多余空格）。")

if __name__ == '__main__':
    run_import()