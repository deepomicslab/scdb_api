import os
import sys
import django

# ================= 1. 配置区域 =================
BASE_DIR = "/data3/platform/sc_db/scgpt/data/cellxgene/st/kidney"
ORGAN_NAME = "Kidney"

# 强制所有数据都叫 Cancer (因为你说没有 Normal)
FORCE_DISEASE_NAME = "Cancer"

# ⛔️ 黑名单：这些文件会被直接跳过
SKIP_FILES = {
    "02fba04c-c5c0-4e44-98f5-e3c5588918f8.h5ad",
    "cbeaecd5-8aeb-4cf0-8a3c-4164c9d62493.h5ad",
}

# DRY_RUN = True  # 先空跑看看 ID 顺序对不对
DRY_RUN = False # 正式写入
# ===========================================

sys.path.append(os.getcwd())
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'scdb_api.settings')
django.setup()

from dataset.models import Dataset

def generate_dataset_id(organ, disease, index):
    return f"{organ.capitalize()}_{disease}_{index:03d}"

def run_import():
    print(f"🚀 开始扫描 Kidney 目录: {BASE_DIR}")
    print(f"🚫 黑名单包含 {len(SKIP_FILES)} 个文件 (将被跳过)")
    
    # 计数器: { 'Cancer': 1 }
    counters = {}
    total_files = 0
    skipped_count = 0

    # 使用 os.walk 因为文件在 cancer/ 子目录里
    for root, dirs, files in os.walk(BASE_DIR):
        
        # 排除 sc 目录 (习惯性保留，防止误伤)
        if os.path.basename(root) == 'sc':
            continue
            
        # 跳过根目录本身 (如果根目录只有 csv 没有 h5ad 的话)
        # 你的 tree 显示根目录只有 donor_stats_global.csv，所以这里不跳过也没事，
        # 因为下面有 endswith('.h5ad') 把关。
        
        # 确定 Disease 标签
        # 既然全是 Cancer，我们就直接用配置好的常量
        disease_label = FORCE_DISEASE_NAME
        
        if disease_label not in counters:
            counters[disease_label] = 1
        
        #为了保证生成ID的顺序在不同机器上一致，建议对文件名排序
        files.sort()

        for file in files:
            # 1. 必须是 h5ad
            if not file.endswith('.h5ad'):
                continue
            
            # 2. 黑名单检查
            if file in SKIP_FILES:
                print(f"🙈 [跳过-黑名单] {file}")
                skipped_count += 1
                continue

            # 3. 排除统计文件 (双重保险)
            if 'donor_stats' in file:
                continue

            full_path = os.path.join(root, file)
            
            # 生成 ID
            idx = counters[disease_label]
            ds_id = generate_dataset_id(ORGAN_NAME, disease_label, idx)
            counters[disease_label] += 1
            
            title = file.replace('.h5ad', '')
            
            # 获取当前文件夹名用于显示
            folder_name = os.path.basename(root)

            print(f"📄 [{folder_name}] 发现: {file}")
            print(f"   🆔 ID: {ds_id} | 🏷️ Disease: {disease_label}")

            if not DRY_RUN:
                try:
                    obj, created = Dataset.objects.update_or_create(
                        dataset_id=ds_id,
                        defaults={
                            'title': title,
                            'file_path': full_path,
                            'organ': ORGAN_NAME,
                            'disease': disease_label,
                            'description': f"Imported from {folder_name}"
                        }
                    )
                    status = "🆕" if created else "♻️"
                    print(f"   ✅ {status} 成功 (Spots: {obj.n_spots})")
                except Exception as e:
                    print(f"   ❌ 失败: {e}")
            
            total_files += 1

    print("="*30)
    print(f"🏁 结束。共入库: {total_files} 个文件。")
    print(f"🗑️ 跳过黑名单: {skipped_count} 个")

if __name__ == '__main__':
    run_import()