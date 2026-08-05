from rest_framework.decorators import api_view
from rest_framework.response import Response
from django.http import FileResponse
from django.db.models import Count, Sum, Q
import os
import time
import h5py
import numpy as np
import pandas as pd
from collections import Counter

from .models import Dataset, GlobalStat
from utils.spatial_calibration import read_spatial_calibration

# ================================
# 1. Global stats (Hero Stats) - very fast
# ================================
@api_view(['GET'])
def global_stats(request):
    """
    Corresponds to the 4 big numbers at the top of the page
    """
    gs = GlobalStat.objects.first()
    
    if gs:
        data = {
            'total_spots': gs.total_spots,
            'total_datasets': gs.total_datasets,
            'total_donors': gs.total_donors,
            'total_organs': gs.total_organs,
        }
    else:
        data = {
            'total_spots': 0, 'total_datasets': 0, 
            'total_donors': 0, 'total_organs': 0
        }
    
    return Response({'status': 'success', 'data': data})

# ================================
# 2. Organ stats (Organ List & Charts) - SQL aggregation
# ================================
@api_view(['GET'])
def organ_stats(request):
    rows = (
        Dataset.objects
        .values('organ')
        .annotate(
            datasets=Count('id'),
            spots=Sum('n_spots'),
            donors=Sum('n_donors'),
            normal_donors=Sum('n_donors', filter=Q(disease='Normal')),
            disease_donors=Sum('n_donors', filter=~Q(disease='Normal')),
        )
        .order_by('organ')
    )

    agg_result = {}
    for row in rows:
        organ = row['organ'] or 'Unknown'
        agg_result[organ] = {
            'datasets': row['datasets'],
            'spots': row['spots'] or 0,
            'donors': row['donors'] or 0,
            'normal_donors': row['normal_donors'] or 0,
            'disease_donors': row['disease_donors'] or 0,
        }

    return Response({'status': 'success', 'data': agg_result})

# ================================
# 3. Dataset table (Table List) - slower
# ================================
@api_view(['GET'])
def dataset_list(request):
    """
    Return the full data for the bottom table
    """
    datasets = Dataset.objects.all().values(
        'dataset_id', 
        'title', 
        'organ',
        'disease', 
        'n_spots', 
        'n_donors',
        'citation_label',
        'citation_url',
        'collection_url',
        'explorer_url', 
        'created_at'
    ).order_by('created_at')
    
    return Response({'status': 'success', 'data': list(datasets)})

# ================================
# 4. Cell type stats (pie chart) - cached
# ================================
_celltype_cache = {}
_celltype_cache_time = {}
_CELLTYPE_CACHE_TTL = 60


@api_view(['GET'])
def celltype_stats(request):
    target_organ = request.GET.get('organ', 'All') or 'All'
    cache_key = target_organ.lower()

    now = time.time()
    if cache_key in _celltype_cache and (now - _celltype_cache_time.get(cache_key, 0)) < _CELLTYPE_CACHE_TTL:
        return Response({'status': 'success', 'data': _celltype_cache[cache_key]})

    if target_organ != 'All':
        counts_list = Dataset.objects.filter(organ__iexact=target_organ).values_list('cell_type_counts', flat=True)
    else:
        counts_list = Dataset.objects.values_list('cell_type_counts', flat=True)

    global_counter = Counter()
    for counts in counts_list:
        if counts:
            global_counter.update(counts)

    result_list = [{'name': k, 'value': v} for k, v in global_counter.items()]
    result_list.sort(key=lambda x: x['value'], reverse=True)

    if len(result_list) > 10:
        top_10 = result_list[:10]
        others_count = sum(item['value'] for item in result_list[10:])
        top_10.append({'name': 'Others', 'value': others_count})
        result_list = top_10

    _celltype_cache[cache_key] = result_list
    _celltype_cache_time[cache_key] = now

    return Response({'status': 'success', 'data': result_list})

# ================================
# 5. Detail page Info (unchanged)
# ================================
@api_view(['GET'])
def detail_info(request, dataset_id):
    try:
        ds = Dataset.objects.get(dataset_id=dataset_id)
        return Response({
            'status': 'success',
            'data': {
                'dataset_id': ds.dataset_id,
                'title': ds.title,
                'organ': ds.organ,
                'disease': ds.disease,
                'description': ds.description,
                'n_spots': ds.n_spots,
                'n_donors': ds.n_donors,
                'has_image': ds.has_image(),
            }
        })
    except Dataset.DoesNotExist:
        return Response({'status': 'error', 'message': 'Dataset not found'}, status=404)

# ================================
# 6. Detail page Scatter (vectorized + long TTL cache)
# ================================
_scatter_cache = {}
_SCATTER_CACHE_TTL = 3600


def _scatter_first_truthy(df, cols):
    s = None
    for c in cols:
        if c in df.columns:
            v = df[c].replace('', np.nan)
            s = v if s is None else s.fillna(v)
    if s is None:
        return pd.Series('Unknown', index=df.index)
    return s.fillna('Unknown')


def _h5ad_obs_cols(f, target_cols):
    """Read the given /obs columns directly with h5py (bypasses scanpy's full
    load of uns images, speeding up the first call).

    Categorical columns are Groups in h5ad (codes + categories); string/numeric
    columns are Datasets.
    """
    obs = f['obs']
    data = {}
    for col in target_cols:
        if col not in obs:
            continue
        obj = obs[col]
        if isinstance(obj, h5py.Group):
            codes = np.asarray(obj['codes'][:])
            categories = np.asarray(obj['categories'][:])
            if categories.dtype.kind == 'S':
                categories = np.array([c.decode('utf-8', 'replace') for c in categories])
            elif categories.dtype.kind == 'O':
                # categories elements may be raw bytes (object dtype); assigning
                # them directly leaves bytes in vals -> astype(str) would yield "b'B cell'"
                categories = np.array(
                    [c.decode('utf-8', 'replace') if isinstance(c, bytes) else c for c in categories]
                )
            vals = np.empty(len(codes), dtype=object)
            vals[:] = 'Unknown'
            mask = (codes >= 0) & (codes < len(categories))
            vals[mask] = categories[codes[mask]]
            data[col] = vals
        else:
            v = np.asarray(obj[:])
            if v.dtype.kind == 'S':
                v = np.array([x.decode('utf-8', 'replace') for x in v])
            elif v.dtype.kind == 'O':
                # object-dtype array elements may be bytes (undecoded string columns);
                # astype(str) directly would produce reprs like "b'unknown'"
                v = np.array(
                    [x.decode('utf-8', 'replace') if isinstance(x, bytes) else x for x in v],
                    dtype=object,
                )
            data[col] = v
    return data


@api_view(['GET'])
def detail_scatter(request, dataset_id):
    try:
        now = time.time()
        cached = _scatter_cache.get(dataset_id)
        if cached and cached[1] > now:
            return Response(cached[0])

        ds = Dataset.objects.get(dataset_id=dataset_id)
        file_path = ds.file_path

        if not os.path.exists(file_path):
            return Response({'status': 'error', 'message': 'File not found'}, status=404)

        target_cols = ['cell_type', 'annotation', 'Label', 'donor', 'donor_id', 'tissue']
        with h5py.File(file_path, 'r') as f:
            obsm_keys = list(f['obsm'].keys())
            coords = None
            coord_type = 'spatial'
            for k in ('spatial', 'X_spatial', 'X_umap'):
                if k in f['obsm']:
                    coords = np.asarray(f['obsm'][k][:])
                    if k == 'X_umap':
                        coord_type = 'umap'
                    break

            if coords is None:
                return Response({'status': 'error', 'message': 'No coordinates found'}, status=500)

            tissue_hires_scalef = None
            spot_diameter_fullres = None
            if coord_type == 'spatial' and 'spatial' in f['uns']:
                tissue_hires_scalef, spot_diameter_fullres = read_spatial_calibration(dataset_id)

            obs_data = _h5ad_obs_cols(f, target_cols)
            index = np.asarray(f['obs']['_index'][:])
            if index.dtype.kind == 'S':
                index = np.array([x.decode('utf-8', 'replace') for x in index])
            df = pd.DataFrame(obs_data, index=index.astype(str))

        available_cols = [c for c in target_cols if c in df.columns]
        for col in df.columns:
            df[col] = df[col].fillna('Unknown')
        if available_cols:
            df[available_cols] = df[available_cols].astype(str)

        if 'Label' in df.columns:
            label_series = df['Label']
        else:
            label_series = _scatter_first_truthy(df, ['cell_type', 'annotation', 'Label'])
        if 'donor' in df.columns:
            donor_series = df['donor']
        else:
            donor_series = _scatter_first_truthy(df, ['donor_id', 'donor'])

        df['x'] = coords[:, 0].astype(float)
        df['y'] = coords[:, 1].astype(float)
        df['Label'] = label_series
        df['donor'] = donor_series
        df.index = df.index.astype(str)

        data_dict = df.to_dict(orient='index')

        body = {
            'status': 'success',
            'data': data_dict,
            'coord_type': coord_type,
            'tissue_hires_scalef': tissue_hires_scalef,
            'spot_diameter_fullres': spot_diameter_fullres,
        }
        _scatter_cache[dataset_id] = (body, time.time() + _SCATTER_CACHE_TTL)
        return Response(body)

    except Exception as e:
        print('[detail_scatter]', e)
        return Response({'status': 'error', 'message': str(e)}, status=500)
    

# ================================
# 7. Download H5AD file endpoint (new)
# ================================
@api_view(['GET'])
def download_h5ad(request, dataset_id):
    """
    Stream the .h5ad file
    """
    try:
        ds = Dataset.objects.get(dataset_id=dataset_id)
        file_path = ds.file_path
        
        if not os.path.exists(file_path):
            return Response({'status': 'error', 'message': 'File not found on server'}, status=404)

        # Open the file handle
        # FileResponse closes the file automatically and handles headers such as Content-Length
        file_handle = open(file_path, 'rb')
        response = FileResponse(file_handle)
        # Streaming gzip on a GB-scale h5ad would blow up the CPU - explicit
        # identity lets GZipMiddleware skip it
        response['Content-Encoding'] = 'identity'
        
        # Set the download file name (the name shown by the browser when downloading)
        # Defaults to {dataset_id}.h5ad here
        filename = f"{ds.dataset_id}.h5ad"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        
        return response

    except Dataset.DoesNotExist:
        return Response({'status': 'error', 'message': 'Dataset ID not found'}, status=404)
    except Exception as e:
        return Response({'status': 'error', 'message': str(e)}, status=500)


# ================================
# 8. Gene expression lookup (per-spot, single dataset)
# ================================
_gene_spot_cache = {}
_GENE_CACHE_TTL = 3600


def _h5ad_attr_str(attrs, key, default):
    v = attrs.get(key, default)
    if isinstance(v, bytes):
        v = v.decode('utf-8', 'replace')
    return v


def _h5ad_str_array(arr):
    a = np.asarray(arr)
    if a.dtype.kind == 'S':
        a = np.array([x.decode('utf-8', 'replace') for x in a])
    elif a.dtype.kind == 'O':
        a = np.array(
            [x.decode('utf-8', 'replace') if isinstance(x, bytes) else x for x in a],
            dtype=object,
        )
    return a.astype(str)


def _var_col_values(f, col):
    """Read the values of a var column (supports categorical Group / Dataset), returns a str array."""
    obj = f['var'][col]
    if isinstance(obj, h5py.Group):
        codes = np.asarray(obj['codes'][:])
        categories = _h5ad_str_array(obj['categories'][:])
        vals = np.array(
            [categories[int(c)] if 0 <= int(c) < len(categories) else '' for c in codes],
            dtype=object,
        )
        return vals.astype(str)
    return _h5ad_str_array(obj[:])


def _strip_ensembl_suffix(names):
    """feature_name looks like 'A1BG_ENSG00000121410' -> 'A1BG'; returned unchanged if there is no _ENSG suffix."""
    cleaned = np.empty(len(names), dtype=object)
    for i, n in enumerate(names):
        if '_ENSG' in n:
            cleaned[i] = n.split('_ENSG')[0]
        else:
            cleaned[i] = n
    return cleaned.astype(str)


def _find_gene_col(f, gene):
    """Locate the gene column in var. Tries the index column / gene_symbols /
    gene_ids / feature_name in order, exact match first then case-insensitive;
    feature_name additionally strips the '_ENSG' suffix (CELLxGENE concatenated format).
    Returns (column index, match source) or (None, None)."""
    index_col = _h5ad_attr_str(f['var'].attrs, '_index', '_index')
    candidates = [index_col] if index_col in f['var'] else []
    for extra in ('gene_symbols', 'gene_ids', 'feature_name'):
        if extra in f['var'] and extra not in candidates:
            candidates.append(extra)

    gene_lower = gene.lower()
    for cand in candidates:
        names = _var_col_values(f, cand)
        hits = np.where(names == gene)[0]
        if hits.size:
            return int(hits[0]), cand
        hits = np.where(np.char.lower(names) == gene_lower)[0]
        if hits.size:
            return int(hits[0]), cand
        if cand == 'feature_name':
            cleaned = _strip_ensembl_suffix(names)
            hits = np.where(cleaned == gene)[0]
            if hits.size:
                return int(hits[0]), cand
            hits = np.where(np.char.lower(cleaned) == gene_lower)[0]
            if hits.size:
                return int(hits[0]), cand
    return None, None


def _extract_gene_column(f, col_idx):
    """Extract the expression vector of the col_idx-th gene from X (supports csr / csc / dense)."""
    X = f['X']
    if isinstance(X, h5py.Group):
        indptr = np.asarray(X['indptr'][:])
        indices = np.asarray(X['indices'][:])
        data = np.asarray(X['data'][:], dtype=float)
        encoding = _h5ad_attr_str(X.attrs, 'encoding-type', 'csr_matrix')
        n = len(indptr) - 1
        expr = np.zeros(n, dtype=float)
        if encoding == 'csc_matrix':
            start, end = indptr[col_idx], indptr[col_idx + 1]
            expr[indices[start:end]] = data[start:end]
        else:
            pos = np.where(indices == col_idx)[0]
            if pos.size:
                rows = np.searchsorted(indptr, pos, side='right') - 1
                expr[rows] = data[pos]
        return expr
    return np.asarray(X[:, col_idx], dtype=float).ravel()


@api_view(['GET'])
def dataset_gene_expression(request, dataset_id):
    """Per-spot gene expression for a single dataset (returns only non-zero spots, for scatter coloring).

    GET /dataset/detail/<id>/gene/?gene=CD68
    """
    gene = (request.GET.get('gene') or '').strip()
    if not gene:
        return Response({'status': 'error', 'message': 'gene parameter is required'}, status=400)

    try:
        ds = Dataset.objects.get(dataset_id=dataset_id)
    except Dataset.DoesNotExist:
        return Response({'status': 'error', 'message': 'Dataset not found'}, status=404)

    cache_key = f"{dataset_id}|{gene.lower()}"
    now = time.time()
    cached = _gene_spot_cache.get(cache_key)
    if cached and cached[1] > now:
        return Response(cached[0])

    file_path = ds.file_path
    if not file_path or not os.path.exists(file_path):
        return Response({'status': 'error', 'message': 'File not found'}, status=404)

    try:
        with h5py.File(file_path, 'r') as f:
            col_idx, matched_by = _find_gene_col(f, gene)
            if col_idx is None:
                body = {
                    'status': 'success',
                    'gene': gene,
                    'matched': False,
                    'matched_by': None,
                    'min': 0.0,
                    'max': 0.0,
                    'n_expressed': 0,
                    'data': {},
                }
                return Response(body)

            expr = _extract_gene_column(f, col_idx)
            index_col = _h5ad_attr_str(f['obs'].attrs, '_index', '_index')
            barcodes = _h5ad_str_array(f['obs'][index_col][:])

        nz = np.where(expr != 0)[0]
        data = {barcodes[i]: float(expr[i]) for i in nz}
        body = {
            'status': 'success',
            'gene': gene,
            'matched': True,
            'matched_by': matched_by,
            'min': float(expr.min()) if expr.size else 0.0,
            'max': float(expr.max()) if expr.size else 0.0,
            'n_expressed': int(nz.size),
            'data': data,
        }
        _gene_spot_cache[cache_key] = (body, time.time() + _GENE_CACHE_TTL)
        return Response(body)

    except Exception as e:
        print('[gene_expression]', e)
        return Response({'status': 'error', 'message': str(e)}, status=500)


# ================================
# 9. Gene name suggestions (Gene selector dropdown)
# ================================
_gene_suggest_cache = {}
_GENE_SUGGEST_TTL = 300


@api_view(['GET'])
def dataset_gene_suggest(request, dataset_id):
    """Gene name suggestions for a single dataset (dropdown candidates for the
    gene-coloring selector on the detail page).

    GET /dataset/detail/<id>/gene/suggest/?q=CD&limit=20
    """
    q = (request.GET.get('q') or '').strip()
    try:
        limit = int(request.GET.get('limit', 20))
    except (TypeError, ValueError):
        limit = 20
    limit = max(1, min(limit, 50))

    if not q:
        return Response({'status': 'success', 'symbols': []})

    try:
        ds = Dataset.objects.get(dataset_id=dataset_id)
    except Dataset.DoesNotExist:
        return Response({'status': 'error', 'message': 'Dataset not found'}, status=404)

    file_path = ds.file_path
    if not file_path or not os.path.exists(file_path):
        return Response({'status': 'error', 'message': 'File not found'}, status=404)

    cache_key = f"{dataset_id}|{q.lower()}|{limit}"
    now = time.time()
    cached = _gene_suggest_cache.get(cache_key)
    if cached and cached[1] > now:
        return Response(cached[0])

    try:
        with h5py.File(file_path, 'r') as f:
            if 'feature_name' in f['var']:
                names = _strip_ensembl_suffix(_var_col_values(f, 'feature_name'))
            elif 'gene_symbols' in f['var']:
                names = _var_col_values(f, 'gene_symbols')
            else:
                index_col = _h5ad_attr_str(f['var'].attrs, '_index', '_index')
                names = _var_col_values(f, index_col)

        q_lower = q.lower()
        hits = np.char.find(np.char.lower(names), q_lower) >= 0
        matched = names[hits]
        prefix = np.char.startswith(np.char.lower(matched), q_lower)
        ordered = np.concatenate([matched[prefix], matched[~prefix]])

        seen = set()
        symbols = []
        for name in ordered:
            s = str(name)
            if not s or s in seen:
                continue
            seen.add(s)
            symbols.append(s)
            if len(symbols) >= limit:
                break

        body = {'status': 'success', 'symbols': symbols}
        _gene_suggest_cache[cache_key] = (body, time.time() + _GENE_SUGGEST_TTL)
        return Response(body)

    except Exception as e:
        print('[gene_suggest]', e)
        return Response({'status': 'error', 'message': str(e)}, status=500)