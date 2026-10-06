#!/usr/bin/env python3
"""入口：定时冲刺抢课（适合选课开放/扩容放名额的瞬间决胜）

用法：
  python run_burst.py --open "2026-09-08 16:30:00"    # 指定开放时刻
  python run_burst.py --open "16:30:00"               # 今天的某时刻
  python run_burst.py myconfig.json --open 16:30:00    # 指定配置文件

config.json 的 targets 里，"primary": true 的课全速抢（300ms/发），
false 的课低频捡漏（适合没扩容、只能等退课的课程）。
"""
import sys
import argparse
import logging
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))
from sii_grabber.find_course import load_config, make_client
from sii_grabber.burst import BurstGrabber

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s.%(msecs)03d [%(levelname)s] %(message)s",
                    datefmt="%H:%M:%S")
logger = logging.getLogger("sii_grabber")


def parse_open_at(s: str) -> datetime:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%H:%M:%S", "%H:%M"):
        try:
            dt = datetime.strptime(s, fmt)
            if fmt == "%Y-%m-%d %H:%M:%S":
                return dt
            return dt.replace(year=datetime.now().year, month=datetime.now().month,
                              day=datetime.now().day)
        except ValueError:
            continue
    raise argparse.ArgumentTypeError(f"无法解析时间: {s}（支持 'HH:MM:SS' 或 'YYYY-MM-DD HH:MM:SS'）")


def main():
    ap = argparse.ArgumentParser(description="SII 选课冲刺抢课")
    ap.add_argument("config", nargs="?", default="config.json", help="配置文件路径")
    ap.add_argument("--open", required=True, type=parse_open_at, help="选课开放时刻")
    ap.add_argument("--warmup", type=int, default=10, help="预热提前秒数（默认10）")
    ap.add_argument("--fullspeed", type=int, default=90, help="全速持续秒数（默认90）")
    args = ap.parse_args()

    cfg = load_config(args.config)
    client = make_client(cfg)
    probe_url = cfg.get("probe_url", cfg["backend_base"].replace(
        "/educationalAdministrationBackend", "") + "/educationalStudent/config.js")

    targets = []
    for t in cfg["targets"]:
        if isinstance(t, str):
            sys.exit("冲刺模式必须用 [{\"id\":..., \"name\":..., \"primary\":...}] 形式配置 targets，"
                     "先用 python -m sii_grabber.find_course 查课程ID")
        targets.append((t.get("name", t["id"][:8]), t["id"], t.get("primary", True)))

    try:
        import winsound
        def on_success(name):
            for _ in range(3):
                winsound.Beep(1400, 300)
    except ImportError:
        def on_success(name):
            logger.info("♪ 抢到了 %s", name)

    grabber = BurstGrabber(client, targets, args.open,
                          school_year=cfg.get("school_year", "S003"),
                          warmup_seconds=args.warmup,
                          fullspeed_seconds=args.fullspeed,
                          on_success=on_success)
    grabber.run(probe_url)


if __name__ == "__main__":
    main()
