"""全量抓取回归测试：每次改 fetcher/runner 后跑一遍，对比基线。

基线记录每个 URL 的状态码（不只是成功的），这样能看到：
- 退化：之前 200，现在不是 200
- 改进：之前不是 200，现在 200
- 状态变化：失败原因变了（比如 403 → 412）

用法：
    .venv/bin/python -m gov_monitor.tests.test_baseline

通过标准：退化（200→非200）不超过容错数。
"""

from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import gov_site_list

from gov_monitor.fetcher import fetch_notice_links

BASELINE = Path(__file__).with_name("baseline.json")
TOLERANCE = 3  # 允许退化几个（网络波动），超过就算不过


def _probe(col: dict) -> tuple[str, int]:
    url = col["url"]
    try:
        fetch_notice_links(url, encoding=col.get("encoding", "utf-8"))
        return url, 200
    except Exception as e:
        code = getattr(getattr(e, "response", None), "status_code", -1)
        return url, code


def main() -> int:
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    old: dict[str, int] = baseline["status"]
    old_ok = {u for u, c in old.items() if c == 200}
    print(f"基线：{len(old_ok)} / {len(old)} 成功\n")

    cols = gov_site_list.load_notice_columns()
    print(f"全量抓取 {len(cols)} 个栏目...\n")

    current: dict[str, int] = {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        futs = {pool.submit(_probe, c): c for c in cols}
        for f in as_completed(futs):
            url, code = f.result()
            current[url] = code

    current_ok = {u for u, c in current.items() if c == 200}

    regressed = old_ok - current_ok
    improved = current_ok - old_ok
    status_changed = {
        u for u in old
        if u in current and old[u] != current[u] and u not in regressed and u not in improved
    }

    print(f"当前成功：{len(current_ok)} / {len(cols)}")
    print(f"基线成功：{len(old_ok)}")

    if regressed:
        print(f"\n--- ❌ 退化 {len(regressed)} 个（之前 200，现在失败）---")
        for u in sorted(regressed):
            print(f"  {u}  →  {current[u]}")

    if improved:
        print(f"\n--- ✅ 改进 {len(improved)} 个（之前失败，现在 200）---")
        for u in sorted(improved):
            print(f"  {u}  {old[u]} → 200")

    if status_changed:
        print(f"\n--- ⚠️ 状态变化 {len(status_changed)} 个（非200之间变了）---")
        for u in sorted(status_changed):
            print(f"  {u}  {old[u]} → {current[u]}")

    print(f"\n变化：{len(current_ok) - len(old_ok):+d}")

    if len(regressed) > TOLERANCE:
        print(f"\n❌ 失败：退化 {len(regressed)} 个，超过容错 {TOLERANCE}。")
        return 1

    print(f"\n✅ 通过：退化 {len(regressed)} 个（容错 {TOLERANCE}）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
