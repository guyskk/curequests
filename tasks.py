from invoke import task


@task
def lint(ctx):
    ctx.run('pre-commit run --all-files')


@task
def test(ctx, cov=False, verbose=False):
    cov = ' --cov=curequests --cov-report=term-missing' if cov else ''
    verbose = ' -v -x --log-level=debug' if verbose else ''
    cmd = (f'REQUESTS_CA_BUNDLE=`python -m pytest_httpbin.certs` '
           f'pytest --tb=short{cov}{verbose} tests')
    ctx.run(cmd)


@task
def dist(ctx, upload=False):
    cmds = [
        'rm -f dist/*',
        'python setup.py bdist_wheel',
    ]
    if upload:
        cmds.append('twine upload dist/*')
    for cmd in cmds:
        ctx.run(cmd, echo=True)
