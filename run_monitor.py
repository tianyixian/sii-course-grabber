#!/usr/bin/env python3
"""入口：24 小时轮询监控抢课（适合满员课程等退课捡漏）

用法：
  python run_monitor.py                 # 使用 ./config.json
  python run_monitor.py myconfig.json   # 指定配置文件
"""
import sys
import logging
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))
from sii_grabber.find_course import load_config, make_client
from sii_grabber.monitor import CourseMonitor

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S")
logger = logging.getLogger("sii_grabber")


def main():
    cfg_path = sys.argv[1] if len(sys.argv) > 1 else "config.json"
    cfg = load_config(cfg_path)

    # targets 两种写法：["课程名"]（按名匹配，同名多班全命中）或 [{"id":..., "name":...}]（精确到班）
    id_targets = {t["id"]: t.get("name", t["id"]) for t in cfg["targets"] if isinstance(t, dict)}
    name_targets = [t for t in cfg["targets"] if isinstance(t, str)]
    if name_targets:
        client_now = make_client(cfg)
        client_now.ensure_token()
        courses = client_now.fetch_courses(cfg.get("school_year", "S003"))
        resolved = {c["id"]: c["courseName"] for c in courses if c["courseName"] in name_targets}
        missing = set(name_targets) - set(resolved.values())
        if missing:
            logger.error("未找到课程: %s（请用 python -m sii_grabber.find_course 核对课程名）", "、".join(missing))
            sys.exit(1)
        id_targets.update(resolved)
        logger.info("按课程名解析到 %d 个课程实例：%s", len(resolved), "、".join(resolved.values()))
    if not id_targets:
        logger.error("targets 为空，请编辑 config.json")
        sys.exit(1)
    targets = id_targets

    deadline = None
    if cfg.get("deadline"):
        deadline = datetime.fromisoformat(cfg["deadline"])

    monitor = CourseMonitor(
        client, targets,
        school_year=cfg.get("school_year", "S003"),
        check_interval=cfg.get("check_interval", 20),
        jitter=cfg.get("jitter", 4),
        deadline=deadline,
        state_file=Path(cfg_path).parent / "state.json",
    )
    monitor.run()


if __name__ == "__main__":
    main()
