"""Fetch pinned upstream code, verifying each Git blob before use."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path

import requests
from .phrases import REVISION, SSMS_REVISION

MODEL_NAME = "tcn_downbeat_unsupervised_v3.0_1024_context_6_tcn.sdict"
MODEL_HASH = "993855d2bc61ed80ae2a75e1a810b513a9e1d18864877aa12b0524d908cfcbde"


def fetch_repository(repository, revision, target, include):
    response = requests.get(f"https://api.github.com/repos/{repository}/git/trees/{revision}?recursive=1", timeout=(10, 45))
    response.raise_for_status()
    entries = [e for e in response.json()["tree"] if e["type"] == "blob" and include(e["path"])]
    def fetch(entry):
        path = target / entry["path"]
        def valid(data):
            return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest() == entry["sha"]
        if path.is_file() and valid(path.read_bytes()):
            return
        last_error = None
        for _ in range(3):
            try:
                result = requests.get(f"https://raw.githubusercontent.com/{repository}/{revision}/{entry['path']}", timeout=(10, 45))
                result.raise_for_status()
                if not valid(result.content):
                    raise ValueError(f"上游文件校验失败：{entry['path']}")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(result.content)
                return
            except (OSError, ValueError, requests.RequestException) as error:
                last_error = error
        raise last_error
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(fetch, entries))
    return len(entries)


def install():
    target = Path(__file__).resolve().parents[1] / ".runtime/tools/loop-miner-src"
    count = fetch_repository("erl-j/loop-miner", REVISION, target,
        lambda name: name.startswith("loop_miner/") or name in ("LICENSE", "README.md"))
    count += fetch_repository("music-x-lab/Self-Supervised-Metrical-Structure", SSMS_REVISION,
        target / "Self-Supervised-Metrical-Structure",
        lambda name: name.endswith(".py") or name.lower().startswith(("license", "readme")))
    model = target / "model_weights" / MODEL_NAME
    if not model.is_file() or hashlib.sha256(model.read_bytes()).hexdigest() != MODEL_HASH:
        import gdown
        model.parent.mkdir(parents=True, exist_ok=True)
        temporary = model.with_suffix(".partial")
        gdown.download(id="1t19m3wavR8JAvHGo1u37jqidTnylSmeO", output=str(temporary), quiet=False)
        if hashlib.sha256(temporary.read_bytes()).hexdigest() != MODEL_HASH:
            raise ValueError("模型文件校验失败，未启用。")
        temporary.replace(model)
    (target / "installed.json").write_text(json.dumps({"revision": REVISION,
        "structure_revision": SSMS_REVISION, "model_sha256": MODEL_HASH}), encoding="utf-8")
    print(f"自动分段引擎已安装；{count} 个上游文件与模型校验通过。", flush=True)


if __name__ == "__main__":
    install()
