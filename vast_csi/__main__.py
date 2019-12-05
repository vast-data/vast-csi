import sys
import re
import argparse
from easypy.colors import C
from easypy.bunch import Bunch


IS_INTERACTIVE = sys.stdin.isatty()


def main():
    parser = argparse.ArgumentParser(
        description="Vast CSI Plugin",
        usage="docker run -it --net=host -v `pwd`:/out <IMAGE> template")
    parser.set_defaults(func=lambda *_, **__: parser.print_help())

    subparsers = parser.add_subparsers()

    serve_parse = subparsers.add_parser("serve", help='Start the CSI Plugin Server (not for humans)')
    serve_parse.set_defaults(func=_serve)

    template_parse = subparsers.add_parser("template", help='Generate a kubectl template for deploying this CSI plugin')
    for p in "image hostname username password vippool export load-balancing pull-policy".split():
        template_parse.add_argument("--" + p)
    template_parse.set_defaults(func=_template)

    args = parser.parse_args(namespace=Bunch())
    args.pop("func")(args)


def _serve(args):
    from . server import serve
    return serve()


def _template(args):
    try:
        fname = "vast-csi-deployment.yaml"
        with open(f"/out/{fname}", "w") as file:
            generate_deployment(file, **args)
        print(C(f"\nWritten to WHITE<<{fname}>>\n"))
        print(f"Inspect the file and then run:")
        print(C(f">> CYAN<<kubectl apply -f {fname}>>\n"))
    except KeyboardInterrupt:
        return


def generate_deployment(
        file, load_balancing=None, pull_policy=None, image=None, hostname=None,
        username=None, password=None, vippool=None, export=None):

    from . utils import RESTSession
    from requests import HTTPError, ConnectionError
    from base64 import b64encode
    from prompt_toolkit.completion import WordCompleter
    from prompt_toolkit.shortcuts import prompt as _prompt
    from prompt_toolkit.styles import Style

    style = Style.from_dict({'': '#AAAABB', 'prompt': '#ffffff'})

    def prompt(arg, message, **kwargs):
        if not IS_INTERACTIVE:
            raise Exception(f"Missing argument: {arg}")
        return _prompt([('class:prompt', message)], style=style, **kwargs)

    print(C("\n\nWHITE<<Vast CSI Plugin - Deployment generator for Kubernetes>>\n\n"))

    IMAGE_NAME = image or prompt("image", "Name of this Docker Image: ", default="vast-csi:latest")

    LB_STRATEGY = "roundrobin"
    # opts = ['random', 'roundrobin']
    # LB_STRATEGY = prompt(
    #     "load_balancing"
    #     f"Load-Balancing Strategy ({'|'.join(opts)}): ", default="random", completer=WordCompleter(opts))

    opts = ['Never', 'Always']
    PULL_POLICY = pull_policy or prompt(
        "pull_policy",
        f"Image Pull Policy ({'|'.join(opts)}): ", default="Never", completer=WordCompleter(opts))

    exports = vippools = []
    while True:
        VMS_HOST = hostname or prompt("hostname", "Vast Management hostname: ", default="vms")
        username = username or prompt("username", "Vast Management username: ", default="admin")
        password = password or prompt("password", "Vast Management password: ", is_password=True)

        DISABLE_SSL = '"false"'
        ssl_verify = DISABLE_SSL != '"false"'
        if not ssl_verify:
            import urllib3
            urllib3.disable_warnings()

        vms = RESTSession(
            base_url=f"https://{VMS_HOST}/api",
            auth=(username, password),
            ssl_verify=ssl_verify)

        try:
            vippools = sorted(p.name for p in vms.vippools())
            exports = sorted({path for e in vms.exports() for path in (e.path, e.alias) if path})
        except (ConnectionError, HTTPError) as exc:
            print(C(f"YELLOW<<Error connecting to Vast Management>>: {exc}"))
            if IS_INTERACTIVE and not prompt(None, "Hit (y) to ignore, any other key to retry: "):
                continue
            else:
                break
        else:
            print()
            print(C("GREEN<<Connected successfully!>>"))
            print(" - VIP Pools:", ", ".join(vippools or ["(none)"]))
            print(" - Exports:", ", ".join(exports or ["(none)"]))
            print()
            break

    VIP_POOL_NAME = vippool or prompt(
        "vippool",
        "Virtual IP Pool Name: ", default="vippool-1",
        completer=WordCompleter(vippools), complete_while_typing=True)

    NFS_EXPORT = export or prompt(
        "export",
        "NFS Export Path: ", default="/k8s",
        completer=WordCompleter(exports), complete_while_typing=True)

    B64_USERNAME = b64encode("admin".encode("utf8")).decode("utf8")
    B64_PASSWORD = b64encode(password.encode("utf8")).decode("utf8")

    template = open("vast-csi.yaml").read()
    print(re.sub("#.*", "", template.format(**locals())).strip(), file=file)


if __name__ == '__main__':
    main()
