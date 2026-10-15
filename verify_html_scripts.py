import re
import sys
import os

files = ["hod.html", "vp.html", "hr.html"]

def check_script(filename):
    with open(filename, "r", encoding="utf-8") as f:
        content = f.read()

    scripts = re.findall(r"<script>(.*?)</script>", content, re.DOTALL)
    print(f"File: {filename} — Found {len(scripts)} script block(s)")

    for idx, script in enumerate(scripts, 1):
        # Basic bracket balancer & syntax sanity check
        stack = []
        lines = script.splitlines()
        in_squote = False
        in_dquote = False
        in_backtick = False
        in_comment_line = False
        in_comment_block = False

        for l_num, line in enumerate(lines, 1):
            i = 0
            while i < len(line):
                ch = line[i]
                if not in_squote and not in_dquote and not in_backtick:
                    if line[i:i+2] == '//':
                        break # Rest of line is comment
                    if line[i:i+2] == '/*':
                        in_comment_block = True
                        i += 2
                        continue

                if in_comment_block:
                    if line[i:i+2] == '*/':
                        in_comment_block = False
                        i += 2
                    else:
                        i += 1
                    continue

                if ch == '\\' and (in_squote or in_dquote or in_backtick):
                    i += 2 # Skip escaped char
                    continue

                if ch == "'" and not in_dquote and not in_backtick:
                    in_squote = not in_squote
                elif ch == '"' and not in_squote and not in_backtick:
                    in_dquote = not in_dquote
                elif ch == '`' and not in_squote and not in_dquote:
                    in_backtick = not in_backtick
                elif not in_squote and not in_dquote and not in_backtick:
                    if ch in '({[':
                        stack.append((ch, l_num, i+1))
                    elif ch in ')}]':
                        if not stack:
                            print(f"  [ERROR] Unmatched closing '{ch}' at line {l_num}:{i+1} in block {idx}")
                        else:
                            top, t_line, t_col = stack.pop()
                            expected = {'(': ')', '{': '}', '[': ']'}[top]
                            if ch != expected:
                                print(f"  [ERROR] Mismatched '{ch}' at line {l_num}:{i+1} (expected '{expected}' for '{top}' from {t_line}:{t_col})")
                i += 1

        if stack:
            for top, t_line, t_col in stack:
                print(f"  [ERROR] Unclosed '{top}' from line {t_line}:{t_col} in block {idx}")
        elif not in_squote and not in_dquote and not in_backtick:
            print(f"  [PASS] Block {idx} in {filename} has balanced braces, brackets, and quotes.")
        else:
            print(f"  [ERROR] Unclosed string/template literal in block {idx}")

for filename in files:
    if os.path.exists(filename):
        check_script(filename)
