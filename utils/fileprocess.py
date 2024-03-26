import os

def get_gene_list(directory):
    """
    #获取目录下所有文件名中下划线后的部分，返回一个列表, 用于batcheffect
    """
    file_names_without_extension = []
    genepathdict = {}
    for item in os.listdir(directory):
        if os.path.isfile(os.path.join(directory, item)):
            file_name_without_extension, _ = os.path.splitext(item)
            parts = file_name_without_extension.split('_')
            if len(parts) > 1:
                file_names_without_extension.append(parts[1])
                genepathdict[parts[1]] =  item
            else:
                # 如果文件名中没有下划线，你可以选择忽略或者做其他处理
                pass
    return file_names_without_extension, genepathdict

def get_cluster_list(directory):
    file_names_without_extension = []
    clusterdict = {}
    for item in os.listdir(directory):
        if os.path.isfile(os.path.join(directory, item)):
            file_name_without_extension, _ = os.path.splitext(item)
            parts = file_name_without_extension.split('_')
            if len(parts) > 1:
                file_names_without_extension.append(parts[1])
                clusterdict[parts[1]] =  item
            else:
                # 如果文件名中没有下划线，你可以选择忽略或者做其他处理
                pass
    return file_names_without_extension, clusterdict