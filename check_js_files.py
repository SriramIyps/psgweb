import re

files = ['hod_script.js', 'vp_script.js', 'hr_script.js']

def clean_js(content):
    # Strip single-line and multi-line comments
    content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
    content = re.sub(r'//.*', '', content)
    # Strip regex literals like /.../g or /.../i
    content = re.sub(r'/[^/\n]+/[gi]*', '""', content)
    return content

for filename in files:
    with open(filename, 'r', encoding='utf-8') as f:
        raw = f.read()

    cleaned = clean_js(raw)
    lines = cleaned.splitlines()

    stack = []
    in_squote = False
    in_dquote = False
    in_backtick = False
    errors = []

    for l_idx, line in enumerate(lines, 1):
        i = 0
        while i < len(line):
            ch = line[i]

            if ch == '\\' and (in_squote or in_dquote or in_backtick):
                i += 2
                continue

            if ch == "'" and not in_dquote and not in_backtick:
                in_squote = not in_squote
            elif ch == '"' and not in_squote and not in_backtick:
                in_dquote = not in_dquote
            elif ch == '`' and not in_squote and not in_dquote:
                in_backtick = not in_backtick
            elif not in_squote and not in_dquote and not in_backtick:
                if ch in '({[':
                    stack.append((ch, l_idx, i+1))
                elif ch in ')}]':
                    if not stack:
                        errors.append(f"Line {l_idx}:{i+1} Unmatched closing '{ch}'")
                    else:
                        top, t_line, t_col = stack.pop()
                        exp = {'(': ')', '{': '}', '[': ']'}[top]
                        if ch != exp:
                            errors.append(f"Line {l_idx}:{i+1} Mismatched '{ch}', expected '{exp}' matching '{top}' from line {t_line}:{t_col}")
            i += 1

    for top, t_line, t_col in stack:
        errors.append(f"Unclosed '{top}' from line {t_line}:{t_col}")

    if errors:
        print(f"=== {filename}: {len(errors)} ERROR(S) FOUND ===")
        for e in errors:
            print("  " + e)
    else:
        print(f"=== {filename}: CLEAN (No syntax or bracket errors) ===")
