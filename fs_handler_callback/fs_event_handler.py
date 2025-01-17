# -*-coding: utf-8 -*-
"""Freeswitch主机事件监听处理进程

1.对每台fs主机外呼调用，由run_call(只在web服务机器中运行)外呼进程依据host表中的fs主机配置，任务配额，发起外呼调用
2.此进程运行在各fs主机上，监听通道事件并处理，跟远程队列服务通信，及数据库访问
"""
import ESL
import atexit
import signal
import sys
import time
import json
import datetime
from datetime import date
import urllib2
import Config as conf
import multiprocessing
from multiprocessing import managers
import DBhandler as db
from LogUtils import Logger

logger = Logger()
print '[...ESL_HOST %s,---- port %s]'%(conf.ESL_HOST, conf.ESL_PORT)
con = ESL.ESLconnection(conf.ESL_HOST, conf.ESL_PORT, conf.ESL_PWD)
_begin_time = time.time()
_pid = multiprocessing.current_process().pid

class DateEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime.datetime):
            return obj.strftime('%Y-%m-%d %H:%M:%S')
        elif isinstance(obj, date):
            return obj.strftime("%Y-%m-%d")
        elif isinstance(obj,time):
            return obj.strftime("%H:%M:%S")
        else:
            return json.JSONEncoder.default(self, obj)

#atexit.register
def bye():
    sec = time.time() - _begin_time
    print 'bye, program run %d second.' % sec

#监听事件 更新呼叫时间
cc_sql = "update fs_call set call_at = '{0}',call_status = 'calling'  where channal_uuid ='{1}'"
#监听事件 更新应答时间
ca_sql = "update fs_call set answer_at = '{0}' where channal_uuid ='{1}'"
#监听事件 更新hangup事件
chc_sql = "update fs_call set call_status='{0}'," \
          " finish_at='{1}', channal_status='{2}'," \
          " channal_detail='{3}' " \
          "where channal_uuid='{4}'"

#监听到CHANNEL_CREATE 事件后 已用线路数加一
chc_update_line = 'update fs_host set line_use = line_use + 1 where id = {0}'

#挂机后已用线路数减一
chc_host_sql = "update fs_host set line_use = line_use - 1 where id = {0}"

#根据channal_uuid 查询当前电话开始时间 挂机时间 任务ID 用户id
chc_call_info = sql = "select  fs_call.answer_at,fs_call.finish_at,fs_call.task_id,task.user_id " \
          "from fs_call left join fs_task as task on fs_call.task_id = task.id " \
          "where channal_uuid = '{0}'"
chc_call_update = " update fs_call set call_minute = {0} where channal_uuid = '{1}' "
#更新用户剩余分钟数
chc_user_minute = " update fs_user set call_minute = call_minute - {0} where id = {1} "


#============================update fs_event_sql===============================================
#fs_task 电话挂机时 fs_task call_finish +1
fs_task_sql = ' update fs_task set call_finish = call_finish + 1  where id = {0} '



def event_processor(event_queue):
    """事件处理进程，消费者"""
    while 1:
        # 读队列会阻塞进程
        event = event_queue.get()
        time_at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        if event['call_back'] != None:
            if event['event_name'] == 'CHANNEL_CREATE':
                sql = cc_sql.format(time_at, event['channal_uuid'])
                logger.info('[sql]:........CHANNEL_CREATE........ %s' % sql)
                db.update_sql(sql)
                #更新fs_host 线路数+1
                host_sql = chc_update_line.format(event['host_id'])
                logger.info('[sql]:........CHANNEL_CREATE.. table...host line+1...... %s' % host_sql)
                db.update_sql(host_sql)
            elif event['event_name'] == 'CHANNEL_ANSWER':
                sql = ca_sql.format(time_at, event['channal_uuid'])
                logger.info('[sql]:.........CHANNEL_ANSWER...... %s' % sql)
                db.run_sql(sql)
            elif event['event_name'] == 'CHANNEL_HANGUP_COMPLETE':
                call_back = event['call_back']
                host_id = event['host_id']
                user_id = event['user_id']
                call_id = event['call_id']
                logger.info('[ call_back----> %s ,user_id---->%s, call_id---->%s]' % (call_back, user_id, call_id))
                logger.info('[ is_test----> %s  ]' % event['is_test'])
                if call_back != None and call_back == 'true':
                    try:
                        sql2 = chc_host_sql.format(int(host_id))
                        logger.info('[ sql2 :----> fs_host line_use - 1 ]%s ' % sql2)
                        db.update_sql(sql2)
                        sql3 = chc_sql.format('finish', time_at, event['Channel-Call-State'],
                                              event['Hangup-Cause'], event['channal_uuid'])
                        logger.info('[sql3 :..........CHANNEL_HANGUP_COMPLETE....... ]%s' % sql3)
                        db.update_sql(sql3)
                        # 回调函数
                        callback_aliyun(event['channal_uuid'], user_id, call_id)
                    except Exception as e:
                        logger.info('hangup_complete execute sql error %s ' % e)
        else:
            print '[ ***** curent event is not platform ***** ]'

#-----------------------fs_handler_callback---------------------------------------

fs_callback_sql =  " select * from fs_call where channal_uuid ='{0}' "
fs_callback_sqllist = " select who,text,record_fpath,create_at from fs_call_replay " \
                      " where call_id = {0} ORDER BY create_at "

fs_callback_host = " select * from fs_user where id  =  {0} "

fs_update_call_callback = "update fs_call set is_callback = {0} , callback_ct = callback_ct + 1  ,callback_at = '{1}'  where channal_uuid = '{2}' "
def callback_aliyun(channal_uuid,user_id,call_id):
    data_obj = {}
    success = True
    callback_url = None
    error = None
    print '[ ------0--------]'
    try:
        # 拿call 信息
        ss_sql = fs_callback_sql.format(channal_uuid)
        call_info = db.get_one_sql(ss_sql)
        print '[ ------1--------%s ]'%call_info
    except Exception as e:
        success = False
        print 'callback_sql1 error .....%s'%e.message
        error = 'sql except %s ' % e.message
    try:
        # 拿replay 分段信息
        item_sql = fs_callback_sqllist.format(call_id)
        item_info = db.get_all_sql(item_sql)
        print '[ ------2--------%s ]' % item_info
    except Exception as e:
        success = False
        print 'callback_sql2 error .....%s' % e.message
        error = 'sql except %s '%e.message

    try:
        # 拿host callback_url信息
        host_sql = fs_callback_host.format(user_id)
        host_info = db.get_one_sql(host_sql)
        print '[ ------3-`-------%s ]' % host_info
        callback_url = host_info['callback_url']
    except Exception as e:
        success = False
        print 'callback_sql3 error .....%s' % e.message
        error = 'sql except %s ' % e.message


    params = {"call": call_info, "call_item": item_info}
    data_obj['success'] = success
    data_obj['data'] = params
    data_obj['error'] =error
    logger.info('body_data------->%s'%json.dumps(data_obj,cls=DateEncoder))
    time_at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    try:
        req = urllib2.Request(callback_url, json.dumps(data_obj,cls=DateEncoder))  # 需要是json格式的参数
        req.add_header('Content-Type', 'application/json')  # 要非常注意这行代码的写法
        response = urllib2.urlopen(req)
        result = json.loads(response.read())
        print result
        print '[------result -----]',result['status']
        if result['status'] == 0:
            update_sql = fs_update_call_callback.format(True,time_at,channal_uuid)
            logger.info('[ ------- sql_update_callback ------- is %s]'%update_sql)
            db.update_sql(update_sql)
        else:
            update_sql = fs_update_call_callback.format(False, time_at, channal_uuid)
            logger.info('[ ------- sql_update_callback ------- is %s]' % update_sql)
            db.update_sql(update_sql)
    except Exception, e:
        print e

def is_valid_date(str):
    '''判断是否是一个有效的日期字符串'''
    try:
        time.strptime(str, "%Y-%m-%d")
        return True
    except:
        return False

def event_listener(event_queue):
    """事件监听进程，收到事件后将事件加入队列，生成者
    :param call_list:
    :return:
    """
    # standard_event = "CHANNEL_CREATE CHANNEL_ANSWER CHANNEL_HANGUP CHANNEL_HANGUP_COMPLETE"
    if con.connected:
        print con.connected()
        # 只订阅通道事件
        con.events('plain', 'CHANNEL_CREATE CHANNEL_ANSWER CHANNEL_HANGUP_COMPLETE')
        while con.connected:
            # 等待接收事件会阻塞进程，不用time.sleep
            e = con.recvEvent()
            logger.info("----------event---------%s" % e.serialize('json'))
            if e:
                # print '-----------------'
                # dict是python保留字，不要做变量名
                dct = dict()
                dct['event_name'] = e.getHeader("Event-Name")
                dct['channal_uuid'] = e.getHeader("unique-id")
                dct['call_number'] = e.getHeader("Caller-Destination-Number")
                dct['Channel-Call-State'] = e.getHeader("Channel-Call-State")
                dct['host_id'] = e.getHeader("variable_host_id")
                dct['call_back'] = e.getHeader("variable_call_back")
                if dct['event_name'] in ['CHANNEL_CREATE','CHANNEL_ANSWER', 'CHANNEL_HANGUP_COMPLETE'] and dct['call_back'] =='true':
                    dct['call_id'] = e.getHeader("variable_call_id")
                    dct['is_test'] = e.getHeader("variable_is_test")
                    dct['user_id'] = e.getHeader("variable_user_id")
                    if dct['event_name'] == 'CHANNEL_HANGUP_COMPLETE':
                        dct['Hangup-Cause'] = e.getHeader("Hangup-Cause")

                    event_queue.put(dct)
                    logger.info('.......event_listener.......name: %s, uuid: %s, number: %s,' %
                                (dct['event_name'], dct['channal_uuid'], dct['call_number']))
                if dct['channal_uuid'] == None:
                    continue


    logger.error('.......esl connect error.......')
    sys.exit(-1)

def handler(signum, frame):
    pid = multiprocessing.current_process().pid
    if _pid == pid:
        print "\nsubprocess will exit, please wait..."

    time.sleep(2)
    sys.exit(-1)

signal.signal(signal.SIGINT, handler)

class QueueManager(managers.BaseManager):
    pass

if __name__ == '__main__':

    # 事件队列，event_listener与event_processor共享
    manager = multiprocessing.Manager()
    event_queue = manager.Queue()

    proc_event_listener = multiprocessing.Process(
        target=event_listener, name='event_listener', args=(event_queue,))
    proc_event_listener.start()

    # proc_event_processor = multiprocessing.Process(
    #     target=event_processor, name='event_processor', args=(event_queue,))
    # proc_event_processor.start()
    print '[fs_event_server ....start.....]'
    while True:
        # print '[fs_event_server ....start.....]'
        time.sleep(3)

