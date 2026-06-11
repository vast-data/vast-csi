import os
import sys
import argparse
from easypy.bunch import Bunch


def main():
    parser = argparse.ArgumentParser(
        description="Vast CSI Plugin")
    parser.set_defaults(func=lambda *_, **__: parser.print_help())

    subparsers = parser.add_subparsers()

    serve_parse = subparsers.add_parser("serve", help='Start the CSI Plugin Server (not for humans)')
    serve_parse.add_argument(
        "--plugin", "-p",
        default=None,
        choices=["nfs", "cosi", "block"],
        help="Specify the core plugin type. Mutually exclusive with --addons."
    )
    serve_parse.add_argument(
        "--addons", "-a",
        default="",
        help=(
            "Comma-separated list of CSI-Addons to enable. "
            "Valid addons: replication[nfs], replication[block], volumegroup[nfs], volumegroup[block]. "
            "Example: --addons=replication[block],volumegroup[block]"
        )
    )
    serve_parse.set_defaults(func=_serve)

    info_parse = subparsers.add_parser("info", help='Print versioning information for this CSI plugin')
    info_parse.add_argument("--output", default="json", choices=['json', 'yaml'], help="Output format")
    info_parse.set_defaults(func=_info)

    info_parse = subparsers.add_parser("system_info", help='Print system information')
    info_parse.set_defaults(func=_system_info)

    test_parse = subparsers.add_parser("test", help='Start unit tests')
    test_parse.set_defaults(func=_test)

    args = parser.parse_args(namespace=Bunch())
    args.pop("func")(args)


def _info(args):
    from . configuration import Config
    conf = Config()
    info = dict(
        name=conf.plugin_name, version=conf.plugin_version, commit=conf.git_commit,
        supported_k8s_versions=open("k8s_supported.txt").read().split(),
    )
    if args.output == "yaml":
        import yaml
        yaml.dump(info, sys.stdout)
    elif args.output == "json":
        import json
        json.dump(info, sys.stdout)
    else:
        assert False, f"invalid output format: {args.output}"

def _system_info(*_):
    os.system("cat /etc/os-release")


def _test(args):
    """Runs the tests without code coverage"""
    import pytest
    pytest_args = ["-x", "tests", "-s", "-v", "--maxfail=5", "--disable-warnings", "-m", "not host_only"]
    sys.exit(pytest.main(pytest_args))


def _serve(args):
    from . server import serve
    return serve(args.plugin, args.addons)


if __name__ == '__main__':
    main()
