from task.serializers import taskSerializer
from django.core.management.base import BaseCommand, CommandError
from task.models import tasks
import datetime, pickle, json, os
from scdb_api import settings_local as local_settings

# 定义任务的终止状态（包括成功和失败）
FINISHED_STATUSES = [
    'COMPLETED', 'CANCELLED', 'FAILED', 'TIMEOUT', 
    'NODE_FAIL', 'PREEMPTED', 'BOOT_FAIL'
]

class Command(BaseCommand):
    help = 'Check and update status of running tasks from Slurm'

    def handle(self, *args, **options):
        
        # 获取所有标记为 Running 的任务
        tasklist = tasks.objects.filter(status__iexact='Running')
        
        for task in tasklist:
            # 将 try 移到循环内部，防止一个任务报错卡死整个脚本
            try:
                if task.task_type != 'module':
                    continue

                # 使用 os.path.join 拼接路径更安全
                base_path = os.path.join(local_settings.USERTASKPATH, task.userpath)
                objectpath = os.path.join(base_path, 'moduleobject.pkl')
                jsonpath = os.path.join(base_path, 'taskdetail.json')

                if not os.path.exists(objectpath):
                    # 工作目录已被清理 / pkl 缺失 -> 直接从 DB 删除
                    task_id = task.id
                    task.delete()
                    self.stdout.write(self.style.WARNING(f'Pickle file not found for task {task_id}, deleted from DB'))
                    continue

                # 加载对象
                with open(objectpath, 'rb') as f:
                    taskobject = pickle.load(f)
                
                # 获取最新状态
                # 注意：这里假设 Module 类里正确处理了 check_status
                current_slurm_status = taskobject.check_status()
                
                # --- 关键修改：判断是否处于结束状态（无论成功还是失败） ---
                if current_slurm_status in FINISHED_STATUSES:
                    # 1. 更新数据库
                    # 注意：Slurm 返回全大写，建议统一格式，或者根据需要转换大小写
                    task.status = 'Completed' if current_slurm_status == 'COMPLETED' else 'Error' 
                    # 也可以直接存 task.status = current_slurm_status，看你前端怎么展示
                    task.save()
                    
                    # 2. 更新 JSON 文件
                    if os.path.exists(jsonpath):
                        with open(jsonpath, 'r') as f:
                            jsondata = json.load(f)
                        
                        # 确保 jsondata 结构正确
                        if isinstance(jsondata, list) and len(jsondata) > 0:
                            jsondata[0]['status'] = task.status
                            with open(jsonpath, 'w') as f:
                                json.dump(jsondata, f, ensure_ascii=False, indent=4)
                    
                    # 3. 更新 Pickle 文件 (保存最终状态)
                    with open(objectpath, 'wb') as f:
                        pickle.dump(taskobject, f)
                        
                    self.stdout.write(self.style.SUCCESS(f'Task {task.id} updated to {task.status}'))

                else:
                    # 任务还在运行 (PENDING, RUNNING 等)
                    # 可选：如果想保持 pickle 文件状态最新，也可以在这里 dump 一次
                    pass

            except Exception as e:
                # 捕获单个任务的错误，打印日志，但不中断循环
                error_msg = f'Error processing task {task.id}: {str(e)}'
                self.stdout.write(self.style.ERROR(error_msg))
                # 实际生产中建议这里使用 logger.error(error_msg)
                # 兜底：避免 pkl 损坏 / SLURM 异常导致任务永远 Running
                # 只在原本就是 Running 时才改，避免覆盖已终态
                try:
                    if (task.status or '').lower() == 'running':
                        task.status = 'Failed'
                        task.save()
                        self.stdout.write(self.style.WARNING(f'Task {task.id} marked Failed due to processing error'))
                except Exception:
                    pass

        # 记录脚本运行日志
        try:
            current_time = datetime.datetime.now()
            # 写在项目外, 避免 StatReloader 误判文件变更触发无限重启
            log_dir = "/home/platform/project/scdb_platform/scdb_api_logs"
            os.makedirs(log_dir, exist_ok=True)
            log_path = os.path.join(log_dir, "update.txt")
            with open(log_path, 'a+') as f:
                f.write('exec update finish at '+str(current_time)+"\n")
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Failed to write execution log: {e}'))