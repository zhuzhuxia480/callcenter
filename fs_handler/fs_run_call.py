# -*-coding: utf-8 -*-

import os
import ESL
import sys
import time
import signal
import DBhandler as db
from LogUtils import Logger

logger = Logger()
get_host_sql = " select * from fs_host  where state = 1"
get_call_sql = " select * from view_call_running "
get_free_line_sql = " select (line_num-line_use) as rec from fs_host where id ={0} "
chc_host_sql = " update fs_host set line_use = line_use + 1 where id = {0}"
update_call_sql = " update fs_call set call_status = 'trying' , queue_at = '{0}'  where channal_uuid = '{1}' "
ahq_host_sql = " select * from fs_host where id = {0}  "
#freeswitch 呼叫代理
class Proxy(object):
    def __init__(self, host):
        self.host_id = host.id
        self.line_name = host.line_name
        self.ip = str(host.gateway_ip)
        self.port = 8021
        self.gateway = str(host.gateway_name)
        print '             加载网关:  %s ' % self.gateway
        self.password = 'Aicyber'
        self.line_max = host.line_num
        self.conn = ESL.ESLconnection(self.ip, self.port, self.password)
        print '             freeswitch esl 连接 %s   %s'%(self.ip,'success' if self.conn.connected() else 'fail')

    def call(self, item):
        task_id = item.task_id
        call_id = item.id
        uuid = str(item.channal_uuid)
        number = str(item.cust_number)
        flow_id = str(item.flow_id)
        user_id = item.user_id
        task_type=item.task_type
        is_success = self.fs_api(uuid=uuid, number=number, task_id=task_id, flow_id=flow_id,call_id=call_id,
                                 host_id=self.host_id,gateway='sofia/gateway/{0}'.format(self.gateway),user_id = user_id,task_type=task_type)
        logger.error('[  call is_success = %s ]'%is_success)

    def fs_api(self, uuid, number, task_id, flow_id,call_id, host_id, gateway,user_id,task_type):
        if not gateway:
            gateway = 'sofia/gateway/gw1'
        if self.conn.connected:
            channel_vars = 'ignore_early_media=true,absolute_codec_string=g729,' \
                           'origination_uuid=%s,task_id=%s,flow_id=%s,call_back=false,call_id=%s,host_id=%s,is_test=%s,user_id=%s,task_type=%s' % \
                           (uuid, task_id, flow_id,call_id, host_id, '1',user_id,task_type)
            command = "originate {%s}%s/%s &python(callappv2.Bot)" % (channel_vars, gateway, number)
            logger.error('Invoke fs api:\n%s' % command)
            print '[********************************] ',self.ip
            print '[********************************] ', self.conn.connected()
            self.conn.bgapi(command)
            try:
               time_at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
               db.update_sql(update_call_sql.format(time_at,uuid))
            except Exception as e:
               print 'eror',e.message
            return True
        else:
            return False

    #查询当前host可用线路数
    def can_use(self):
        if not self.conn.connected:
            return 'disconnect'
        num = db.get_one_sql(get_free_line_sql.format(self.host_id))
        if num <= 0:
            return 'full'
        return 'free'

# 呼叫管理
class CallManager(object):
    #初始化，加载host
    def __init__(self):
        self.proxy_factory = ProxyFactory()
        self.list_num = 0
        self.flg = True
    #执行轮询进程，获取要拨打的电话号码
    def process(self):
        if self.flg:
            list_call_number = db.get_all_sql(get_call_sql)
            time_at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
            self.list_num = len(list_call_number)
            if len(list_call_number) > 0:
                self.flg = False
                logger.debug('[ %s   list_call_number count is ....%s.....flg....%s]'%(time_at,self.list_num,self.flg))
            for item in list_call_number:
                self.list_num = self.list_num-1
                print ('[ for in -- self.list_num is ].....%s'%self.list_num)
                host_id = item.host_id
                self.prepare_call(item,host_id)
            self.flg = True


    def prepare_call(self, item, host_id):
        res, pof = self.proxy_factory.get_proxy(host_id)
        if res == 'free':
            pof.call(item)
            return
        # res == 'fail' fs都断开了，或都线路满
        if pof == 'all_disconnect':
            # fs主机连接都断开了
            print('CallManager: ERROR! all fs host disconnect, start fs server or check host table.')
            time.sleep(2)
            sys.exit(0)
        elif pof == 'all_full':
            print('CallManager: WARN! all fs host line full, retry later...')

#代理工厂
class ProxyFactory(object):
    def __init__(self):
        self.proxy_list = []
        self.load_proxy()
    def load_proxy(self):
        list_host_class =db.get_all_sql(get_host_sql)
        for host in list_host_class:#循环 host列表
            proxy = Proxy(host)
            self.proxy_list.append(proxy)
    def get_proxy(self, host_id):
        ps = []
        for proxy in self.proxy_list:
            if host_id == proxy.host_id:
                print '[===current fs_server ==== ] ', proxy.ip
                status = proxy.can_use()
                ps.append(status)
                if status == 'free':
                    return 'free', proxy
        res = all([bool(s == 'disconnect') for s in ps])
        if res:
            return 'fail', 'all_disconnect'
        else:
            return 'fail', 'all_full'

def handler(signal_num, frame):
    print("\nCall service exit, wait a moment...")
    time.sleep(2)
    sys.exit(0)

signal.signal(signal.SIGINT, handler)

if __name__ == '__main__':
    manager = CallManager()
    print '\n==============================================================\n'
    print '               fs_run_call ....running.....                   '
    print '\n==============================================================\n'
    while True:
        try:
            manager.process()
            time.sleep(2)
        except Exception as e:
            print('polling warnning!!! error:%s' %(e,))
