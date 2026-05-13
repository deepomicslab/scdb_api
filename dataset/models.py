# dataset/models.py

import os
import anndata as ad
from django.db import models
from django.db.models import Sum, Count
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

CELL_TYPE_COL = 'cell_type'

# === 1. 全局统计表 (新加的) ===
class GlobalStat(models.Model):
    """
    这张表永远只存一行数据 (ID=1)。
    每次 Dataset 变动时，自动更新这里的数字。
    """
    total_spots = models.BigIntegerField("总细胞/Spot数", default=0)
    total_donors = models.IntegerField("总供体数 (去重后)", default=0)
    total_organs = models.IntegerField("覆盖器官数", default=0)
    total_datasets = models.IntegerField("数据集总数", default=0)
    
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"系统统计 (最后更新: {self.updated_at})"

# === 2. 数据集表 (简化版) ===
class Dataset(models.Model):
    dataset_id = models.CharField("系统ID", max_length=100, unique=True)
    title = models.CharField("显示标题", max_length=200)
    file_path = models.CharField("文件绝对路径", max_length=500)
    
    organ = models.CharField("器官 (Organ)", max_length=100)
    disease = models.CharField("疾病 (Disease)", max_length=100, default='Normal')
    description = models.TextField("描述", blank=True, default='')

    # 自动提取字段
    n_spots = models.IntegerField("细胞/Spot数", default=0, editable=False)
    n_donors = models.IntegerField("该数据集供体数", default=0, editable=False)
    donor_list = models.JSONField("供体名单", default=list, editable=False)
    
    # ★ 新增：存储细胞类型统计 { "T-cell": 100, "B-cell": 50 }
    cell_type_counts = models.JSONField("细胞类型分布", default=dict, blank=True, editable=False)
    
    # 1. 引用显示的文字 (例如: "Valdeolivas et al. (2024)...")
    citation_label = models.CharField("引用文本", max_length=500, blank=True, default='')
    
    # 2. 完整的 DOI 链接 (例如: "https://doi.org/10.1038/...")
    citation_url = models.CharField("DOI链接", max_length=500, blank=True, default='')
    
    # 3. Collection 链接
    collection_url = models.CharField("Collection链接", max_length=500, blank=True, default='')
    
    # 4. Explorer 链接
    explorer_url = models.CharField("Explorer链接", max_length=500, blank=True, default='')
    
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        """
        保存时自动从 h5ad 提取元数据
        """
        # 只有在还没提取过 n_spots 或者强制更新时才读取文件（避免每次修改标题都读大文件）
        # 这里简化处理：每次 save 都检查一下文件
        if os.path.exists(self.file_path):
            try:
                # 1. 读取文件 (backed模式节省内存)
                adata = ad.read_h5ad(self.file_path, backed='r')
                
                # 2. 基础信息
                self.n_spots = adata.n_obs
                
                # 3. 供体提取
                obs_keys = adata.obs.keys()
                if 'donor_id' in obs_keys:
                    donors = adata.obs['donor_id'].unique().tolist()
                    self.donor_list = [str(d) for d in donors]
                    self.n_donors = len(self.donor_list)

                # 4. ★ 细胞类型提取 (新增逻辑)
                if CELL_TYPE_COL in obs_keys:
                    # value_counts 获取分布
                    counts = adata.obs[CELL_TYPE_COL].value_counts().to_dict()
                    # 转换 key/value 为标准格式 (防止 numpy int64 导致 JSON 报错)
                    self.cell_type_counts = {str(k): int(v) for k, v in counts.items()}
                    print(f"🧬 [自动提取] {self.dataset_id} 细胞类型统计成功")
                else:
                    print(f"⚠️ [警告] 未在 {self.dataset_id} 中找到列: {CELL_TYPE_COL}")

            except Exception as e:
                print(f"❌ 读取失败 {self.file_path}: {e}")
        
        super().save(*args, **kwargs)

# === 3. 信号触发器 (自动更新总数的核心) ===
# 无论是新增(save) 还是 删除(delete)，都会触发这个函数
@receiver([post_save, post_delete], sender=Dataset)
def refresh_global_stats(sender, **kwargs):
    print("🔄 正在刷新全局统计数据...")
    
    # 1. 简单的聚合计算
    aggs = Dataset.objects.aggregate(
        sum_spots=Sum('n_spots'),
        count_datasets=Count('id'),
        count_organs=Count('organ', distinct=True) # 统计有多少个不重复的 Organ
    )
    
    # 2. 复杂的 Donor 全局去重
    # 获取所有数据集的 donor_list
    all_rows = Dataset.objects.values_list('donor_list', flat=True)
    unique_donors = set()
    for d_list in all_rows:
        if d_list:
            unique_donors.update(d_list)
            
    # 3. 写入 GlobalStat 表
    # get_or_create 保证永远只有一行数据 (id=1)
    stat_obj, _ = GlobalStat.objects.get_or_create(id=1)
    
    stat_obj.total_spots = aggs['sum_spots'] or 0
    stat_obj.total_datasets = aggs['count_datasets'] or 0
    stat_obj.total_organs = aggs['count_organs'] or 0
    stat_obj.total_donors = len(unique_donors)
    
    stat_obj.save()
    print("✅ 全局统计刷新完毕！")