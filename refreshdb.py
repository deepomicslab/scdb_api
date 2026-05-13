import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'scdb_api.settings') # ⚠️ 改为你项目的 settings 文件夹名
django.setup()

from dataset.models import Dataset

def run():
    print("🚀 开始刷新所有数据集的元数据...")
    datasets = Dataset.objects.all()
    for ds in datasets:
        print(f"🔄 处理: {ds.dataset_id} ...")
        # 调用 save() 会触发我们在 Model 里写的 h5ad 读取逻辑
        ds.save() 
    print("✅ 全部完成！")

if __name__ == '__main__':
    run()