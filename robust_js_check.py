import os

files = ['hod_script.js', 'vp_script.js', 'hr_script.js']

def check_js_syntax(filename):
    with open(filename, 'r', encoding='utf-8') as f:
        code = f.read()

    lines = code.splitlines()
    stack = []
    errors = []

    state = 'NORMAL' # NORMAL, SQUOTE, DQUOTE, BACKTICK, LINE_COMMENT, BLOCK_COMMENT, REGEX
    escaped = False

    for line_no, line in enumerate(lines, 1):
        if state == 'LINE_COMMENT':
            state = 'NORMAL'

        col_no = 0
        while col_no < len(line):
            ch = line[col_no]
            next_ch = line[col_no+1] if col_no+1 < len(line) else ''

            if escaped:
                escaped = False
                col_no += 1
                continue

            if ch == '\\' and state in ('SQUOTE', 'DQUOTE', 'BACKTICK', 'REGEX'):
                escaped = True
                col_no += 1
                continue

            if state == 'NORMAL':
                if ch == '/' and next_ch == '/':
                    state = 'LINE_COMMENT'
                    break
                elif ch == '/' and next_ch == '*':
                    state = 'BLOCK_COMMENT'
                    col_no += 2
                    continue
                elif ch == '/' and (col_no == 0 or line[col_no-1] in '(,=:[!&|?{};'):
                    # JS Regex literal start
                    state = 'REGEX'
                elif ch == "'":
                    state = 'SQUOTE'
                elif ch == '"':
                    state = 'DQUOTE'
                elif ch == '`':
                    state = 'BACKTICK'
                elif ch in '({[':
                    stack.append((ch, line_no, col_no+1))
                elif ch in ')}]':
                    if not stack:
                        errors.append(f"Line {line_no}:{col_no+1} Unmatched closing '{ch}'")
                    else:
                        top, t_line, t_col = stack.pop()
                        exp = {'(': ')', '{': '}', '[': ']'}[top]
                        if ch != exp:
                            errors.append(f"Line {line_no}:{col_no+1} Mismatched '{ch}' (expected '{exp}' for '{top}' from line {t_line}:{t_col})")

            elif state == 'REGEX':
                if ch == '/':
                    state = 'NORMAL'
            elif state == 'SQUOTE':
                if ch == "'":
                    state = 'NORMAL'
            elif state == 'DQUOTE':
                if ch == '"':
                    state = 'NORMAL'
            elif state == 'BACKTICK':
                if ch == '`':
                    state = 'NORMAL'
            elif state == 'BLOCK_COMMENT':
                if ch == '*' and next_ch == '/':
                    state = 'NORMAL'
                    col_no += 2
                    continue

            col_no += 1

    if state not in ('NORMAL', 'LINE_COMMENT'):
        errors.append(f"Unclosed state: {state} at end of file")

    for top, t_line, t_col in stack:
        errors.append(f"Unclosed '{top}' from line {t_line}:{t_col}")

    if errors:
        print(f"=== {filename}: {len(errors)} ERROR(S) FOUND ===")
        for e in errors:
            print("  " + e)
    else:
        print(f"=== {filename}: CLEAN (Syntax & Braces Validated) ===")

for filename in files:
    if os.path.exists(filename):
        check_js_syntax(filename)
