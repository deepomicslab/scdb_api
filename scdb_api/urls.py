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
from django.urls import path
from task.views import taskViewSet
from rest_framework import routers
import task.views
import dataset.views
from django.urls import path, include
from django.conf.urls.static import static
from django.conf import settings

router = routers.DefaultRouter()
router.register('task', taskViewSet)


urlpatterns = [
    path('', include(router.urls)),
    path('api/', include('rest_framework.urls')),
    path('tasks/detail/', task.views.viewtask),
    path('tasks/list/', task.views.viewtasklist),
    path('tasks/createtask/', task.views.createtask),
    #getoutputfile
    path('tasks/getoutputfile/<path:path>/', task.views.getoutputfile),
    #taskdetailview
    path('tasks/taskdetailview/', task.views.taskdetailview),
    #taskresultview
    path('tasks/taskresultview/', task.views.taskresultview),
    #taskImg
    path('tasks/getImg/', task.views.getImg),
    #subtask create
    path('tasks/createsubtask/', task.views.create_subtask),
    path('tasks/subtask/status/', task.views.subtask_status_update),
    
    # path('dataset/index/', dataset.views.index_data),
    path('dataset/index/stats/global/', dataset.views.global_stats),    # 顶部数据
    path('dataset/index/stats/organs/', dataset.views.organ_stats),     # 左侧器官列表 & 柱状图
    path('dataset/index/list/', dataset.views.dataset_list),            # 底部表格
    path('dataset/index/stats/celltypes/', dataset.views.celltype_stats),
    
    path('dataset/detail/<str:dataset_id>/info/', dataset.views.detail_info),
    path('dataset/detail/<str:dataset_id>/scatter/', dataset.views.detail_scatter),
    path('dataset/download/<str:dataset_id>/', dataset.views.download_h5ad),
]

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)


