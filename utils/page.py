import pandas as pd

def paginate_dataframe(df: pd.DataFrame, page_number: int, page_size: int) -> pd.DataFrame:
    """
    返回DataFrame的一个子集，对应于给定的页码和页面大小。

    参数:
    df -- 要分页的Pandas DataFrame
    page_number -- 页码，从1开始
    page_size -- 每页的行数

    返回值:
    分页后的DataFrame，如果页码超出范围，则为空DataFrame
    """
    # 检查输入参数
    if not isinstance(page_number, int) or not isinstance(page_size, int):
        raise ValueError("Page number and page size should be integers.")
    if page_number < 1 or page_size < 1:
        raise ValueError("Page number and page size should be positive integers.")
    
    # 计算起始和结束的索引
    start = (page_number - 1) * page_size
    end = start + page_size
    
    # 检查页码是否超出范围
    if start >= len(df) or start < 0:
        return pd.DataFrame()
    
    # 调整结束索引以避免超出DataFrame的长度
    end = min(end, len(df))

    # 返回分页后的DataFrame
    return df.iloc[start:end]



