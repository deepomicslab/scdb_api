from django.shortcuts import render
from task.models import tasks
from task.serializers import taskSerializer
from rest_framework.views import APIView
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import viewsets
# Create your views here.



class taskViewSet(viewsets.ModelViewSet):
    queryset = tasks.objects.order_by('id')
    serializer_class = taskSerializer


@api_view(['GET'])
def viewtask(request):
    userid = request.query_params.dict()['userid']
    taskslist = tasks.objects.filter(user=userid)
    serializer = taskSerializer(taskslist, many=True)
    return Response({'results': serializer.data})

# @api_view(['GET'])
# def viewscquery(request):
#     userid = request.query_params.dict()['userid']
#     taskslist = tasks.objects.filter(user=userid)
#     serializer = taskSerializer(taskslist, many=True)
#     return Response({'results': serializer.data})

