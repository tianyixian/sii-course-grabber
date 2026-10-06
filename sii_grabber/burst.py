"""冲刺抢课：开放时刻一到（或扩容提前生效）多线程全速抢课

适用场景：选课系统定时开放、扩容放开名额，拼手速的瞬间决胜。
策略：
  - 服务器时钟校准，消除本地时钟偏差
  - 扩容监视哨：轮询中发现容量放开（比通知的开放时间更早）则提前开火
  - 开放前低频预热保持连接热度；开放后每线程 300ms 一发直打选课接口
  - 跳过『查询列表 → 点选课 → 点确认』全部中间环节，一次请求完成选课
"""
import time
import threading
import logging
from datetime import datetime, timedelta

import requests

from .cas_login import UA

logger = logging.getLogger("sii_grabber")


class BurstGrabber:
    """冲刺模式

    targets: [(显示名, 课程实例ID, 是否主力课)] —— 主力课全速，非主力低频捡漏
    open_at: 预计开放时刻（datetime）
    """

    def __init__(self, client, targets: list, open_at: datetime,
                 school_year: str = "S003",
                 warmup_seconds: int = 10, fullspeed_seconds: int = 90,
                 cooldown_seconds: int = 600,
                 on_success=None):
        self.client = client
        self.targets = targets
        self.open_at = open_at
        self.school_year = school_year
        self.warmup_at = open_at - timedelta(seconds=warmup_seconds)
        self.fullspeed_until = open_at + timedelta(seconds=fullspeed_seconds)
        self.cooldown_until = open_at + timedelta(seconds=cooldown_seconds)
        self.on_success = on_success or (lambda name: None)
        self.clock_offset = 0.0
        self.fire_event = threading.Event()
        self.results = {}
        self._results_lock = threading.Lock()

    # ---------- 服务器时间 ----------
    def server_now(self) -> datetime:
        return datetime.now() + timedelta(seconds=self.clock_offset)

    def calibrate(self, probe_url: str, rounds: int = 5):
        self.clock_offset = self.client.calibrate_clock(probe_url, rounds)
        logger.info("时钟校准: offset=%+.3fs，服务器当前 %s",
                    self.clock_offset, self.server_now().strftime("%H:%M:%S.%f")[:-3])

    # ---------- 选课请求 ----------
    def _select_once(self, session, course_id, label):
        """单次尝试。返回 'OK' | 'B0001'(满/未开) | 'A0200' | 'ERR:xxx'"""
        try:
            r = session.post(self.client.base + "/studentSelectCourseInfo/selectCourse",
                             json={"courseOpenId": course_id},
                             headers={"Authorization": self.client.token}, timeout=4)
            j = r.json()
            code = j.get("errorCode")
            if code == "00000":
                return "OK"
            if code == "A0200":
                logger.warning("[%s] token 失效，重登", label)
                try:
                    self.client.ensure_token()
                    self.client._login()
                except Exception as e:
                    logger.error("[%s] 重登失败(下轮再试): %s", label, e)
                return "A0200"
            if code == "B0001":
                return "B0001"  # "选课未开启" 与 "人数已到上限" 共用此码，均应继续重试
            logger.info("[%s] 响应: %s %s", label, code, j.get("userTips"))
            return "ERR:" + str(code)
        except Exception:
            return "ERR:NET"

    # ---------- 线程体 ----------
    def _worker(self, name, course_id, primary):
        session = requests.Session()
        session.verify = False
        session.headers["User-Agent"] = UA
        while self.server_now() < self.warmup_at and not self.fire_event.is_set():
            time.sleep(0.05)
        logger.info("[%s] 线程就绪，预热开始%s", name,
                    "（提前开火！）" if self.fire_event.is_set() else "")

        consecutive_b1 = 0
        while self.server_now() < self.fullspeed_until:
            now = self.server_now()
            interval = 0.3 if primary else 2.0   # 主力课 300ms 全速；捡漏课 2s
            if now < self.open_at and not self.fire_event.is_set():
                interval = 1.0                    # 定时兜底的预热期：1s 一发
            try:
                res = self._select_once(session, course_id, name)
            except Exception as e:
                logger.error("[%s] 全速阶段异常(继续): %s", name, e)
                res = "ERR:EXC"
            if res == "OK":
                with self._results_lock:
                    self.results[name] = "OK"
                logger.info("*** [%s] 抢课成功！ ***", name)
                self.on_success(name)
                return
            if res == "B0001":
                consecutive_b1 += 1
                if now > self.open_at and consecutive_b1 > 20:
                    interval = min(1.0, 0.3 * (consecutive_b1 - 19))
            else:
                consecutive_b1 = 0
            time.sleep(interval)

        # 降频收尾阶段
        while self.server_now() < self.cooldown_until:
            try:
                res = self._select_once(session, course_id, name)
                if res == "OK":
                    with self._results_lock:
                        self.results[name] = "OK"
                    logger.info("*** [%s] 降频阶段抢课成功！ ***", name)
                    self.on_success(name)
                    return
            except Exception as e:
                logger.error("[%s] 降频阶段异常(继续): %s", name, e)
            time.sleep(2.0 if primary else 5.0)

        with self._results_lock:
            self.results.setdefault(name, "FAIL")
        logger.info("[%s] 冲刺阶段结束，未抢到", name)

    # ---------- 扩容监视哨 ----------
    def _watcher(self):
        session = requests.Session()
        session.verify = False
        session.headers["User-Agent"] = UA
        id_map = {t[1]: t[0] for t in self.targets}
        watch_until = self.open_at + timedelta(seconds=60)
        logger.info("监视哨启动：每3秒查容量，扩容提前生效即提前开火")
        while self.server_now() < watch_until and not self.fire_event.is_set():
            try:
                r = session.post(self.client.base + "/studentSelectCourseInfo/getSelectCoursePagingList",
                                 json={"pageNum": 1, "pageSize": 100, "schoolYear": self.school_year},
                                 headers={"Authorization": self.client.token}, timeout=8)
                lst = r.json()["data"]["list"] or []
                hit = [f"{c['courseName']}({c['studentSelectLimit']}/{c['studentLimit']})"
                       for c in lst if c["id"] in id_map and c["studentLimit"] > c["studentSelectLimit"]]
                if hit:
                    logger.info("!!! 扩容已生效，有空缺: %s → 提前开火 !!!", "; ".join(hit))
                    self.fire_event.set()
                    return
            except Exception:
                pass  # 扩容期间接口可能短暂异常，跳过继续
            time.sleep(3)
        logger.info("监视哨结束（未发现提前扩容）")

    # ---------- 主入口 ----------
    def run(self, probe_url: str):
        logger.info("冲刺程序启动，开放时刻: %s", self.open_at.strftime("%H:%M:%S"))
        self.calibrate(probe_url)
        for attempt in range(3):
            try:
                self.client.ensure_token()
                self.client._login()
                break
            except Exception as e:
                logger.error("登录失败(第%d次): %s", attempt + 1, e)
                time.sleep(2)
        else:
            raise RuntimeError("三次登录均失败")

        threads = []
        for name, cid, primary in self.targets:
            t = threading.Thread(target=self._worker, args=(name, cid, primary), daemon=True)
            t.start()
            threads.append(t)
            logger.info("线程已启动: %s (primary=%s)", name, primary)
        threading.Thread(target=self._watcher, daemon=True).start()

        for t in threads:
            t.join()

        ok = [n for n, r in self.results.items() if r == "OK"]
        fail = [n for n, r in self.results.items() if r != "OK"]
        logger.info("冲刺结果 — 成功: %s；未成: %s", ok or "无", fail or "无")
        return self.results
