from invoke import task


@task
def test(ctx, cov=True):
    cov = '--cov=curequests --cov-report=term-missing' if cov else ''
    cmd = (f'REQUESTS_CA_BUNDLE=`python -m pytest_httpbin.certs` '
           f'pytest --tb=short {cov} tests')
    ctx.run(cmd, echo=True)
