import click

from honesty.releases import parse_index
from honesty.checker import run_checker

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
@click.option("--verbose", is_flag=True, type=bool)
@click.argument("package_name")
@click.argument("version")
def check(verbose, package_name, version):
    package = parse_index(package_name)
    run_checker(package, version, verbose=verbose)


cli.add_command(list)
cli.add_command(check)
if __name__ == '__main__':
    cli()
