#!/usr/bin/env python3
"""三方逐行合并小工具（只使用 Python 标准库）。

用法：
    python3 merge3.py 老底稿 我改过的稿 对方改过的稿

结果写到标准输出；完全合上退出码 0，存在冲突退出码 1，
参数或文件读写错误退出码 2。
"""

import sys
from difflib import SequenceMatcher


def split_lines(data):
    """按 \\n 切成 (行内容, 是否有换行符)，行尾空白与 \\r 原样保留。"""
    lines = []
    start = 0
    for index, byte in enumerate(data):
        if byte == 0x0A:
            lines.append((data[start:index], True))
            start = index + 1
    if start < len(data):
        lines.append((data[start:], False))
    return lines


class Stream:
    """一侧稿子相对老底稿的 opcode 游标。"""

    def __init__(self, base, after, lines, base_len):
        matcher = SequenceMatcher(a=base, b=after, autojunk=False)
        self.ops = matcher.get_opcodes()
        self.lines = lines
        self.base_len = base_len
        self.index = 0
        self.offset = 0

    def head(self):
        if self.index >= len(self.ops):
            return None
        tag, i1, i2, j1, j2 = self.ops[self.index]
        if tag == "equal":
            return ("equal", i1 + self.offset, i2, j1 + self.offset, j2)
        kind = "insert" if i1 == i2 else "change"
        return (kind, i1, i2, j1, j2)

    def position(self):
        head = self.head()
        return self.base_len if head is None else head[1]

    def take_equal_line(self):
        _tag, i1, _i2, j1, _j2 = self.ops[self.index]
        line = self.lines[j1 + self.offset]
        self.offset += 1
        if self.offset >= self.ops[self.index][2] - i1:
            self.index += 1
            self.offset = 0
        return line

    def take_change(self):
        _tag, i1, i2, j1, j2 = self.ops[self.index]
        segment = self.lines[j1:j2]
        self.index += 1
        self.offset = 0
        return segment, i1, i2


def merge_three(base_lines, mine_lines, theirs_lines):
    """返回 (区域列表, 是否有冲突)。

    区域为 ("text", 行列表) 或 ("conflict", 我的行, 对方行)。
    """
    base = [line[0] for line in base_lines]
    mine = [line[0] for line in mine_lines]
    theirs = [line[0] for line in theirs_lines]
    base_len = len(base)

    mine_stream = Stream(base, mine, mine_lines, base_len)
    theirs_stream = Stream(base, theirs, theirs_lines, base_len)
    regions = []

    def emit(lines):
        regions.append(("text", list(lines)))

    def gather(seed_mine, seed_theirs):
        """从当前共同位置收集一个变更区域，吸收缠在一起的改动。"""
        seg_mine = []
        seg_theirs = []
        changed_mine = False
        changed_theirs = False
        align = mine_stream.position()

        if seed_mine:
            segment, _start, end = mine_stream.take_change()
            seg_mine.extend(segment)
            changed_mine = True
            align = max(align, end)
        if seed_theirs:
            segment, _start, end = theirs_stream.take_change()
            seg_theirs.extend(segment)
            changed_theirs = True
            align = max(align, end)

        while True:
            progressed = False
            for stream, segment, side in (
                (mine_stream, seg_mine, "mine"),
                (theirs_stream, seg_theirs, "theirs"),
            ):
                head = stream.head()
                if head is None:
                    continue
                kind, start, end = head[0], head[1], head[2]
                if kind == "equal":
                    while stream.position() < align:
                        segment.append(stream.take_equal_line())
                        progressed = True
                elif start < align:
                    segment.extend(stream.take_change()[0])
                    if side == "mine":
                        changed_mine = True
                    else:
                        changed_theirs = True
                    align = max(align, end)
                    progressed = True
            if not progressed:
                break

        if changed_mine and changed_theirs:
            mine_content = [line[0] for line in seg_mine]
            theirs_content = [line[0] for line in seg_theirs]
            if mine_content == theirs_content:
                emit(seg_mine)
            else:
                regions.append(("conflict", seg_mine, seg_theirs))
        elif changed_mine:
            emit(seg_mine)
        elif changed_theirs:
            emit(seg_theirs)

    def drain(stream):
        while True:
            head = stream.head()
            if head is None:
                return
            if head[0] == "equal":
                emit([stream.take_equal_line()])
            else:
                emit(stream.take_change()[0])

    while True:
        head_mine = mine_stream.head()
        head_theirs = theirs_stream.head()
        if head_mine is None and head_theirs is None:
            break
        if head_mine is None:
            drain(theirs_stream)
            break
        if head_theirs is None:
            drain(mine_stream)
            break

        kind_mine = head_mine[0]
        kind_theirs = head_theirs[0]

        if kind_mine == "equal" and kind_theirs == "equal":
            line = mine_stream.take_equal_line()
            theirs_stream.take_equal_line()
            emit([line])
        elif kind_mine == "insert" and kind_theirs == "insert":
            gather(True, True)
        elif kind_mine == "insert":
            emit(mine_stream.take_change()[0])
        elif kind_theirs == "insert":
            emit(theirs_stream.take_change()[0])
        elif kind_mine == "change" and kind_theirs == "change":
            gather(True, True)
        elif kind_mine == "change":
            gather(True, False)
        else:
            gather(False, True)

    coalesced = []
    has_conflict = False
    for region in regions:
        if region[0] == "text":
            lines = region[1]
            if not lines:
                continue
            if coalesced and coalesced[-1][0] == "text":
                coalesced[-1][1].extend(lines)
            else:
                coalesced.append(("text", list(lines)))
        else:
            has_conflict = True
            if coalesced and coalesced[-1][0] == "conflict":
                coalesced[-1][1].extend(region[1])
                coalesced[-1][2].extend(region[2])
            else:
                coalesced.append(
                    ("conflict", list(region[1]), list(region[2]))
                )

    return coalesced, has_conflict


def render(regions):
    chunks = []

    def add_line(line):
        content, terminated = line
        chunks.append(content + (b"\n" if terminated else b""))

    def add_marker(word):
        if chunks and not chunks[-1].endswith(b"\n"):
            chunks.append(b"\n")
        chunks.append(word.encode("utf-8") + b"\n")

    for region in regions:
        if region[0] == "text":
            for line in region[1]:
                add_line(line)
        else:
            _kind, seg_mine, seg_theirs = region
            add_marker("冲突起")
            add_marker("我的")
            for line in seg_mine:
                add_line(line)
            add_marker("对方")
            for line in seg_theirs:
                add_line(line)
            add_marker("冲突止")

    return b"".join(chunks)


def main(argv):
    if len(argv) != 4:
        sys.stderr.write("用法：python3 merge3.py 老底稿 我改过的稿 对方改过的稿\n")
        return 2

    paths = argv[1:4]
    contents = []
    for path in paths:
        try:
            with open(path, "rb") as handle:
                contents.append(handle.read())
        except OSError as error:
            detail = error.strerror or str(error)
            sys.stderr.write("读不了文件 %s：%s\n" % (path, detail))
            return 2

    base_lines = split_lines(contents[0])
    mine_lines = split_lines(contents[1])
    theirs_lines = split_lines(contents[2])

    regions, has_conflict = merge_three(base_lines, mine_lines, theirs_lines)
    try:
        sys.stdout.buffer.write(render(regions))
        sys.stdout.buffer.flush()
    except BrokenPipeError:
        try:
            sys.stdout.close()
        except OSError:
            pass
        return 2
    return 1 if has_conflict else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
