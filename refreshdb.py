import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'scdb_api.settings')
django.setup()

from dataset.models import Dataset, set_bulk_import, _do_refresh_global_stats

def run():
    print("Starting metadata refresh for all datasets...")
    set_bulk_import(True)
    try:
        for ds in Dataset.objects.all():
            print(f"Processing: {ds.dataset_id} ...")
            ds.save(update_metadata=True)
    finally:
        set_bulk_import(False)
    _do_refresh_global_stats()
    print("Done!")

if __name__ == '__main__':
    run()
