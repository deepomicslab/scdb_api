import os
import sys
import django

# ================= 1. 修改配置区域 =================
# 更改路径为 Intestine 的路径
BASE_DIR = "/data3/platform/sc_db/scgpt/data/cellxgene/st/intestine"
ORGAN_NAME = "Intestine"

# 映射表
FOLDER_TO_DISEASE_MAP = {
    'cancer': 'Cancer',
    # 如果之后有别的文件夹，可以在这里加
}

# ⚠️ 根目录下文件的默认分类
# 因为你的目录结构是：根目录有一些文件，cancer 文件夹里有一些文件。
# 通常根目录下的文件默认为 Normal (正常组织)，如果不准确请修改这里。
ROOT_DIR_DISEASE = 'Normal'

# DRY_RUN = True  # 先空跑看一眼 ID 对不对
DRY_RUN = False # 正式写入
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
        # 排除规则：跳过 sc 目录
        if os.path.basename(root) == 'sc':
            continue
            
        current_folder_name = os.path.basename(root)
        
        # ================= 2. 核心逻辑修改 =================
        # 以前的代码这里有一句 if root == BASE_DIR: continue
        # 我把它删掉了！因为你现在根目录下有文件 (例如 35eff8ad....h5ad)
        
        # 判断 Disease
        if root == BASE_DIR:
            # 如果是在根目录找到的文件，使用我们上面定义的默认值 (Normal)
            disease_label = ROOT_DIR_DISEASE
        else:
            # 如果是在子文件夹 (如 cancer)，则查表或使用文件夹名
            disease_label = FOLDER_TO_DISEASE_MAP.get(current_folder_name, current_folder_name)
        # ==================================================
        
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

            # 打印的时候加上 [ROOT] 标记方便你看是不是根目录文件
            loc_tag = "[ROOT]" if root == BASE_DIR else f"[{current_folder_name}]"

            print(f"📄 {loc_tag} 发现: {file}")
            print(f"   🆔 ID: {ds_id} | 🏷️ Disease: {disease_label}")

            if not DRY_RUN:
                try:
                    obj, created = Dataset.objects.update_or_create(
                        dataset_id=ds_id,
                        defaults={
                            'title': title, # 你可能想手动改成更易读的名字，暂时用文件名
                            'file_path': full_path,
                            'organ': ORGAN_NAME,
                            'disease': disease_label,
                            'description': ""
                        }
                    )
                    status = "🆕" if created else "♻️"
                    # 这里只会显示 Spots，Donor数需要你的 Model 逻辑正确才能算出来
                    print(f"   ✅ {status} 入库成功 (Spots: {obj.n_spots})")
                except Exception as e:
                    print(f"   ❌ 失败: {e}")
            
            total_files += 1

    print("="*30)
    print(f"🏁 扫描结束。共处理 {total_files} 个文件。")

if __name__ == '__main__':
    run_import()