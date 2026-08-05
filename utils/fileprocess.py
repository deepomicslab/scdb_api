import os

def get_gene_list(directory):
    """
    # get the part after the underscore in every file name in the directory,
# return as a list; used by batcheffect
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
                # if the file name has no underscore, ignore it or handle otherwise
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
                # if the file name has no underscore, ignore it or handle otherwise
                pass
    return file_names_without_extension, clusterdict