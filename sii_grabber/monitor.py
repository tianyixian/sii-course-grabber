"""24 小时轮询监控抢课：盯紧目标课程，一有退课空缺立即抢入"""
import time
import random
import logging
import traceback
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("sii_grabber")


class CourseMonitor:
    """常规监控模式：适合『课程满员、等别人退课捡漏』的场景

    targets: {课程实例ID: 显示名} —— 同名课程多班时按 ID 精确匹配，不会误抢其他班
    deadline: 选课窗口截止时间，到点自动退出
    """

    def __init__(self, client, targets: dict, school_year: str = "S003",
                 check_interval: int = 20, jitter: int = 4,
                 relogin_interval: int = 6 * 3600,
                 deadline: datetime = None, state_file: Path = None):
        self.client = client
        self.targets = targets
        self.school_year = school_year
        self.check_interval = check_interval
        self.jitter = jitter
        self.relogin_interval = relogin_interval
        self.deadline = deadline
        self.state_file = state_file
        self.selected = set()
        self._load_state()

    # ---------- 状态持久化（重启免登录、记住已抢到的课） ----------
    def _load_state(self):
        if self.state_file and self.state_file.exists():
            try:
                import json
                st = json.loads(self.state_file.read_text(encoding="utf-8"))
                self.client.token = st.get("token")
                self.selected = set(st.get("selected", []))
                if self.selected:
                    logger.info("恢复状态：已抢到 %s", "、".join(self.selected))
            except Exception:
                pass

    def _save_state(self):
        if not self.state_file:
            return
        import json
        self.state_file.write_text(
            json.dumps({"token": self.client.token, "selected": list(self.selected)},
                       ensure_ascii=False, indent=2), encoding="utf-8")

    # ---------- 主循环 ----------
    def run(self):
        logger.info("=" * 60)
        logger.info("选课监控启动。目标：%s", "、".join(self.targets.values()))
        logger.info("轮询间隔 %d±%d 秒%s", self.check_interval, self.jitter,
                    f"；截止 {self.deadline}" if self.deadline else "")
        logger.info("=" * 60)

        last_relogin = time.time()
        while True:
            try:
                if self.deadline and datetime.now() >= self.deadline:
                    logger.info("已到选课截止时间（%s），监控结束", self.deadline)
                    break

                if time.time() - last_relogin > self.relogin_interval:
                    self.client.ensure_token()
                    self.client._login()
                    last_relogin = time.time()

                courses = self.client.fetch_courses(self.school_year)
                pending = [c for c in courses
                           if c["id"] in self.targets
                           and self.targets[c["id"]] not in self.selected]

                if not pending:
                    logger.info("全部目标已抢到：%s", "、".join(sorted(self.selected)) or "(无)")
                    logger.info("监控任务完成，退出")
                    break

                now = datetime.now().strftime("%H:%M:%S")
                for c in pending:
                    label = self.targets[c["id"]]
                    full = c["studentSelectLimit"] >= c["studentLimit"]
                    gap = c["studentLimit"] - c["studentSelectLimit"]
                    logger.info("[%s] %-24s %s/%s %s (%s)", now, label,
                                c["studentSelectLimit"], c["studentLimit"],
                                "满" if full else f"空缺 {gap} 个名额", c["teacherName"])
                    if not full and c.get("selectStatus") != "1":
                        logger.info(">>> 发现 %s 有空缺！立即抢课 ...", label)
                        try:
                            self.client.select(c["id"])
                            self.selected.add(label)
                            self._save_state()
                            logger.info("*** 成功选上【%s】(%s) ***", label, c["teacherName"])
                        except Exception as e:
                            logger.error("抢课【%s】失败: %s", label, e)

            except KeyboardInterrupt:
                logger.info("手动停止")
                break
            except Exception as e:
                logger.error("循环异常: %s\n%s", e, traceback.format_exc())
                time.sleep(10)

            time.sleep(self.check_interval + random.uniform(0, self.jitter))
