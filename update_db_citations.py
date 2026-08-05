import os
import django
import pandas as pd
import numpy as np

# 1. Initialize the Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'scdb_api.settings') # change to your actual project name if needed
django.setup()

from dataset.models import Dataset

# 2. Configure the path
csv_path = "/data3/platform/sc_db/scgpt/data/cellxgene/st/dataset_sources_formatted.csv"  # the CSV you just generated

def update_database():
    print(f"📂 Reading CSV: {csv_path} ...")
    
    # Read the CSV and replace NaN (empty values) with empty strings to avoid DB errors
    df = pd.read_csv(csv_path)
    df = df.replace({np.nan: None}) 
    
    success_count = 0
    skip_count = 0
    
    print(f"🔍 Processing {len(df)} rows...\n")
    
    for index, row in df.iterrows():
        # Get the key info from the CSV
        file_path = row.get('File Path')
        citation_label = row.get('citation_label') or ''
        
        # Handle the DOI: if the CSV contains "10.1038/...", we need to build the full URL
        clean_doi = row.get('clean_doi')
        if clean_doi:
            # Simple check: use it directly if it already contains http, otherwise prepend the prefix
            if str(clean_doi).startswith('http'):
                citation_url = clean_doi
            else:
                citation_url = f"https://doi.org/{clean_doi}"
        else:
            citation_url = ''
            
        collection_url = row.get('collection_url') or ''
        explorer_url = row.get('explorer_url') or ''
        
        try:
            # Core alignment logic: look up the database by file_path
            dataset = Dataset.objects.get(file_path=file_path)
            
            # Update the fields
            dataset.citation_label = citation_label
            dataset.citation_url = citation_url
            dataset.collection_url = collection_url
            dataset.explorer_url = explorer_url
            
            # save() no longer reads h5ad by default (update_metadata=False),
            # so this is safe without update_fields workaround
            dataset.save()
            
            print(f"✅ [{index+1}] Updated: {dataset.dataset_id}")
            success_count += 1
            
        except Dataset.DoesNotExist:
            print(f"⚠️ [{index+1}] Skipped: file path not found in the database -> {os.path.basename(file_path)}")
            skip_count += 1
        except Exception as e:
            print(f"❌ [{index+1}] Error: {e}")

    print("\n" + "="*30)
    print(f"🎉 Done! Updated: {success_count}, skipped: {skip_count}")

if __name__ == "__main__":
    update_database()