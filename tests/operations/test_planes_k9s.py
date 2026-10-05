import json
import os
import pty
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SLOTS = ["management", "shared-control", "shared-data", "isolated-1-control", "isolated-1-data"]
FAKE = r"""
import hashlib,json,os,sys
from pathlib import Path
tool=Path(sys.argv[0]).name
args=sys.argv[1:]
spec=json.loads(Path(os.environ["FAKE_SPEC"]).read_text())
with Path(os.environ["FAKE_LOG"]).open("a") as log:
    log.write(json.dumps({"tool":tool,"args":args})+"\n")
slots=["management","shared-control","shared-data","isolated-1-control","isolated-1-data"]
stem="radplanes-learning-"+spec["environment"]
def argument(key):
    return args[args.index(key)+1]
def slot_of(name):
    return name.removeprefix("aks-").removeprefix(stem+"-")
def node_id(name):
    return hashlib.sha256(name.encode()).hexdigest()
def profile(name,local):
    context=("kind-" if local else "")+name
    server=f"https://127.0.0.1:{35495+slots.index(slot_of(name))}" if local else f"https://{name}.example.azmk8s.io"
    return {
        "apiVersion":"v1","kind":"Config","current-context":context,
        "contexts":[{"name":context,"context":{"cluster":"cluster-"+name,"user":"user-"+name}}],
        "clusters":[{"name":"cluster-"+name,"cluster":{"server":server,"certificate-authority-data":"Y2E="}}],
        "users":[{"name":"user-"+name,"user":
            {"client-certificate-data":"Y2VydA==","client-key-data":"a2V5"} if local else
            {"exec":{"command":"kubelogin","apiVersion":"client.authentication.k8s.io/v1beta1","args":["get-token"]}}}],
    }
if tool=="docker":
    if args[:3]==["context","inspect","desktop-linux"]:
        print(json.dumps("unix:///test/docker.sock"))
    elif args[2]=="ps":
        name=argument("--filter").rsplit("=",1)[1]
        if slot_of(name) in spec["nodes"]: print(node_id(name))
    elif args[2]=="inspect":
        name=next(stem+"-"+s for s in spec["nodes"] if node_id(stem+"-"+s)==args[-1])
        running=spec["nodes"][slot_of(name)]=="running"
        if "--format" in args: print("true" if running else "false")
        else:
            print(json.dumps([{"Id":args[-1],"Name":"/"+name+"-control-plane","State":{"Running":running},
                "Config":{"Labels":{"io.x-k8s.kind.cluster":name}},
                "HostConfig":{"PortBindings":{"6443/tcp":[{"HostIp":"127.0.0.1",
                    "HostPort":str(35495+slots.index(slot_of(name)))}]}}}]))
    else: raise SystemExit("unexpected Docker command")
elif tool=="kind":
    print(json.dumps(profile(argument("--name"),True)))
elif tool=="az":
    name=argument("--name").removeprefix("aks-")
    if args[:2]==["aks","show"]:
        print(json.dumps({"id":f"/subscriptions/{argument('--subscription')}/resourceGroups/rg-{name}"
            f"/providers/Microsoft.ContainerService/managedClusters/aks-{name}",
            "fqdn":name+".example.azmk8s.io","provisioningState":"Succeeded",
            "tags":{"project":"radplanes","deployment":"learning"}}))
    elif args[:2]==["aks","get-credentials"]:
        Path(argument("--file")).write_text(json.dumps(profile(name,False)))
    else: raise SystemExit("unexpected Azure command")
elif tool=="kubelogin":
    if args[0]!="convert-kubeconfig": raise SystemExit("unexpected credential command")
elif tool=="kubectl":
    path=Path(argument("--kubeconfig"))
    if "rename-context" in args:
        value=json.loads(path.read_text())
        value["current-context"]=args[-1];value["contexts"][0]["name"]=args[-1]
        path.write_text(json.dumps(value))
    elif args[2:4]==["config","view"]: print(path.read_text())
    else: raise SystemExit("unexpected Kubernetes command")
elif tool=="python":
    if not args[0].endswith("catalog.py") or args[1:]!=["--slots"]:
        raise SystemExit("unexpected Python")
    print("\n".join(spec["catalog"]))
elif tool=="k9s":
    path=Path(argument("--kubeconfig"))
    Path(os.environ["FAKE_K9S"]).write_text(json.dumps({
        "args":args,"KUBECONFIG":os.environ.get("KUBECONFIG"),"tty":[os.isatty(0),os.isatty(1)],
        "mode":oct(path.stat().st_mode&0o777),"kubeconfig":json.loads(path.read_text())}))
    raise SystemExit(spec.get("k9s_exit",0))
else: raise SystemExit("unexpected tool")
"""


@pytest.fixture
def checkout(tmp_path):
    for relative in (
        "Makefile",
        "scripts/lib/output.sh",
        "scripts/lib/progress.sh",
        "scripts/lib/env.sh",
        "scripts/lib/discovery.sh",
        "scripts/operations/k9s.sh",
    ):
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, destination)
    (tmp_path / "bin").mkdir()
    (tmp_path / "work").mkdir()
    (tmp_path / ".venv/bin").mkdir(parents=True)
    tools = ("az", "kind", "docker", "kubectl", "kubelogin", "k9s")
    for path in [tmp_path / "bin" / tool for tool in tools] + [tmp_path / ".venv/bin/python"]:
        path.write_text(f"#!{ROOT / '.venv/bin/python'}\n" + FAKE)
        path.chmod(0o700)
    (tmp_path / "bin/jq").symlink_to(shutil.which("jq"))
    return tmp_path


def configure(root, environment, nodes=None, catalog=None, k9s_exit=0):
    values = {"DEMO_ENV": environment, "DEMO_PROJECT": "radplanes", "DEMO_DEPLOYMENT": "learning"}
    if environment == "azure":
        values.update(
            AZURE_SUBSCRIPTION_ID="11111111-1111-1111-1111-111111111111", AZURE_LOCATION="centralus"
        )
    (root / ".env").write_text(
        "".join(f"{key}={json.dumps(value)}\n" for key, value in values.items())
    )
    (root / ".env").chmod(0o600)
    spec = {"environment": environment, "nodes": nodes or {}, "catalog": catalog or []}
    (root / "spec.json").write_text(json.dumps(spec | {"k9s_exit": k9s_exit}))


def run(root, command, *, terminal=True, path=None):
    env = {
        **os.environ,
        "PATH": path or f"{root / 'bin'}{os.pathsep}{os.environ['PATH']}",
        "TMPDIR": str(root / "work"),
        "FAKE_SPEC": str(root / "spec.json"),
        "FAKE_LOG": str(root / "calls.jsonl"),
        "FAKE_K9S": str(root / "k9s.json"),
        "COLOR": "never",
    }
    if not terminal:
        return subprocess.run(
            command, cwd=root, env=env, capture_output=True, text=True, timeout=60, check=False
        )
    primary, secondary = pty.openpty()
    try:
        result = subprocess.run(
            command,
            cwd=root,
            env=env,
            stdin=secondary,
            stdout=secondary,
            stderr=subprocess.PIPE,
            text=True,
            timeout=60,
            check=False,
        )
    finally:
        os.close(secondary)
        os.close(primary)
    return result


def calls(root):
    log = root / "calls.jsonl"
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def test_make_planes_k9s_opens_every_running_local_plane_with_private_access(checkout):
    configure(
        checkout,
        "local",
        nodes={
            "management": "running",
            "shared-control": "running",
            "shared-data": "running",
            "isolated-1-control": "stopped",
        },
        k9s_exit=3,
    )
    result = run(checkout, ["make", "--no-print-directory", "planes-k9s", "ARGS=shared-control"])
    assert result.returncode != 0
    assert "planes-k9s" in result.stderr
    assert "Skip isolated-1-control: its kind node is stopped" in result.stderr
    assert "Skip isolated-1-data: no cluster exists" in result.stderr
    assert "Opening k9s on 3 plane clusters" in result.stderr
    direct = run(checkout, ["bash", str(checkout / "scripts/operations/k9s.sh"), "shared-control"])
    assert direct.returncode == 3, direct.stderr
    opened = json.loads((checkout / "k9s.json").read_text())
    args = opened["args"]
    assert args[args.index("--context") + 1] == "shared-control-plane"
    assert "--all-namespaces" in args
    assert opened["KUBECONFIG"] == args[args.index("--kubeconfig") + 1]
    assert Path(opened["KUBECONFIG"]).parent.name.startswith("plane-discovery.")
    assert opened["tty"] == [True, True]
    assert opened["mode"] == "0o600"
    kubeconfig = opened["kubeconfig"]
    assert kubeconfig["current-context"] == "shared-control-plane"
    assert [context["name"] for context in kubeconfig["contexts"]] == [
        f"{slot}-plane" for slot in SLOTS[:3]
    ]
    for context in kubeconfig["contexts"]:
        cluster = "kind-" + context["name"]
        assert context["context"] == {"cluster": cluster, "user": cluster, "namespace": "all"}
    assert [cluster["name"] for cluster in kubeconfig["clusters"]] == [
        f"kind-{slot}-plane" for slot in SLOTS[:3]
    ]
    assert [user["name"] for user in kubeconfig["users"]] == [
        f"kind-{slot}-plane" for slot in SLOTS[:3]
    ]
    assert "radplanes" not in json.dumps(
        {key: kubeconfig[key] for key in ("contexts", "current-context")}
    )
    assert [cluster["cluster"]["server"] for cluster in kubeconfig["clusters"]] == [
        f"https://127.0.0.1:{35495 + index}" for index in range(3)
    ]
    assert list((checkout / "work").iterdir()) == []
    assert not any(call["tool"] in {"az", "kubelogin"} for call in calls(checkout))
    kind_names = {call["args"][-1] for call in calls(checkout) if call["tool"] == "kind"}
    assert kind_names == {f"radplanes-learning-local-{slot}" for slot in SLOTS[:3]}


def test_planes_k9s_uses_the_azure_catalog_without_docker(checkout):
    configure(checkout, "azure", catalog=SLOTS[:3])
    result = run(checkout, ["bash", str(checkout / "scripts/operations/k9s.sh")])
    assert result.returncode == 0, result.stderr
    kubeconfig = json.loads((checkout / "k9s.json").read_text())["kubeconfig"]
    assert kubeconfig["current-context"] == "management-plane"
    assert [context["name"] for context in kubeconfig["contexts"]] == [
        f"{slot}-plane" for slot in SLOTS[:3]
    ]
    assert [cluster["name"] for cluster in kubeconfig["clusters"]] == [
        f"aks-{slot}-plane" for slot in SLOTS[:3]
    ]
    assert all(user["user"]["exec"]["command"] == "kubelogin" for user in kubeconfig["users"])
    assert not any(call["tool"] in {"docker", "kind"} for call in calls(checkout))
    assert list((checkout / "work").iterdir()) == []


def test_planes_k9s_refuses_a_starting_plane_that_is_not_running(checkout):
    configure(checkout, "local", nodes={"management": "running", "shared-control": "stopped"})
    result = run(checkout, ["bash", str(checkout / "scripts/operations/k9s.sh"), "shared-control"])
    assert result.returncode == 1
    assert "Skip shared-control: its kind node is stopped" in result.stderr
    assert "The shared-control cluster is not running" in result.stderr
    assert {call["args"][-1] for call in calls(checkout) if call["tool"] == "kind"} == {
        "radplanes-learning-local-management"
    }
    assert not (checkout / "k9s.json").exists()
    assert list((checkout / "work").iterdir()) == []


@pytest.mark.parametrize(
    "case,message",
    [
        ("no-terminal", "run it in a terminal"),
        ("missing-k9s", "k9s was not found. Install it: brew install k9s"),
        ("unknown-slot", "Unknown plane slot"),
    ],
)
def test_planes_k9s_refuses_before_discovery(checkout, case, message):
    configure(checkout, "local", nodes={"management": "running"})
    command = ["bash", str(checkout / "scripts/operations/k9s.sh")]
    path = None
    if case == "missing-k9s":
        (checkout / "bin/k9s").unlink()
        path = f"{checkout / 'bin'}{os.pathsep}/usr/bin{os.pathsep}/bin"
    if case == "unknown-slot":
        command.append("isolated-2-data")
    result = run(checkout, command, terminal=case != "no-terminal", path=path)
    assert result.returncode == 1
    assert message in result.stderr
    assert calls(checkout) == []
    assert list((checkout / "work").iterdir()) == []
