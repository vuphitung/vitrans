"""Bản sao logic Lexer.string() của Ren'Py (renpy/lexer.py, giấy phép MIT) làm thước đo độc lập cho các test."""
import re

_PATTERN = re.compile(r'r?"([^\\"]|\\.)*"', re.DOTALL)


def lex_string(text):
    """Đọc một chuỗi "..." ở đầu `text` đúng như Ren'Py. Trả về (giá trị, vị trí kết thúc) hoặc None."""
    m = _PATTERN.match(text)
    if m is None:
        return None
    s = m.group(0)
    raw = s[0] == "r"
    if raw:
        s = s[1:]
    s = s[1:-1]

    def dequote(m):
        c = m.group(1)
        if c == "{":
            return "{{"
        elif c == "[":
            return "[["
        elif c == "%":
            return "%%"
        elif c == "n":
            return "\n"
        elif c[0] == "u":
            group2 = m.group(2)
            if group2:
                return chr(int(m.group(2), 16))
        else:
            return c

    if not raw:
        s = re.sub(r"[ \n]+", " ", s)
        s = re.sub(r"\\(u([0-9a-fA-F]{1,4})|.)", dequote, s)
    return s, m.end()
