import sys

import click
import pkg_resources

from honesty.checker import is_pep517, run_checker
from honesty.releases import parse_index


@click.group()
def cli():
    pass


@click.command()
@click.argument("package_name")
def list(package_name):
    package = parse_index(package_name)
    print(f"package {package.name}")
    print("releases:")
    for k, v in package.releases.items():
        print(f"  {k}:")
        for f in v.files:
            print(f"    {f.basename}")


@click.command()
@click.option("--verbose", "-v", is_flag=True, type=bool)
@click.option("--fresh", "-f", is_flag=True, type=bool)
@click.argument("package_name")
@click.argument("version", default="latest")
def check(verbose, fresh, package_name, version):
    package = parse_index(package_name, fresh=fresh)
    if version == "latest":
        if not package.releases:
            raise click.ClickException("No releases at all")
        version = sorted(package.releases, key=pkg_resources.parse_version)[-1]

    if verbose:
        click.echo(f"check {package_name} {version}")

    rc = 0
    if version == "*":
        for v in sorted(package.releases, key=pkg_resources.parse_version):
            rc |= run_checker(package, v, verbose=verbose)
    else:
        rc |= run_checker(package, version, verbose=verbose)

    if rc != 0:
        sys.exit(rc)


@click.command()
@click.option("--verbose", "-v", is_flag=True, type=bool)
@click.option("--fresh", "-f", is_flag=True, type=bool)
@click.argument("package_name")
@click.argument("version", default="latest")
def ispep517(verbose, fresh, package_name, version):
    package = parse_index(package_name, fresh=fresh)
    if version == "latest":
        if not package.releases:
            raise click.ClickException("No releases at all")
        version = sorted(package.releases, key=pkg_resources.parse_version)[-1]

    if verbose:
        click.echo(f"check {package_name} {version}")

    if not is_pep517(package, version, verbose=verbose):
        sys.exit(1)


cli.add_command(list)
cli.add_command(check)
cli.add_command(ispep517)
if __name__ == "__main__":
    cli()
