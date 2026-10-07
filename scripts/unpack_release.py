import shutil, sys, tarfile
from pathlib import Path

folder = Path(sys.argv[1])
parts = sorted(folder.glob("*.tar.a?"))
if parts:
    tar_path = folder / "day.tar"
    with open(tar_path, "wb") as out:
        for p in parts:
            with open(p, "rb") as f:
                shutil.copyfileobj(f, out)
            p.unlink()
else:
    tar_path = next(folder.glob("*.tar"))
with tarfile.open(tar_path) as t:
    t.extractall(folder)
tar_path.unlink()
print("extracted to", folder)
