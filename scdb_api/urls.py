"""
URL configuration for scdb_api project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
import task.views
import dataset.views
from django.conf.urls.static import static
from django.conf import settings


urlpatterns = [
    path('api/', include('rest_framework.urls')),
    path('tasks/list/', task.views.viewtasklist),
    path('tasks/createtask/', task.views.createtask),
    #taskdetailview
    path('tasks/taskdetailview/', task.views.taskdetailview),
    #taskresultview
    path('tasks/taskresultview/', task.views.taskresultview),
    #taskImg
    path('tasks/getImg/', task.views.getImg),
    #subtask create
    path('tasks/createsubtask/', task.views.create_subtask),
    path('tasks/subtask/status/', task.views.subtask_status_update),
    path('tasks/subtask/log/', task.views.subtask_log),
    
    # path('dataset/index/', dataset.views.index_data),
    path('dataset/index/stats/global/', dataset.views.global_stats),    # top stats bar
    path('dataset/index/stats/organs/', dataset.views.organ_stats),     # organ list & bar chart
    path('dataset/index/list/', dataset.views.dataset_list),            # bottom table
    path('dataset/index/stats/celltypes/', dataset.views.celltype_stats),
    
    path('dataset/detail/<str:dataset_id>/info/', dataset.views.detail_info),
    path('dataset/detail/<str:dataset_id>/scatter/', dataset.views.detail_scatter),
    path('dataset/detail/<str:dataset_id>/gene/', dataset.views.dataset_gene_expression),
    path('dataset/detail/<str:dataset_id>/gene/suggest/', dataset.views.dataset_gene_suggest),
    path('dataset/download/<str:dataset_id>/', dataset.views.download_h5ad),
]

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)


