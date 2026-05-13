import os
import django
import pandas as pd
import numpy as np

# 1. 初始化 Django 环境
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'scdb_api.settings') # ★★★ 请把 your_project_name 换成你的实际项目名
django.setup()

from dataset.models import Dataset

# 2. 配置路径
csv_path = "/data3/platform/sc_db/scgpt/data/cellxgene/st/dataset_sources_formatted.csv"  # 你刚才生成的 CSV 文件

def update_database():
    print(f"📂 正在读取 CSV: {csv_path} ...")
    
    # 读取 CSV，并将 NaN (空值) 替换为空字符串，防止数据库报错
    df = pd.read_csv(csv_path)
    df = df.replace({np.nan: None}) 
    
    success_count = 0
    skip_count = 0
    
    print(f"🔍 开始处理 {len(df)} 条数据...\n")
    
    for index, row in df.iterrows():
        # 获取 CSV 中的关键信息
        file_path = row.get('File Path')
        citation_label = row.get('citation_label') or ''
        
        # 处理 DOI：如果 CSV 里是 "10.1038/..."，我们需要拼成完整的 URL
        clean_doi = row.get('clean_doi')
        if clean_doi:
            # 简单的判断：如果已经包含 http 就直接用，否则拼接前缀
            if str(clean_doi).startswith('http'):
                citation_url = clean_doi
            else:
                citation_url = f"https://doi.org/{clean_doi}"
        else:
            citation_url = ''
            
        collection_url = row.get('collection_url') or ''
        explorer_url = row.get('explorer_url') or ''
        
        try:
            # ★ 核心对齐逻辑：通过 file_path 查找数据库
            dataset = Dataset.objects.get(file_path=file_path)
            
            # 更新字段
            dataset.citation_label = citation_label
            dataset.citation_url = citation_url
            dataset.collection_url = collection_url
            dataset.explorer_url = explorer_url
            
            # 保存 (只更新这几个字段，提高效率且不触发 Dataset.save 里的读取 h5ad 逻辑)
            dataset.save(update_fields=['citation_label', 'citation_url', 'collection_url', 'explorer_url'])
            
            print(f"✅ [{index+1}] 更新成功: {dataset.dataset_id}")
            success_count += 1
            
        except Dataset.DoesNotExist:
            print(f"⚠️ [{index+1}] 跳过: 数据库中找不到文件路径 -> {os.path.basename(file_path)}")
            skip_count += 1
        except Exception as e:
            print(f"❌ [{index+1}] 出错: {e}")

    print("\n" + "="*30)
    print(f"🎉 完成！成功更新: {success_count} 条，跳过: {skip_count} 条")

if __name__ == "__main__":
    update_database()