"""SII 教务系统 API 封装：token 管理、课程查询、选课、退课、服务器校时"""
import time
import base64
import json
import logging
from email.utils import parsedate_to_datetime
from datetime import datetime, timedelta

import requests

from .cas_login import login, UA

logger = logging.getLogger("sii_grabber")


class SiiClient:
    """教务后端客户端：自动登录、token 自动续期"""

    def __init__(self, backend_base: str, username: str, password: str):
        self.base = backend_base.rstrip("/")
        self.username = username
        self.password = password
        self.token = None
        self.http = requests.Session()
        self.http.verify = False
        self.http.headers["User-Agent"] = UA

    # ---------- 登录 ----------
    def _login(self):
        logger.info("重新登录获取 token ...")
        self.token = login(self.base, self.username, self.password)
        logger.info("登录成功")

    def _token_exp(self):
        """解析 JWT 过期时间，失败返回 None"""
        try:
            payload = self.token.split(".")[1]
            payload += "=" * (-len(payload) % 4)
            return json.loads(base64.urlsafe_b64decode(payload)).get("exp")
        except Exception:
            return None

    def ensure_token(self):
        """token 缺失或即将过期（10 分钟内）时自动重新登录"""
        if self.token:
            exp = self._token_exp()
            if not (exp and time.time() > exp - 600):
                return
        self._login()

    # ---------- API ----------
    def post(self, path: str, body: dict, retries: int = 1) -> dict:
        """带鉴权 POST；token 失效（A0200）自动重登重试一次"""
        last_err = None
        for attempt in range(retries + 1):
            self.ensure_token()
            try:
                r = self.http.post(self.base + path, json=body,
                                   headers={"Authorization": self.token}, timeout=15)
                j = r.json()
            except Exception as e:
                last_err = f"网络异常: {e}"
                continue
            if j.get("errorCode") == "00000":
                return j
            if j.get("errorCode") == "A0200" and attempt == 0:
                logger.warning("token 失效，自动重新登录")
                self.token = None
                continue
            raise RuntimeError(f"API {path} 返回异常: {j}")
        raise RuntimeError(f"API {path} 重试后仍失败: {last_err}")

    def fetch_courses(self, school_year: str = "S003") -> list:
        """分页拉取指定学年的可选课程列表（每条含 id/课程名/老师/已选人数/容量/选课状态）"""
        j = self.post("/studentSelectCourseInfo/getSelectCoursePagingList",
                      {"pageNum": 1, "pageSize": 100, "schoolYear": school_year})
        return j["data"]["list"] or []

    def select(self, course_open_id: str) -> dict:
        """选课。course_open_id 为课程实例 ID（fetch_courses 返回的 id 字段）"""
        return self.post("/studentSelectCourseInfo/selectCourse",
                         {"courseOpenId": course_open_id})

    def refund(self, course_open_id: str) -> dict:
        """退课"""
        return self.post("/studentSelectCourseInfo/refundCourse",
                         {"courseOpenId": course_open_id})

    # ---------- 服务器校时 ----------
    def calibrate_clock(self, probe_url: str, rounds: int = 5) -> float:
        """取服务器 Date 响应头估算本地->服务器时钟偏移（秒），返回中位数"""
        offsets = []
        for _ in range(rounds):
            try:
                t0 = time.time()
                r = self.http.get(probe_url, timeout=8)
                rtt = time.time() - t0
                d = r.headers.get("Date")
                if d:
                    svr = parsedate_to_datetime(d).timestamp() + rtt / 2
                    offsets.append(svr - time.time())
            except Exception as e:
                logger.warning("校时单轮失败(跳过): %s", e)
            time.sleep(0.3)
        return sorted(offsets)[len(offsets) // 2] if offsets else 0.0
