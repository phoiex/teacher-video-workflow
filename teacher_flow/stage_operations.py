"""内容阶段的执行状态；重试次数与结果写入独立记录。"""
import fcntl
import re
import time
from .common import RUNTIME, course_dir, load, save, version, state
from . import network_retry, model_roles

TITLES = {'prepare_materials':'解析课件', 'prepare_references':'提炼参考风格',
          'prepare_script:plan':'安排教学内容',
          'prepare_script:draft':'生成讲稿初稿', 'prepare_script:deslop':'调整讲稿表达',
          'show:requirements':'整理课程要求', 'show:script':'准备讲稿', 'show:storyboard':'准备分镜'}


def execute(fn, *args):
    cid = args[0] if args else ''
    if not isinstance(cid,str) or not re.fullmatch(r'[a-f0-9]{24}',cid):
        return fn(*args)
    stage = fn.__name__ + (':' + str(args[1]) if len(args)>1 else '')
    folder=course_dir(cid)/'operations';folder.mkdir(exist_ok=True)
    path=folder/(version(stage)+'.json')
    with path.with_suffix('.lock').open('a') as guard:
        fcntl.flock(guard,fcntl.LOCK_EX)
        record={'stage':stage,'title':TITLES.get(stage,'处理课程'),'status':'running',
                'attempt':1,'max_attempts':network_retry.ATTEMPTS,'updated_at':time.time()}
        def update(fields):
            record.update(fields,updated_at=time.time());save(path,record)
        save(folder/'current.json',{'file':path.name})
        update({'message':record['title']+'。'})
        token=network_retry.progress.set(update)
        models_token=model_roles.CURRENT.set(state(cid).get('model_roles'))
        try:
            value=fn(*args)
            update({'status':'complete','retryable':False,'message':'这一步已完成。'})
            return value
        except Exception as exc:
            transient=network_retry.is_network_error(exc)
            update({'status':'failed','retryable':transient,'error_type':type(exc).__name__,
                    'message':'连接暂时未恢复，已保存完成的内容。可以稍后重试。' if transient else str(exc)[:250]})
            raise
        finally:
            network_retry.progress.reset(token)
            model_roles.CURRENT.reset(models_token)


def status_for_run(run_id):
    if not re.fullmatch(r'[a-f0-9-]{36}',run_id):raise ValueError('运行编号不正确')
    mapping=RUNTIME/'workflow-runs'/(run_id+'.json')
    if not mapping.exists():return {'status':'idle','course_id':None}
    cid=load(mapping)['course_id'];folder=course_dir(cid)/'operations';pointer=folder/'current.json'
    if not pointer.exists():return {'status':'idle','course_id':cid}
    filename=load(pointer)['file']
    if not re.fullmatch(r'[a-f0-9]{20}\.json',filename):raise ValueError('阶段记录不正确')
    return {**load(folder/filename),'course_id':cid}
