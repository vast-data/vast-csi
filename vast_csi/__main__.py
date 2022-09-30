import sys
import re
import argparse
from easypy.colors import C
from easypy.bunch import Bunch
from easypy.semver import SemVer


IS_INTERACTIVE = sys.stdin.isatty()


CSI_SIDECAR_VERSIONS = {
    'csi-provisioner':           'v3.2.1',  # min k8s: v1.17
    'csi-attacher':              'v3.1.0',  # min k8s: v1.17
    'csi-resizer':               'v1.1.0',  # min k8s: v1.16
    'csi-node-driver-registrar': 'v2.0.1',  # min k8s: v1.13
    'csi-snapshotter':           'v6.0.1',  # min k8s: v1.20
}


def main():
    parser = argparse.ArgumentParser(
        description="Vast CSI Plugin",
        usage="docker run -it --net=host -v `pwd`:/out <IMAGE> template")
    parser.set_defaults(func=lambda *_, **__: parser.print_help())

    subparsers = parser.add_subparsers()

    serve_parse = subparsers.add_parser("serve", help='Start the CSI Plugin Server (not for humans)')
    serve_parse.set_defaults(func=_serve)

    template_parse = subparsers.add_parser("template", help='Generate a kubectl template for deploying this CSI plugin')
    for p in "image hostname username password vippool export load-balancing pull-policy mount-options deployment".split():
        template_parse.add_argument("--" + p)
    template_parse.set_defaults(func=_template)

    info_parse = subparsers.add_parser("info", help='Print versioning information for this CSI plugin')
    info_parse.add_argument("--output", default="json", choices=['json', 'yaml'], help="Output format")
    info_parse.set_defaults(func=_info)

    args = parser.parse_args(namespace=Bunch())
    args.pop("func")(args)


def _info(args):
    from . server import Config
    conf = Config()
    info = dict(
        name=conf.plugin_name, version=conf.plugin_version, commit=conf.git_commit,
        supported_k8s_versions=open("k8s_supported.txt").read().split(),
        sidecars=CSI_SIDECAR_VERSIONS,
    )
    if args.output == "yaml":
        import yaml
        yaml.dump(info, sys.stdout)
    elif args.output == "json":
        import json
        json.dump(info, sys.stdout)
    else:
        assert False, f"invalid output format: {args.output}"


def _serve(args):
    from . server import serve
    return serve()


def _template(args):
    if deployment := (args.get("deployment") or ""):
        deployment = f"-{deployment}"

    try:
        fname = f"vast-csi-deployment{deployment}.yaml"
        with open(f"/out/{fname}", "w") as file:
            storage_class = generate_deployment(file, **args)
        print(C(f"\nWritten to WHITE<<{fname}>>\n"))
        print("Inspect the file and then run:")
        print(C(f">> CYAN<<kubectl apply -f {fname}>>\n"))
        print(C("YELLOW<<Be sure to delete the file when done, as it contains Vast Management credentials>>\n"))
        print(C(f"Use CYAN<<storageClassName: {storage_class}>> in your PVCs\n"))
    except KeyboardInterrupt:
        return


def generate_deployment(
        file, load_balancing=None, pull_policy=None, image=None, hostname=None,
        username=None, password=None, vippool=None, export=None, mount_options=None, deployment=None):

    from . utils import RESTSession
    from requests import HTTPError, ConnectionError
    from base64 import b64encode
    from prompt_toolkit.completion import WordCompleter
    from prompt_toolkit.shortcuts import prompt as _prompt
    from prompt_toolkit.styles import Style

    style = Style.from_dict({'': '#AAAABB', 'prompt': '#ffffff'})
    context = Bunch()

    from . server import Config
    conf = Config()
    name = conf.plugin_name
    namespace = "vast-csi"
    storage_class = "vastdata-filesystem"
    if deployment:
        name = f"{deployment}.{name}"
        namespace = f"{namespace}-{deployment}"
        storage_class = f"{storage_class}-{deployment}"

    context.update(PLUGIN_NAME=name, NAMESPACE=namespace, STORAGE_CLASS=storage_class)

    def prompt(arg, message, **kwargs):
        if not IS_INTERACTIVE:
            raise Exception(f"Missing argument: {arg}")
        return _prompt([('class:prompt', message)], style=style, **kwargs)

    print(C("\n\nWHITE<<Vast CSI Plugin - Deployment generator for Kubernetes>>\n\n"))

    context.IMAGE_NAME = image or prompt("image", "Name of this Docker Image: ")

    context.LB_STRATEGY = "roundrobin"
    # opts = ['random', 'roundrobin']
    # context.LB_STRATEGY = prompt(
    #     "load_balancing"
    #     f"Load-Balancing Strategy ({'|'.join(opts)}): ", default="random", completer=WordCompleter(opts))

    opts = ['Never', 'Always', 'IfNotPresent', 'Auto']
    context.PULL_POLICY = pull_policy or prompt(
        "pull_policy",
        f"Image Pull Policy ({'|'.join(opts)}): ", default="IfNotPresent", completer=WordCompleter(opts))

    if context.PULL_POLICY.lower() == 'auto':
        context.PULL_POLICY = 'null'

    exports = vippools = []
    while True:
        context.VMS_HOST = hostname or prompt("hostname", "Vast Management hostname: ", default="vms")
        username = username or prompt("username", "Vast Management username: ", default="admin")
        password = password or prompt("password", "Vast Management password: ", is_password=True)

        context.DISABLE_SSL = '"false"'
        ssl_verify = context.DISABLE_SSL != '"false"'
        if not ssl_verify:
            import urllib3
            urllib3.disable_warnings()

        vms = RESTSession(
            base_url=f"https://{context.VMS_HOST}/api",
            auth=(username, password),
            ssl_verify=ssl_verify)

        try:
            versions = vms.versions()
        except (ConnectionError, HTTPError) as exc:
            print(C(f"YELLOW<<Error connecting to Vast Management>>: {exc}"))
            if IS_INTERACTIVE and not prompt(None, "Hit (y) to ignore, any other key to retry: "):
                continue
            else:
                break
        else:
            vippools = sorted(p.name for p in vms.vippools())
            latest_ver = max(versions, key=lambda v: v.created)
            version = SemVer.loads(latest_ver.sys_version or "3.0.0")  # in QA this is sometimes empty
            if version >= SemVer(3, 4):
                exports = sorted({(v.alias or v.path) for v in vms.views() if "NFS" in v.protocols})
            else:
                print(C("RED<<Incompatible Vast Version!>>"), "VMS Version:", version)
                print(C("This plugin supports WHITE<<version 3.4 and above>>"))
                raise SystemExit(5)

            print()
            print(C("GREEN<<Connected successfully!>>"), "VMS Version:", version)
            print(" - VIP Pools:", ", ".join(vippools or ["(none)"]))
            print(" - Exports:", ", ".join(exports or ["(none)"]))
            print()
            break

    context.VIP_POOL_NAME = vippool or prompt(
        "vippool",
        "Virtual IP Pool Name: ", default="vippool-1",
        completer=WordCompleter(vippools), complete_while_typing=True)

    context.NFS_EXPORT = export or prompt(
        "export",
        "NFS Export Path: ", default="/k8s",
        completer=WordCompleter(exports), complete_while_typing=True)

    context.MOUNT_OPTIONS = prompt(
        "mount_options",
        "Additional Mount Options: ", default=""
    ) if mount_options is None else mount_options

    context.B64_USERNAME = b64encode(username.encode("utf8")).decode("utf8")
    context.B64_PASSWORD = b64encode(password.encode("utf8")).decode("utf8")

    context.update(CSI_SIDECAR_VERSIONS)

    template = open("vast-csi.yaml").read()
    print(re.sub("#.*", "", template.format(**context)).strip(), file=file)
    return storage_class


if __name__ == '__main__':
    main()
