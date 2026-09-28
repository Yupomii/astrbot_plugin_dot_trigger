import json
import os
from pathlib import Path

from astrbot.api import logger
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, StarTools, register


@register(
    "astrbot_plugin_dot_trigger",
    "Yupomii",
    "消息包含设定关键词时自动唤醒LLM回复",
    "1.0.0",
)
class CustomTriggerPlugin(Star):
    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context)
        self.context = context
        self.config = config if isinstance(config, dict) else {}

        # 使用框架规范的插件专属数据存储目录: data/plugin_data/astrbot_plugin_dot_trigger
        try:
            self.data_dir = StarTools.get_data_dir("astrbot_plugin_dot_trigger")
        except Exception:
            self.data_dir = Path("data/plugin_data/astrbot_plugin_dot_trigger")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.storage_file = self.data_dir / "custom_triggers.json"

        # 如果已有本地持久化数据，则合并载入
        if self.storage_file.exists():
            try:
                with open(self.storage_file, "r", encoding="utf-8") as f:
                    saved_data = json.load(f)
                    if isinstance(saved_data, dict):
                        if "enable" in saved_data:
                            self.config["enable"] = saved_data["enable"]
                        if "triggers" in saved_data and isinstance(saved_data["triggers"], list):
                            self.config["triggers"] = saved_data["triggers"]
            except Exception as e:
                logger.error(f"[CustomTrigger] 读取持久化数据失败: {e}")

        # 清除旧版遗留的句号配置项
        if "allow_chinese_dot" in self.config:
            self.config.pop("allow_chinese_dot", None)

        # 补全默认项
        if "enable" not in self.config:
            self.config["enable"] = True
        if "triggers" not in self.config or not isinstance(self.config["triggers"], list):
            self.config["triggers"] = []

        self._save_data()

    def _save_data(self):
        """将触发词数据持久化保存到标准 plugin_data 目录下"""
        try:
            data = {
                "enable": self.config.get("enable", True),
                "triggers": self.config.get("triggers", []),
            }
            with open(self.storage_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"[CustomTrigger] 保存持久化数据失败: {e}")

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_trigger_message(self, event: AstrMessageEvent):
        """当消息中含有自定义触发词时唤醒 LLM 回复"""
        if not self.config.get("enable", True):
            return

        if event.is_at_or_wake_command:
            return

        msg_str = event.get_message_str().strip()
        if not msg_str:
            return

        # 避免干扰以指令前缀开头的命令
        wake_prefixes = self.context._config.get("wake_prefix", ["/"])
        for wp in wake_prefixes:
            if wp and msg_str.startswith(wp):
                return

        # 收集生效的触发词
        raw_triggers = self.config.get("triggers", [])
        triggers = [str(w) for w in raw_triggers if w]
        if not triggers:
            return

        # 检查是否包含任一触发词
        matched = False
        for word in triggers:
            if word in msg_str:
                matched = True
                break

        if not matched:
            return

        # 标记为唤醒命令，进入后续的 LLM 默认回复流程
        event.is_at_or_wake_command = True
        return

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("触发", alias={"点触发"})
    async def trigger_cmd(self, event: AstrMessageEvent, action: str = "", arg: str = ""):
        """自定义触发词控制命令:
        /触发 开 - 开启触发功能
        /触发 关 - 关闭触发功能
        /触发 添加 <词> - 添加触发词
        /触发 删除 <词> - 删除触发词
        /触发 列表 - 查看触发词
        /触发 状态 - 查看当前状态
        """
        action = (action or "").strip().lower()
        arg = (arg or "").strip()

        if action in ["开", "开启", "on", "enable"]:
            self.config["enable"] = True
            self._save_data()
            yield event.plain_result("触发回复功能已开启！包含任何设定关键词的消息都会唤醒回复。")

        elif action in ["关", "关闭", "off", "disable"]:
            self.config["enable"] = False
            self._save_data()
            yield event.plain_result("触发回复功能已关闭！")

        elif action in ["添加", "add", "+"]:
            if not arg:
                yield event.plain_result("请提供要添加的触发词，例如：/触发 添加 关键词")
                return
            triggers = self.config.setdefault("triggers", [])
            if not isinstance(triggers, list):
                triggers = []
                self.config["triggers"] = triggers
            if arg in triggers:
                yield event.plain_result(f"触发词“{arg}”已经在列表里啦！")
                return
            triggers.append(arg)
            self._save_data()
            yield event.plain_result(f"成功添加触发词：“{arg}”！\n当前触发词：{', '.join(triggers)}")

        elif action in ["删除", "del", "remove", "删", "-"]:
            if not arg:
                yield event.plain_result("请提供要删除的触发词，例如：/触发 删除 关键词")
                return
            triggers = self.config.get("triggers", [])
            if not isinstance(triggers, list) or arg not in triggers:
                yield event.plain_result(f"列表中没有找到触发词“{arg}”！")
                return
            triggers.remove(arg)
            self.config["triggers"] = triggers
            self._save_data()
            yield event.plain_result(f"成功删除触发词：“{arg}”！\n当前触发词：{', '.join(triggers) if triggers else '暂无'}")

        elif action in ["列表", "list", "词", "words"]:
            triggers = self.config.get("triggers", [])
            word_list_str = "、".join(f"“{w}”" for w in triggers) if triggers else "暂无"
            yield event.plain_result(f"当前自定义触发词列表：\n{word_list_str}")

        elif action in ["状态", "status", "info"]:
            is_enabled = self.config.get("enable", True)
            triggers = self.config.get("triggers", [])
            word_list_str = "、".join(f"“{w}”" for w in triggers) if triggers else "暂无"
            status_text = (
                f"【关键词触发功能状态】\n"
                f"• 当前总开关：{'已开启' if is_enabled else '已关闭'}\n"
                f"• 触发词列表：{word_list_str}\n\n"
                f"常用指令：\n"
                f"/触发 开 | /触发 关\n"
                f"/触发 添加 <词>\n"
                f"/触发 删除 <词>\n"
                f"/触发 列表"
            )
            yield event.plain_result(status_text)

        else:
            yield event.plain_result(
                "触发功能指令用法：\n"
                "• /触发 开 - 开启功能\n"
                "• /触发 关 - 关闭功能\n"
                "• /触发 添加 <词> - 添加自定义触发词\n"
                "• /触发 删除 <词> - 删除指定触发词\n"
                "• /触发 列表 - 查看所有触发词\n"
                "• /触发 状态 - 查看当前状态"
            )
