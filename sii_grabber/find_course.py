"""课程查询工具：列出全部可选课程及其实例 ID，用于填写 config.json 的 targets"""
import json
import sys
from pathlib import Path


def load_config(path: str = "config.json") -> dict:
    p = Path(path)
    if not p.exists():
        sys.exit(f"未找到配置文件 {path}，请先复制 config.example.json 为 config.json 并填写")
    return json.loads(p.read_text(encoding="utf-8"))


def make_client(cfg: dict):
    import urllib3
    urllib3.disable_warnings()
    from .api import SiiClient
    return SiiClient(cfg["backend_base"], cfg["username"], cfg["password"])


def main():
    cfg = load_config()
    client = make_client(cfg)
    client.ensure_token()
    year = cfg.get("school_year", "S003")
    courses = client.fetch_courses(year)
    print(f"\n{'课程名':<28} {'老师':<16} {'已选/容量':<10} {'状态':<6} 课程实例ID")
    print("-" * 110)
    for c in courses:
        status = "已选" if c["selectStatus"] == "1" else "未选"
        print(f"{c['courseName']:<28} {c['teacherName']:<16} "
              f"{c['studentSelectLimit']}/{c['studentLimit']:<6} {status:<6} {c['id']}")
    print(f"\n共 {len(courses)} 门课。把想抢的课程实例ID 填入 config.json 的 targets 即可。")


if __name__ == "__main__":
    main()
