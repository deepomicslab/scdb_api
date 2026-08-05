import pandas as pd

def paginate_dataframe(df: pd.DataFrame, page_number: int, page_size: int) -> pd.DataFrame:
    """
    Return a subset of the DataFrame corresponding to the given page number and page size.

    Args:
    df -- the Pandas DataFrame to paginate
    page_number -- page number, starting from 1
    page_size -- number of rows per page

    Returns:
    The paginated DataFrame, or an empty DataFrame if the page number is out of range
    """
    # Validate the input parameters
    if not isinstance(page_number, int) or not isinstance(page_size, int):
        raise ValueError("Page number and page size should be integers.")
    if page_number < 1 or page_size < 1:
        raise ValueError("Page number and page size should be positive integers.")
    
    # Compute the start and end indices
    start = (page_number - 1) * page_size
    end = start + page_size
    
    # Check whether the page number is out of range
    if start >= len(df) or start < 0:
        return pd.DataFrame()
    
    # Clamp the end index to avoid exceeding the DataFrame length
    end = min(end, len(df))

    # Return the paginated DataFrame
    return df.iloc[start:end]



