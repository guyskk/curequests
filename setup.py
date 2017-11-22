from setuptools import setup

setup(
    name='curequests',
    version='0.2.0',
    description='Curio + Requests: Async HTTP for Humans',
    long_description=__doc__,
    author='guyskk',
    author_email='guyskk@qq.com',
    url='https://github.com/guyskk/curequests',
    license='MIT',
    packages=['curequests'],
    install_requires=[
        'httptools',
        'yarl',
        'curio',
        'requests',
        'namedlist',
    ],
    zip_safe=False,
    classifiers=[
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
        'Programming Language :: Python :: 3 :: Only',
        'Programming Language :: Python :: 3.6',
        'Topic :: Software Development :: Libraries :: Python Modules'
    ],
)
