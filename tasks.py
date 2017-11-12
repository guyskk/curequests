from invoke import task


@task
def test(ctx, cov=True, k='', pdb=False):
    cov = '--cov=curequests --cov-report=term-missing' if cov else ''
    k = f'-k test_{k}' if k else ''
    pdb = f'--pdb' if pdb else ''
    cmd = (f'REQUESTS_CA_BUNDLE=`python -m pytest_httpbin.certs` '
           f'pytest --tb=short -s {cov} {k} {pdb} tests')
    ctx.run(cmd, echo=True, pty=True)


@task
def dist(ctx, upload=False):
    cmds = [
        'rm dist/*',
        'python setup.py bdist_wheel',
    ]
    if upload:
        cmds.append('twine upload dist/*')
    for cmd in cmds:
        ctx.run(cmd, echo=True, pty=True)
