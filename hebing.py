#!/usr/bin/env python3
"""三向逐行合并小工具，只使用 Python 标准库。

用法:
    python3 hebing.py 老底稿 我改过的稿 对方改过的稿

老底稿是两边分叉前的原文。合并结果整段写到标准输出，不读取键盘输入。
退出码:
    0  完全合上，没有冲突
    1  合并结果已全部输出，但其中存在冲突
    2  用法错误，或文件打不开、读不了
"""

import sys


MARK_START = "冲突起"
MARK_MINE = "我的"
MARK_THEIRS = "对方"
MARK_END = "冲突止"


def split_lines(text):
    """按换行符切行；行内容（含行尾空白）原样保留。"""
    parts = text.split("\n")
    if parts[-1] == "":
        parts.pop()
    return parts


def diff_script(left, right):
    """用经典 Myers O(ND) 前向算法求编辑脚本。

    返回操作序列，每项是 (类型, left 的行, right 的行)：
        ("eq", i, j)  left[i] == right[j]，对齐保留
        ("del", i, -1) right 中删掉了 left[i]
        ("ins", -1, j) right 在 left 基础上插入了 right[j]
    平局规则固定，保证同一组输入每次结果相同。
    """
    n = len(left)
    m = len(right)
    if n == 0 and m == 0:
        return []

    max_d = n + m
    offset = max_d + 1
    size = 2 * max_d + 3
    unreachable = -10 ** 9

    layers = []
    furthest = [unreachable] * size
    furthest[offset + 1] = 0
    final_d = None
    for d in range(max_d + 1):
        k = -d
        while k <= d:
            idx = offset + k
            down_x = furthest[idx - 1]
            right_x = furthest[idx + 1]
            if k == -d:
                x = right_x
            elif k == d:
                x = down_x + 1
            elif down_x >= right_x:
                x = down_x + 1
            else:
                x = right_x
            y = x - k
            while x < n and y < m and left[x] == right[y]:
                x += 1
                y += 1
            furthest[idx] = x
            if x == n and y == m:
                final_d = d
            k += 2
        layers.append(list(furthest))
        if final_d is not None:
            break

    def layer_value(layer, diag):
        idx = offset + diag
        return layer[idx] if 0 <= idx < size else unreachable

    # 回溯出编辑步序列，每项 (i, j, is_down)：编辑步发生在 (i,j)，
    # is_down=True 表示删除 left 中的行，False 表示插入 right 中的行。
    edits = []
    x, y, d = n, m, final_d
    while x > 0 or y > 0:
        k = x - y
        if d == 0:
            ex, ey = x, y
            while ex > 0 and ey > 0:
                ex -= 1
                ey -= 1
            x, y = ex, ey
            continue
        prev = layers[d - 1]
        down = layer_value(prev, k - 1)
        right = layer_value(prev, k + 1)
        if k == -d:
            parent_k, parent_x, move_is_down = k + 1, right, False
        elif k == d:
            parent_k, parent_x, move_is_down = k - 1, down, True
        elif down >= right:
            parent_k, parent_x, move_is_down = k - 1, down, True
        else:
            parent_k, parent_x, move_is_down = k + 1, right, False
        parent_y = parent_x - parent_k
        snake_end_x = parent_x + 1 if move_is_down else parent_x
        snake_end_y = parent_y if move_is_down else parent_y + 1
        ex, ey = x, y
        while ex > snake_end_x and ey > snake_end_y:
            ex -= 1
            ey -= 1
        if move_is_down:
            edits.append((parent_x, parent_y, True))
        else:
            edits.append((parent_x, parent_y, False))
        x, y, d = parent_x, parent_y, d - 1
    edits.reverse()

    script = []
    i = j = 0
    for edit_i, edit_j, is_down in edits:
        while i < edit_i and j < edit_j:
            script.append(("eq", i, j))
            i += 1
            j += 1
        if is_down:
            script.append(("del", i, -1))
            i += 1
        else:
            script.append(("ins", -1, j))
            j += 1
    while i < n and j < m:
        script.append(("eq", i, j))
        i += 1
        j += 1
    return script


def classify_gap(base_gap, mine_gap, theirs_gap):
    """对两个共同锚点之间的一段做分类，返回 (是否冲突, 采用的行)。"""
    if mine_gap == base_gap:
        if theirs_gap == base_gap:
            return False, base_gap
        return False, theirs_gap
    if theirs_gap == base_gap:
        return False, mine_gap
    if mine_gap == theirs_gap:
        return False, mine_gap
    return True, None


def sync_map(script):
    """从编辑脚本提取同步行映射：{老底稿行号: 这一侧行号}。"""
    return {i: j for op, i, j in script if op == "eq"}


def merge_lines(base, mine, theirs):
    """合并三份已切行的文本，返回 (输出行列表, 是否有冲突)。"""
    mine_sync = sync_map(diff_script(base, mine))
    theirs_sync = sync_map(diff_script(base, theirs))

    sync_points = sorted(set(mine_sync) & set(theirs_sync))

    chunks = []
    bp = mp = tp = 0
    for bi in sync_points:
        mi = mine_sync[bi]
        ti = theirs_sync[bi]
        base_gap = base[bp:bi]
        mine_gap = mine[mp:mi]
        theirs_gap = theirs[tp:ti]
        conflict, chosen = classify_gap(base_gap, mine_gap, theirs_gap)
        if conflict:
            chunks.append(("conflict", mine_gap, theirs_gap))
        elif chosen:
            chunks.append(("lines", chosen))
        chunks.append(("lines", [base[bi]]))
        bp, mp, tp = bi + 1, mi + 1, ti + 1

    base_gap = base[bp:]
    mine_gap = mine[mp:]
    theirs_gap = theirs[tp:]
    conflict, chosen = classify_gap(base_gap, mine_gap, theirs_gap)
    if conflict:
        chunks.append(("conflict", mine_gap, theirs_gap))
    elif chosen:
        chunks.append(("lines", chosen))

    output = []
    has_conflict = False
    for chunk in chunks:
        if chunk[0] == "lines":
            output.extend(chunk[1])
            continue
        has_conflict = True
        mine_side = chunk[1]
        theirs_side = chunk[2]
        output.append(MARK_START)
        output.extend(mine_side)
        output.append(MARK_MINE)
        output.extend(theirs_side)
        output.append(MARK_THEIRS)
        output.append(MARK_END)

    return output, has_conflict


def read_text(path):
    try:
        with open(path, mode="r", encoding="utf-8", errors="strict", newline="") as handle:
            return handle.read()
    except OSError as exc:
        detail = exc.strerror or str(exc)
        raise RuntimeError("读不了文件 %s：%s" % (path, detail))
    except UnicodeDecodeError as exc:
        raise RuntimeError(
            "文件 %s 不是合法的 UTF-8 文本（第 %s 字节附近解码失败），没法按行合并"
            % (path, exc.start)
        )


def run(argv):
    if len(argv) != 4:
        sys.stderr.write(
            "用法：python3 hebing.py 老底稿 我改过的稿 对方改过的稿\n"
            "三份文件按这个固定顺序给，结果写到标准输出。\n"
        )
        return 2

    try:
        base_text = read_text(argv[1])
        mine_text = read_text(argv[2])
        theirs_text = read_text(argv[3])
    except RuntimeError as exc:
        sys.stderr.write(str(exc) + "\n")
        return 2

    base = split_lines(base_text)
    mine = split_lines(mine_text)
    theirs = split_lines(theirs_text)

    output_lines, has_conflict = merge_lines(base, mine, theirs)

    if output_lines:
        merged = "\n".join(output_lines)
        if base_text.endswith("\n") or mine_text.endswith("\n") or theirs_text.endswith("\n"):
            merged += "\n"
    else:
        merged = ""

    data = merged.encode("utf-8")
    try:
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()
    except BrokenPipeError:
        import os

        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        return 0

    return 1 if has_conflict else 0


if __name__ == "__main__":
    sys.exit(run(sys.argv))
