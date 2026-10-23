"""Application entry point and optional standalone diagnostic."""
import argparse
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="FolderPilot 文件夹差异与安全管理")
    parser.add_argument("--smoke-test", type=Path, metavar="RESULT_JSON", help="使用生成数据测试界面与核心操作后退出")
    parser.add_argument("--data-dir", type=Path, help="指定独立应用数据位置")
    args = parser.parse_args()
    if args.smoke_test:
        from .smoke import smoke_test
        smoke_test(args.smoke_test)
    else:
        from .ui import App
        App(args.data_dir).mainloop()


if __name__ == "__main__":
    main()
