# __init__.py

import threading
from queue import Queue
from time import time, sleep
from typing import Any, List, Dict, Tuple
from urllib.parse import quote_plus

from app.core.event import eventmanager, Event
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import EventType, NotificationType
from app.utils.http import RequestUtils


class Webhook_plus(_PluginBase):
    # 插件名称
    plugin_name = "Webhook消息通知plus"
    # 插件描述
    plugin_desc = "通过自定义Webhook发送消息通知。"
    # 插件图标 (建议替换为一个更通用的图标)
    plugin_icon = "webhook.png"
    # 插件版本
    plugin_version = "1.0"
    # 插件作者
    plugin_author = "jxxghp & moded by lesiwo"
    # 作者主页
    author_url = "https://github.com/lesiwo"
    # 插件配置项ID前缀 (修改以避免与旧配置冲突)
    plugin_config_prefix = "webhookplusmsg_"
    # 加载顺序
    plugin_order = 25
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    _enabled = False
    _webhook_url = None
    _msgtypes = []

    # 消息处理线程
    processing_thread = None
    # 上次发送时间
    last_send_time = 0
    # 消息队列
    message_queue = Queue()
    # 消息发送间隔（秒）
    send_interval = 5
    # 退出事件
    __event = threading.Event()

    def init_plugin(self, config: dict = None):
        self.__event.clear()
        if config:
            self._enabled = config.get("enabled")
            self._webhook_url = config.get("webhook_url")
            self._msgtypes = config.get("msgtypes") or []

            # 启动线程的条件是：插件已启用且Webhook地址已填写
            if self._enabled and self._webhook_url:
                self.processing_thread = threading.Thread(target=self.process_queue)
                self.processing_thread.daemon = True
                self.processing_thread.start()

    def get_state(self) -> bool:
        # 插件有效状态取决于是否启用和是否填写了Webhook地址
        return self._enabled and (True if self._webhook_url else False)

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        pass

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面，需要返回两块数据：1、页面配置；2、数据结构
        """
        MsgTypeOptions = []
        for item in NotificationType:
            MsgTypeOptions.append({
                "title": item.value,
                "value": item.name
            })
        return [
            {
                'component': 'VForm',
                'content': [
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {'model': 'enabled', 'label': '启用插件'}
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12},
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'webhook_url',
                                            'label': 'Webhook 地址',
                                            'placeholder': 'https://your-service.com/send?...',
                                            'hint': '必填项。支持变量 {title}, {text}。变量会自动进行URL编码。',
                                            'persistent-hint': True
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12},
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'multiple': True,
                                            'chips': True,
                                            'model': 'msgtypes',
                                            'label': '消息类型',
                                            'items': MsgTypeOptions
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                ]
            }
        ], {
            "enabled": False,
            'webhook_url': '',
            'msgtypes': []
        }

    def get_page(self) -> List[dict]:
        pass

    @eventmanager.register(EventType.NoticeMessage)
    def send(self, event: Event):
        """
        消息发送事件，将消息加入队列
        """
        if not self.get_state() or not event.event_data:
            return

        msg_body = event.event_data
        if not msg_body.get("title") and not msg_body.get("text"):
            logger.warn("Webhook通知：标题和内容不能同时为空")
            return

        self.message_queue.put(msg_body)
        logger.info("Webhook消息已加入队列等待发送")

    def process_queue(self):
        """
        处理队列中的消息，按间隔时间发送
        """
        while True:
            if self.__event.is_set():
                logger.info("Webhook消息发送线程正在退出...")
                break
            
            msg_body = self.message_queue.get()

            current_time = time()
            time_since_last_send = current_time - self.last_send_time
            if time_since_last_send < self.send_interval:
                sleep(self.send_interval - time_since_last_send)

            channel = msg_body.get("channel")
            if channel:
                continue
            msg_type: NotificationType = msg_body.get("type")
            title = msg_body.get("title") or ""
            text = msg_body.get("text") or ""

            if msg_type and self._msgtypes and msg_type.name not in self._msgtypes:
                logger.info(f"消息类型 {msg_type.value} 未开启Webhook发送")
                continue

            # 构建并发送Webhook请求
            sc_url = ""
            try:
                # 对变量进行URL编码，防止特殊字符导致URL格式错误
                encoded_title = quote_plus(title)
                encoded_text = quote_plus(text)
                
                # 替换Webhook URL中的占位符
                sc_url = self._webhook_url.replace("{title}", encoded_title) \
                    .replace("{text}", encoded_text)
                
                logger.debug(f"发送Webhook通知: {sc_url}")
                res = RequestUtils().get_res(sc_url)

                if res and res.status_code == 200:
                    logger.info("Webhook消息发送成功")
                    self.last_send_time = time()
                elif res is not None:
                    logger.warn(f"Webhook消息发送失败，地址：{sc_url}，状态码：{res.status_code}，原因：{res.reason}")
                else:
                    logger.warn(f"Webhook消息发送失败，未获取到返回信息，地址：{sc_url}")
            except Exception as msg_e:
                logger.error(f"Webhook消息发送异常，地址：{sc_url}，错误：{str(msg_e)}")

            self.message_queue.task_done()

    def stop_service(self):
        """
        退出插件
        """
        self.__event.set()
