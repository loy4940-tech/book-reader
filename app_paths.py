"""実行ファイルの基準ディレクトリを解決する。

通常実行時はスクリプトのあるフォルダ、PyInstallerでexe化した場合は
exeと同じフォルダを返す。これにより config.json / logs を
exeの隣に置いて非エンジニアでも編集・確認できるようにする。
"""
import sys
from pathlib import Path


def base_dir() -> Path:
    if getattr(sys, "frozen", False):
        # PyInstallerでexe化された状態: exeと同じフォルダ
        return Path(sys.executable).parent
    return Path(__file__).parent
