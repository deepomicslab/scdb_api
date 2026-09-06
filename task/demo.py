"""Instant demo-task construction helpers.

Try Demo creates a real tasks/SubTask graph that is already Completed. It
must never submit SLURM work and must never depend on production result
artifacts. The compact workspace fixture below is schema-compatible with the
normal result readers; it is synthetic demo data, not a production analysis.
"""

import json
import os

from task.models import SubTask, TaskStatus, tasks
from task.services import MAPPING_DEPENDENT_TYPES
from utils.mapping_paths import ALL_METHODS, resolve_mapping_output_path


DEMO_DATASET_ID = 'Breast_Normal_002'
DEMO_TASK_NAME = 'Demo Task'
DEMO_JOB_ID = 'viewer_only'
DEMO_DEFAULT_MAPPING_METHOD = 'he_scatter'
DEMO_ORGAN_FALLBACK = 'breast'
DEMO_SPOTS = ['spot_0', 'spot_1', 'spot_2', 'spot_3', 'spot_4']
DEMO_GENES = ['gene_0', 'gene_1', 'gene_2']
DEMO_CELL_TYPES = ['DemoTypeA', 'DemoTypeB']
DEMO_LR_PAIR = 'DEMO_LIGAND_DEMO_RECEPTOR'


def demo_task_parameters(dataset, taskname):
    """Production-shaped Scstquery params for a demo task.

    Scstquery.__init__ requires projectname/organParts/processType, so a demo
    taskdetail.json must contain them even though no pipeline ever runs.
    """
    organ = str(getattr(dataset, 'organ', '') or DEMO_ORGAN_FALLBACK).lower()
    return {
        'projectname': taskname,
        'organParts': organ,
        'processType': 'celltype',
        'disease': 'all',
        'demo': True,
        'dataset_id': dataset.dataset_id,
    }


def demo_subtask_specs(dataset_id, default_method=DEMO_DEFAULT_MAPPING_METHOD):
    """SubTask rows that light every display tool under the default method.

    Method-aware interaction tools carry an explicit mapping_method so the
    frontend cache key subtask_type__mapping_method restores correctly.
    Mapping outputs for all ALL_METHODS are seeded separately as files, which
    is what scstmappingStatus actually checks for completion.
    """
    specs = []
    specs.append(('scst_mapping', {'demo': True, 'dataset_id': dataset_id, 'mapping_method': 'cytospace'}))
    specs.append(('scst_mapping', {'demo': True, 'dataset_id': dataset_id, 'mapping_method': 'tangram'}))
    specs.append(('he_scatter', {'demo': True, 'dataset_id': dataset_id}))
    specs.append(('hierarchical_clustering', {'demo': True, 'dataset_id': dataset_id}))
    specs.append(('annotation_mapping', {'demo': True, 'dataset_id': dataset_id}))
    specs.append(('recall_analysis', {'demo': True, 'dataset_id': dataset_id}))
    for tool in MAPPING_DEPENDENT_TYPES:
        specs.append((tool, {'demo': True, 'dataset_id': dataset_id, 'mapping_method': default_method}))
    specs.append(('scgpt_embedding', {'demo': True, 'dataset_id': dataset_id}))
    specs.append(('umap_embedding', {'demo': True, 'dataset_id': dataset_id}))
    specs.append(('heatmap_embedding', {'demo': True, 'dataset_id': dataset_id}))
    return specs


def create_demo_task_rows(demo_task, dataset_id, default_method=DEMO_DEFAULT_MAPPING_METHOD):
    """Create all Completed demo SubTask rows inside the caller's transaction."""
    for subtask_type, parameters in demo_subtask_specs(dataset_id, default_method):
        SubTask.objects.create(
            main_task=demo_task,
            subtask_type=subtask_type,
            dataset_path=dataset_id,
            status=TaskStatus.COMPLETED,
            job_id=DEMO_JOB_ID,
            parameters=parameters,
        )


def write_demo_workspace(task_abs_path, dataset_id, dataset_title, organ='breast'):
    """Write a compact, schema-valid demo workspace for one dataset.

    Layout mirrors a real task workspace so the normal result readers work:
    result/sc_query/result_scores.json plus dataset_<uuid>/subtask_*/result.
    """
    import anndata as ad
    import numpy as np
    import pandas as pd
    from PIL import Image

    uuid = dataset_title or dataset_id
    rng = np.random.RandomState(7)
    spots = list(DEMO_SPOTS)
    genes = list(DEMO_GENES)

    def ensure_parent(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)

    def write_h5ad(path, obs_names, var_names, obsm=None):
        ensure_parent(path)
        adata = ad.AnnData(
            X=np.ones((len(obs_names), len(var_names)), dtype=np.float32),
            obs=pd.DataFrame(index=list(obs_names)),
            var=pd.DataFrame(index=list(var_names)),
            obsm=dict(obsm or {}),
        )
        adata.write(path)

    # Marker/cluster/filtered inputs referenced by result_scores.json and datasetInfo.
    ref_dir = os.path.join(task_abs_path, 'demo_ref', uuid, 'st_marker')
    marker_path = os.path.join(ref_dir, 'test_marker.csv')
    clusters_path = os.path.join(ref_dir, 'test_clusters.csv')
    filtered_path = os.path.join(task_abs_path, 'demo_ref', uuid, 'st_filtered_adata', 'test_filtered.h5ad')
    marker_df = pd.DataFrame(
        {gene: [1.0, 0.0, 2.0, 1.0, 0.5] for gene in genes},
        index=[f'cluster_{i}' for i in range(5)],
    )
    clusters_df = pd.DataFrame(
        {'cluster': ['DemoTypeA', 'DemoTypeA', 'DemoTypeB', 'DemoTypeB', 'DemoTypeA']},
        index=spots,
    )
    ensure_parent(marker_path)
    marker_df.to_csv(marker_path)
    clusters_df.to_csv(clusters_path)
    ensure_parent(filtered_path)
    ad.AnnData(
        X=np.ones((len(spots), len(genes)), dtype=np.float32),
        obs=pd.DataFrame(
            {'tissue': ['demo_tissue'] * len(spots), 'donor_id': ['demo_donor'] * len(spots)},
            index=spots,
        ),
        var=pd.DataFrame(index=genes),
    ).write(filtered_path)

    # Card list consumed by getOrgansAndDatasets.
    scores_path = os.path.join(task_abs_path, 'result', 'sc_query', 'result_scores.json')
    ensure_parent(scores_path)
    with open(scores_path, 'w', encoding='utf-8') as f:
        json.dump({
            organ: {
                marker_path: {
                    'match_score': 1.0,
                    'pearson_score': 0.516,
                    'match_rank': 1,
                    'pearson_rank': 3,
                    'fused_rank': 1,
                    'fused_score': 0.516,
                }
            }
        }, f, ensure_ascii=False, indent=2)

    # Mapping outputs for every method: scstmappingStatus checks file presence.
    for method in ALL_METHODS:
        method_path = resolve_mapping_output_path(task_abs_path, uuid, method)
        write_h5ad(method_path, ['demo_cell_0', 'demo_cell_1'], genes)

    # Shared HE outputs used by annotation/recall panels.
    he_csv = os.path.join(task_abs_path, 'result', 'he', 'all_merged_data_with_labels.csv')
    ensure_parent(he_csv)
    pd.DataFrame(
        {
            'x': [float(i) for i in range(len(spots))],
            'y': [float(i * 2) for i in range(len(spots))],
            'Label': ['DemoTypeA', 'DemoTypeA', 'DemoTypeB', 'DemoTypeB', 'DemoTypeA'],
        },
        index=spots,
    ).to_csv(he_csv)
    dist_path = os.path.join(task_abs_path, 'result', 'he', 'cluster_celltype_distribution.json')
    with open(dist_path, 'w', encoding='utf-8') as f:
        json.dump({spot: {'DemoTypeA': 3, 'DemoTypeB': 2} for spot in spots}, f)
    hc_dir = os.path.join(task_abs_path, 'result', 'he', 'HierarchicalClustering')
    os.makedirs(hc_dir, exist_ok=True)
    gene_expression = pd.DataFrame(
        rng.random((len(spots), len(genes))),
        index=spots,
        columns=genes,
    )
    gene_expression.to_csv(os.path.join(task_abs_path, 'result', 'he', 'gene_expression.csv'))
    for celltype in DEMO_CELL_TYPES:
        cluster_name = celltype.replace(' ', '_')
        cluster_df = pd.DataFrame(
            {
                'x': [float(i) for i in range(len(spots))],
                'y': [float(i * 2) for i in range(len(spots))],
                'Label': [celltype] * len(spots),
            },
            index=spots,
        )
        cluster_df.to_csv(os.path.join(hc_dir, f'cluster{cluster_name}_merged_data_with_labels.csv'))

    # File-list inputs/outputs.
    sc_marker_dir = os.path.join(task_abs_path, 'result', 'sc_marker')
    os.makedirs(sc_marker_dir, exist_ok=True)
    marker_df.to_csv(os.path.join(sc_marker_dir, 'test_marker.csv'))
    clusters_df.to_csv(os.path.join(sc_marker_dir, 'test_clusters.csv'))
    annotation_dir = os.path.join(task_abs_path, 'result', 'sc_query', 'annotation_h5ad')
    os.makedirs(annotation_dir, exist_ok=True)
    write_h5ad(os.path.join(annotation_dir, 'demo_annotation.h5ad'), spots, genes)

    # Commot LR result for the default mapping method.
    commot_dir = os.path.join(
        task_abs_path, f'dataset_{uuid}', 'subtask_commot', 'result',
        'sc_st_mapping', DEMO_DEFAULT_MAPPING_METHOD,
    )
    os.makedirs(commot_dir, exist_ok=True)
    receiver = pd.DataFrame(
        {DEMO_LR_PAIR: [0.0, 1.5, 0.0, 2.5, 1.0]},
        index=spots,
    )
    ad.AnnData(
        X=np.ones((len(spots), 1), dtype=np.float32),
        obs=pd.DataFrame(index=spots),
        var=pd.DataFrame(index=['gene_0']),
        obsm={
            'spatial': np.array([[float(i), float(i * 2)] for i in range(len(spots))], dtype=np.float32),
            'commot-cellchat-sum-receiver': receiver,
        },
    ).write(os.path.join(commot_dir, 'input_sc_LR.h5ad'))

    # SPIDER result for the default mapping method.
    spider_dir = os.path.join(
        task_abs_path, f'dataset_{uuid}', 'subtask_spider', 'result',
        'sc_st_mapping', DEMO_DEFAULT_MAPPING_METHOD,
    )
    os.makedirs(spider_dir, exist_ok=True)
    spider_vars = ['DEMO_LR_1', 'DEMO_LR_2']
    ad.AnnData(
        X=np.ones((len(spots), len(spider_vars)), dtype=np.float32),
        obs=pd.DataFrame(index=spots),
        var=pd.DataFrame(
            {
                'label': [0, 1],
                'pattern_correlation_0': [0.9, 0.1],
                'pattern_correlation_1': [0.2, 0.8],
            },
            index=spider_vars,
        ),
        obsm={
            'spatial': np.array([[float(i), float(i * 2)] for i in range(len(spots))], dtype=np.float32),
            'pattern_score': np.array([[0.9, 0.1]] * len(spots), dtype=np.float32),
        },
    ).write(os.path.join(spider_dir, 'adata_spider.h5ad'))

    # AlphaTalk result for the default mapping method.
    alphatalk_dir = os.path.join(
        task_abs_path, f'dataset_{uuid}', 'subtask_alphatalk', 'result',
        'sc_st_mapping', DEMO_DEFAULT_MAPPING_METHOD,
    )
    os.makedirs(alphatalk_dir, exist_ok=True)
    alphatalk_df = pd.DataFrame([{
        'cell_sender': 'DemoTypeA',
        'cell_receiver': 'DemoTypeB',
        'ligand': 'DEMO_LIGAND',
        'receptor': 'DEMO_RECEPTOR',
        'type': 'demo',
        'score': 0.9,
        'lr_score': 0.8,
        'co_exp_p': 0.01,
    }])
    with open(os.path.join(alphatalk_dir, 'cci_result.pkl'), 'wb') as f:
        import pickle
        pickle.dump({'lr_score': alphatalk_df}, f)

    # LR comparison CSVs.
    lr_base = os.path.join(task_abs_path, f'dataset_{uuid}', 'subtask_lr_comparison', 'result')
    lr_sc_dir = os.path.join(lr_base, 'spearman')
    lr_st_dir = os.path.join(lr_base, 'sc_st_mapping', DEMO_DEFAULT_MAPPING_METHOD, 'spearman')
    os.makedirs(lr_sc_dir, exist_ok=True)
    os.makedirs(lr_st_dir, exist_ok=True)
    lr_rows = [
        {
            'id': DEMO_LR_PAIR,
            'lr_pair': DEMO_LR_PAIR,
            'type': row_type,
            'spearman_rho': 0.75,
            'spearman_pval': 0.01,
            'n_receivers': 5,
            'mean_activity': 0.6,
            'mean_max_ccc': 0.7,
        }
        for row_type in ('SC', 'SC + ST')
    ]
    # The reader hard-labels rows by file (sc CSV -> "SC", sc_st CSV -> "SC + ST"),
    # so each file must only contain its own rows or the panel shows duplicates.
    pd.DataFrame([r for r in lr_rows if r['type'] == 'SC']).to_csv(
        os.path.join(lr_sc_dir, 'lr_level_spearman_correlation_sc.csv'), index=False
    )
    pd.DataFrame([r for r in lr_rows if r['type'] == 'SC + ST']).to_csv(
        os.path.join(lr_st_dir, 'lr_level_spearman_correlation_sc_st.csv'), index=False
    )

    # scGPT images are served as files; generate tiny valid PNGs for local review.
    scgpt_dir = os.path.join(task_abs_path, f'dataset_{uuid}', 'subtask_scgpt_embedding', 'result')
    os.makedirs(scgpt_dir, exist_ok=True)
    for name, size in (
        ('cell_embeddings_umap.png', (32, 32)),
        ('cell_embeddings_heatmap_sorted_by_celltype.png', (64, 32)),
    ):
        image = Image.new('RGB', size, color=(24, 90, 157))
        image.save(os.path.join(scgpt_dir, name), format='PNG')


def build_demo_snapshot(task_abs_path, dataset, organ=None):
    """Public entry point used by createDemoTask and tests."""
    dataset_title = dataset.title if dataset is not None else ''
    write_demo_workspace(
        task_abs_path,
        dataset.dataset_id if dataset is not None else '',
        dataset_title,
        organ=organ or str(getattr(dataset, 'organ', '') or 'breast'),
    )
    return dataset_title
