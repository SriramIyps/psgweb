import re

def extract_scripts(html_file, js_file):
    with open(html_file, 'r', encoding='utf-8') as f:
        content = f.read()
    match = re.search(r'<script>(.*?)</script>', content, re.DOTALL)
    if match:
        js_code = match.group(1)
        with open(js_file, 'w', encoding='utf-8') as f:
            f.write(js_code)
        print(f"Extracted script from {html_file} -> {js_file} ({len(js_code.splitlines())} lines)")
        return js_code
    else:
        print(f"No script tag found in {html_file}")
        return ""

extract_scripts('hod.html', 'hod_script.js')
extract_scripts('vp.html', 'vp_script.js')
extract_scripts('hr.html', 'hr_script.js')
