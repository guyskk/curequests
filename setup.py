from setuptools import setup

setup(
    name='curequests',
    version='0.0.1',
    keywords='web',
    description='web framework on curio',
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
    ],
    zip_safe=False,
    classifiers=[
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
        'Programming Language :: Python :: 3 :: Only',
        'Topic :: Software Development :: Libraries :: Python Modules'
    ],
    extras_require={
        'security': ['pyOpenSSL>=0.14', 'cryptography>=1.3.4', 'idna>=2.0.0'],
        'socks': ['PySocks>=1.5.6, !=1.5.7'],
        'socks:sys_platform == "win32" and (python_version == "2.7" or python_version == "2.6")': ['win_inet_pton'],
    },
)
