conda activate phage
module load GCCcore/11.2.0 GCC/11.2.0 Python/3.9.6


python manage.py migrate


python manage.py makemigrations