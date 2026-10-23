"""Step 2a: 中文名 -> JSON 分子文本 (AST) 规则解析器.

流水线: normalize -> tokenize -> morpheme segmentation -> recursive-descent grammar -> AST(dict)
任何未知 token / 结构 => ParseError, 显式失败 (待人工归 pending_review).
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Sequence

HERE = Path(__file__).parent
CORPUS = HERE / "corpus.tsv"
RING_TOPO = json.loads((HERE / "ring_topo.json").read_text(encoding="utf-8"))
FUNC_TOPO = json.loads((HERE / "func_group_topo.json").read_text(encoding="utf-8"))

# ---------- 化学元素周期表 (前三周期 + 有机常用卤素/硒/砷) ----------
# 格式: 符号 → {z: 原子序数, mass: 相对原子质量, valence: [常见价态], arom_val: 芳香价}
ELEM = {
    # Period 1
    "H":  {"z":  1, "mass":   1.008, "valence": [1]},
    "He": {"z":  2, "mass":   4.003, "valence": [0]},
    # Period 2
    "Li": {"z":  3, "mass":   6.941, "valence": [1]},
    "Be": {"z":  4, "mass":   9.012, "valence": [2]},
    "B":  {"z":  5, "mass":  10.811, "valence": [3]},
    "C":  {"z":  6, "mass":  12.011, "valence": [4],       "arom_val": 3},
    "N":  {"z":  7, "mass":  14.007, "valence": [3, 5],    "arom_val": 3},
    "O":  {"z":  8, "mass":  15.999, "valence": [2],       "arom_val": 2},
    "F":  {"z":  9, "mass":  18.998, "valence": [1]},
    "Ne": {"z": 10, "mass":  20.180, "valence": [0]},
    # Period 3
    "Na": {"z": 11, "mass":  22.990, "valence": [1]},
    "Mg": {"z": 12, "mass":  24.305, "valence": [2]},
    "Al": {"z": 13, "mass":  26.982, "valence": [3]},
    "Si": {"z": 14, "mass":  28.086, "valence": [4]},
    "P":  {"z": 15, "mass":  30.974, "valence": [3, 5],    "arom_val": 3},
    "S":  {"z": 16, "mass":  32.065, "valence": [2, 4, 6], "arom_val": 2},
    "Cl": {"z": 17, "mass":  35.453, "valence": [1]},
    "Ar": {"z": 18, "mass":  39.948, "valence": [0]},
    # 有机常用 (Period 4+)
    "Br": {"z": 35, "mass":  79.904, "valence": [1]},
    "I":  {"z": 53, "mass": 126.904, "valence": [1]},
    "Se": {"z": 34, "mass":  78.971, "valence": [2, 4, 6], "arom_val": 2},
    "As": {"z": 33, "mass":  74.922, "valence": [3, 5],    "arom_val": 3},
}

# 中文名 → 符号
ELEM_CN = {
    "氢": "H", "氦": "He",
    "锂": "Li", "铍": "Be", "硼": "B", "碳": "C", "氮": "N", "氧": "O", "氟": "F", "氖": "Ne",
    "钠": "Na", "镁": "Mg", "铝": "Al", "硅": "Si", "磷": "P", "硫": "S", "氯": "Cl", "氩": "Ar",
    "溴": "Br", "碘": "I", "硒": "Se", "砷": "As",
}

def elem_valence(sym: str, aromatic: bool = False) -> int:
    """返回原子的有效价态 (int)."""
    e = ELEM.get(sym)
    if not e:
        return 4
    return e.get("arom_val", e["valence"][0]) if aromatic else e["valence"][0]

# ---------------- 词表 (数据驱动; 按 len 降序贪心匹配) ----------------

RING_MORPHS = {
    "苯": "benzene",
    "吡啶": "pyridine",
    "哒嗪": "pyridazine",
    "嘧啶": "pyrimidine",
    "吡嗪": "pyrazine",
    "吡咯": "pyrrole",
    "咪唑": "imidazole",
    "吡唑": "pyrazole",
    "三唑": "triazole",
    "噁唑": "oxazole",
    "噻唑": "thiazole",
    "呋喃": "furan",
    "吡喃": "pyran",
    "哌嗪": "piperazine",
    "哌啶": "piperidine",
    "吗啉": "morpholine",
    "吲哚": "indole",
    "吲唑": "indazole",
    "喹啉": "quinoline",
    "异喹啉": "isoquinoline",
    "异吲哚啉": "isoindoline",
    "茚": "indene",
    "噻二唑": "thiadiazole",
    "噁嗪": "oxazine",
    "环丙烷": "cyclopropane",
    "环丁烷": "cyclobutane",
    "环戊烷": "cyclopentane",
    "环己烷": "cyclohexane",
    "环庚烷": "cycloheptane",
    "噻吩": "thiophene",
}
# 氢化等级
H_LEVEL = {"二氢": 2, "四氢": 4, "六氢": 6, "全氢": "max"}
# 杂原子置换前缀 (在 螺/双环/母体环 前)
HETERO_PRE = {
    "二氮杂": [("N", 2)],
    "氮杂": [("N", 1)],
    "氧杂": [("O", 1)],
    "硫杂": [("S", 1)],
    "三氮杂": [("N", 3)],
}
CHAIN_CHARS = {
    "甲": 1,
    "乙": 2,
    "丙": 3,
    "丁": 4,
    "戊": 5,
    "己": 6,
    "庚": 7,
    "辛": 8,
    "壬": 9,
    "癸": 10,
}
MULTI = {"二": 2, "三": 3, "四": 4, "五": 5, "六": 6}
# 括号链接词: (子片段)氨基 / (子片段)氧基
LINKERS = {
    "氨基": "amino",
    "氧基": "oxy",
    "羰基": "carbonyl",
    "亚氨基": "imino",
    "甲基": "methyl_link",
    "乙基": "ethyl_link",
}
# 简单取代基词 (分支里不带括号的) 及语义 hint
WORD_HINT = {
    "氧代": "oxo",
    "乙酸": "acetic_acid",
    "羰基": "carbonyl_link",
    "甲酰基": "formyl",
    "氨基": "amino_link",
    "亚氨基": "imino",
    "羟基亚甲基": "hydroxymethylene",
    "氧基": "oxy",
    "甲基": "methyl",
    "乙基": "ethyl",
    "丙基": "propyl",
    "异丙基": "isopropyl",
    "丁基": "butyl",
    "叔丁基": "tertbutyl",
    "苄基": "benzyl",
    "苯基": "phenyl",
    "环丙基": "cyclopropyl",
    "环丁基": "cyclobutyl",
    "环戊基": "cyclopentyl",
    "环己基": "cyclohexyl",
    "羟基": "hydroxy",
    "氰基": "cyano",
    "氟": "fluoro",
    "氯": "chloro",
    "溴": "bromo",
    "碘": "iodo",
    "巯基": "mercapto",
    "甲硫基": "methylthio",
    "乙氧基": "ethoxy",
    "甲氧基": "methoxy",
    "烟酰基": "nicotinoyl",
    "异烟酰基": "isonicotinoyl",
    "硫代": "thioxo",
    "羧酸": "carboxylic",
    "羧基": "carboxy",
    "氨基甲酰基": "carbamoyl",
    "磺酰基": "sulfonyl",
    "乙酰氨基": "acetamido",
    "丙酰氨基": "propionamido",
    "烯": "ene",
    "炔": "yne",
    "乙酰基": "acetyl",
    "异丁氧基": "isobutoxy",
    "异丁基": "isobutyl",
    "吗啉代": "morpholino",
    "哌啶代": "piperidino",
    "甲酰氨基": "formamido",
    "环戊氧基": "cyclopentyloxy",
    "氧杂环丁基": "oxetanyl",
    "甲磺酰基": "mesyl",
    "乙磺酰基": "esyl",
    "磷酰基": "phosphoryl",
    "二甲基磷酰基": "dimethylphosphoryl",
    "羟甲基": "hydroxymethyl",
    "羟乙基": "hydroxyethyl",
    "磺酰亚胺基": "sulfoximine",
    "磺酰亚氨基": "sulfoximine",
    "磺酰胺基": "sulfonamido",
}
# 在“2-羟基乙基”这类片段中，最右侧词是母体，不能被左侧分支贪心吞掉。
TERMINAL_HEAD_WORDS = {
    "甲基",
    "乙基",
    "丙基",
    "异丙基",
    "丁基",
    "叔丁基",
    "苄基",
    "环丙基",
    "环丁基",
    "环戊基",
    "环己基",
    "甲氧基",
    "乙氧基",
    "异丁氧基",
    "吗啉代",
    "哌啶代",
}
# 尾词 (决定附着方式)
TAIL_WORDS = {
    "基": "yl",
    "氧基": "oxy_link",
    "羰基": "carbonyl_link",
    "酰基": "acyl",
    "甲酰基": "formyl",
    "氧化物": "n_oxide",
    "羧酸": "carboxylic",
    "羧基": "carboxy",
    "酰胺": "amide",
    "甲酰胺": "formamide",
    "酸": "acid",
    "磺酰胺": "sulfonamide",
    "胺": "amine",
    "醇": "alcohol",
    "醛": "aldehyde",
    "酮": "ketone",
    "腈": "nitrile",
    "甲醛": "aldehyde",
    "乙醛": "aldehyde",
    "甲酸": "acid",
    "乙酸": "acid",
    "甲酯": "ester_methyl",
    "乙酯": "ester_ethyl",
    # 酯: 羧酸上的 -COOR。羧酸+酯必须作为一个整体识别, 否则
    # ``吡唑-4-羧酸乙酯`` 会在 羧酸 之后停下并报 unconsumed。
    "羧酸甲酯": "ester_methyl",
    "羧酸乙酯": "ester_ethyl",
    "羧酸丙酯": "ester_propyl",
    "甲酸甲酯": "ester_methyl",
    "甲酸乙酯": "ester_ethyl",
    "乙酸甲酯": "ester_methyl",
    "乙酸乙酯": "ester_ethyl",
}
# 简单主体：链长字 + 末端官能团。组合词由规则生成，不逐个硬编码。
SIMPLE_PARENT_SUFFIXES = {
    "烷": "alkane",
    "烯": "alkene",
    "炔": "alkyne",
    "酸": "acid",
    "酰胺": "amide",
    "醇": "alcohol",
    "醛": "aldehyde",
    "酮": "ketone",
    "胺": "amine",
    "腈": "nitrile",
}


def simple_parent_words():
    words = {stem + suffix for stem in CHAIN_CHARS for suffix in SIMPLE_PARENT_SUFFIXES}
    # 丙烯酰胺这类“链长字 + 不饱和度 + 官能团”也属于同一规则。
    words.update(
        stem + unsat + suffix
        for stem in CHAIN_CHARS
        for unsat in ("烯", "炔")
        for suffix in SIMPLE_PARENT_SUFFIXES
        if suffix not in {"烯", "炔"}
    )
    return words


SIMPLE_PARENT_WORDS = simple_parent_words()
# 常见芳香化合物 (非链+后缀形式)
SIMPLE_PARENT_WORDS.update({
    "甲苯", "苯酚", "苯胺", "苯甲醛", "苯甲酸", "苯甲醇",
    "萘", "蒽", "菲",
    "氯甲烷", "二氯甲烷", "三氯甲烷", "四氯化碳",
    "氯乙烷", "二氯乙烷",
    "氯苯", "二氯苯", "三氯苯",
    "溴甲烷", "溴乙烷", "溴苯",
    "碘甲烷", "碘乙烷", "碘苯",
    "乙醚", "甲醚", "丙醚",
    "乙酸甲酯", "甲酸甲酯", "乙酸乙酯",
})
# 保留不切的单字 (词素可组合)
SINGLE_OK = set(
    "苯甲乙丙丁戊己庚辛壬癸氟氯溴碘氧氮硫环杂烷烯炔基代酰酸酯酚胺亚螺桥异并氢硝肟脲噻吩噁唑咯啶嗪嘧哌吗啉吲茚吡呋咪羰酰羟氨腈巯"
)
# head 级额外词
HEAD_EXTRA = ["双环", "甲苯", "苯酚", "苯胺", "苯甲醛", "苯甲酸", "苯甲醇",
              "氯甲烷", "二氯甲烷", "三氯甲烷", "四氯化碳",
              "氯乙烷", "二氯乙烷", "氯苯", "二氯苯", "三氯苯",
              "溴甲烷", "溴乙烷", "溴苯", "碘甲烷", "碘乙烷", "碘苯",
              "乙醚", "甲醚", "丙醚",
              "乙酸甲酯", "甲酸甲酯", "乙酸乙酯", "甲酸乙酯"]

YL_TYPE_WORDS = {
    "甲基", "乙基", "丙基", "异丙基", "丁基", "叔丁基", "异丁基",
    "苄基", "苯基", "环丙基", "环丁基", "环戊基", "环己基", "氧杂环丁基",
}

ALL_MORPHS = sorted(
    set(
        list(RING_MORPHS)
        + list(H_LEVEL)
        + list(HETERO_PRE)
        + list(WORD_HINT)
        + list(TAIL_WORDS)
        + list(SIMPLE_PARENT_WORDS)
        + list(MULTI)
        + list(CHAIN_CHARS)
        + list(LINKERS)
        + HEAD_EXTRA
    ),
    key=len,
    reverse=True,
)

# ---------------- 预处理 & tokenize ----------------

FULLWIDTH = str.maketrans(
    {
        "（": "(",
        "）": ")",
        "，": ",",
        "－": "-",
        "［": "[",
        "］": "]",
        "。": ".",
        "：": ":",
        "　": " ",
    }
)
OCR_NOISE_PREFIX = re.compile(r"^实施例\d+[：:]")
_CTRL = re.compile(r"[\x00-\x1f]")


def normalize(name: str):
    warns = []
    s = name.translate(FULLWIDTH).replace(" ", "")
    if "$" in s:
        s = s.replace("$", "")
        warns.append("stripped_$")
    s = _CTRL.sub("", s)
    m = OCR_NOISE_PREFIX.match(s)
    if m:
        s = s[m.end() :]
        warns.append(f"stripped_prefix:{m.group(0)}")
    return s, warns


def delimiter_issues(s: str):
    """Return structural OCR symptoms without repairing the input."""
    pairs = {")": "(", "]": "["}
    stack = []
    issues = []
    for pos, char in enumerate(s):
        if char in "([":
            stack.append((char, pos))
        elif char in pairs:
            if not stack or stack[-1][0] != pairs[char]:
                issues.append(f"unexpected {char} at {pos}")
            else:
                stack.pop()
    issues.extend(f"unclosed {char} at {pos}" for char, pos in stack)
    return issues


TOKEN_RE = re.compile(
    r"(?P<STEREO>\((?:[1-9][SRsr](?:,[1-9][SRsr])*|[SRsr])\))"
    r"|(?P<LOC>[0-9]+(?:,[0-9]+)*)"
    r"|(?P<LATIN>[A-Za-z])"
    r"|(?P<CJK>[\u4e00-\u9fff]+)"
    r"|(?P<LP>\()|(?P<RP>\))|(?P<LB>\[)|(?P<RB>\])"
    r"|(?P<DASH>-)|(?P<COMMA>,)|(?P<DOT>\.)"
)


def tokenize(s: str):
    toks = []
    end = 0
    for m in TOKEN_RE.finditer(s):
        if m.start() != end:
            toks.append(("UNKNOWN", s[end : m.start()]))
        kind, val = m.lastgroup, m.group()
        if kind == "CJK":
            cjk_pos = 0
            while cjk_pos < len(val):
                hit = None
                for morph in ALL_MORPHS:
                    if val.startswith(morph, cjk_pos):
                        hit = morph
                        break
                if hit is None:
                    ch = val[cjk_pos]
                    toks.append(("CJK" if ch in SINGLE_OK else "UNK_CJK", ch))
                    cjk_pos += 1
                else:
                    toks.append(("CJK", hit))
                    cjk_pos += len(hit)
        else:
            toks.append((kind, val))
        end = m.end()
    if end != len(s):
        toks.append(("UNKNOWN", s[end:]))
    return toks


def group_parentheses(toks):
    """Fold only round-parenthesis syntax into explicit GROUP nodes.

    Square brackets remain tokens because fused-ring notation gives them
    chemical meaning; STEREO tokens are already atomic and need no folding.
    """

    next_group_id = 0

    def fold(start, nested):
        nonlocal next_group_id
        result = []
        i = start
        while i < len(toks):
            token = toks[i]
            if token == ("LP", "("):
                child, i = fold(i + 1, True)
                next_group_id += 1
                result.append(("GROUP", {"id": f"G{next_group_id}", "tokens": child}))
                continue
            if token == ("RP", ")"):
                if not nested:
                    raise ParseError(f"unexpected ) at token {i}")
                return result, i + 1
            result.append(token)
            i += 1
        if nested:
            raise ParseError("unclosed ( in token stream")
        return result, i

    grouped, end = fold(0, False)
    if end != len(toks):
        raise ParseError(f"unconsumed tokens after grouping at {end}")
    return grouped


# ---------------- 递归下降文法 ----------------


class ParseError(Exception):
    pass


class Parser:
    def __init__(self, toks):
        self.t = toks
        self.i = 0

    def peek(self, k=0):
        j = self.i + k
        return self.t[j] if j < len(self.t) else None

    def take(self):
        tok = self.peek()
        if tok is None:
            raise ParseError(f"unexpected EOF at {self.i}")
        self.i += 1
        return tok

    def expect(self, kind, val=None):
        tok = self.peek()
        if tok is None or tok[0] != kind or (val is not None and tok[1] != val):
            raise ParseError(f"expect {kind}({val}) got {tok} at {self.i}")
        return self.take()

    # ---- helpers ----
    def is_loc_start(self):
        tk = self.peek()
        return tk is not None and (
            tk[0] == "LOC" or (tk[0] == "LATIN" and tk[1] == "N")
        )

    def parse_locants(self):
        tk = self.peek()
        if tk[0] == "LOC":
            self.take()
            return [int(x) for x in tk[1].split(",")]
        if tk == ("LATIN", "N"):
            self.take()
            # N,N- 形式: 同一位置的多个取代基 (N,N-二甲基甲酰胺)
            locs = ["N"]
            while self.peek() == ("COMMA", ",") and self.peek(1) == ("LATIN", "N"):
                self.take()
                self.take()
                locs.append("N")
            return locs
        raise ParseError(f"not a locant: {tk}")

    def chain_start(self, k=0):
        """链长字 + 合法后继 (链母体开头)?"""
        tk, nxt = self.peek(k), self.peek(k + 1)
        if not tk or tk[0] != "CJK" or tk[1] not in CHAIN_CHARS:
            return False
        return (
            nxt is None
            or nxt[0] in ("DASH", "LP", "RP")
            or (nxt[0] == "CJK" and (nxt[1] in ("烯", "炔") or nxt[1] in TAIL_WORDS))
        )

    # ---- 词组 (简单取代基): [multiplier] word*  遇 head 起点/边界停 ----
    def parse_words(self, reserve_terminal_head=False):
        words, mult = [], None
        while True:
            tk = self.peek()
            if tk is None or tk[0] != "CJK":
                break
            nxt = self.peek(1)
            if tk[1] in H_LEVEL or (
                tk[1] in MULTI and nxt and nxt[0] == "CJK" and nxt[1] in H_LEVEL
            ):
                break  # 二氢/四氢.. 属 head
            if tk[1] in HETERO_PRE:
                break
            if tk[1] in RING_MORPHS:
                break
            if tk[1] in SIMPLE_PARENT_WORDS:
                break
            if self.chain_start():
                break
            if (
                reserve_terminal_head
                and words
                and tk[1] in TERMINAL_HEAD_WORDS
                and nxt is None
            ):
                break
            if tk[1] not in MULTI and tk[1] not in WORD_HINT:
                raise ParseError(f"unknown word {tk[1]!r} at {self.i}")
            self.take()
            if tk[1] in MULTI:
                mult = tk[1]
                continue
            words.append(tk[1])
        if not words:
            raise ParseError(f"empty word group at {self.i}")
        if mult is not None and len(words) == 1 and len(words[0]) == 1:
            pass  # 多卤代: 二氟/三氟 由组装器解释
        return words, mult

    # ---- entry ----
    def parse_name(self, top=False):
        frag = {"branches": [], "stereo": None}
        if self.peek() and self.peek()[0] == "STEREO":
            frag["stereo"] = self.take()[1]
            if self.peek() == ("DASH", "-"):
                self.take()
        branches, head_stereo, head, tail = self.parse_frame_right(self.t[self.i :])
        frag["branches"] = branches
        if head_stereo is not None:
            frag["head_stereo"] = head_stereo
        frag["head"] = head
        if tail is not None:
            frag["tail"] = tail
        frag = self.expand_groups(frag)
        if top and frag.get("tail", {}).get("kind") == "yl":
            raise ParseError("terminal yl requires a parent attachment")
        if (
            top
            and not frag.get("branches")
            and head.get("type") == "word_group"
            and all(w in YL_TYPE_WORDS for w in head.get("words", []))
        ):
            raise ParseError("terminal yl requires a parent attachment")
        return frag

    def parse_prefixes(self):
        """Parse the left side as sibling ``locant-(branch)`` prefixes."""
        branches = []
        while self.peek() is not None:
            if self.peek() == ("DASH", "-"):
                self.take()
                continue
            # 位次后可以连续出现多个同级位次 (N,N-二甲基 / 1,2,4-三唑 -> 已由
            # LOC token 涵盖; 但 ``N,N-`` 是 LATIN N + COMMA + LATIN N), 因此
            # 这里用 parse_locants 能接受的形式来判断前缀起点。
            if not (self.is_loc_start() and self._peek_after_locants() == ("DASH", "-")):
                raise ParseError(f"expect prefix at {self.i}, got {self.peek()}")
            branches.append(self.parse_branch())
        return branches

    def _peek_after_locants(self):
        """跳过 [N,N] / [LOC] 之后的下一个 token (不移动解析位置)."""
        j = self.i
        if self.peek() is None:
            return None
        # 跳过首 token 及其 ",N" 重复
        j += 1
        while (
            j + 1 < len(self.t)
            and self.t[j] == ("COMMA", ",")
            and self.t[j + 1] == ("LATIN", "N")
        ):
            j += 2
        return self.t[j] if j < len(self.t) else None

    def parse_frame_right(self, body):
        """Find the right-anchored subject, then validate prefixes to its left.

        The scan is intentionally small (names are short) and keeps the grammar
        strict: a candidate subject is accepted only when every token to its
        left is a complete sibling prefix.  This avoids interpreting a locant
        such as ``1,3,4-`` as a substituent before a ring head.
        """
        last_error = ParseError("EOF expecting head")
        # ponytail: bounded O(n²) candidate scan; replace with a token index if corpus names grow materially.
        for start in range(len(body) - 1, -1, -1):
            suffix = Parser(body[start:])
            try:
                head_stereo = None
                if suffix.peek() and suffix.peek()[0] == "STEREO":
                    head_stereo = suffix.take()[1]
                    if suffix.peek() == ("DASH", "-"):
                        suffix.take()
                head = suffix.parse_head()
                tail = suffix.try_parse_tail()
                if suffix.peek() is not None:
                    raise ParseError(
                        f"unconsumed from {suffix.i}: {suffix.t[suffix.i : suffix.i + 8]}"
                    )
                branches = Parser(body[:start]).parse_prefixes()
            except ParseError as exc:
                last_error = exc
                continue
            self.i = len(self.t)
            return branches, head_stereo, head, tail
        raise last_error

    def expand_groups(self, frag):
        """Expand child GROUP nodes only after this frame's head is known."""
        branches = []
        for branch in frag["branches"]:
            if branch["type"] != "group_ref":
                branches.append(branch)
                continue
            group = branch.pop("group")
            branches.append(
                {
                    **branch,
                    "type": "subtree",
                    "frag": self.parse_group(group),
                }
            )
        frag["branches"] = branches

        head = frag["head"]
        if head["type"] == "linked_group":
            group = head.pop("group")
            head["type"] = "linked_frag"
            head["frag"] = self.parse_group(group)
        return frag

    def parse_group(self, group):
        try:
            return Parser(group["tokens"]).parse_name(top=False)
        except ParseError as exc:
            raise ParseError(f"group {group['id']}: {exc}") from exc

    def parse_branch(self):
        locs = self.parse_locants()
        self.expect("DASH")
        if self.peek() and self.peek()[0] == "GROUP":
            group = self.take()[1]
            if self.peek() == ("DASH", "-"):
                self.take()
            return {"locants": locs, "type": "group_ref", "group": group}
        words, mult = self.parse_words(reserve_terminal_head=True)
        if (
            mult is not None
            and len(locs) < MULTI.get(mult, 2)
            and not any(len(w) > 1 for w in words)
        ):
            # 多取代: 位次数应 >= multiplier (二氟 2 个位次; 三氟甲基 例外)
            raise ParseError(f"multiplier {mult} needs locants, got {locs}")
        return {
            "locants": locs,
            "type": "word",
            "words": words,
            "multiplier": mult,
            "hints": [WORD_HINT.get(w) for w in words],
        }

    def parse_head(self):
        tk = self.peek()
        if tk is None:
            raise ParseError("EOF expecting head")
        if tk[0] == "CJK" and tk[1] in SIMPLE_PARENT_WORDS:
            self.take()
            return {
                "type": "word_group",
                "words": [tk[1]],
                "multiplier": None,
                "hints": ["simple_parent"],
            }
        if self.chain_start():
            tk = self.take()
            unsat = []
            if self.peek() and self.peek()[1] in ("烯", "炔"):
                unsat.append(self.take()[1])
            return {
                "type": "chain",
                "length": CHAIN_CHARS[tk[1]],
                "char": tk[1],
                "unsat": unsat,
            }
        if tk[0] == "GROUP":
            # (子片段)链接词 形式
            group = self.take()[1]
            lk = self.peek()
            if lk is None or lk[0] != "CJK" or lk[1] not in LINKERS:
                raise ParseError(
                    f"implicit attachment after group {group['id']}, got {lk} at {self.i}"
                )
            self.take()
            return {
                "type": "linked_group",
                "group": group,
                "linker": lk[1],
                "link_kind": LINKERS[lk[1]],
            }
        if tk[0] == "CJK" and (tk[1] in WORD_HINT or tk[1] in MULTI):
            words, mult = self.parse_words()
            return {
                "type": "word_group",
                "words": words,
                "multiplier": mult,
                "hints": [WORD_HINT.get(w) for w in words],
            }
        return self.parse_ring()

    def parse_ring(self):
        head = {"type": "ring", "h_mark": None, "hydrogenation": None, "hetero": None}
        # 氢化: [LOC-] 级别 [DASH?]
        if (
            self.peek()
            and self.peek()[0] == "LOC"
            and self.peek(1) == ("DASH", "-")
            and self.peek(2)
            and self.peek(2)[0] == "CJK"
            and self.peek(2)[1] in H_LEVEL
        ):
            locs = self.parse_locants()
            self.expect("DASH")
            w = self.take()[1]
            head["hydrogenation"] = {"level": w, "locants": locs}
            if self.peek() == ("DASH", "-"):
                self.take()
        elif self.peek() and self.peek()[0] == "CJK" and self.peek()[1] in H_LEVEL:
            w = self.take()[1]
            head["hydrogenation"] = {"level": w, "locants": None}
            if self.peek() == ("DASH", "-"):
                self.take()
        # tautomer H mark: 1H- / 2H-
        if self.peek() and self.peek()[0] == "LOC" and self.peek(1) == ("LATIN", "H"):
            n = self.take()[1]
            self.take()  # H
            head["h_mark"] = n + "H"
            if self.peek() == ("DASH", "-"):
                self.take()
        # 杂前缀 (可带位次: 5,8-二氮杂螺)
        if (
            self.peek()
            and self.peek()[0] == "LOC"
            and self.peek(1) == ("DASH", "-")
            and self.peek(2)
            and self.peek(2)[0] == "CJK"
            and self.peek(2)[1] in HETERO_PRE
        ):
            head["hetero_locants"] = [int(x) for x in self.take()[1].split(",")]
            self.take()
        if self.peek() and self.peek()[0] == "CJK" and self.peek()[1] in HETERO_PRE:
            head["hetero"] = self.take()[1]
        # 螺 / 双环: [a.b(.c)] 辛烷
        if self.peek() and self.peek()[1] in ("螺", "双环"):
            kind = self.take()[1]
            self.expect("LB")
            parts = []
            while True:
                parts.append(self.expect("LOC")[1])
                if self.peek() == ("DOT", "."):
                    self.take()
                else:
                    break
            self.expect("RB")
            ch = self.expect("CJK")[1]
            if ch.endswith("烷") and ch[:-1] in CHAIN_CHARS:
                ch = ch[:-1]
            if ch not in CHAIN_CHARS:
                raise ParseError(f"bad spiro/bridged ring size {ch}{self.peek()}")
            if self.peek() == ("CJK", "烷"):
                self.take()
            spec = ".".join(parts)
            head["type"] = "spiro" if kind == "螺" else "bridged"
            head["template"] = f"{head.get('hetero') or ''}{kind}[{spec}]{ch}烷"
            head["spiro_spec"] = parts
            head["ring_size"] = CHAIN_CHARS[ch]
            return head
        # 前置环编号: 1,3,4-噻二唑 / [1,2,4]三唑
        head["first_brloc"] = None
        if (
            self.peek()
            and self.peek()[0] == "LOC"
            and self.peek(1) == ("DASH", "-")
            and self.peek(2)
            and self.peek(2)[0] == "CJK"
            and self.peek(2)[1] in RING_MORPHS
        ):
            head["first_brloc"] = self.parse_locants()
            self.expect("DASH")
        elif (
            self.peek() == ("LB", "[")
            and self.peek(1)
            and self.peek(1)[0] == "LOC"
            and self.peek(2) == ("RB", "]")
        ):
            self.take()
            head["first_brloc"] = [int(x) for x in self.take()[1].split(",")]
            self.take()
            if self.peek() == ("DASH", "-"):
                self.take()
        # 母体环
        tk = self.peek()
        if tk is None or tk[0] != "CJK" or tk[1] not in RING_MORPHS:
            raise ParseError(f"expect ring morph, got {tk} at {self.i}")
        head["core"] = self.take()[1]
        # 兼容旧语序: 三唑[1,2,4]
        if (
            head["first_brloc"] is None
            and self.peek() == ("LB", "[")
            and self.peek(1)
            and self.peek(1)[0] == "LOC"
        ):
            self.take()
            head["first_brloc"] = [int(x) for x in self.expect("LOC")[1].split(",")]
            self.expect("RB")
        # 稠环拼合: 并 [loc-side] ring
        fused = []
        while self.peek() == ("CJK", "并"):
            self.take()
            node = {}
            if self.peek() == ("LB", "["):
                self.take()
                if self.peek() and self.peek()[0] == "LATIN":
                    node["loc"] = None
                    node["side"] = self.take()[1]
                else:
                    spec = self.expect("LOC")[1]
                    node["loc"] = [int(x) for x in spec.split(",")]
                    node["side"] = None
                if node["side"] is None and self.peek() == ("DASH", "-"):
                    self.take()
                    node["side"] = self.expect("LATIN")[1]
                self.expect("RB")
                if node["side"] is not None and self.peek() == ("LB", "["):
                    self.take()
                    node["brloc"] = [int(x) for x in self.expect("LOC")[1].split(",")]
                    self.expect("RB")
            tk2 = self.peek()
            if tk2 and tk2[0] == "CJK" and tk2[1] in RING_MORPHS:
                node["core"] = self.take()[1]
                if "brloc" not in node and self.peek() == ("LB", "["):
                    self.take()
                    node["brloc"] = [int(x) for x in self.expect("LOC")[1].split(",")]
                    self.expect("RB")
            else:
                raise ParseError(f"expect fused ring after 并, got {tk2} at {self.i}")
            fused.append(node)
        if fused:
            head["type"] = "fused"
            head["fused"] = fused
        return head

    def try_parse_tail(self):
        # tail := [DASH?] LOC (LP nH RP)? DASH? SUF  |  SUF (chain 酰胺/酸)
        tk = self.peek()
        if tk is None:
            return None
        locs, h_loc = None, None
        j = self.i
        if (
            tk == ("DASH", "-")
            and self.peek(1)
            and (self.peek(1)[0] == "LOC" or self.peek(1) == ("LATIN", "N"))
        ):
            self.take()
            tk = self.peek()
        if tk and (tk[0] == "LOC" or tk == ("LATIN", "N")):
            locs = self.parse_locants()
            if self.peek() and self.peek()[0] == "GROUP":
                group = self.peek()[1]["tokens"]
                if (
                    len(group) == 2
                    and group[0][0] == "LOC"
                    and group[1] == ("LATIN", "H")
                ):
                    self.take()
                    h_loc = group[0][1] + "H"
            if self.peek() == ("DASH", "-"):
                self.take()
            tk = self.peek()
        if tk is None or tk[0] != "CJK":
            self.i = j
            return None
        if tk[1] in TAIL_WORDS:
            self.take()
            tail = {
                "locants": locs,
                "h_loc": h_loc,
                "word": tk[1],
                "kind": TAIL_WORDS[tk[1]],
            }
            if tk[1] == "基" and self.peek() == ("CJK", "氧基"):
                self.take()
                tail["linker"] = "氧基"
            return tail
        self.i = j
        return None


# ---------------- 主流程 ----------------


def parse_one(raw: str):
    rec = {"name": raw, "status": "pending_review"}
    norm, warns = normalize(raw)
    rec["normalized"] = norm
    rec["warn"] = warns
    issues = delimiter_issues(norm)
    if issues:
        rec.update(ok=False, status="pending_review_ocr", error="; ".join(issues))
        return rec
    toks = tokenize(norm)
    rec["tokens"] = [list(t) for t in toks]
    if any(t[0] in ("UNK_CJK", "UNKNOWN") for t in toks):
        bad = [v for k, v in toks if k in ("UNK_CJK", "UNKNOWN")]
        rec.update(ok=False, status="pending_review", error=f"unknown chars {bad}")
        return rec
    try:
        ast = Parser(group_parentheses(toks)).parse_name(top=True)
        rec.update(ok=True, status="ok", ast=ast)
        del rec["tokens"]
    except ParseError as e:
        rec.update(ok=False, status="pending_review", error=str(e))
    return rec


# ---------------- 分子图 & SMILES 生成 ----------------


class MoleculeGraph:
    """轻量分子图: 原子列表 + 键列表, 支持片段合并与连接."""

    def __init__(self) -> None:
        self.atoms: list[str] = []
        self.bonds: list[tuple[int, int]] = []
        self.orders: list[int | float] = []
        self.charges: list[int] = []
        self.locant_map: dict[str, int] = {}
        self.aromatic_indices: set[int] = set()
        # 显式氢覆盖: 芳香吡咯型 N 需要 [nH], 而价态公式无法推断。
        self.explicit_h: dict[int, int] = {}
        # 原子是否允许带显式 H (只有 N/O/S 等写成 [nH]/[OH] 才有意义)。
        self.h_counted: set[int] = set()
        self.chiral_centers: dict[int, str] = {}

    def merge(
        self,
        frag_atoms: list[str],
        frag_bonds: list[tuple[int, int]],
        frag_orders: Sequence[int | float] | None = None,
        offset: int | None = None,
        aromatic_atom_indices: Sequence[int] | None = None,
        explicit_h: dict[int, int] | None = None,
    ) -> list[int]:
        if offset is None:
            offset = len(self.atoms)
        n = len(frag_atoms)
        self.atoms.extend(frag_atoms)
        self.bonds.extend((a + offset, b + offset) for a, b in frag_bonds)
        self.orders.extend(frag_orders or [1] * len(frag_bonds))
        self.charges.extend([0] * n)
        if aromatic_atom_indices:
            self.aromatic_indices.update(i + offset for i in aromatic_atom_indices)
        if explicit_h:
            for i, h in explicit_h.items():
                self.explicit_h[i + offset] = h
        return list(range(offset, offset + n))

    def connect(self, ai: int, aj: int, order: int | float = 1) -> None:
        self.bonds.append((ai, aj))
        self.orders.append(order)

    def atom_valence(self, idx: int) -> int:
        v = {"C": 4, "N": 3, "O": 2, "S": 2, "P": 5,
             "F": 1, "Cl": 1, "Br": 1, "I": 1}.get(self.atoms[idx], 4)
        return v - self.charges[idx]

    def bond_sum(self, idx: int) -> float:
        s = 0.0
        for a, b in self.bonds:
            if a == idx or b == idx:
                s += self.orders[self.bonds.index((a, b))]
        return s


def _apply_hydrogenation(
    atoms: list[str],
    bonds: list[tuple[int, int]],
    orders: list[float],
    hydro: dict,
    nh_positions: set[int],
    topo: dict,
) -> tuple[bool, set[int], list[float], list[tuple[int, int]], list[str]]:
    """把芳环按 二氢/四氢/六氢 部分饱和.

    返回替换后的 ``(is_arom, nh_positions, orders, bonds, atoms)``。
    ``氢化`` 的位次按环位次 (1 起) 给出; 给定 ``locants`` 时把与这些位次
    相邻的环内双键改为单键, 否则按级别把芳环整体降为单键骨架 (四氢/六氢)。
    """
    level = hydro.get("level")
    locants = hydro.get("locants") or []

    # 位次 → 原子下标
    locs_table = topo.get("locants") or {}
    pos_to_idx: dict[int, int] = {}
    for k, v in locs_table.items():
        if isinstance(k, str) and k.isdigit():
            pos_to_idx[int(k)] = v
    if not pos_to_idx:
        pos_to_idx = {i + 1: i for i in range(len(atoms))}

    # 该环全部环内双键
    double_edges = [i for i, o in enumerate(orders) if o == 2 or o == 1.5]

    saturate: set[int] = set()
    if locants:
        target_atoms = {pos_to_idx[int(p)] for p in locants if int(p) in pos_to_idx}
        for ei in double_edges:
            a, b = bonds[ei]
            if a in target_atoms or b in target_atoms:
                saturate.add(ei)
    else:
        # 无位次: 二氢饱和 1 条双键, 四氢/六氢/全氢饱和全部剩余双键
        want = {2: 1, 4: 2, 6: 3}.get(level if isinstance(level, int) else 0, None)
        if want is None:
            want = len(double_edges)
        saturate = set(double_edges[:want])

    new_orders = list(orders)
    for ei in saturate:
        new_orders[ei] = 1

    # 饱和后仍存在双键 → 仍按芳香写 (例如 1,6-二氢吡啶的残环此时已非芳香,
    # 应整体改用 kekulé 单双键; 这里简化为: 只要还有 1.5 键就保留芳香性,
    # 否则退化为脂肪环)。
    still_arom = any(o == 1.5 for o in new_orders)
    if still_arom:
        arom_mask_atoms = set()
        for ei, o in enumerate(new_orders):
            if o == 1.5:
                arom_mask_atoms.update(bonds[ei])
        return True, nh_positions & arom_mask_atoms, new_orders, bonds, atoms

    return False, set(), new_orders, bonds, atoms


def _find_smallest_ring(graph: MoleculeGraph, anchor: int) -> list[int] | None:
    """从 anchor 出发找一条最短闭合回路, 返回按环序排列的边下标列表.

    做法: 对 anchor 的每对邻居, 在"移除 anchor"的图中求最短路; 走通即得到
    ``anchor → 邻居A → … → 邻居B → anchor`` 的环。这样得到的是真正按环上
    顺序排列的边, 才能正确交替赋单双键 (此前版本返回的边顺序是乱的, 导致
    ``O=C(N=1)=CCCC=1`` 这种非法 SMILES)。
    """
    adj: dict[int, list[tuple[int, int]]] = {}
    for ei, (a, b) in enumerate(graph.bonds):
        adj.setdefault(a, []).append((b, ei))
        adj.setdefault(b, []).append((a, ei))

    neighbors = adj.get(anchor, [])
    if len(neighbors) < 2:
        return None

    def _shortest_path(src: int, dst: int) -> list[int] | None:
        """src → dst 的最短边序列, 禁止经过 anchor."""
        prev: dict[int, tuple[int, int]] = {src: (-1, -1)}
        queue = [src]
        while queue:
            cur = queue.pop(0)
            if cur == dst:
                break
            for nbr, ei in adj.get(cur, []):
                if nbr == anchor or nbr in prev:
                    continue
                prev[nbr] = (cur, ei)
                queue.append(nbr)
        if dst not in prev:
            return None
        path: list[int] = []
        node = dst
        while node != src:
            parent, ei = prev[node]
            path.append(ei)
            node = parent
        path.reverse()
        return path

    best: list[int] | None = None
    for i in range(len(neighbors)):
        for j in range(i + 1, len(neighbors)):
            nbr_a, edge_a = neighbors[i]
            nbr_b, edge_b = neighbors[j]
            middle = _shortest_path(nbr_a, nbr_b)
            if middle is None:
                continue
            candidate = [edge_a] + middle + [edge_b]
            if best is None or len(candidate) < len(best):
                best = candidate
    return best


def _kekulize_around(graph: MoleculeGraph, anchor: int) -> None:
    """把一个芳环局部降级为 kekulé 单双键 (锚点原子以单键入环).

    芳香原子若再挂一个外环双键 (``2-氧代吡啶`` 的 C=O), 该原子在芳香体系里
    已有 3 条键, 再加 =O 就是 5 价, RDKit 无法 kekulize。命名上这类
    "吡啶酮"本来就是内酰胺: 环内改成交替单双键, 让锚点只带单键入环。
    """
    cycle_edges = _find_smallest_ring(graph, anchor)
    if not cycle_edges or len(cycle_edges) < 4:
        return

    # 环序: [anchor→n1, …, nk→anchor]。anchor 两侧必须都是单键 (腾一条价给
    # 外环 =O), 中间按 2/1 交替。偶数环保证这样能闭合且无相邻双键。
    n_edges = len(cycle_edges)
    for step, ei in enumerate(cycle_edges):
        if step == 0 or step == n_edges - 1:
            graph.orders[ei] = 1
        else:
            graph.orders[ei] = 2 if step % 2 == 1 else 1

    ring_atoms = set()
    for ei in cycle_edges:
        ring_atoms.update(graph.bonds[ei])
    for atom in ring_atoms:
        graph.aromatic_indices.discard(atom)
        graph.explicit_h.pop(atom, None)


def _assemble_fragment(graph: MoleculeGraph, frag: dict) -> tuple[list[int], dict[str, int]]:
    """递归把 AST fragment 组装进 graph, 返回 (head_atom_indices, locant_map)."""
    head = frag["head"]
    head_type = head["type"]

    # ---- 环体系 ----
    if head_type in ("ring", "fused", "spiro", "bridged"):
        if head_type == "ring":
            core = head.get("core", "")
        elif head_type == "fused":
            core = head.get("core", "")
        elif head_type in ("spiro", "bridged"):
            core = head.get("template", "")
        else:
            core = head.get("core", "")

        topo = RING_TOPO["fused_systems"].get(core)
        if topo is None:
            topo = RING_TOPO["monocycles"].get(core)
        if topo is None:
            topo = RING_TOPO["benzofused"].get(core)

        if topo:
            atoms = list(topo["atoms"])
            bonds = [tuple(b) for b in topo["bonds"]]
            orders = [float(o) for o in topo.get("orders", [1] * len(bonds))]
            # 芳香性来自拓扑数据, 不再靠环名清单推断 (喹啉等稠环由数据声明)。
            # 默认 False: 哌啶/哌嗪/吗啉/环己烷等饱和环必须留在脂肪族。
            is_arom = bool(topo.get("aromatic", False))
            # 吡咯型氮的氢必须显式登记, 否则芳环无法 kekulize。
            nh_positions = set(topo.get("nh", [])) if is_arom else set()

            # 部分氢化: 二氢/四氢/六氢 把芳环换成饱和骨架。
            # 位次给出时 (1,6-二氢) 只饱和与这些位次相邻的键; 无位次时
            # 按"补足到指定 H 数"的语义处理环内双键。
            hydro = head.get("hydrogenation")
            if hydro and is_arom:
                is_arom, nh_positions, orders, bonds, atoms = _apply_hydrogenation(
                    atoms, bonds, orders, hydro, nh_positions, topo
                )

            arom_idx = list(range(len(atoms))) if is_arom else []
            explicit_h = {i: 1 for i in nh_positions} if is_arom else {}
            atom_indices = graph.merge(
                atoms, bonds, orders,
                aromatic_atom_indices=arom_idx,
                explicit_h=explicit_h,
            )
            locs = topo.get("locants", {})
            locant_map = {}
            for k, v in locs.items():
                if v < len(atom_indices):
                    locant_map[k] = atom_indices[v]
            for i, idx in enumerate(atom_indices):
                # 有显式位次表时, 只把未被占用的序号当作位次别名, 避免
                # 8a/4a 这类稠环位次被顺序号覆盖。
                locant_map.setdefault(str(i + 1), idx)
                if atoms[i] == "N":
                    locant_map.setdefault("N", idx)
        else:
            atom_indices = graph.merge(["C"], [])
            locant_map = {"1": atom_indices[0]}

    # ---- 链 ----
    elif head_type == "chain":
        length = head.get("length", 1)
        atoms = ["C"] * length
        bonds = [(i, i + 1) for i in range(length - 1)]
        orders = [1] * len(bonds)
        atom_indices = graph.merge(atoms, bonds, orders)
        locant_map = {str(i + 1): idx for i, idx in enumerate(atom_indices)}

    # ---- 简单词组 ----
    elif head_type == "word_group":
        words = head.get("words", [])
        atom_indices, locant_map = _assemble_word_group(graph, words)

    # ---- 链接组 ----
    elif head_type in ("linked_group", "linked_frag"):
        group = head.get("group")
        if group:
            child_indices, _ = _assemble_fragment(graph, Parser(group["tokens"]).parse_name(top=False))
            atom_indices = child_indices
            locant_map = {}
        else:
            atom_indices = graph.merge(["C"], [])
            locant_map = {"1": atom_indices[0]}
    else:
        atom_indices = graph.merge(["C"], [])
        locant_map = {"1": atom_indices[0]}

    # ---- 分支 ----
    for br in frag.get("branches", []):
        if br["type"] == "subtree":
            child_frag = br["frag"]
        elif br["type"] == "group_ref":
            group = br["group"]
            child_frag = Parser(group["tokens"]).parse_name(top=False)
        elif br["type"] == "word":
            child_frag = {"head": {"type": "word_group", "words": br["words"],
                                    "multiplier": br.get("multiplier"),
                                    "hints": br.get("hints", [])},
                          "branches": [], "tail": None}
        else:
            continue

        child_indices, child_locs = _assemble_fragment(graph, child_frag)

        # 连接点: 子片段若以 "-基" 结尾, 必须挂在它声明的位次上
        # (吡啶-2-基 挂 C2, 环己基 挂 C1); 否则挂第一个原子。
        attach = child_indices[0] if child_indices else None
        child_tail = child_frag.get("tail") or {}
        if child_tail.get("kind") == "yl":
            for loc in child_tail.get("locants") or []:
                mapped = child_locs.get(str(loc))
                if mapped is not None:
                    attach = mapped
                    break
        if attach is None:
            continue

        # 分支词以 羰基/甲酰基 等结尾时, 不是把分支直接连到主体, 而是先接
        # 一个羰基碳: 哌嗪-1-羰基 = 哌嗪-N-C(=O)-, 再接下一级。
        linker = child_tail.get("linker")
        if linker == "羰基":
            co = graph.merge(["C", "O"], [(0, 1)], [2])
            graph.connect(attach, co[0])
            attach = co[0]

        # 氧代/硫代 是双键取代: 2-氧代吡啶 的 2 位碳与 O 之间必须是双键。
        # 但芳香环上挂外环双键会破坏 kekulé 结构 (RDKit 直接拒绝
        # ``n1c(=O)cccc1``), 所以此时把该环整体降级为 kekulé 单双键。
        br_hints = br.get("hints") or []
        is_oxo = any(h in ("oxo", "thioxo") for h in br_hints)
        bond_order = 2 if is_oxo else 1

        for loc in br.get("locants", []):
            loc_key = str(loc)
            target = locant_map.get(loc_key)
            if target is None:
                continue
            if is_oxo and target in graph.aromatic_indices:
                _kekulize_around(graph, target)
            graph.connect(target, attach, bond_order)

    # ---- 尾基 ----
    tail = frag.get("tail")
    if tail and atom_indices:
        tail_kind = tail.get("kind", "")
        if tail_kind == "n_oxide":
            o_idx = graph.merge(["O"], [])[0]
            for loc in tail.get("locants", []):
                loc_key = str(loc)
                if loc_key in locant_map:
                    parent_idx = locant_map[loc_key]
                    graph.connect(parent_idx, o_idx, 1)
                    graph.charges[parent_idx] = graph.charges[parent_idx] + 1
                    graph.charges[o_idx] = -1
        elif tail_kind == "yl":
            # yl = 游离价, 连接由上层处理
            pass
        else:
            # 官能团尾基 (酸/酰胺/甲酰胺/羧酸/磺酰胺...) 必须真正挂上原子,
            # 否则 1H-吡唑-4-甲酰胺 会退化成裸吡唑 (旧实现就是直接丢掉)。
            _attach_tail(graph, tail, locant_map, atom_indices)

    return atom_indices, locant_map


# 尾基 → 官能团拓扑名 (从 func_group_topo.json 的 functional_heads 取)。
_TAIL_FUNC_NAME = {
    "acid": "酸",
    "amide": "酰胺",
    "formamide": "甲酰胺",
    "carboxylic": "酸",
    "carboxy": "酸",
    "sulfonamide": "磺酰胺",
    "aldehyde": "醛",
    "ketone": "酮",
    "alcohol": "醇",
    "amine": "胺",
    "nitrile": "腈",
}

# 酯尾基: 羧酸碳上的 -OR。R 由 kind 决定 (甲酯/乙酯/丙酯)。
_ESTER_ALKYL = {
    "ester_methyl": ["C"],
    "ester_ethyl": ["C", "C"],
    "ester_propyl": ["C", "C", "C"],
}


def _attach_tail(
    graph: MoleculeGraph,
    tail: dict,
    locant_map: dict[str, int],
    head_indices: list[int],
) -> None:
    """把尾基官能团原子挂到主体上.

    连接点按尾基的 ``locants`` 选主体原子; 没有位次时退化为主体的第一个原子。
    ``甲酰胺`` 挂在环上表示 ``-C(=O)NH2``, 其碳是尾基自己提供的碳, 不占用
    主体原子 —— 这一点和 ``酸`` (主体末端碳带上 =O 与 -OH) 不同, 所以
    统一按 functional_heads 的图谱"整组挂接", 不再对主体做原位修饰。

    两种"连接型"尾基单独处理, 因为它们不改主体、只插入一个原子:

    * ``酰基/甲酰基`` (-C(=O)-): 苯甲酰基 = 苯基-C(=O)-, 少这个碳就会把
      苯甲酰基退化成苯基, 少一个 O 和一个 C。
    * ``氧基`` (-O-): 4-氟苯氧基 = 4-氟苯基-O-, 少这个氧就会把醚变成
      直接相连的联苯类结构。
    """
    kind = tail.get("kind", "")
    locants = tail.get("locants") or []
    targets = []
    for loc in locants:
        key = str(loc)
        if key in locant_map:
            targets.append(locant_map[key])
    if not targets:
        targets = head_indices[:1]
    if not targets:
        return

    # 连接型尾基: 只插一个羰基/醚氧, 然后返回 (不追加整组官能团)
    if kind in ("acyl", "formyl"):
        co = graph.merge(["C", "O"], [(0, 1)], [2])
        for target in targets:
            graph.connect(target, co[0], 1)
        return
    if kind in ("oxy_link",):
        o = graph.merge(["O"], [])
        for target in targets:
            graph.connect(target, o[0], 1)
        return
    if kind in ("carbonyl_link",):
        co = graph.merge(["C", "O"], [(0, 1)], [2])
        for target in targets:
            graph.connect(target, co[0], 1)
        return

    # 酯: 主体-C(=O)-O-R。
    #
    # 两种来源必须分开处理, 否则 苯甲酸乙酯 会得到"苯环上挂两个羧基"的
    # 荒谬结构 (苯甲酸 的 COMPOUND_TOPO 已含完整 -COOH):
    #
    #   1. 主体本身已是羧酸 (苯甲酸/乙酸...) -> 只把这个 -OH 的氢换成烷基;
    #   2. 主体是环/链 (吡唑-4-羧酸乙酯 的 羧酸 部分由尾基提供) -> 新建酯基。
    if kind in _ESTER_ALKYL:
        alkyl_chain = _ESTER_ALKYL[kind]

        existing_oh = _find_acid_hydroxyl(graph, targets[0])
        if existing_oh is not None:
            chain_idx = graph.merge(
                list(alkyl_chain),
                [(i, i + 1) for i in range(len(alkyl_chain) - 1)],
                [1] * (len(alkyl_chain) - 1),
            )
            graph.connect(existing_oh, chain_idx[0], 1)
            return

        acid = FUNC_TOPO["functional_heads"]["酸"]
        ester = graph.merge(
            list(acid["atoms"]),
            [tuple(b) for b in acid["bonds"]],
            acid.get("orders"),
        )
        # functional_heads["酸"] = C,O,O, bonds (0,1)=2 (0,2)=1
        ester_c, ester_o = ester[0], ester[2]
        chain_idx = graph.merge(
            list(alkyl_chain),
            [(i, i + 1) for i in range(len(alkyl_chain) - 1)],
            [1] * (len(alkyl_chain) - 1),
        )
        graph.connect(ester_o, chain_idx[0], 1)
        for target in targets:
            graph.connect(target, ester_c, 1)
        return

    fname = _TAIL_FUNC_NAME.get(kind)
    if not fname:
        return
    topo = FUNC_TOPO["functional_heads"].get(fname)
    if not topo or topo.get("modify"):
        return

    frag_atoms = list(topo["atoms"])
    frag_bonds = [tuple(b) for b in topo["bonds"]]
    frag_orders = list(topo.get("orders", [1] * len(frag_bonds)))
    new_indices = graph.merge(frag_atoms, frag_bonds, frag_orders)

    # 挂接点: 官能团的 0 号原子 (与 func_group_topo 的 connect_chain 约定一致)
    anchor = new_indices[0]
    for target in targets:
        graph.connect(target, anchor, 1)


def _find_acid_hydroxyl(graph: MoleculeGraph, start: int) -> int | None:
    """找羧酸里那个带氢的氧 (-C(=O)-OH 的 O).

    酯化只需替换这个氧上的 H, 不该再长出一个羧基。

    ``start`` 可能只是主体上的一个普通原子 (例如 苯甲酸 里挂的是环碳,
    羧基碳在环外), 所以这里做一次全图扫描而不是从 start 起搜: 候选 O 必须
    是末端重原子, 且它的碳邻居同时带一个 =O。
    """

    def _neighbors(i: int):
        out = []
        for ei, (a, b) in enumerate(graph.bonds):
            if a == i:
                out.append((b, graph.orders[ei]))
            elif b == i:
                out.append((a, graph.orders[ei]))
        return out

    candidates = []
    for idx, atom in enumerate(graph.atoms):
        if atom != "O":
            continue
        nbrs = _neighbors(idx)
        if len(nbrs) != 1:
            continue
        carbon, c_order = nbrs[0]
        if graph.atoms[carbon] != "C":
            continue
        # 必须是与羰基碳**单键**相连的那个氧 (-OH); 双键氧是羰基本身。
        if c_order != 1:
            continue
        if not any(
            graph.atoms[x] == "O" and od == 2 for x, od in _neighbors(carbon)
        ):
            continue
        candidates.append(idx)

    if not candidates:
        return None
    candidates.sort()
    return candidates[0]


def _assemble_word_group(graph: MoleculeGraph, words: list[str]) -> tuple[list[int], dict[str, int]]:
    """组装 word_group 类型的 head."""
    w = words[0] if words else ""

    # 常见化合物 (预定义拓扑) — must check before chain_char
    COMPOUND_TOPO = {
        "甲苯": {
            "atoms": ["C", "C", "C", "C", "C", "C", "C"],
            "bonds": [(0,1),(1,2),(2,3),(3,4),(4,5),(5,0),(0,6)],
            "orders": [1.5]*6 + [1],
            "arom": [0,1,2,3,4,5],
        },
        "苯酚": {
            "atoms": ["C", "C", "C", "C", "C", "C", "O"],
            "bonds": [(0,1),(1,2),(2,3),(3,4),(4,5),(5,0),(0,6)],
            "orders": [1.5]*6 + [1],
            "arom": [0,1,2,3,4,5],
        },
        "苯胺": {
            "atoms": ["C", "C", "C", "C", "C", "C", "N"],
            "bonds": [(0,1),(1,2),(2,3),(3,4),(4,5),(5,0),(0,6)],
            "orders": [1.5]*6 + [1],
            "arom": [0,1,2,3,4,5],
        },
        "苯甲醛": {
            "atoms": ["C", "C", "C", "C", "C", "C", "C", "O"],
            "bonds": [(0,1),(1,2),(2,3),(3,4),(4,5),(5,0),(0,6),(6,7)],
            "orders": [1.5]*6 + [1, 2],
            "arom": [0,1,2,3,4,5],
        },
        "苯甲酸": {
            "atoms": ["C", "C", "C", "C", "C", "C", "C", "O", "O"],
            "bonds": [(0,1),(1,2),(2,3),(3,4),(4,5),(5,0),(0,6),(6,7),(6,8)],
            "orders": [1.5]*6 + [1, 2, 1],
            "arom": [0,1,2,3,4,5],
        },
        "苯甲醇": {
            "atoms": ["C", "C", "C", "C", "C", "C", "C", "O"],
            "bonds": [(0,1),(1,2),(2,3),(3,4),(4,5),(5,0),(0,6),(6,7)],
            "orders": [1.5]*6 + [1, 1],
            "arom": [0,1,2,3,4,5],
        },
        "氯甲烷": {
            "atoms": ["C", "Cl"],
            "bonds": [(0, 1)],
            "orders": [1],
            "arom": [],
        },
        "二氯甲烷": {
            "atoms": ["C", "Cl", "Cl"],
            "bonds": [(0, 1), (0, 2)],
            "orders": [1, 1],
            "arom": [],
        },
        "三氯甲烷": {
            "atoms": ["C", "Cl", "Cl", "Cl"],
            "bonds": [(0, 1), (0, 2), (0, 3)],
            "orders": [1, 1, 1],
            "arom": [],
        },
        "四氯化碳": {
            "atoms": ["C", "Cl", "Cl", "Cl", "Cl"],
            "bonds": [(0, 1), (0, 2), (0, 3), (0, 4)],
            "orders": [1, 1, 1, 1],
            "arom": [],
        },
        "氯苯": {
            "atoms": ["C", "C", "C", "C", "C", "C", "Cl"],
            "bonds": [(0,1),(1,2),(2,3),(3,4),(4,5),(5,0),(0,6)],
            "orders": [1.5]*6 + [1],
            "arom": [0,1,2,3,4,5],
        },
        "溴苯": {
            "atoms": ["C", "C", "C", "C", "C", "C", "Br"],
            "bonds": [(0,1),(1,2),(2,3),(3,4),(4,5),(5,0),(0,6)],
            "orders": [1.5]*6 + [1],
            "arom": [0,1,2,3,4,5],
        },
        "碘苯": {
            "atoms": ["C", "C", "C", "C", "C", "C", "I"],
            "bonds": [(0,1),(1,2),(2,3),(3,4),(4,5),(5,0),(0,6)],
            "orders": [1.5]*6 + [1],
            "arom": [0,1,2,3,4,5],
        },
        "乙醚": {
            "atoms": ["C", "C", "O", "C", "C"],
            "bonds": [(0,1),(1,2),(2,3),(3,4)],
            "orders": [1, 1, 1, 1],
            "arom": [],
        },
        "乙酸甲酯": {
            "atoms": ["C", "C", "O", "C", "O"],
            "bonds": [(0,1),(0,2),(2,3),(0,4)],
            "orders": [1, 1, 1, 2],
            "arom": [],
        },
        "乙酸乙酯": {
            "atoms": ["C", "C", "O", "C", "C", "O"],
            "bonds": [(0,1),(0,2),(2,3),(3,4),(0,5)],
            "orders": [1, 1, 1, 1, 2],
            "arom": [],
        },
        "氯乙烷": {
            "atoms": ["C", "C", "Cl"],
            "bonds": [(0, 1), (0, 2)],
            "orders": [1, 1],
            "arom": [],
        },
        "二氯乙烷": {
            "atoms": ["C", "C", "Cl", "Cl"],
            "bonds": [(0, 1), (0, 2), (1, 3)],
            "orders": [1, 1, 1],
            "arom": [],
        },
        "溴甲烷": {
            "atoms": ["C", "Br"],
            "bonds": [(0, 1)],
            "orders": [1],
            "arom": [],
        },
        "溴乙烷": {
            "atoms": ["C", "C", "Br"],
            "bonds": [(0, 1), (0, 2)],
            "orders": [1, 1],
            "arom": [],
        },
        "碘甲烷": {
            "atoms": ["C", "I"],
            "bonds": [(0, 1)],
            "orders": [1],
            "arom": [],
        },
        "碘乙烷": {
            "atoms": ["C", "C", "I"],
            "bonds": [(0, 1), (0, 2)],
            "orders": [1, 1],
            "arom": [],
        },
    }
    if w in COMPOUND_TOPO:
        topo = COMPOUND_TOPO[w]
        atom_indices = graph.merge(
            list(topo["atoms"]),
            [tuple(b) for b in topo["bonds"]],
            topo.get("orders"),
            aromatic_atom_indices=topo.get("arom", []),
        )
        locant_map = {str(i + 1): idx for i, idx in enumerate(atom_indices)}
        for i, a in enumerate(topo["atoms"]):
            if a == "N":
                locant_map["N"] = atom_indices[i]
        return atom_indices, locant_map

    # 直接查链头 (乙烷, 丙烷, ...)
    if w in FUNC_TOPO["chain_heads"]:
        topo = FUNC_TOPO["chain_heads"][w]
        atom_indices = graph.merge(list(topo["atoms"]),
                                    [tuple(b) for b in topo["bonds"]],
                                    topo.get("orders"))
        locant_map = {str(i + 1): idx for i, idx in enumerate(atom_indices)}
        return atom_indices, locant_map

    # 直接查官能团头 (酸, 酰胺, ...)
    if w in FUNC_TOPO["functional_heads"]:
        topo = FUNC_TOPO["functional_heads"][w]
        if topo.get("modify"):
            atom_indices = graph.merge(["C"], [])
            locant_map = {"1": atom_indices[0]}
            return atom_indices, locant_map
        atom_indices = graph.merge(list(topo["atoms"]),
                                    [tuple(b) for b in topo["bonds"]],
                                    topo.get("orders"))
        locant_map = {str(i + 1): idx for i, idx in enumerate(atom_indices)}
        for i, a in enumerate(topo["atoms"]):
            if a == "N" and i < len(atom_indices):
                locant_map["N"] = atom_indices[i]
                break
        return atom_indices, locant_map

    # 官能团取代基 (羟基/氟/氯/溴/碘/氰基/巯基/甲氧基/磺酰基/羟甲基...)
    #
    # 必须排在 "链长字 + 后缀" 组合之前: ``甲磺酰基`` 以 ``甲`` 开头, 若先走
    # 链长字分支就会被拆成"甲基 + 磺酰基"并静默产出一个碳, 丢掉整个磺酰基。
    sub_topo = (
        FUNC_TOPO["hetero_substituents"].get(w)
        or FUNC_TOPO["simple_substituents"].get(w)
        or FUNC_TOPO["ring附属基团"].get(w)
    )
    if sub_topo:
        atoms_s = list(sub_topo.get("atoms") or ["C"])
        bonds_s = [tuple(b) for b in sub_topo.get("bonds", [])]
        orders_s = sub_topo.get("orders") or [1] * len(bonds_s)
        atom_indices = graph.merge(atoms_s, bonds_s, orders_s)
        locant_map = {"1": atom_indices[0], str(atom_indices[0] + 1): atom_indices[0]}
        for i, a in enumerate(atoms_s):
            if a == "N":
                locant_map["N"] = atom_indices[i]
                break
        return atom_indices, locant_map

    # 尝试 "链长字 + 后缀" 组合
    chain_char = None
    for ch, n in CHAIN_CHARS.items():
        if w.startswith(ch) and len(w) > len(ch):
            chain_char = (ch, n)
            break

    if chain_char:
        ch, n = chain_char
        suffix = w[len(ch):]
        atoms = ["C"] * n
        bonds = [(i, i + 1) for i in range(n - 1)]
        orders = [1] * len(bonds)

        if suffix in ("酸",):
            atoms.extend(["O", "O"])
            bonds.append((0, n))
            bonds.append((0, n + 1))
            orders.extend([2, 1])
        elif suffix == "酰胺":
            atoms.extend(["O", "N"])
            bonds.append((0, n))
            bonds.append((0, n + 1))
            orders.extend([2, 1])
        elif suffix == "醛":
            atoms.append("O")
            bonds.append((0, n))
            orders.append(2)
        elif suffix == "酮":
            atoms.append("O")
            bonds.append((1, n))
            orders.append(2)
        elif suffix == "醇":
            atoms.append("O")
            bonds.append((n - 1, n))
            orders.append(1)
        elif suffix == "胺":
            atoms.append("N")
            bonds.append((n - 1, n))
            orders.append(1)
        elif suffix == "腈":
            atoms.extend(["C", "N"])
            bonds.append((n - 1, n))
            bonds.append((n, n + 1))
            orders.extend([1, 3])

        atom_indices = graph.merge(atoms, bonds, orders)
        locant_map = {str(i + 1): idx for i, idx in enumerate(atom_indices)}
        if "N" in atoms:
            locant_map["N"] = atom_indices[atoms.index("N")]
        return atom_indices, locant_map

    # 芳基取代基 (苯基, 吡啶基, etc.)
    RING_WORDS = {
        "苯基": ("苯", 1),
        "吡啶基": ("吡啶", 1),
        "吡咯基": ("吡咯", 1),
        "呋喃基": ("呋喃", 1),
        "噻吩基": ("噻吩", 1),
        "咪唑基": ("咪唑", 1),
        "吡唑基": ("吡唑", 1),
        "噁唑基": ("噁唑", 1),
        "噻唑基": ("噻唑", 1),
        "三唑基": ("三唑", 1),
    }
    if w in RING_WORDS:
        core, _connect_pos = RING_WORDS[w]
        topo = RING_TOPO["monocycles"].get(core)
        if topo:
            atoms_l = list(topo["atoms"])
            bonds_l = [tuple(b) for b in topo["bonds"]]
            orders_l = topo.get("orders", [1] * len(bonds_l))
            is_arom = bool(topo.get("aromatic"))
            arom_idx = list(range(len(atoms_l))) if is_arom else []
            explicit_h = {i: 1 for i in (topo.get("nh", []) if is_arom else [])}
            atom_indices = graph.merge(
                atoms_l, bonds_l, orders_l,
                aromatic_atom_indices=arom_idx,
                explicit_h=explicit_h,
            )
            locant_map = {str(i + 1): idx for i, idx in enumerate(atom_indices)}
            for i, a in enumerate(atoms_l):
                if a == "N":
                    locant_map.setdefault("N", atom_indices[i])
            return atom_indices, locant_map

    # 官能团取代基 (羟基/氟/氯/溴/碘/氰基/巯基/甲氧基/...)
    sub_topo = (
        FUNC_TOPO["hetero_substituents"].get(w)
        or FUNC_TOPO["simple_substituents"].get(w)
        or FUNC_TOPO["ring附属基团"].get(w)
    )
    if sub_topo:
        atoms_s = list(sub_topo.get("atoms") or ["C"])
        bonds_s = [tuple(b) for b in sub_topo.get("bonds", [])]
        orders_s = sub_topo.get("orders") or [1] * len(bonds_s)
        atom_indices = graph.merge(atoms_s, bonds_s, orders_s)
        locant_map = {"1": atom_indices[0], str(atom_indices[0] + 1): atom_indices[0]}
        for i, a in enumerate(atoms_s):
            if a == "N":
                locant_map["N"] = atom_indices[i]
                break
        return atom_indices, locant_map

    # 未覆盖的词: 绝不能静默造一个碳冒充结构 —— 显式失败, 保持 pending_review 语义。
    raise ParseError(f"unsupported substituent or head word {w!r}")


def assemble_graph(ast: dict) -> MoleculeGraph:
    """AST dict → MoleculeGraph."""
    g = MoleculeGraph()
    _assemble_fragment(g, ast)
    return g


# ---- SMILES 生成 ----

# 芳香原子价态 (kekulé 之前的成键能力)
_AROM_VALENCE = {"C": 3, "N": 3, "O": 2, "S": 2, "P": 3, "B": 3, "Se": 2, "As": 3}


def _implicit_h(graph: MoleculeGraph, idx: int, aromatic_indices: set[int]) -> int:
    """计算隐式氢数 (脂肪族)."""
    atom = graph.atoms[idx]
    e = ELEM.get(atom)
    if not e:
        return 0

    bond_order_sum = sum(
        graph.orders[graph.bonds.index((a, b))]
        for a, b in graph.bonds if a == idx or b == idx
    )

    valence = elem_valence(atom, aromatic=(idx in aromatic_indices))
    h = valence - round(bond_order_sum) - graph.charges[idx]
    return max(0, h)


def _atom_h_for_token(graph: MoleculeGraph, idx: int) -> int:
    """方括号原子要写出的氢数.

    负电荷杂原子 (N-氧化物里的 ``[O-]``) 不带氢 —— 用价态公式会算出
    ``[OH2-]``, RDKit 会报氧价态 4。只有正电荷/中性杂原子才按价态补氢。
    """
    if graph.charges[idx] < 0:
        return 0
    if idx in graph.aromatic_indices:
        return _aromatic_h(graph, idx)
    return _implicit_h(graph, idx, set())


def _aromatic_h(graph: MoleculeGraph, idx: int) -> int:
    """芳香原子的氢数.

    芳香碳按芳香价 3 与成键数之差给出。吡咯型氮 (``[nH]``) 只有在环内仅
    两条键时才带氢 —— 一旦 N-取代 (``N-甲基吡咯``) 或 N-桥接, 它就没有氢,
    必须写裸 ``n``。这一点无法由价态推断, 需要 ``graph.explicit_h`` 与度数
    共同判定, 否则 RDKit 会以度 5 拒绝整个分子。
    """
    atom = graph.atoms[idx]
    degree = sum(1 for a, b in graph.bonds if a == idx or b == idx)
    if atom == "N":
        if graph.explicit_h.get(idx, 0) and degree == 2:
            return 1
        return 0
    valence = _AROM_VALENCE.get(atom, 3)
    return max(0, valence - degree - graph.charges[idx])


def _charge_str(charge: int) -> str:
    if charge == 0:
        return ""
    sign = "+" if charge > 0 else "-"
    mag = abs(charge)
    return sign if mag == 1 else f"{sign}{mag}"


def _atom_token(graph: MoleculeGraph, idx: int) -> str:
    """输出一个原子的 SMILES 记号, 必要时改用方括号形式."""
    atom = graph.atoms[idx]
    charge = graph.charges[idx]

    if idx in graph.aromatic_indices:
        low = atom.lower()
        if atom == "N":
            if charge:
                # 芳香 N-氧化物: N 必须写成 [n+] 才能承载正电荷并成环
                h = _atom_h_for_token(graph, idx)
                hpart = "H" if h == 1 else (f"H{h}" if h > 1 else "")
                return f"[{low}{hpart}{_charge_str(charge)}]"
            # 吡咯型氮写 [nH]; 吡啶型/N-取代氮写裸 n
            return "[nH]" if _aromatic_h(graph, idx) else "n"
        if charge:
            h = _atom_h_for_token(graph, idx)
            hpart = "H" if h == 1 else (f"H{h}" if h > 1 else "")
            return f"[{low}{hpart}{_charge_str(charge)}]"
        return low

    if charge:
        h = _atom_h_for_token(graph, idx)
        hpart = "H" if h == 1 else (f"H{h}" if h > 1 else "")
        return f"[{atom}{hpart}{_charge_str(charge)}]"
    return atom


def _bond_symbol(graph: MoleculeGraph, ai: int, bi: int, order: float) -> str:
    """键记号.

    两个**仍然**属于芳香体系的原子之间省略符号 (芳香键)。一旦某侧已按
    kekulé 降级 (吡啶酮), 就必须写出 ``=``, 否则环闭合那一步会变成
    ``O=C(N=1)=CCCC=1`` 这种非法写法。

    芳香-芳香之间的**单键**要显式写 ``-``。省略时 RDKit 会把两个芳环之间
    的键当作可参与 kekulize 的芳香键, 在 ``c1ccc(cc1)c2(O)ccccc2`` 这类
    "芳香环 + 环外取代" 的组合上直接失败 ("Can't kekulize"); 显式 ``-``
    明确告诉它这是定域单键, 与带取代基的芳环才能正确 kekulize。
    """
    if ai in graph.aromatic_indices and bi in graph.aromatic_indices:
        if order == 1.5:
            return ""
        if order == 1:
            return "-"
    if order == 2:
        return "="
    if order == 3:
        return "#"
    return ""


def _find_start_atom(graph: MoleculeGraph) -> int:
    """起始原子: 优先"干净"的环原子, 其次末端碳.

    "干净"指该原子的全部邻居都在同一个芳香体系内 (无环外取代)。RDKit 的
    kekulizer 在 ``n1ccccc1-c2(O)ccccc2`` 这种"环闭合编号正好开在一个带取代
    基的环原子上"的写法会失败, 而把编号挪到未取代的位置
    (``n1ccccc1-c2ccccc2(O)``)就正常。因此起始原子优先选无环外取代的环原子。
    """
    n = len(graph.atoms)
    degree = [0] * n
    for a, b in graph.bonds:
        degree[a] += 1
        degree[b] += 1

    adj_view: list[list[tuple[int, float, int]]] = [[] for _ in range(n)]
    for ei, (a, b) in enumerate(graph.bonds):
        adj_view[a].append((b, graph.orders[ei], ei))
        adj_view[b].append((a, graph.orders[ei], ei))

    def _is_clean_ring_atom(i: int) -> bool:
        if i not in graph.aromatic_indices:
            return False
        return all(j in graph.aromatic_indices for j, _o, _e in adj_view[i])

    # 1) 环外末端碳: 让链从末端展开, 输出可读 (Cc1ccccc1 而非 c(c1C)cccc1)
    terminal_c = [
        i for i in range(n)
        if degree[i] == 1 and graph.atoms[i] == "C" and i not in graph.aromatic_indices
    ]
    if terminal_c:
        return terminal_c[0]

    # 2) 无环外取代的芳香原子: 避免环闭合编号开在带取代基的环原子上,
    #    否则 n1ccccc1-c2(O)ccccc2 这类组合 RDKit 无法 kekulize。
    clean = [i for i in range(n) if _is_clean_ring_atom(i)]
    if clean:
        return clean[0]

    # 3) 任何末端原子, 最后退化到 0
    terminal = [i for i in range(n) if degree[i] == 1]
    return terminal[0] if terminal else 0


def _kekulize_exocyclic_double_bonds(graph: MoleculeGraph) -> None:
    """芳香环上若有外环双键 (=O/=[N]), 把该环整体降级为 kekulé 单双键.

    ``c1c(=O)ccc(...)c1`` 这类写法 RDKit 直接拒绝 ("Can't kekulize"), 因为
    芳香原子在芳香体系里已有 3 条键, 再加外环 =O 就是 5 价。化学上这类
    "吡啶酮/苯醌" 本来就应该用 kekulé 结构表达。
    """
    targets: list[int] = []
    for ei, (a, b) in enumerate(graph.bonds):
        if graph.orders[ei] != 2:
            continue
        for exo, ring_atom in ((a, b), (b, a)):
            if exo in graph.aromatic_indices:
                continue
            if ring_atom not in graph.aromatic_indices:
                continue
            if ring_atom not in targets:
                targets.append(ring_atom)
    for ring_atom in targets:
        _kekulize_around(graph, ring_atom)


def _needs_ring_double_bond(graph: MoleculeGraph, idx: int) -> bool:
    """该芳香原子在 kekulé 式里是否需要一个环内双键.

    Kekulé 表示中每个 sp2 芳香原子用掉一条 π 键。判定必须看**环外**键:
    环原子的价态 = 环内键数 + 环外键数 (按键级)。

    * 吡咯型氮 (带 H 或 N-取代): 贡献孤对电子, 环内全单键 → 不需要双键。
    * 呋喃氧/噻吩硫: 同理。
    * 环外已有**双键**的碳 (吡啶酮/醌): 环内不能再有双键, 否则 5 价。
    * 环外只有单键的碳: 需要一条环内双键 (芳香碳的本义)。
    """
    atom = graph.atoms[idx]
    if atom in ("O", "S", "Se"):
        return False

    # 环外键的键级总和; 环内边只统计条数
    exo_double = False
    exo_single = 0
    for ei, (a, b) in enumerate(graph.bonds):
        if idx != a and idx != b:
            continue
        other = b if a == idx else a
        order = graph.orders[ei]
        if other in graph.aromatic_indices and order == 1.5:
            continue  # 环内芳香键
        if other in graph.aromatic_indices and order in (1, 2):
            continue  # 已降级的环内键
        if order == 2:
            exo_double = True
        else:
            exo_single += 1

    if atom == "N":
        if graph.explicit_h.get(idx, 0):
            return False
        if exo_double:
            # 环外 =N (如 N-氧化物/亚胺) 已用掉 π
            return False
        degree = sum(1 for a, b in graph.bonds if a == idx or b == idx)
        return not (degree >= 3 or exo_single)

    return not exo_double


def _kekulize_all(graph: MoleculeGraph) -> None:
    """把所有芳香环改写成 kekulé 单双键 (消除小写芳香记号).

    这是生成 SMILES 前最稳的一步。芳香的隐式写法要求 RDKit 自己找到合法
    kekulé 结构, 只要有一个原子"给谁 π 电子"不明确 (吡啶酮、N-氧化物、
    多环并合), 它就整体失败并拒绝该 SMILES。这里主动求解完美匹配:
    每个"需要双键"的芳香原子恰好匹配一条环内双键, 于是输出的是明确的
    ``C1=CC=CC=C1`` 形式, RDKit 无需再推断。

    匹配用回溯 (环原子数很小, 且 3-正则芳香图几乎不需要回溯)。
    """
    arom = sorted(graph.aromatic_indices)
    if not arom:
        return
    arom_set = set(arom)

    # 芳香子图的边 (只保留两端都芳香的边)
    ring_edges = [
        ei for ei, (a, b) in enumerate(graph.bonds)
        if a in arom_set and b in arom_set
    ]

    need = {i for i in arom if _needs_ring_double_bond(graph, i)}

    # 每个待匹配原子可用的候选边
    candidates: dict[int, list[tuple[int, int]]] = {i: [] for i in need}
    for ei in ring_edges:
        a, b = graph.bonds[ei]
        if a in need and b in need:
            candidates[a].append((b, ei))
            candidates[b].append((a, ei))

    matched: dict[int, int] = {}  # atom -> edge index
    used_edges: set[int] = set()

    def _solve(remaining: set[int]) -> bool:
        if not remaining:
            return True
        # 选候选最少的原子, 减少回溯
        atom = min(remaining, key=lambda i: len(candidates[i]))
        for nbr, ei in candidates[atom]:
            if ei in used_edges or nbr in matched:
                continue
            matched[atom] = ei
            matched[nbr] = ei
            used_edges.add(ei)
            rest = remaining - {atom, nbr}
            if _solve(rest):
                return True
            used_edges.discard(ei)
            del matched[atom]
            del matched[nbr]
        return False

    if not _solve(set(need)):
        # 无法完美匹配: 保留原芳香写法, 让 RDKit 自己尝试 (可能成功)
        return

    # 先全部置单键, 再把匹配到的边置双键
    for ei in ring_edges:
        graph.orders[ei] = 1
    for ei in used_edges:
        graph.orders[ei] = 2

    # 芳香记号全部撤除, 输出为普通大写原子 + 显式单双键
    for idx in arom:
        graph.aromatic_indices.discard(idx)
        graph.explicit_h.pop(idx, None)


def _to_smiles(graph: MoleculeGraph) -> str:
    """MoleculeGraph → SMILES.

    标准 DFS 写法: 每个原子输出 ``记号 + 环闭合号 + (支链...) + 主链延续``。

    两个必须成立的性质, 也是旧实现的 bug 根源:

    1. 支链必须排在主链延续之前 —— ``C(=O)O`` 正确, 而 ``CO(=O)`` 会把
       ``=O`` 挂到羟基氧上 (氧价态 3, RDKit 直接拒绝)。
    2. 每个环闭合键的两个端点都要带同一个编号, 且两端都要输出 —— 旧实现把
       浅端写在子节点前、深端写在子节点后, 对 5 元芳环会漏掉一端。

    图不连通时用 ``.`` 连接各组分, 不静默丢原子 (旧实现只从原子 0 遍历,
    非连通图的其余片段被整体丢弃)。
    """
    if not graph.atoms:
        return ""

    # 芳香环 + 外环双键必须先降级为 kekulé, 否则 RDKit 无法 kekulize。
    _kekulize_exocyclic_double_bonds(graph)
    # 其余芳香环主动求 kekulé 完美匹配, 输出大写显式单双键形式。
    # 比起依赖 RDKit 猜测, 这样对吡咯/吡唑/N-氧化物/稠环都稳定。
    _kekulize_all(graph)

    n = len(graph.atoms)
    adj: list[list[tuple[int, float, int]]] = [[] for _ in range(n)]
    for ei, (a, b) in enumerate(graph.bonds):
        order = graph.orders[ei]
        adj[a].append((b, order, ei))
        adj[b].append((a, order, ei))

    # ---- pass 1: 生成树; 非树边即环闭合边 ----
    tree_edges: set[int] = set()
    visited = [False] * n

    def _span(root: int) -> None:
        """真正的深度优先生成树.

        必须逐个深入, 不能一次性把某原子的全部邻居都收为子节点 ——
        后者会把苯环展开成 ``c(c1)cccc1`` (合法但不可读), 而深度优先
        沿环走一圈得到惯用的 ``c1ccccc1``。

        先把环内边排在环外边之前, 让编号开在环上的**未取代**位置, 并且
        让取代基作为支链而不是主链 —— ``Cc1ccccc1`` 而不是 ``c(c1C)cccc1``。
        """
        visited[root] = True
        stack = [(root, iter(_ordered_neighbors(root)))]
        while stack:
            _cur, it = stack[-1]
            descended = False
            for nbr, _order, ei in it:
                if not visited[nbr]:
                    visited[nbr] = True
                    tree_edges.add(ei)
                    stack.append((nbr, iter(_ordered_neighbors(nbr))))
                    descended = True
                    break
            if not descended:
                stack.pop()

    def _ordered_neighbors(idx: int) -> list[tuple[int, float, int]]:
        """先沿双键走 (让双键进入生成树), 再沿环内单键, 最后才是环外取代基.

        双键必须优先进入生成树, 这样被当作"环闭合键"的边永远是单键。否则
        会写出 ``C2(O)=CC=...`` 或 ``C(O)2=CC=...`` 这类形式: 环闭合号后面
        紧跟 ``=``, RDKit 把它读成环闭合键的双键, 该碳同时拥有 支链 + 环双键
        + 环单键 = 5 价而被拒绝。这是语料里最大的一类失败 (191/233)。
        """

        def _exo_count(atom: int) -> int:
            return sum(
                1 for j, _o, _e in adj[atom] if j not in graph.aromatic_indices
            )

        in_ring_double = []
        in_ring_single = []
        outside = []
        for item in adj[idx]:
            nbr, order, _ei = item
            if idx in graph.aromatic_indices and nbr in graph.aromatic_indices:
                if order == 2:
                    in_ring_double.append(item)
                else:
                    in_ring_single.append(item)
            else:
                outside.append(item)

        in_ring_single.sort(key=lambda it: (_exo_count(it[0]), it[0]))
        return in_ring_double + in_ring_single + outside

    roots: list[int] = []
    for i in range(n):
        if not visited[i]:
            roots.append(i)
            _span(i)

    ring_digit: dict[int, int] = {}
    next_digit = 1
    for ei, (a, b) in enumerate(graph.bonds):
        if ei in tree_edges or ei in ring_digit:
            continue
        ring_digit[ei] = next_digit
        next_digit += 1

    ring_edges_at: dict[int, list[int]] = {i: [] for i in range(n)}
    for ei in ring_digit:
        a, b = graph.bonds[ei]
        ring_edges_at[a].append(ei)
        ring_edges_at[b].append(ei)

    emitted = [False] * n
    sys.setrecursionlimit(max(sys.getrecursionlimit(), 4000))

    def _subtree_size(root: int, blocked: int) -> int:
        """root 方向可经生成树到达的原子数, 用来挑主链延续."""
        seen = {blocked}
        stack = [root]
        count = 0
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            count += 1
            for nbr, _o, ei in adj[cur]:
                if ei in tree_edges and nbr not in seen:
                    stack.append(nbr)
        return count

    def _ring_tokens(idx: int) -> list[str]:
        """该原子的环闭合键记号列表 (两端都输出, 编号相同)."""
        out = []
        for ei in sorted(ring_edges_at[idx], key=lambda e: ring_digit[e]):
            d = ring_digit[ei]
            a, b = graph.bonds[ei]
            sym = _bond_symbol(graph, a, b, graph.orders[ei])
            out.append(sym + (str(d) if d < 10 else "%" + str(d)))
        return out

    def _emit(idx: int, parent: int) -> str:
        if emitted[idx]:
            return ""
        emitted[idx] = True

        children = [
            (nbr, order)
            for nbr, order, ei in adj[idx]
            if ei in tree_edges and nbr != parent and not emitted[nbr]
        ]

        # 支链先行、环闭合号后行。
        #
        # 顺序很关键: 若写成 ``C2(O)=CC=...`` (环闭合号在支链之前), RDKit 会把
        # 紧跟的 ``=`` 理解为**环闭合键**的双键, 于是该碳同时拥有 支链O + 环双键
        # + 环单键 = 5 价而拒绝。把支链写到环闭合号之前
        # (``C(O)2=CC=...`` 这一类顺序) 时, ``=`` 明确属于主链延续键。
        parts = [_atom_token(graph, idx)]

        if not children:
            parts.extend(_ring_tokens(idx))
            return "".join(parts)

        def _cont_key(item):
            nbr, _order = item
            size = _subtree_size(nbr, idx)
            is_carbon = 1 if graph.atoms[nbr] == "C" else 0
            return (-size, -is_carbon, nbr)

        children.sort(key=_cont_key)
        cont = children[0]
        for nbr, order in children[1:]:
            sym = _bond_symbol(graph, idx, nbr, order)
            parts.append("(" + sym + _emit(nbr, idx) + ")")
        parts.extend(_ring_tokens(idx))
        sym = _bond_symbol(graph, idx, cont[0], cont[1])
        parts.append(sym + _emit(cont[0], idx))
        return "".join(parts)

    order_of_roots = []
    start = _find_start_atom(graph)
    order_of_roots.append(start)
    order_of_roots.extend(r for r in roots if r != start)

    chunks = []
    for root in order_of_roots:
        if emitted[root]:
            continue
        chunk = _emit(root, -1)
        if chunk:
            chunks.append(chunk)
    return ".".join(chunks)


def parse_one_with_smiles(raw: str) -> dict:
    """解析名称并生成 SMILES (回退到纯 AST)."""
    rec = parse_one(raw)
    if rec["ok"]:
        try:
            g = assemble_graph(rec["ast"])
            rec["smiles_gen"] = _to_smiles(g)
        except Exception:
            rec["smiles_gen"] = None
    return rec


def main():
    rows = []
    with open(CORPUS, encoding="utf-8") as f:
        f.readline()
        for line in f:
            # columns: seq,page,stereo,name,smiles,conf,status,merged
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 7 and parts[6] == "ok" and parts[3]:
                rows.append({"seq": int(parts[0]), "name": parts[3]})
    recs = []
    for r in rows:
        rec = parse_one(r["name"])
        rec["seq"] = r["seq"]
        recs.append(rec)
    ok = [r for r in recs if r["ok"]]
    out = HERE / "corpus_parse.jsonl"
    with open(out, "w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    fails = [r for r in recs if not r["ok"]]
    lines = [
        f"total {len(recs)}  ok {len(ok)}  fail {len(fails)}  rate {len(ok) / len(recs):.1%}"
    ]
    err_counter = Counter()
    for r in fails:
        err = re.sub(r"at \d+|from \d+", "at N", r.get("error", "?"))
        err_counter[err] += 1
        lines.append(f"[{r['seq']}] {r['name'][:60]}")
        lines.append(f"      {r.get('error')}")
    lines.append("\n== error classes ==")
    for e, c in err_counter.most_common():
        lines.append(f"{c:4d}  {e}")
    (HERE / "parse_report.txt").write_text("\n".join(lines), encoding="utf-8")
    print(f"parsed {len(ok)}/{len(recs)} -> corpus_parse.jsonl, parse_report.txt")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
