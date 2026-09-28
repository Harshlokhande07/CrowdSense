import os
from bs4 import BeautifulSoup
import re

html_path = r"d:\CrowdSense\Frontend\dashboard.html"
out_html_path = r"d:\CrowdSense\Frontend\index.html"
out_css_path = r"d:\CrowdSense\Frontend\style.css"
out_js_path = r"d:\CrowdSense\Frontend\script.js"

with open(html_path, 'r', encoding='utf-8') as f:
    content = f.read()

soup = BeautifulSoup(content, 'html.parser')

# Extract CSS
style_tag = soup.find('style')
css_content = style_tag.string if style_tag else ""
if style_tag:
    style_tag.decompose()

# Extract JS
script_tag = soup.find('script')
js_content = script_tag.string if script_tag else ""
if script_tag:
    script_tag.decompose()

# Add link to css and script src
head = soup.find('head')
if head:
    css_link = soup.new_tag('link')
    css_link['rel'] = 'stylesheet'
    css_link['href'] = 'style.css'
    head.append(css_link)

body = soup.find('body')
if body:
    js_link = soup.new_tag('script')
    js_link['src'] = 'script.js'
    body.append(js_link)

# Write HTML
with open(out_html_path, 'w', encoding='utf-8') as f:
    f.write(soup.prettify())

# Simple basic CSS formatter
css_content = re.sub(r'\}', '}\n', css_content)
css_content = re.sub(r'\{', ' {\n  ', css_content)
css_content = re.sub(r';', ';\n  ', css_content)

with open(out_css_path, 'w', encoding='utf-8') as f:
    f.write(css_content.strip())

# Write JS
js_content = js_content.replace(';', ';\n').replace('{', '{\n').replace('}', '}\n')
with open(out_js_path, 'w', encoding='utf-8') as f:
    f.write(js_content.strip())

print("Formatting complete")
