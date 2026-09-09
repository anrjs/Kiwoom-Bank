# show_tree.py
import os

def print_tree(startpath, prefix=""):
    for item in sorted(os.listdir(startpath)):
        path = os.path.join(startpath, item)
        if os.path.isdir(path):
            print(f"{prefix}📁 {item}/")
            print_tree(path, prefix + "    ")
        else:
            print(f"{prefix}📄 {item}")

if __name__ == "__main__":
    root_dir = "."  # 현재 디렉토리
    print_tree(root_dir)
