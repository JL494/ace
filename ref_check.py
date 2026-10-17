#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
import sys


# ============================ 文本预处理 ============================
def preprocess_text(text):
   
    # 全角【】→ 半角[]
    text = text.replace('【', '[').replace('】', ']')
    # 先移除 Markdown 代码块（避免其中 $ 被误当公式）
    text = re.sub(r'```.*?```', ' ', text, flags=re.DOTALL)
    # 移除块级公式 $$...$$
    text = re.sub(r'\$\$.*?\$\$', ' ', text, flags=re.DOTALL)
    # 移除行内公式 $...$（不含换行）
    text = re.sub(r'\$[^$\n]*?\$', ' ', text)
    return text


# ============================ 引用标记解析 ============================
def parse_citations(text):
    """解析正文中的所有 [..] 标记，区分有效引用与非法标记。

    返回字典：
        valid        : set[int]    有效且去重的正引用编号（均 > 0）
        ordered      : list[int]   按出现顺序展开后的编号（用于乱序检测）
        counts       : dict        每个编号被引用的次数（连续重复只计一次）
        invalid      : list[str]   非法/无效标记的原文（如 [0] [] [无数字]）
        consecutive  : list[tuple] (位置索引, 编号)：连续紧贴重复标注

    说明：函数内部先调用 preprocess_text 跳过 LaTeX 公式与代码块，
    再对中文全角【】做半角归一，最后提取引用标记。
    """
    # 文本预处理：跳过 LaTeX 公式与 Markdown 代码块（内部方括号不参与引用匹配）
    text = preprocess_text(text)
    # 文本预处理：中文全角【】统一替换为半角[]，避免漏识别
    text = text.replace('【', '[').replace('】', ']')

    valid = set()
    ordered = []
    counts = {}
    invalid = []
    consecutive = []   # 连续紧贴重复标注（如 [1][1]）
    prev = None        # 上一个展开出的编号，用于判定连续重复

    for m in re.finditer(r'\[([^\[\]]*)\]', text):
        inner = m.group(1)
        # 空括号 []
        if inner.strip() == "":
            invalid.append("[]")
            prev = None   # 空括号打断连续判定
            continue

        tokens = re.split(r'[,\s]+', inner.strip())
        nums_here = []
        ok = True
        for tok in tokens:
            tok = tok.strip()
            if tok == "":
                continue
            if re.fullmatch(r'\d+', tok):
                n = int(tok)
                if n <= 0:           # [0] 之类的无效编号
                    ok = False
                    break
                nums_here.append(n)
            elif re.fullmatch(r'\d+-\d+', tok):
                a, b = tok.split('-')
                a, b = int(a), int(b)
                if a <= 0 or b <= 0:
                    ok = False
                    break
                lo, hi = min(a, b), max(a, b)
                nums_here.extend(range(lo, hi + 1))
            else:                   # 含非数字或非法格式，如 [无数字] [a] [1-a]
                ok = False
                break

        if ok:
            for n in nums_here:
                valid.add(n)
                ordered.append(n)
                if prev is not None and n == prev:
                    # 连续紧贴重复标注：频次不重复累加，仅记录为冗余
                    consecutive.append((len(ordered) - 1, n))
                else:
                    counts[n] = counts.get(n, 0) + 1
                prev = n
        else:
            invalid.append("[" + inner + "]")
            prev = None   # 非法标记打断连续判定

    return {"valid": valid, "ordered": ordered,
            "counts": counts, "invalid": invalid, "consecutive": consecutive}


def extract_citations(text):
    """从正文中提取有效引用编号集合（去重）。

    为兼容既有调用，保持返回 set[int] 的原有行为，
    新功能请直接使用 parse_citations()。
    """
    return parse_citations(text)["valid"]


def extract_references(text):
    r"""从参考文献列表中提取编号（预处理：清除多余空行、逐行匹配）。

    允许行首存在任意空白字符（空格 / 缩进）；兼容四种开头格式，
    返回去重后的编号集合 set[int]：
        [1]   /  [1].   → 正则 ^\[(\d+)\]
        1.    /  1)     → 正则 ^(\d+)[\.\)]
    """
    found = set()
    for line in text.splitlines():
        line = line.strip()        # 清除行首/行尾空白（含缩进），并跳过空行
        if not line:               # 清除多余空行
            continue
        m = re.match(r'^\[(\d+)\]', line)
        if m:
            found.add(int(m.group(1)))
            continue
        m = re.match(r'^(\d+)[\.\)]', line)
        if m:
            found.add(int(m.group(1)))
    return found


# ============================ 三项创新检测 ============================
def check_order(ordered):
    """检查引用序号是否严格升序，返回下降处的列表。

    每项形如 (index, prev, cur)，表示在第 index 个位置从 prev 降到 cur。
    同时返回整体判断：'desc'（整体倒序）/ 'mixed'（局部乱序）/ 'ok'。
    """
    drops = []
    for i in range(1, len(ordered)):
        if ordered[i] < ordered[i - 1]:
            drops.append((i, ordered[i - 1], ordered[i]))
    if not drops:
        kind = "ok"
    elif all(ordered[i] < ordered[i - 1] for i in range(1, len(ordered))):
        kind = "desc"
    else:
        kind = "mixed"
    return drops, kind


def check_duplicates(counts):
    """返回引用次数大于 1 的编号及其频次，按频次降序、编号升序。"""
    dups = [(n, c) for n, c in counts.items() if c > 1]
    dups.sort(key=lambda x: (-x[1], x[0]))
    return dups


def check_consecutive(consecutive):
    """汇总连续紧贴重复标注（如 [1][1]），返回 {编号: 冗余出现次数}。"""
    summary = {}
    for _, n in consecutive:
        summary[n] = summary.get(n, 0) + 1
    return summary


def check_invalid(invalid):
    """汇总非法标记，返回去重后的标记及各自出现次数。"""
    summary = {}
    for mark in invalid:
        summary[mark] = summary.get(mark, 0) + 1
    return summary


# ============================ 报告生成 ============================
def build_report(body_text, ref_text):
    """生成完整校验报告字符串（基础两类错误 + 三项创新检测）。"""
    parsed = parse_citations(body_text)
    cited = parsed["valid"]
    ordered = parsed["ordered"]
    counts = parsed["counts"]
    invalid_raw = parsed["invalid"]
    consecutive_raw = parsed["consecutive"]

    refs = extract_references(ref_text)

    missing = sorted(cited - refs)   # 正文引用但参考文献缺失
    orphan = sorted(refs - cited)    # 参考文献存在但正文无引用
    ok = sorted(cited & refs)        # 正确匹配

    drops, order_kind = check_order(ordered)
    dups = check_duplicates(counts)
    consecutive_summary = check_consecutive(consecutive_raw)
    invalid_summary = check_invalid(invalid_raw)

    lines = []
    lines.append("=" * 60)
    lines.append("        论文参考文献交叉引用校验报告")
    lines.append("=" * 60)
    lines.append("【统计概览】")
    lines.append("  正文有效引用编号（去重） : {}".format(len(cited)))
    lines.append("  正文引用标记出现总次数   : {}".format(len(ordered)))
    lines.append("  参考文献编号总数（去重） : {}".format(len(refs)))
    lines.append("  非法/无效引用标记数      : {}".format(len(invalid_raw)))
    lines.append("  连续紧贴重复标注数       : {}".format(len(consecutive_raw)))
    lines.append("-" * 60)

    # 错误类型一
    lines.append("【错误类型一】正文引用但参考文献缺失")
    if missing:
        lines.append("  发现问题 {} 处，编号：{}".format(len(missing), missing))
        lines.append("  说明：正文中出现了引用标记，但参考文献列表中没有对应编号。")
    else:
        lines.append("  ✓ 未发现问题")
    lines.append("-" * 60)

    # 错误类型二
    lines.append("【错误类型二】参考文献存在但正文无引用")
    if orphan:
        lines.append("  发现问题 {} 处，编号：{}".format(len(orphan), orphan))
        lines.append("  说明：参考文献列表中的编号在正文中从未被引用（冗余/孤立文献）。")
    else:
        lines.append("  ✓ 未发现问题")
    lines.append("-" * 60)

    # 创新点一：乱序检测
    lines.append("【错误类型三】引用顺序乱序检测（升序规范校验）")
    if not ordered:
        lines.append("  正文中未检测到有效引用标记，跳过。")
    elif order_kind == "ok":
        lines.append("  ✓ 引用序号严格升序，符合学术规范：{}".format(ordered))
    else:
        label = "整体倒序" if order_kind == "desc" else "局部乱序"
        lines.append("  发现 {} 处顺序下降，判定为：{}".format(len(drops), label))
        lines.append("  正文引用出现序列：{}".format(ordered))
        for idx, prev, cur in drops:
            lines.append("    · 第 {} 个引用：在 {} 之后出现 {}（应为升序）"
                         .format(idx + 1, prev, cur))
    lines.append("-" * 60)

    # 创新点二：重复引用 + 连续冗余
    lines.append("【错误类型四】重复引用冗余检测（频次统计 + 连续冗余）")
    has_repeat_issue = bool(dups) or bool(consecutive_summary)
    if has_repeat_issue:
        if dups:
            lines.append("  · 多次引用（非紧贴）的文献：")
            for n, c in dups:
                lines.append("    - 文献 [{}] 被引用 {} 次".format(n, c))
        if consecutive_summary:
            lines.append("  · 连续紧贴重复标注（冗余）的文献：")
            for n, c in consecutive_summary.items():
                lines.append("    - 文献 [{}] 出现 {} 处连续重复（如 [{}][{}]）"
                             .format(n, c, n, n))
        lines.append("  建议：合并连续重复标注，确认是否确为必要多次引用。")
    else:
        lines.append("  ✓ 未发现重复引用或连续冗余标注")
    lines.append("-" * 60)

    # 创新点三：无效标记清洗
    lines.append("【错误类型五】空引用 / 无效标记清洗")
    if invalid_summary:
        lines.append("  发现 {} 个非法引用标记：".format(len(invalid_raw)))
        for mark, c in invalid_summary.items():
            cnt = "（出现 {} 次）".format(c) if c > 1 else ""
            lines.append("    · {}{}".format(mark, cnt))
        lines.append("  说明：[0]、空括号 []、含非数字的标记等均属非法引用，"
                     "应从正文中修正。")
    else:
        lines.append("  ✓ 未发现非法引用标记")
    lines.append("-" * 60)

    lines.append("正确匹配的引用编号：{}".format(ok if ok else "无"))
    lines.append("=" * 60)

    # 校验结论
    hard_issues = missing or orphan or drops or invalid_summary
    has_warn = bool(dups) or bool(consecutive_summary)
    if hard_issues:
        n_issue = (len(missing) + len(orphan) + len(drops)
                   + len(invalid_summary))
        warn_note = ("（另含重复/连续冗余 {} 处提醒）"
                     .format(len(dups) + len(consecutive_summary))) if has_warn else ""
        lines.append("校验结论：❌ 未通过，共发现 {} 处问题{}".format(n_issue, warn_note))
    elif has_warn:
        lines.append("校验结论：✅ 通过（含重复/连续冗余 {} 处提醒，建议复核）"
                     .format(len(dups) + len(consecutive_summary)))
    else:
        lines.append("校验结论：✅ 通过，引用与参考文献完全一致且规范。")
    lines.append("=" * 60)
    return "\n".join(lines)


# ============================ 交互输入 ============================
def read_multiline(prompt):
    """多行输入：可粘贴多行文本，单独一行输入 end 结束。"""
    print(prompt)
    print("（可粘贴多行文本，单独一行输入 end 结束输入）")
    buf = []
    while True:
        try:
            line = input(">> ")
        except EOFError:
            break
        if line.strip().lower() == "end":
            break
        buf.append(line)
    return "\n".join(buf)


def main():
    print("\n论文参考文献交叉引用校验工具  RefCrossCheck（本地控制台版）")
    print("（纯 Python 标准库实现，无需安装任何第三方依赖）\n")

    # 文件模式： python ref_check.py 正文文件 参考文献文件
    if len(sys.argv) == 3:
        try:
            with open(sys.argv[1], encoding="utf-8") as f:
                body = f.read()
            with open(sys.argv[2], encoding="utf-8") as f:
                refs = f.read()
        except OSError as e:
            print("文件读取失败：{}".format(e))
            return
        print("已从文件读取：\n  正文：{}\n  参考文献：{}\n".format(
            sys.argv[1], sys.argv[2]))
    else:
        body = read_multiline("【第一步】请粘贴论文正文（含 [1] 等引用标记）")
        refs = read_multiline("【第二步】请粘贴参考文献列表（编号如 [1] 或 1.）")

    print()
    print(build_report(body, refs))


if __name__ == "__main__":
    main()
