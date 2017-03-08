﻿#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
QQBot   -- A conversation robot base on Tencent's SmartQQ
Website -- https://github.com/pandolia/qqbot/
Author  -- pandolia@yeah.net
"""

import sys, os
p = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if p not in sys.path:
    sys.path.insert(0, p)

import random, time, sys, subprocess

from qqbot.qconf import QConf
from qqbot.utf8logger import INFO, WARN, DEBUG
from qqbot.qsession import QSession, QLogin
from qqbot.qterm import QTermServer
from qqbot.common import Utf8Partition, MinusSeperate
from qqbot.qcontacts import QContact
from qqbot.messagefactory import MessageFactory, Message
from qqbot.exitcode import QSESSION_ERROR, RESTART, POLL_ERROR, FETCH_ERROR
from qqbot.exitcode import ErrorInfo

# see QQBot.LoginAndRun
if sys.argv[-1] == '--subprocessCall':
    isSubprocessCall = True
    sys.argv.pop()
else:
    isSubprocessCall = False

class QQBot(MessageFactory):
    def __init__(self, qq=None, user=None, conf=None, ai=None):
        MessageFactory.__init__(self)
        self.conf = conf if conf else QConf(qq, user)
        ai = ai if ai else BasicAI()
        termServer = QTermServer(self.conf.termServerPort)

        self.AddGenerator(self.pollForever)             # child thread 1
        self.AddGenerator(self.fetchForever)            # child thread 2
        self.AddGenerator(termServer.Run)               # child thread 3
        
        # main thread
        self.On('poll-complete', QQBot.onPollComplete)

        # main thread
        for name in dir(ai):
            if name.startswith('On'):
                self.On(MinusSeperate(name[2:]), getattr(ai, name))
    
    def Login(self):
        self.conf.Display()
        session, contacts = QLogin(conf=self.conf)
        
        self.Get = contacts.Get                         # main thread
        self.List = contacts.List                       # main thread
        self.send = session.Send                        # main thread
        
        self.poll = session.Copy().Poll                 # child thread 1
        
        # child thread 2
        f = session.Copy().Fetch
        self.fetch = lambda : f(contacts, self.conf.PicklePath(), self)
    
    def LoginAndRun(self):
        if isSubprocessCall:
            self.Login()
            self.Run()
        else:
            if sys.argv[0].endswith('py') or sys.argv[0].endswith('pyc'):
                args = [sys.executable] + sys.argv
            else:
                args = sys.argv

            args = args + ['--mailAuthCode', self.conf.mailAuthCode]
            args = args + ['--qq', self.conf.qq]
            args = args + ['--subprocessCall']

            while True:
                code = subprocess.call(args)
                if code == 0:
                    INFO('QQBot 正常停止')
                    sys.exit(code)
                elif code == RESTART:
                    args[-2] = ''
                    INFO('重新启动 QQBot （手工登陆）')
                else:
                    INFO('QQBOT 异常停止，原因：%s', ErrorInfo(code))
                    if self.conf.restartOnOffline:
                        args[-2] = self.conf.qq
                        INFO('重新启动 QQBot ')
                    else:
                        sys.exit(code)
            

    # send buddy|group|discuss x|uin=x|qq=x|name=x content
    # Send('buddy', '1234', 'hello')
    # Send('buddy', 'uin=1234', 'hello')
    # Send('buddy', uin='1234', content='hello')
    def Send(self, ctype, *args, **kw):
        if len(args) + len(kw) != 2:
            raise TypeError('Wrong arguments!')
        
        if len(args) < 2 and 'content' not in kw:
            raise TypeError('Wrong arguments!')
        
        if len(args) == 2:
            content, args = args[1], args[:1]
        else:
            content = kw.pop('content')
        
        result = []
        if content:
            for contact in self.Get(ctype, *args, **kw):
                result.append(self.SendTo(contact, content))
        return result
    
    def SendTo(self, contact, content):
        if content:        
            content = str(content)
            result = '向 %s 发消息成功' % str(contact)
            while content:
                front, content = Utf8Partition(content, 600)
                self.send(contact.ctype, contact.uin, front)
                INFO('%s：%s' % (result, front))
            return result

    def pollForever(self):
        try:
            while True:
                yield Message('poll-complete', result=self.poll())
        except QSession.Error:
            yield Message('stop', code=QSESSION_ERROR)
            raise
        except:
            yield Message('stop', code=POLL_ERROR)
            raise
    
    def onPollComplete(self, message):
        ctype, fromUin, memberUin, content = message.result
        
        if ctype == 'timeout':
            self.Process(Message('poll-timeout'))
            return

        try:
            contact = self.Get(ctype, uin=fromUin)[0]
        except IndexError:
            contact = QContact(ctype, uin=fromUin, name='##UNKNOWN')

        if ctype == 'buddy':
            member = None
            INFO('来自 %s 的消息: "%s"' % (str(contact), content))
        else:
            try:
                member = contact.memberList.Get(uin=memberUin)[0]
            except IndexError:
                member = QContact('member', memberUin, '##UNKNOWN')

            INFO('来自 %s[%s] 的消息: "%s"' % \
                 (str(contact), str(member), content))

        self.Process(QQMessage(contact, member, content, self.SendTo))
    
    def fetchForever(self):
        try:
            while True:
                time.sleep(10)
                for msg in self.fetch():
                    yield msg
        except:
            yield Message('stop', code=FETCH_ERROR)
            raise

class QQMessage(Message):
    mtype = 'qq-message'
    
    def __init__(self, contact, member, content, sendTo):
        self.contact = contact
        self.member = member
        self.content = content
        self.sendTo = sendTo
    
    def Reply(self, reply):
        if reply:
            time.sleep(random.randint(1, 4))
            self.sendTo(self.contact, reply)

class BasicAI(object):
    def __init__(self):
        self.cmdFuncs = {}
        self.docs = []

        for k in dir(self):
            if k.startswith('cmd_'):
                func = getattr(self, k)
                self.cmdFuncs[k[4:]] = func
                self.docs.append(func.__doc__)
        self.docs.sort()

        self.termUsage = '欢迎使用 QQBot ，使用方法：'
        self.qqUsage = self.termUsage
        for doc in self.docs:
            self.termUsage += '\n    qq ' + doc[2:]
            self.qqUsage += '\n   -' + doc[2:]

    def OnPollTimeout(self, bot, msg):
        pass
    
    def OnQqMessage(self, bot, msg):
        if msg.content == '--version':
            msg.Reply('QQbot-' + bot.conf.version)
    
    def OnNewBuddy(self, bot, msg):
        INFO('%s 已经是你的好友了', msg.contact)
        
    def OnNewGroup(self, bot, msg):
        INFO('您已加入 %s', msg.contact)
        
    def OnNewDiscuss(self, bot, msg):
        INFO('您已加入 %s', msg.contact)
    
    def OnNewMember(self, bot, msg):
        INFO('%s 已加入 %s', msg.contact.name, msg.contact.owner)
    
    def OnLostBuddy(self, bot, msg):
        INFO('%s 已将你拉黑', msg.contact)
        
    def OnLostGroup(self, bot, msg):
        INFO('你已退出 %s', msg.contact)
        
    def OnLostDiscuss(self, bot, msg):
        INFO('你已退出 %s', msg.contact)
    
    def OnLostMember(self, bot, msg):
        INFO('%s 已退出 %s', msg.contact.name, msg.contact.owner)

    def OnTermMessage(self, bot, msg):
        try:
            result = self.execute(bot, msg)
        except (Exception, QSession.Error) as e:
            result = '运行命令过程中出错：' + str(e)
            WARN(result)
            DEBUG('', exc_info=True)

        msg.Reply(result)
    
    def execute(self, bot, msg):
        argv = msg.content.strip().split()
        if argv and argv[0]:
            f = self.cmdFuncs.get(argv[0], None)
            return f and f(argv[1:], msg, bot)
    
    def cmd_help(self, args, msg, bot):
        '''1 help'''       
        if len(args) == 0:
            return (msg.mtype=='qq-message' and self.qqUsage or self.termUsage)
    
    def cmd_list(self, args, msg, bot):
        '''2 list buddy|group|discuss'''
        if len(args) == 1:
            return '\n'.join(map(repr, bot.List(args[0])))
    
    def cmd_send(self, args, msg, bot):
        '''3 send buddy|group|discuss x|uin=x|qq=x|name=x message'''
        if len(args) >= 3:
            return '\n'.join(bot.Send(args[0], args[1], ' '.join(args[2:])))
    
    def cmd_get(self, args, msg, bot):
        '''4 get buddy|group|discuss x|uin=x|qq=x|name=x'''
        if len(args) == 2:
            return '\n'.join(map(repr, bot.Get(args[0], args[1])))
    
    def cmd_member(self, args, msg, bot):
        '''5 member group|discuss x|uin=x|qq=x|name=x'''
        if len(args) == 2 and args[0] in ('group', 'discuss'):
            result = ''
            for contact in bot.Get(args[0], args[1]):
                result += repr(contact) + '\n'
                result += '\n'.join(map(repr, contact.memberList))
            return result
    
    def cmd_stop(self, args, msg, bot):
        '''6 stop'''
        if len(args) == 0:
            INFO('收到 stop 命令，QQBot 即将停止')
            msg.Reply('QQBot已停止')
            bot.Stop(code=0)
    
    def cmd_restart(self, args, msg, bot):
        '''7 restart'''
        if len(args) == 0:
            INFO('收到 restart 命令， QQBot 即将重启')
            msg.Reply('QQBot已重启')
            bot.Stop(code=RESTART)

def Main():
    try:
        bot = QQBot()
        bot.LoginAndRun()
    except KeyboardInterrupt:
        sys.exit(0)
