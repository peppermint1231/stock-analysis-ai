import os

pykrx_dir = r"C:\Users\mycom\AppData\Local\Programs\Python\Python311\Lib\site-packages\pykrx"

for root, _, files in os.walk(pykrx_dir):
    for f in files:
        if f.endswith(".py"):
            path = os.path.join(root, f)
            with open(path, "rb") as file:
                content = file.read()
            
            if b"coding: utf-8" not in content and b"coding:utf-8" not in content:
                new_content = b"# -*- coding: utf-8 -*-\n" + content
                with open(path, "wb") as file:
                    file.write(new_content)
                print(f"Patched {f}")

print("Done patching pykrx.")
