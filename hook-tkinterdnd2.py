"""Include the native TkDnD runtime in the standalone executable."""
from PyInstaller.utils.hooks import collect_data_files

datas = collect_data_files('tkinterdnd2')
