import sys
import argparse
from easypy.bunch import Bunch


def main():
    parser = argparse.ArgumentParser(
        description="Vast CSI Plugin")
    parser.set_defaults(func=lambda *_, **__: parser.print_help())

    subparsers = parser.add_subparsers()

    serve_parse = subparsers.add_parser("serve", help='Start the CSI Plugin Server (not for humans)')
    serve_parse.set_defaults(func=_serve)

    info_parse = subparsers.add_parser("info", help='Print versioning information for this CSI plugin')
    info_parse.add_argument("--output", default="json", choices=['json', 'yaml'], help="Output format")
    info_parse.set_defaults(func=_info)

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


def _test(args):
    """Runs the tests without code coverage"""
    import pytest
    sys.exit(pytest.main(["-x", "tests", "-s", "-v"]))


def _serve(args):
    from . server import serve
    return serve()


if __name__ == '__main__':
    main()
