from setuptools import setup
from setuptools.command.build_py import build_py as build_py_orig
import subprocess
import pathlib
import shutil

class build_py(build_py_orig):
    def run(self):
        root = pathlib.Path(__file__).parent.resolve()
        proj = root / 'RoslynCleaner'
        temp_out = root / 'build' / 'RoslynCleaner'
        try:
            subprocess.check_call(['dotnet', 'publish', '-c', 'Release', '-o', str(temp_out), str(proj)])
        except Exception:
            pass
        super().run()
        if temp_out.exists():
            dest = pathlib.Path(self.build_lib) / 'RoslynCleaner'
            dest.mkdir(parents=True, exist_ok=True)
            for f in temp_out.iterdir():
                target = dest / f.name
                if f.is_dir():
                    shutil.copytree(f, target, dirs_exist_ok=True)
                else:
                    shutil.copy(f, target)

setup(cmdclass={'build_py': build_py})
